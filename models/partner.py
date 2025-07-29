from odoo import models

import logging
_logger = logging.getLogger(__name__)

class ResPartner(models.Model):
    _inherit = 'res.partner'

    def create_debtor_account(self):
        KONTEN_START = 101100000
        KONTEN_MAX = 109999999

        Account = self.env['account.account']
        account_type = self.env.ref('account.data_account_type_receivable')

        for partner in self:
            if not partner.property_account_receivable_id:
                existing_accounts = Account.search([
                    ('code', '>=', str(KONTEN_START)),
                    ('code', '<=', str(KONTEN_MAX)),
                ], order='code desc', limit=1)

                next_number = int(existing_accounts.code) + 1 if existing_accounts else KONTEN_START
                # Sicherstellen, dass der nächste Code noch frei ist
                while Account.search_count([('code', '=', str(next_number))]) > 0 and next_number <= KONTEN_MAX:
                    next_number += 1

                if next_number <= KONTEN_MAX:
                    konto_nummer = str(next_number)
                    # Name: Nachname, Vorname (Fallback: Partner-Name)
                    if hasattr(partner, "lastname") and hasattr(partner, "firstname") and partner.lastname and partner.firstname:
                        konto_name = f"{partner.lastname}, {partner.firstname}"
                    else:
                        konto_name = partner.name or "Debitor"
                    account = Account.create({
                        'code': konto_nummer,
                        'name': konto_name,
                        'user_type_id': account_type.id,
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
        return True
