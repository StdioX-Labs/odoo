{
    'name': 'Product Wholesale Pricing',
    'version': '18.0.1.0',
    'category': 'Sales/Sales',
    'summary': 'Set a wholesale price and minimum quantity per product',
    'description': """
Wholesale pricing
=================
Adds a Wholesale Price and a Minimum Quantity to each product. Once a customer
orders at least that quantity, every unit on the line is charged at the
wholesale price; below it, the normal sales price applies.

This is a thin front-end over Odoo pricelists - each product's wholesale
settings are kept in sync with a quantity-break rule on the website pricelist.
Because it is a real pricelist rule, the break also applies to quotations and
the portal, not just the shop, and it stays visible and editable under
Sales > Products > Pricelists.
    """,
    'depends': ['website_sale'],
    'data': [
        'views/product_views.xml',
    ],
    'installable': True,
    'application': False,
    'auto_install': False,
    'license': 'LGPL-3',
    'post_init_hook': 'post_init_hook',
}
