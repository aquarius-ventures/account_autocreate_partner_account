from odoo import models, api
import logging

_logger = logging.getLogger(__name__)


class ResPartner(models.Model):
    _inherit = 'res.partner'

    def create_debtor_and_creditor_accounts(self):
        DEBTOR_PREFIX = 10
        CREDITOR_PREFIX = 70
        KONTEN_START = 1100000
        KONTEN_MAX = 9999999

        Account = self.env['account.account']

        for partner in self:
            company = partner.company_id or self.env.company

            # <- HIER: Defaults per Property-System je Company holen
            default_partner = self.with_company(company).new({})
            default_recv = default_partner.property_account_receivable_id
            default_pay = default_partner.property_account_payable_id

            # Höchste vergebene Debitoren-Nummer (mit Präfix 10) finden
            existing_accounts = Account.search([
                ('code', '>=', str(DEBTOR_PREFIX * 10000000 + KONTEN_START)),
                ('code', '<=', str(DEBTOR_PREFIX * 10000000 + KONTEN_MAX)),
                ('company_id', '=', company.id),
            ], order='code desc', limit=1)
            next_number = (
                        int(existing_accounts.code) - DEBTOR_PREFIX * 10000000 + 1) if existing_accounts else KONTEN_START

            # -------- Debitor --------
            if partner.property_account_receivable_id and partner.property_account_receivable_id != default_recv:
                _logger.info("Skip Debitor: %s hat bereits individuelles Konto %s",
                             partner.display_name, partner.property_account_receivable_id.code)
            else:
                next_debtor_number = DEBTOR_PREFIX * 10000000 + next_number
                debtor_max = DEBTOR_PREFIX * 10000000 + KONTEN_MAX
                while Account.search_count(
                        [('code', '=', str(next_debtor_number)), ('company_id', '=', company.id)]) > 0 \
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
                    # Zähler für evtl. aufeinanderfolgende Vergabe anpassen
                    next_number = next_debtor_number - DEBTOR_PREFIX * 10000000 + 1
                else:
                    _logger.warning("Alle Debitorennummern (Prefix %s) vergeben.", DEBTOR_PREFIX)

            # -------- Kreditor --------
            if partner.property_account_payable_id and partner.property_account_payable_id != default_pay:
                _logger.info("Skip Kreditor: %s hat bereits individuelles Konto %s",
                             partner.display_name, partner.property_account_payable_id.code)
            else:
                next_creditor_number = CREDITOR_PREFIX * 10000000 + (next_number or KONTEN_START)
                creditor_max = CREDITOR_PREFIX * 10000000 + KONTEN_MAX
                while Account.search_count(
                        [('code', '=', str(next_creditor_number)), ('company_id', '=', company.id)]) > 0 \
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
                    _logger.warning("Alle Kreditorennummern (Prefix %s) vergeben.", CREDITOR_PREFIX)

        return True

    @api.model_create_multi
    def create(self, vals_list):
        partners = super().create(vals_list)
        partners.create_debtor_and_creditor_accounts()
        return partners
