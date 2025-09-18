from odoo import models, api, fields
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
        prop_obj = self.env['ir.property']
        company = partner.company_id or self.env.company
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

    def create_debtor_and_creditor_accounts(self):
        Account = self.env['account.account'].sudo()
        Sequence = self.env['ir.sequence'].sudo()

        for partner in self:
            company = partner.company_id or self.env.company

            # Skip companies if they are not customers/suppliers? -> we still generate for any contact
            # Determine base suffix – prefer persistent field, then infer, then sequence.
            suffix = None
            if partner.account_suffix:
                try:
                    suffix = int(partner.account_suffix)
                except Exception:
                    suffix = None
            if suffix is None:
                suffix = self._suffix_from_existing_accounts(partner, company)
            if suffix is None:
                # Pull next from global sequence (7 digits)
                next_num = Sequence.next_by_code('res.partner.account_suffix')
                try:
                    suffix = int(next_num or 0)
                except Exception:
                    suffix = 0
            # Ensure minimum & no collisions (both accounts must be free)
            suffix = self._next_free_suffix(suffix or MIN_SUFFIX, company)
            if not suffix:
                _logger.warning("Keine freie Suffixnummer mehr verfügbar (Firma %s).", company.display_name)
                continue

            debtor_code, creditor_code = self._compute_codes_from_suffix(suffix)
            display = self._display_person_name(partner)

            # Create/ensure both accounts
            if not self._has_specific_property(partner, 'property_account_receivable_id'):
                acc_rec = self._ensure_account(debtor_code, f"{display}", 'asset_receivable', company)
                partner.property_account_receivable_id = acc_rec.id
                _logger.info("Debitorenkonto %s angelegt/zugewiesen an %s", debtor_code, partner.display_name)
            else:
                # If property exists, still try to align suffix if possible by deriving it
                _logger.info("Übersprungen (Debitor): %s hat bereits individuelle Property.", partner.display_name)

            if not self._has_specific_property(partner, 'property_account_payable_id'):
                acc_pay = self._ensure_account(creditor_code, f"{display}", 'liability_payable', company)
                partner.property_account_payable_id = acc_pay.id
                _logger.info("Kreditorenkonto %s angelegt/zugewiesen an %s", creditor_code, partner.display_name)
            else:
                _logger.info("Übersprungen (Kreditor): %s hat bereits individuelle Property.", partner.display_name)

            # Store suffix for stability
            if not partner.account_suffix:
                partner.account_suffix = f"{suffix:07d}"

        return True

    @api.model_create_multi
    def create(self, vals_list):
        partners = super().create(vals_list)
        partners.create_debtor_and_creditor_accounts()
        return partners