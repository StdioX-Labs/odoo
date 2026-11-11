"""Bring an existing M-Pesa install up to the plug-and-play setup.

post_init_hook only runs on install, so a database that already has the module
needs the same plumbing back-filled here:

- setup_provider() creates the `account.payment.method` for M-Pesa, and each
  enabled provider gets its journal line. Without them a paid order cannot
  produce a paid invoice ("Please define a payment method line on your payment.").
- The old post_init_hook also linked the generic "card" method to M-Pesa, which
  showed a "Card" option at checkout that actually sent an STK Push. Unlink it.
- Daraja only calls back to a public https URL. Older installs stored one built
  from a bare http IP (http://185.217.127.226:8069//payment/mpesa/callback), so
  payment results never arrived. Replace it when the site itself has an https
  base URL; otherwise leave it and warn.

Both setup calls are idempotent.
"""

import logging

from odoo import SUPERUSER_ID, api
from odoo.addons.payment import setup_provider
from odoo.addons.payment_mpesa.models.payment_provider import CALLBACK_ROUTE

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})

    setup_provider(env, 'mpesa')

    card = env.ref('payment.payment_method_card', raise_if_not_found=False)
    providers = env['payment.provider'].search([('code', '=', 'mpesa')])
    for provider in providers:
        if card and card in provider.with_context(active_test=False).payment_method_ids:
            provider.payment_method_ids = [(3, card.id)]
            _logger.info("M-Pesa: unlinked the card payment method from %s", provider.name)

        if not (provider.mpesa_callback_url or '').startswith('https://'):
            base_url = provider.get_base_url()
            if base_url.startswith('https://'):
                provider.mpesa_callback_url = f'{base_url}{CALLBACK_ROUTE}'
                _logger.info("M-Pesa: callback URL set to %s", provider.mpesa_callback_url)
            else:
                _logger.warning(
                    "M-Pesa: callback URL %s is not https and Daraja will not call it. "
                    "Set it on the provider to https://<your domain>%s",
                    provider.mpesa_callback_url, CALLBACK_ROUTE)

        if provider.state == 'disabled':
            continue
        # A journal rejects two inbound lines with the same name, so only step in
        # when the line is genuinely absent.
        journal = provider.journal_id
        if journal and journal.inbound_payment_method_line_ids.filtered(
            lambda line: line.payment_provider_id == provider
        ):
            continue
        provider._ensure_payment_method_line()
        _logger.info("M-Pesa: created payment method line on journal %s",
                     provider.journal_id.display_name or '(none)')
