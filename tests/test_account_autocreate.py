# -*- coding: utf-8 -*-
"""Tests für die automatische Debitoren-/Kreditoren-Kontoanlage.

Welt-Trennung (siehe AGENTS.md / Business-Logik-Modell):
- Welt 1 (ohne fletscher_wassermeloni_base): kein wm_id-Feld. Anlage-Gate
  greift über den Klartext-Namen. Läuft scharf im vanilla-17-Lab.
- Welt 2 (mit wm_id): skipTest-gated, scharf nach Track-2-Build (siehe E2.2).
"""
import unittest

from odoo.exceptions import UserError
from odoo.tests import common, tagged

DEBTOR_PREFIX = "10"
CREDITOR_PREFIX = "70"


@tagged("account_autocreate", "standard", "post_install", "-at_install")
class TestAutocreateWorld1(common.TransactionCase):
    """Welt 1 — Anlage-Gate über Klartext-Name, ohne wm_id-Abhängigkeit."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Partner = cls.env["res.partner"]
        cls.RP = cls.Partner  # für _has_specific_property-Aufrufe

    # --- Helfer ---------------------------------------------------------
    def _has_rec(self, partner):
        return self.RP._has_specific_property(partner, "property_account_receivable_id")

    def _has_pay(self, partner):
        return self.RP._has_specific_property(partner, "property_account_payable_id")

    def _assert_module_code(self, account, expected_prefix):
        code = (account.code or "").strip()
        self.assertEqual(len(code), 9, f"Kontocode muss 9-stellig sein: {code!r}")
        self.assertTrue(code.isdigit(), f"Kontocode muss numerisch sein: {code!r}")
        self.assertTrue(code.startswith(expected_prefix),
                        f"Kontocode {code!r} muss mit {expected_prefix} beginnen")

    # --- Tests ----------------------------------------------------------
    def test_named_partner_gets_both_accounts(self):
        """Partner mit Klartext-Name → Debitor- UND Kreditorkonto, 9-stellig,
        Präfix 10/70, gemeinsamer Suffix."""
        partner = self.Partner.create({"name": "Acme Handels GmbH"})

        rec = partner.property_account_receivable_id
        pay = partner.property_account_payable_id
        self.assertTrue(rec, "Debitorenkonto muss angelegt sein")
        self.assertTrue(pay, "Kreditorenkonto muss angelegt sein")
        self._assert_module_code(rec, DEBTOR_PREFIX)
        self._assert_module_code(pay, CREDITOR_PREFIX)
        # Gemeinsamer 7-stelliger Suffix
        self.assertEqual(rec.code[-7:], pay.code[-7:],
                         "Debitor und Kreditor müssen denselben Suffix teilen")
        # Suffix im Neu-Datenraum (>= 1.100.000)
        self.assertGreaterEqual(int(rec.code[-7:]), 1_100_000)

    def test_named_partner_account_name_matches_clear_name(self):
        """Kontoname folgt dem Klartext-Namen (Stufe (b) display_name für
        eine Company ohne lastname/firstname)."""
        partner = self.Partner.create({"name": "Beispiel AG"})
        self.assertEqual(partner.property_account_receivable_id.name, "Beispiel AG")

    def test_gate_blocks_nameless_without_wm_id(self):
        """Anlage-Gate (Modell §9.3): ein Partner ohne Klartext-Name und ohne
        wm_id ist nicht benennbar → nicht kontoberechtigt. In-Memory geprüft
        (.new()), um nicht von DB-Pflichtfeld-Verhalten abzuhängen."""
        nameless = self.Partner.new({"name": False})
        self.assertEqual(self.RP._compute_account_name(nameless), "")
        self.assertFalse(self.RP._partner_eligible_for_account(nameless),
                         "Ohne Name/wm_id darf kein Konto angelegt werden")

    def test_manual_button_raises_on_ineligible(self):
        """Einzel-Button (Kontext 'manual') auf einen nicht benennbaren Partner
        → UserError statt stillem Überspringen (Modell §9.3)."""
        nameless = self.Partner.new({"name": False})
        with self.assertRaises(UserError):
            nameless.with_context(
                autocreate_origin='manual').create_debtor_and_creditor_accounts()

    def test_account_suffix_persisted(self):
        """Der verwendete Suffix wird im Feld account_suffix persistiert."""
        partner = self.Partner.create({"name": "Persistenz Test GmbH"})
        self.assertTrue(partner.account_suffix, "account_suffix muss gesetzt sein")
        self.assertEqual(partner.account_suffix,
                         partner.property_account_receivable_id.code[-7:])

    def test_sequence_pulled_past_collision(self):
        """Modell §5: nach einem Kollisions-Scan zeigt die Sequenz über den
        tatsächlich vergebenen Suffix hinaus (number_next_actual >= suffix+1)."""
        seq = self.env["ir.sequence"].search(
            [("code", "=", "res.partner.account_suffix")], limit=1)
        self.assertTrue(seq, "Suffix-Sequenz muss existieren")
        seq.write({"number_next": 5_000_000})  # bekannter Start, resettet die PG-Sequenz
        Account = self.env["account.account"]
        # Debitor-Codes für 5.000.000–5.000.002 belegen → Scan muss überspringen
        for s in (5_000_000, 5_000_001, 5_000_002):
            Account.create({
                "code": str(100_000_000 + s),
                "name": f"Blocker {s}",
                "account_type": "asset_receivable",
                "reconcile": True,
            })
        partner = self.Partner.create({"name": "Kollisions Test GmbH"})
        used = int(partner.account_suffix)
        self.assertEqual(used, 5_000_003, "erster freier Suffix nach den drei Blockern")
        seq.invalidate_recordset(["number_next_actual"])
        self.assertGreaterEqual(
            seq.number_next_actual, used + 1,
            "Sequenz muss über den übersprungenen Suffix hinaus nachgezogen sein")

    def test_userror_on_sequence_exhaustion(self):
        """Modell §9.4: Suffix > 9.999.999 → UserError statt stillem Skip."""
        seq = self.env["ir.sequence"].search(
            [("code", "=", "res.partner.account_suffix")], limit=1)
        seq.write({"number_next": 10_000_000})  # über der Obergrenze 9.999.999
        with self.assertRaises(UserError):
            self.Partner.create({"name": "Erschöpfung Test GmbH"})


@tagged("account_autocreate", "account_autocreate_wmid", "standard", "post_install", "-at_install")
class TestAutocreateWorld2WmId(common.TransactionCase):
    """Welt 2 — wm_id-Fallback. skipTest-gated: läuft scharf erst nach
    Track-2-Build mit fletscher_wassermeloni_base (wm_id-Feld vorhanden)."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Partner = cls.env["res.partner"]
        cls.RP = cls.Partner
        if "wm_id" not in cls.Partner._fields:
            raise unittest.SkipTest(
                "wm_id-Feld nicht verfügbar — fletscher_wassermeloni_base nicht installiert (Welt 1).")

    def test_wm_id_fallback_name_helper(self):
        """Stufe (c): Ohne Klartext-Name, aber mit wm_id → Name "WM-<wm_id>".
        Helfer-Ebene (.new()), unabhängig von DB-Pflichtfeldern."""
        p = self.Partner.new({"name": False, "wm_id": "123456789"})
        self.assertEqual(self.RP._compute_account_name(p), "WM-123456789")
        self.assertTrue(self.RP._partner_eligible_for_account(p),
                        "Partner mit wm_id ist kontoberechtigt")

    def test_wm_id_only_partner_gets_account_named_wm_id(self):
        """Verhaltens-Test: Partner nur mit wm_id (kein Klartext-Name) →
        Konto wird angelegt und trägt den Namen "WM-<wm_id>"."""
        partner = self.Partner.create({"name": False, "wm_id": "123456789"})
        rec = partner.property_account_receivable_id
        self.assertTrue(rec, "Debitorenkonto muss angelegt sein")
        self.assertEqual(rec.code[:2], DEBTOR_PREFIX)
        self.assertEqual(rec.name, "WM-123456789")


