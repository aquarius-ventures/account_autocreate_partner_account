from odoo import models, api
import logging
_logger = logging.getLogger(__name__)

class ResPartner(models.Model):
    _inherit = 'res.partner'

    def _has_specific_property(self, partner, field_name):
        """True, wenn für diesen Partner + Company eine eigene Property existiert (kein Default)."""
        fields_obj = self.env['ir.model.fields']
        prop_obj = self.env['ir.property']
        company = partner.company_id or self.env.company
        field = fields_obj._get('res.partner', field_name)
        return bool(prop_obj.search([
            ('fields_id', '=', field.id),
            ('res_id', '=', f'res.partner,{partner.id}'),
            ('company_id', '=', company.id),
        ], limit=1))

    def create_debtor_and_creditor_accounts(self):
        DEBTOR_PREFIX = 10
        CREDITOR_PREFIX = 70
        KONTEN_START = 1100000
        KONTEN_MAX = 9999999

        Account = self.env['account.account']

        for partner in self:
            company = partner.company_id or self.env.company

            # höchste bereits vergebene Debitorennummer (Prefix 10) in dieser Company
            existing_accounts = Account.search([
                ('code', '>=', str(DEBTOR_PREFIX * 10000000 + KONTEN_START)),
                ('code', '<=', str(DEBTOR_PREFIX * 10000000 + KONTEN_MAX)),
                ('company_id', '=', company.id),
            ], order='code desc', limit=1)
            next_number = (int(existing_accounts.code) - DEBTOR_PREFIX * 10000000 + 1) if existing_accounts else KONTEN_START

            # -------- Debitor --------
            if not self._has_specific_property(partner, 'property_account_receivable_id'):
                next_debtor_number = DEBTOR_PREFIX * 10000000 + next_number
                debtor_max = DEBTOR_PREFIX * 10000000 + KONTEN_MAX
                while Account.search_count([('code', '=', str(next_debtor_number)), ('company_id', '=', company.id)]) > 0 \
                        and next_debtor_number <= debtor_max:
                    next_debtor_number += 1
                if next_debtor_number <= debtor_max:
                    debtor_code = str(next_debtor_number)
                    konto_name = (f"{getattr(partner, 'lastname', '')}, {getattr(partner, 'firstname', '')}".strip(", ")
                                  or partner.name or "Debitor")
                    account_recv = Account.create({
                        'code': debtor_code,
                        'name': konto_name,
                        'account_type': 'asset_receivable',
                        'reconcile': True,
                        'company_id': company.id,
                    })
                    partner.property_account_receivable_id = account_recv.id
                    _logger.info("Debitorenkonto %s angelegt & zugewiesen an %s", debtor_code, partner.display_name)
                    next_number = next_debtor_number - DEBTOR_PREFIX * 10000000 + 1
                else:
                    _logger.warning("Alle Debitorennummern vergeben (Prefix %s).", DEBTOR_PREFIX)
            else:
                _logger.info("Übersprungen (Debitor): %s hat bereits individuelle Property.", partner.display_name)

            # -------- Kreditor --------
            if not self._has_specific_property(partner, 'property_account_payable_id'):
                next_creditor_number = CREDITOR_PREFIX * 10000000 + (next_number or KONTEN_START)
                creditor_max = CREDITOR_PREFIX * 10000000 + KONTEN_MAX
                while Account.search_count([('code', '=', str(next_creditor_number)), ('company_id', '=', company.id)]) > 0 \
                        and next_creditor_number <= creditor_max:
                    next_creditor_number += 1
                if next_creditor_number <= creditor_max:
                    creditor_code = str(next_creditor_number)
                    konto_name = (f"{getattr(partner, 'lastname', '')}, {getattr(partner, 'firstname', '')}".strip(", ")
                                  or partner.name or "Kreditor")
                    account_pay = Account.create({
                        'code': creditor_code,
                        'name': konto_name,
                        'account_type': 'liability_payable',
                        'reconcile': True,
                        'company_id': company.id,
                    })
                    partner.property_account_payable_id = account_pay.id
                    _logger.info("Kreditorenkonto %s angelegt & zugewiesen an %s", creditor_code, partner.display_name)
                else:
                    _logger.warning("Alle Kreditorennummern vergeben (Prefix %s).", CREDITOR_PREFIX)
            else:
                _logger.info("Übersprungen (Kreditor): %s hat bereits individuelle Property.", partner.display_name)

        return True

    @api.model_create_multi
    def create(self, vals_list):
        partners = super().create(vals_list)
        partners.create_debtor_and_creditor_accounts()
        return partners
