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

            existing_accounts = Account.search([
                ('code', '>=', str(DEBTOR_PREFIX * 10000000 + KONTEN_START)),
                ('code', '<=', str(DEBTOR_PREFIX * 10000000 + KONTEN_MAX)),
            ], order='code desc', limit=1)

            next_number = int(
                existing_accounts.code) - DEBTOR_PREFIX * 10000000 + 1 if existing_accounts else KONTEN_START

            # Debitorenkonto erstellen
            if not partner.property_account_receivable_id:

                next_debtor_number = DEBTOR_PREFIX * 10000000 + next_number
                debtor_max = DEBTOR_PREFIX * 10000000 + KONTEN_MAX

                # Sicherstellen, dass der nächste Code noch frei ist
                while Account.search_count(
                        [('code', '=', str(next_debtor_number))]) > 0 and next_debtor_number <= debtor_max:
                    next_debtor_number += 1

                if next_debtor_number <= debtor_max:
                    konto_nummer = str(next_debtor_number)
                    # Name: Nachname, Vorname (Fallback: Partner-Name)
                    if hasattr(partner, "lastname") and hasattr(partner,
                                                                "firstname") and partner.lastname and partner.firstname:
                        konto_name = f"{partner.lastname}, {partner.firstname}"
                    else:
                        konto_name = partner.name or "Debitor"
                    account = Account.create({
                        'code': konto_nummer,
                        'name': konto_name,
                        'account_type': 'asset_receivable',
                        'reconcile': True,
                        'company_id': partner.company_id.id if partner.company_id else self.env.company.id,
                    })
                    _logger.info("Debitorenkonto %s angelegt", konto_nummer)
                    partner.property_account_receivable_id = account.id
                    _logger.info("Debitorenkonto %s dem Partner %s zugewiesen.", konto_nummer, konto_name)
                else:
                    # Optional: Fehler werfen oder warnen, falls alle Nummern belegt
                    _logger.warning('Alle Debitorennummern vergeben!')
                pass

            # Kreditorenkonto erstellen
            if not partner.property_account_payable_id:

                next_creditor_number = CREDITOR_PREFIX * 10000000 + next_number
                creditor_max = CREDITOR_PREFIX * 10000000 + KONTEN_MAX

                # Sicherstellen, dass der nächste Code noch frei ist
                while Account.search_count(
                        [('code', '=', str(next_creditor_number))]) > 0 and next_creditor_number <= creditor_max:
                    next_creditor_number += 1

                if next_creditor_number <= creditor_max:
                    konto_nummer = str(next_creditor_number)
                    # Name: Nachname, Vorname (Fallback: Partner-Name)
                    if hasattr(partner, "lastname") and hasattr(partner,
                                                                "firstname") and partner.lastname and partner.firstname:
                        konto_name = f"{partner.lastname}, {partner.firstname}"
                    else:
                        konto_name = partner.name or "Kreditor"
                    account = Account.create({
                        'code': konto_nummer,
                        'name': konto_name,
                        'account_type': 'liability_payable',
                        'reconcile': True,
                        'company_id': partner.company_id.id if partner.company_id else self.env.company.id,
                    })
                    _logger.info("Kreditorenkonto %s angelegt", konto_nummer)
                    partner.property_account_payable_id = account.id
                    _logger.info("Kreditorenkonto %s dem Partner %s zugewiesen.", konto_nummer, konto_name)
                else:
                    # Optional: Fehler werfen oder warnen, falls alle Nummern belegt
                    _logger.warning('Alle Kreditorennummern vergeben!')
                pass

        return True

    @api.model_create_multi
    def create(self, vals_list):
        partners = super().create(vals_list)
        partners.create_debtor_and_creditor_accounts()
        return partners