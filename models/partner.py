from odoo import models, api

class ResPartner(models.Model):
    _inherit = 'res.partner'

    def action_create_debtor_account(self):
        KONTEN_START = 101100000
        KONTEN_MAX = 109999999

        for partner in self:
            if not partner.property_account_receivable_id:
                Account = self.env['account.account']
                existing_accounts = Account.search([
                    ('code', '>=', str(KONTEN_START)),
                    ('code', '<=', str(KONTEN_MAX)),
                ], order='code desc', limit=1)

                next_number = int(existing_accounts.code) + 1 if existing_accounts else KONTEN_START
                while Account.search_count([('code', '=', str(next_number))]) > 0 and next_number <= KONTEN_MAX:
                    next_number += 1
                if next_number <= KONTEN_MAX:
                    konto_nummer = str(next_number)
                    konto_name = f"{partner.lastname}, {partner.firstname}" if hasattr(partner, "lastname") and hasattr(partner, "firstname") and partner.lastname and partner.firstname else partner.name or "Debitor"
                    account = Account.create({
                        'code': konto_nummer,
                        'name': konto_name,
                        'user_type_id': self.env.ref('account.data_account_type_receivable').id,
                        'reconcile': True,
                        'company_id': partner.company_id.id if partner.company_id else self.env.company.id,
                    })
                    partner.property_account_receivable_id = account.id
        return True
