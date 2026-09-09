"""Back-fill the accounting plumbing on databases where the module is already
installed.

post_init_hook only runs on install, so a production database that predates
setup_provider() being called would never get an `account.payment.method` for
PesaPal. Without it, account_payment's _create_payment() finds no matching
inbound payment method line on the provider's journal and raises
"Please define a payment method line on your payment." -- the paid order then
fails to produce a paid invoice.

Both calls are idempotent: _setup_payment_method() no-ops when the method
already exists, and _ensure_payment_method_line() searches before creating.
"""

import logging

from odoo import SUPERUSER_ID, api
from odoo.addons.payment import setup_provider

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})

    setup_provider(env, 'pesapal')

    providers = env['payment.provider'].search([('code', '=', 'pesapal')])
    for provider in providers:
        # Only providers that are actually switched on need a journal line.
        if provider.state == 'disabled':
            continue
        if not hasattr(provider, '_ensure_payment_method_line'):
            # account_payment not in the registry yet; nothing to reconcile against.
            _logger.warning("PesaPal: account_payment not loaded, skipping journal line")
            continue

        # Odoo already creates the line itself when a provider is switched on, and
        # a journal rejects two inbound lines with the same name. Only step in when
        # the line is genuinely absent.
        journal = provider.journal_id
        if journal and journal.inbound_payment_method_line_ids.filtered(
            lambda line: line.payment_provider_id == provider
        ):
            _logger.info("PesaPal: payment method line already present on %s",
                         journal.display_name)
            continue

        provider._ensure_payment_method_line()
        _logger.info(
            "PesaPal: created payment method line on journal %s",
            provider.journal_id.display_name or '(none)',
        )
