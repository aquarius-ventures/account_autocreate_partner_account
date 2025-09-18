{
    "name": "Auto-create Debtor and Creditor Accounts for Partners",
    "version": "16.0.1.0.0",
    "author": "Aquarius Ventures GmbH",
    "license": "AGPL-3",
    "category": "Accounting",
    "summary": "Automatisch Debitoren- und Kreditorenkonten bei Partner-Erstellung vergeben (9-stellig, DATEV-konform)",
    "depends": ["account"],
    "data": [
        "data/sequence.xml",
        "data/server_action.xml",
        "views/partner.xml",
    ],
    "installable": True,
    "application": False,
}
