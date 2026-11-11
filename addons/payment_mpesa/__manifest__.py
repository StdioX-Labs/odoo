{
    'name': 'Payment Provider: M-Pesa',
    'version': '1.1',
    'category': 'Accounting/Payment Providers',
    'sequence': 350,
    'summary': 'M-Pesa Payment Gateway for Safaricom Kenya',
    'description': """
M-Pesa Payment Provider
=======================
This module adds M-Pesa as a payment provider in Odoo.
Supports M-Pesa STK Push (Lipa Na M-Pesa Online) for seamless mobile payments.

Features:
- STK Push for instant mobile payment requests
- Works at eCommerce checkout, on portal invoices and for appointment bookings
- Paybill or Till (Buy Goods) accounts
- Payment status checking (callback, plus a cron fallback via STK Query)
- Transaction verification
- Support for Kenyan mobile numbers
    """,
    # account_payment supplies _setup_payment_method / _ensure_payment_method_line and the
    # account.payment reconciliation that marks an invoice paid.
    'depends': ['payment', 'account_payment'],
    'data': [
        'views/payment_mpesa_templates.xml',
        'views/payment_provider_views.xml',
        'data/payment_method_data.xml',
        'data/payment_provider_data.xml',
        'data/ir_cron.xml',
    ],
    'assets': {
        'web.assets_frontend': [
            'payment_mpesa/static/src/js/payment_form.js',
        ],
    },
    'application': False,
    'installable': True,
    'auto_install': False,
    'license': 'LGPL-3',
    'post_init_hook': 'post_init_hook',
    'uninstall_hook': 'uninstall_hook',
}
