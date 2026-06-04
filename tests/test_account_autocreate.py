# -*- coding: utf-8 -*-
"""Tests für die automatische Debitoren-/Kreditoren-Kontoanlage.

Welt-Trennung (siehe AGENTS.md / Business-Logik-Modell):
- Welt 1 (ohne fletscher_wassermeloni_base): kein wm_id-Feld. Anlage-Gate
  greift über den Klartext-Namen. Läuft scharf im vanilla-17-Lab.
- Welt 2 (mit wm_id): skipTest-gated, scharf nach Track-2-Build (siehe E2.2).
"""
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

    def test_account_suffix_persisted(self):
        """Der verwendete Suffix wird im Feld account_suffix persistiert."""
        partner = self.Partner.create({"name": "Persistenz Test GmbH"})
        self.assertTrue(partner.account_suffix, "account_suffix muss gesetzt sein")
        self.assertEqual(partner.account_suffix,
                         partner.property_account_receivable_id.code[-7:])