@tagged("account_autocreate", "account_autocreate_wmid", "standard", "post_install", "-at_install")
class TestAutocreateTieBreaker(common.TransactionCase):
    """E2.3 — Tie-Breaker der Namens-Kaskade: Stufe (a) "Nachname, Vorname"
    schlägt Stufe (c) "WM-<wm_id>", wenn beides vorhanden ist. Benötigt
    lastname (partner_firstname) UND wm_id → skipTest-gated (Welt 2 / Track-2)."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Partner = cls.env["res.partner"]
        cls.RP = cls.Partner
        missing = [f for f in ("lastname", "wm_id") if f not in cls.Partner._fields]
        if missing:
            raise unittest.SkipTest(
                f"Felder nicht verfügbar: {missing} — partner_firstname/fletscher nicht installiert.")

    def test_clear_name_wins_over_wm_id_helper(self):
        """Helfer-Ebene: lastname/firstname + wm_id → "Nachname, Vorname"."""
        p = self.Partner.new({"lastname": "Mustermann", "firstname": "Erika", "wm_id": "123456789"})
        self.assertEqual(self.RP._compute_account_name(p), "Mustermann, Erika")

    def test_clear_name_wins_over_wm_id_behavior(self):
        """Verhaltens-Test: Partner mit Klartext-Name UND wm_id → Konto trägt
        den Klartext-Namen, nicht "WM-<wm_id>"."""
        partner = self.Partner.create(
            {"lastname": "Mustermann", "firstname": "Erika", "wm_id": "123456789"})
        self.assertEqual(partner.property_account_receivable_id.name, "Mustermann, Erika")
