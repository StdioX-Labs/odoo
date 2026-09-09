{
    'name': 'Payment Provider: PesaPal',
    'version': '1.1',
    'category': 'Accounting/Payment Providers',
    'sequence': 351,
    'summary': 'PesaPal Payment Gateway - Hosted Checkout',
    'description': """
PesaPal Payment Provider
=========================
This module adds PesaPal as a payment provider in Odoo.
Supports PesaPal Hosted Checkout for seamless payment processing.

Features:
- Hosted checkout page (PesaPal handles payment UI)
- Multiple payment methods (Cards, Mobile Money, etc.)
- IPN (Instant Payment Notification) support
- Transaction verification
- Support for multiple African countries
    """,
    # account_payment supplies _setup_payment_method / _ensure_payment_method_line and the
    # account.payment reconciliation that marks an invoice paid. Declaring it also
    # fixes module load order, so those methods exist when our migration runs.
    'depends': ['payment', 'account_payment'],
    'data': [
        'security/ir.model.access.csv',
        'views/payment_pesapal_templates.xml',
        'views/payment_provider_views.xml',
        'data/payment_method_data.xml',
        'data/payment_provider_data.xml',
    ],
    'assets': {
        'web.assets_frontend': [
            'payment_pesapal/static/src/js/payment_form.js',
        ],
    },
    'application': False,
    'installable': True,
    'auto_install': False,
    'license': 'LGPL-3',
    'post_init_hook': 'post_init_hook',
    'uninstall_hook': 'uninstall_hook',
}
