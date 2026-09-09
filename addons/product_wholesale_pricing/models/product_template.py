import logging

from odoo import _, api, fields, models
from odoo.exceptions import ValidationError

_logger = logging.getLogger(__name__)

class ProductTemplate(models.Model):
    _inherit = 'product.template'

    wholesale_price = fields.Monetary(
        string="Wholesale Price",
        currency_field='currency_id',
        help="Unit price once the customer orders at least the wholesale minimum "
             "quantity. Leave at 0 to sell this product at the normal price only.",
    )
    wholesale_min_qty = fields.Float(
        string="Wholesale Min. Quantity",
        default=0.0,
        help="Order at least this many units and every unit on the line is charged "
             "at the wholesale price.",
    )

    @api.constrains('wholesale_price', 'wholesale_min_qty')
    def _check_wholesale_settings(self):
        for tmpl in self:
            if tmpl.wholesale_price and tmpl.wholesale_min_qty < 1:
                raise ValidationError(_(
                    "Set a wholesale minimum quantity of at least 1 for %s, otherwise "
                    "the wholesale price would apply to every single order.",
                    tmpl.display_name,
                ))
            if tmpl.wholesale_price and tmpl.wholesale_price > tmpl.list_price:
                raise ValidationError(_(
                    "The wholesale price for %s (%s) is higher than its normal price "
                    "(%s), so buying more would cost more per unit.",
                    tmpl.display_name, tmpl.wholesale_price, tmpl.list_price,
                ))

    # -- pricelist plumbing ----------------------------------------------------

    @api.model
    def _wholesale_enable_pricelists(self):
        """Pricelists are behind a settings group; a rule on a disabled feature is
        simply ignored at checkout, so make sure it is on."""
        group = self.env.ref('product.group_product_pricelist', raise_if_not_found=False)
        base_group = self.env.ref('base.group_user', raise_if_not_found=False)
        if group and base_group and group not in base_group.implied_ids:
            base_group.sudo().write({'implied_ids': [fields.Command.link(group.id)]})
            _logger.info("Wholesale pricing: enabled the pricelist feature")

    def _wholesale_get_pricelist(self):
        """The pricelist an anonymous shopper is served.

        Rules have to live on *that* pricelist: a separate "Wholesale" pricelist
        would only apply to customers who had it assigned, which is not what a
        public quantity break means.
        """
        self.ensure_one()
        Pricelist = self.env['product.pricelist'].sudo()
        website = self.env['website'].sudo().search(
            [('company_id', '=', self.company_id.id or self.env.company.id)], limit=1
        ) or self.env['website'].sudo().search([], limit=1)

        pricelist = Pricelist.search([('website_id', '=', website.id)], limit=1)
        if not pricelist:
            # Nothing set up yet (a shop that never used pricelists has none at all).
            pricelist = Pricelist.search([('website_id', '=', False)], limit=1)
        if not pricelist:
            pricelist = Pricelist.create({
                'name': 'Public Pricelist',
                'website_id': website.id,
                'selectable': True,
                'currency_id': (website.company_id or self.env.company).currency_id.id,
            })
            _logger.info("Wholesale pricing: created the Public Pricelist")
        return pricelist

    def _sync_wholesale_pricelist_item(self):
        """Mirror each product's wholesale settings onto a quantity-break rule."""
        Item = self.env['product.pricelist.item'].sudo()
        for tmpl in self:
            pricelist = tmpl._wholesale_get_pricelist()
            # `name` on a pricelist item is a computed display string, so it cannot
            # carry a marker. A real stored flag is what makes this idempotent.
            existing = Item.search([
                ('pricelist_id', '=', pricelist.id),
                ('product_tmpl_id', '=', tmpl.id),
                ('wholesale_auto', '=', True),
            ])

            if not tmpl.wholesale_price or tmpl.wholesale_min_qty < 1:
                existing.unlink()
                continue

            values = {
                'pricelist_id': pricelist.id,
                'applied_on': '1_product',
                'product_tmpl_id': tmpl.id,
                'compute_price': 'fixed',
                'fixed_price': tmpl.wholesale_price,
                'min_quantity': tmpl.wholesale_min_qty,
                'base': 'list_price',
                'wholesale_auto': True,
            }
            if existing:
                existing[0].write(values)
                existing[1:].unlink()
            else:
                Item.create(values)

    # -- keep the rules in step with the product ------------------------------

    @api.model_create_multi
    def create(self, vals_list):
        templates = super().create(vals_list)
        templates.filtered('wholesale_price')._sync_wholesale_pricelist_item()
        return templates

    def write(self, vals):
        res = super().write(vals)
        # list_price matters too: the rule is only valid while it undercuts it.
        if {'wholesale_price', 'wholesale_min_qty', 'list_price'} & set(vals):
            self._sync_wholesale_pricelist_item()
        return res
