"""Regression tests for PesaPal at the standard payment form (eCommerce checkout).

These cover the two blockers that made PesaPal unusable outside the appointments
flow. Both were silent: nothing raised server-side, the customer simply saw
"No payment method available" or a Pay button that did nothing.

No test here touches the network - the three PesaPal API calls are patched.
"""

from unittest.mock import patch

from odoo.tests import tagged
from odoo.tests.common import TransactionCase

_PATH = 'odoo.addons.payment_pesapal.models.payment_transaction.PaymentTransaction'

# A realistic PesaPal SubmitOrderRequest response: the redirect URL carries the
# OrderTrackingId in its query string, which is the detail that makes the plain
# GET form insufficient.
_TRACKING_ID = '59567e26-f5a4-4c14-a1e5-d9ecaf168f07'
_REDIRECT_URL = (
    'https://pay.pesapal.com/iframe/PesapalIframe3/Index'
    f'?OrderTrackingId={_TRACKING_ID}'
)


@tagged('post_install', '-at_install')
class TestPesapalCheckout(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.provider = cls.env.ref('payment_pesapal.payment_provider_pesapal')
        cls.method = cls.env.ref('payment_pesapal.payment_method_pesapal')

    # -- Blocker A: provider was invisible at checkout -------------------------

    def test_payment_method_is_linked_to_provider(self):
        """Without a linked payment.method, _get_compatible_payment_methods()
        filters PesaPal out and checkout renders "No payment method available"
        with no Pay button at all.

        post_init_hook also sets this link, but only runs on install, so a
        database that lost it could never self-heal. The link is declared in
        data XML precisely so that an upgrade restores it.
        """
        self.assertIn(
            self.method,
            self.provider.payment_method_ids,
            "PesaPal payment method must be linked to the provider, otherwise the "
            "provider is filtered out of checkout entirely.",
        )

    # -- Blocker B: Pay button did nothing ------------------------------------

    def test_provider_has_redirect_form_view(self):
        """_get_processing_values() guards the rendering call with
        `if redirect_form_view:`. With no view, _get_specific_rendering_values()
        never runs: no PesaPal order is created, redirect_form_html is absent,
        and the browser throws in _processRedirectFlow.
        """
        self.assertTrue(
            self.provider.redirect_form_view_id,
            "PesaPal needs a redirect form view or the payment flow silently "
            "skips provider rendering.",
        )

    def test_rendering_values_split_url_but_keep_redirect_url(self):
        """The redirect form submits with method="get", and browsers discard the
        query string of a GET form's action. For PesaPal that query string *is*
        the OrderTrackingId, so it has to travel as hidden inputs instead.

        `redirect_url` must survive unchanged: the appointments checkout reads
        that key directly and redirects on it.
        """
        tx = self._make_transaction()

        with patch(f'{_PATH}._pesapal_get_auth_token', return_value='tok'), \
             patch(f'{_PATH}._pesapal_register_ipn', return_value='ipn-id'), \
             patch(f'{_PATH}._pesapal_submit_order', return_value={
                 'order_tracking_id': _TRACKING_ID,
                 'merchant_reference': 'ODOO-1-123',
                 'redirect_url': _REDIRECT_URL,
             }):
            values = tx._get_specific_rendering_values({})

        # Consumed by the appointments flow.
        self.assertEqual(
            values['redirect_url'], _REDIRECT_URL,
            "redirect_url must stay byte-identical; the appointments controller "
            "redirects on it.",
        )
        # Consumed by the redirect form template.
        self.assertEqual(
            values['api_url'],
            'https://pay.pesapal.com/iframe/PesapalIframe3/Index',
            "api_url must be the bare URL, with no query string.",
        )
        self.assertEqual(
            values['url_params'], {'OrderTrackingId': _TRACKING_ID},
            "The tracking id must be carried as form params, or PesaPal receives "
            "a request it cannot attribute to an order.",
        )
        self.assertEqual(tx.pesapal_order_tracking_id, _TRACKING_ID)

    # -- Guard against the upgrade footgun ------------------------------------

    def test_provider_data_does_not_pin_operational_state(self):
        """The provider record carries noupdate=false, so it re-applies on every
        `-u payment_pesapal`. If the data file declared state or is_published,
        that upgrade - the very one used to ship a fix - would switch a live
        provider back to disabled and take payments offline.

        Asserted against the file itself: re-running the data load inside a test
        would not reproduce the failure, since the values would simply be rewritten
        to whatever the file says.
        """
        from pathlib import Path

        import odoo.modules

        data_file = Path(odoo.modules.get_module_path('payment_pesapal'),
                         'data', 'payment_provider_data.xml')
        content = data_file.read_text(encoding='utf-8')

        # Strip XML comments first - the file explains *why* these are absent.
        import re
        content = re.sub(r'<!--.*?-->', '', content, flags=re.DOTALL)

        for field in ('state', 'is_published'):
            self.assertNotIn(
                f'name="{field}"', content,
                f"payment_provider_data.xml must not declare {field!r}: the record "
                f"re-applies on upgrade and would reset a live provider.",
            )

    # -- helpers ---------------------------------------------------------------

    def _make_transaction(self):
        return self.env['payment.transaction'].create({
            'provider_id': self.provider.id,
            'payment_method_id': self.method.id,
            'partner_id': self.env.ref('base.partner_admin').id,
            'currency_id': self.env.company.currency_id.id,
            'amount': 100.0,
            'reference': 'TEST-PESAPAL-1',
        })
