from odoo import fields, models


class ProductPricelistItem(models.Model):
    _inherit = 'product.pricelist.item'

    wholesale_auto = fields.Boolean(
        string="Managed by Wholesale Pricing",
        default=False,
        copy=False,
        help="Set on rules this module generates from a product's wholesale settings. "
             "Rules you create by hand are never touched.",
    )
