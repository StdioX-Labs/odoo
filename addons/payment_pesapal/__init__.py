from . import models
from . import controllers
import logging

from odoo.addons.payment import reset_payment_provider, setup_provider

_logger = logging.getLogger(__name__)


def uninstall_hook(env):
    """Remove the account.payment.method created for this provider."""
    reset_payment_provider(env, 'pesapal')


def post_init_hook(env):
    # Creates the `account.payment.method` for this provider. Without it,
    # account_payment's _create_payment() finds no inbound payment method line
    # on the journal and raises "Please define a payment method line on your
    # payment.", so a paid order can never produce a paid invoice.
    setup_provider(env, 'pesapal')
    """Link payment methods to providers after module installation"""
    pesapal_method = env['payment.method'].search([('code', '=', 'pesapal')], limit=1)
    if not pesapal_method:
        _logger.warning('PesaPal module: PesaPal payment method not found in database')
        return
    
    if not pesapal_method.active:
        pesapal_method.active = True
        _logger.info('PesaPal module: Activated pesapal payment method (ID: %s)', pesapal_method.id)
    
    pesapal_provider = env['payment.provider'].search([('code', '=', 'pesapal')], limit=1)
    if not pesapal_provider:
        _logger.warning('PesaPal module: PesaPal provider not found in database')
        return
    
    if pesapal_method not in pesapal_provider.payment_method_ids:
        pesapal_provider.write({'payment_method_ids': [(4, pesapal_method.id)]})
        _logger.info('PesaPal module: Linked PesaPal payment method to provider')
    else:
        _logger.info('PesaPal module: PesaPal payment method already linked to provider')
    
    card_method = env['payment.method'].search([('code', '=', 'card')], limit=1)
    if card_method:
        if not card_method.active:
            card_method.active = True
            _logger.info('PesaPal module: Activated card payment method (ID: %s)', card_method.id)
        
        if card_method not in pesapal_provider.payment_method_ids:
            pesapal_provider.write({'payment_method_ids': [(4, card_method.id)]})
            _logger.info('PesaPal module: Linked card payment method to provider')
    else:
        _logger.warning('PesaPal module: Card payment method not found in database')
