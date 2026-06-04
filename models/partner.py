from odoo import models, api, fields, _
from odoo.exceptions import UserError
import logging

_logger = logging.getLogger(__name__)

DEBTOR_PREFIX = 10
CREDITOR_PREFIX = 70
BASE = 10_000_000  # 7 digits reserved for the suffix
MIN_SUFFIX = 1_100_000  # ensures min debtor 101100000 / creditor 701100000


class ResPartner(models.Model):
    _inherit = 'res.partner'

    # Optional persistent suffix to ensure stability even if accounts get deleted/recreated
    account_suffix = fields.Char(string="Account Suffix", size=7, readonly=True, copy=False)

    def _has_specific_property(self, partner, field_name):
        """True if this partner+company has a specific (non-default) property set."""
        fields_obj = self.env['ir.model.fields']
        company = partner.company_id or self.env.company
        prop_obj = self.env['ir.property'].sudo().with_company(company)
        field = fields_obj._get('res.partner', field_name)
        return bool(prop_obj.search([
            ('fields_id', '=', field.id),
            ('res_id', '=', f'res.partner,{partner.id}'),
            ('company_id', '=', company.id),
        ], limit=1))

    def _suffix_from_existing_accounts(self, partner, company):
        """Try to derive the 7-digit suffix from existing receivable/payable accounts."""
        debtor = partner.property_account_receivable_id
        creditor = partner.property_account_payable_id

        def extract_suffix(acc, expect_prefix):
            if not acc or acc.company_id.id != company.id:
                return None
            code = (acc.code or '').strip()
            if len(code) == 9 and code.isdigit() and code.startswith(str(expect_prefix)):
                # take last 7 digits
                return int(code[-7:])
            return None

        # Prefer a matching pair; otherwise any existing matching one
        d = extract_suffix(debtor, DEBTOR_PREFIX)
        c = extract_suffix(creditor, CREDITOR_PREFIX)
        return d if d is not None else c

    def _compute_codes_from_suffix(self, suffix):
        return (
            str(DEBTOR_PREFIX * BASE + suffix),
            str(CREDITOR_PREFIX * BASE + suffix),
        )

    def _both_codes_free(self, debtor_code, creditor_code, company):
        Account = self.env['account.account'].sudo()
        exists = Account.search_count([('code', 'in', [debtor_code, creditor_code]), ('company_id', '=', company.id)])
        return exists == 0

    def _next_free_suffix(self, start_suffix, company):
        """Find next suffix so that BOTH debtor+creditor codes are free."""
        suffix = max(start_suffix, MIN_SUFFIX)
        Account = self.env['account.account'].sudo()
        # The theoretical upper bound is 9,999,999 -> codes 109999999 / 709999999
        while suffix <= 9_999_999:
            debtor_code, creditor_code = self._compute_codes_from_suffix(suffix)
            if self._both_codes_free(debtor_code, creditor_code, company):
                return suffix
            suffix += 1
        return None

    def _ensure_account(self, code, name, account_type, company):
        Account = self.env['account.account'].sudo()
        # Try find existing
        account = Account.search([('code', '=', code), ('company_id', '=', company.id)], limit=1)
        if account:
            return account
        # Create new with correct type
        vals = {
            'code': code,
            'name': name,
            'reconcile': True,
            'company_id': company.id,
            'account_type': account_type,  # 'asset_receivable' or 'liability_payable'
        }
        account = Account.create(vals)
        return account

    def _display_person_name(self, partner):
        lastname = getattr(partner, 'lastname', '') or ''
        firstname = getattr(partner, 'firstname', '') or ''
        name = (f"{lastname}, {firstname}" if lastname or firstname else partner.display_name).strip(', ').strip()
        return name or partner.name or partner.display_name

    def _compute_account_name(self, partner):
        """Kontoname nach Fallback-Kaskade (siehe Business-Logik-Modell §9.2).
        Diskriminiert über den Klartext-Namen, NICHT über display_name (das
        selten wirklich leer ist):
          (a) "Nachname, Vorname" aus den OCA-Feldern lastname/firstname,
          (b) display_name, sofern ein Klartext-Name (`name`) vorhanden ist,
          (c) "WM-<wm_id>" als Pseudonym-Fallback.
        Leerer String, wenn kein benennbarer Anker vorhanden ist.

        `wm_id` lebt in fletscher_wassermeloni_base, nicht in diesem Modul —
        Zugriff daher defensiv (weiche Abhängigkeit). Ohne dieses Modul greifen
        nur die Stufen (a) und (b)."""
        lastname = (getattr(partner, 'lastname', '') or '').strip()
        firstname = (getattr(partner, 'firstname', '') or '').strip()
        if lastname or firstname:
            return f"{lastname}, {firstname}".strip(', ').strip()  # (a)
        raw_name = (partner.name or '').strip()
        if raw_name:
            return (partner.display_name or raw_name).strip()       # (b)
        wm_id = getattr(partner, 'wm_id', False)                    # (c)
        wm_id = (wm_id or '').strip() if isinstance(wm_id, str) else wm_id
        if wm_id:
            return f"WM-{wm_id}"
        return ''

    def _partner_eligible_for_account(self, partner):
        """Anlage-Gate (Modell §9.3): ein Partner bekommt nur dann Konten,
        wenn er benennbar ist — Klartext-Name ODER wm_id erforderlich."""
        return bool(self._compute_account_name(partner))

    def create_debtor_and_creditor_accounts(self):
        Account = self.env['account.account'].sudo()
        Sequence = self.env['ir.sequence'].sudo()
        suffix_seq = Sequence.search([('code', '=', 'res.partner.account_suffix')], limit=1)
        # Trigger-Quelle steuert das Gate-Verhalten (Modell §9.3):
        #   'create'  -> Auto-Anlage: still überspringen + Log
        #   'mass'    -> Massenaktion: still überspringen + Sammel-Log am Ende
        #   'manual'  -> Einzel-Button: laut crashen (User hat es explizit gewollt)
        origin = self.env.context.get('autocreate_origin', 'manual')
        skipped = self.env['res.partner']

        for partner in self:
            company = partner.company_id or self.env.company

            # --- Anlage-Gate (Modell §9.3): nur benennbare Partner bekommen Konten ---
            if not self._partner_eligible_for_account(partner):
                if origin == 'manual':
                    raise UserError(_(
                        "Konto kann nicht angelegt werden: Partner '%s' hat weder "
                        "Namen noch WM-ID."
                    ) % (partner.display_name or partner.id))
                skipped |= partner
                _logger.info("Übersprungen (kein Name / keine wm_id): %s", partner.display_name)
                continue

            # --- Früh entscheiden, ob überhaupt Arbeit nötig ist ---
            has_rec = self._has_specific_property(partner, 'property_account_receivable_id')
            has_pay = self._has_specific_property(partner, 'property_account_payable_id')
            if has_rec and has_pay:
                # Beide individuellen Properties existieren -> nichts tun, auch keine Sequenz ziehen
                _logger.info("Übersprungen (beide Properties vorhanden): %s", partner.display_name)
                continue

            # --- Suffix nur ermitteln, wenn mind. eine Property fehlt ---
            suffix = None
            if partner.account_suffix:
                try:
                    suffix = int(partner.account_suffix)
                except Exception:
                    suffix = None

            # Falls noch kein persistenter Suffix: aus bestehend konformen Konten ableiten
            if suffix is None:
                def _derive(acc, expect_prefix):
                    if not acc or acc.company_id.id != company.id:
                        return None
                    code = (acc.code or '').strip()
                    if len(code) == 9 and code.isdigit() and code.startswith(str(expect_prefix)):
                        return int(code[-7:])
                    return None

                suffix = _derive(partner.property_account_receivable_id, DEBTOR_PREFIX) \
                         or _derive(partner.property_account_payable_id, CREDITOR_PREFIX)

            # Sequenz NUR ziehen, wenn weiterhin kein Suffix vorhanden ist und wir wirklich etwas anlegen müssen
            if suffix is None:
                nxt = Sequence.next_by_code('res.partner.account_suffix')
                try:
                    suffix = int(nxt or 0)
                except Exception:
                    suffix = 0

            # nächste freie Suffixzahl finden (beide Codes müssen frei sein)
            def _both_free(d_code, c_code):
                return Account.search_count([
                    ('code', 'in', [d_code, c_code]),
                    ('company_id', '=', company.id),
                ]) == 0

            suffix = max(suffix or 0, MIN_SUFFIX)
            while suffix <= 9_999_999:
                debtor_code = str(DEBTOR_PREFIX * BASE + suffix)
                creditor_code = str(CREDITOR_PREFIX * BASE + suffix)
                if _both_free(debtor_code, creditor_code):
                    break
                suffix += 1
            if suffix > 9_999_999:
                raise UserError(_(
                    "Kontonummern-Kreis erschöpft (Firma '%s'): keine freie "
                    "Suffixnummer mehr verfügbar."
                ) % company.display_name)

            debtor_code = str(DEBTOR_PREFIX * BASE + suffix)
            creditor_code = str(CREDITOR_PREFIX * BASE + suffix)
            display_name = self._compute_account_name(partner)

            # Konten nur erzeugen, wenn wir sie auch zuweisen (min. eine Property fehlt)
            def _ensure(code, name, acc_type):
                acc = Account.search([('code', '=', code), ('company_id', '=', company.id)], limit=1)
                return acc or Account.create({
                    'code': code,
                    'name': name,
                    'reconcile': True,
                    'company_id': company.id,
                    'account_type': acc_type,  # 'asset_receivable' / 'liability_payable'
                })

            # Receivable
            if not has_rec:
                acc_rec = _ensure(debtor_code, display_name, 'asset_receivable')
                partner.property_account_receivable_id = acc_rec.id
                _logger.info("Debitorenkonto %s angelegt/zugewiesen an %s", debtor_code, partner.display_name)
            else:
                acc_rec = partner.property_account_receivable_id  # für evtl. spätere Ableitung / Konsistenz

            # Payable
            if not has_pay:
                acc_pay = _ensure(creditor_code, display_name, 'liability_payable')
                partner.property_account_payable_id = acc_pay.id
                _logger.info("Kreditorenkonto %s angelegt/zugewiesen an %s", creditor_code, partner.display_name)
            else:
                acc_pay = partner.property_account_payable_id

            # Persistenz des Suffix (immer, sobald noch keiner gesetzt ist)
            if not partner.account_suffix:
                partner.account_suffix = f"{suffix:07d}"

            # Sequenz nachziehen (Modell §5): number_next soll auf den nächsten
            # freien Wert zeigen. Nur vorwärts — persistente/abgeleitete Suffixe
            # können unter dem aktuellen Zähler liegen und dürfen ihn nicht
            # zurücksetzen.
            if suffix_seq:
                suffix_seq.invalidate_recordset(['number_next_actual'])
                if (suffix + 1) > suffix_seq.number_next_actual:
                    suffix_seq.write({'number_next': suffix + 1})

        if origin == 'mass' and skipped:
            _logger.info(
                "Massenanlage: %d von %d Partnern übersprungen (weder Name noch WM-ID).",
                len(skipped), len(self))
        return True

    @api.model_create_multi
    def create(self, vals_list):
        partners = super().create(vals_list)
        partners.with_context(autocreate_origin='create').create_debtor_and_creditor_accounts()
        return partners
