from odoo import models, api

import logging

_logger = logging.getLogger(__name__)


class ResPartner(models.Model):
    _inherit = 'res.partner'

    def _has_explicit_property(self, field_name):
        """True, wenn für diesen Partner ein eigener ir.property-Eintrag existiert
        (d. h. nicht nur der Default greift)."""
        self.ensure_one()
        IrProperty = self.env['ir.property'].sudo()
        res_id = f'res.partner,{self.id}'
        company_id = (self.company_id or self.env.company).id
        return bool(IrProperty.search([
            ('name', '=', field_name),
            ('res_id', '=', res_id),
            ('company_id', '=', company_id),
        ], limit=1))

    def create_debtor_and_creditor_accounts(self):
        DEBTOR_PREFIX = 10
        CREDITOR_PREFIX = 70
        KONTEN_START = 1100000
        KONTEN_MAX = 9999999

        Account = self.env['account.account']

        for partner in self:

            # Nur anlegen, wenn KEIN individueller Wert existiert (Default würde greifen)
            need_receivable = not partner._has_explicit_property('property_account_receivable_id')
            need_payable    = not partner._has_explicit_property('property_account_payable_id')

            if not (need_receivable or need_payable):
                _logger.info("Übersprungen (explizite Konten vorhanden) für Partner %s (%s)", partner.id,
                             partner.display_name)
                continue

            existing_accounts = Account.search([
                ('code', '>=', str(DEBTOR_PREFIX * 10000000 + KONTEN_START)),
                ('code', '<=', str(DEBTOR_PREFIX * 10000000 + KONTEN_MAX)),
            ], order='code desc', limit=1)

            next_number = int(
                existing_accounts.code) - DEBTOR_PREFIX * 10000000 + 1 if existing_accounts else KONTEN_START

            # Debitorenkonto erstellen
            if not need_receivable:

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
            if not need_payable:

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