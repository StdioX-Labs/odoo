{
    'name': 'Website Sale: Checkout Tweaks',
    'version': '18.0.1.0',
    'category': 'Website/Website',
    'summary': 'Trims and tidies the eCommerce checkout address form',
    'description': """
Checkout tweaks
===============
Removes B2B fields that a consumer checkout does not need (company name, VAT,
apartment line) and tightens the styling of the address form and the payment
method picker.

Everything here is presentation only - no field is made optional or required,
so server-side validation is untouched.
    """,
    'depends': ['website_sale'],
    'data': [
        'views/checkout_templates.xml',
    ],
    'assets': {
        'web.assets_frontend': [
            'website_sale_lbs/static/src/scss/checkout.scss',
        ],
    },
    'installable': True,
    'application': False,
    'auto_install': False,
    'license': 'LGPL-3',
}
