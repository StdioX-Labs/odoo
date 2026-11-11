from . import models
from . import controllers

from odoo.addons.payment import reset_payment_provider, setup_provider


def post_init_hook(env):
    # Creates the `account.payment.method` for this provider. Without it,
    # account_payment's _create_payment() finds no inbound payment method line
    # on the journal and raises "Please define a payment method line on your
    # payment.", so a paid order can never produce a paid invoice.
    setup_provider(env, 'mpesa')


def uninstall_hook(env):
    """Remove the account.payment.method created for this provider."""
    reset_payment_provider(env, 'mpesa')
