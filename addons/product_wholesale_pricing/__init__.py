from . import models


def post_init_hook(env):
    """Turn on pricelists and back-fill rules for anything already configured."""
    env['product.template']._wholesale_enable_pricelists()
    products = env['product.template'].search([('wholesale_price', '>', 0)])
    products._sync_wholesale_pricelist_item()
