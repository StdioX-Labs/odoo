# -*- coding: utf-8 -*-
{
    'name': 'SMS Provider: Emalify',
    'version': '1.1',
    'category': 'Hidden/Tools',
    'sequence': 10,
    'summary': 'SMS Gateway Integration (Roamtech / Vidatech)',
    'description': """
Emalify SMS Provider
====================
This module integrates Emalify SMS API with Odoo's SMS infrastructure.

Features:
- Custom SMS provider using Emalify API
- System-wide integration (Sales, POS, Marketing, Appointments)
- Delivery status tracking via callbacks
- Configuration interface in Settings
- Test SMS wizard for verification
- Comprehensive logging and error handling

Configuration:
Go to Settings → General Settings → Emalify SMS to configure your API credentials.
    """,
    'depends': ['sms', 'iap', 'base'],
    'data': [
        'security/ir.model.access.csv',
        'data/sms_provider_data.xml',
        'views/res_config_settings_views.xml',
        'views/sms_emalify_delivery_views.xml',
        'wizard/sms_test_wizard_views.xml',
    ],
    'installable': True,
    'application': False,
    'auto_install': False,
    'license': 'LGPL-3',
}

