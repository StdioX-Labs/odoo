# -*- coding: utf-8 -*-
"""SMS must leave through the configured gateway on every Odoo path, and core
must still record the outcome (SMS state, marketing statistics, notifications).

The HTTP call to the gateway is patched throughout; nothing leaves the machine.
"""

from unittest import SkipTest
from unittest.mock import MagicMock, patch

from odoo.addons.sms.tools.sms_api import SmsApi
from odoo.addons.sms_emalify.tools.sms_api import SmsApiEmalify
from odoo.tests import tagged
from odoo.tests.common import TransactionCase

REQUESTS_POST = 'odoo.addons.sms_emalify.models.sms_api.requests.post'


def vidatech_ok(unique_id='vt-1'):
    """What Vidatech returns for one accepted message."""
    response = MagicMock(content=b'[]')
    response.raise_for_status.return_value = None
    response.json.return_value = [{'status': True, 'data': {'uniqueId': unique_id}}]
    return response


class SmsGatewayCase(TransactionCase):
    """Vidatech configured and switched on."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.params = cls.env['ir.config_parameter'].sudo()
        cls._set_gateway(enabled=True)

    @classmethod
    def _set_gateway(cls, enabled=True, token='test-token'):
        for key, value in {
            'sms_emalify.enabled': 'True' if enabled else 'False',
            'sms_emalify.provider': 'vidatech',
            'sms_emalify.vidatech_token': token,
            'sms_emalify.vidatech_sender': 'LashByShazz',
        }.items():
            cls.params.set_param(key, value)

    def _create_sms(self, number='0712345678', **vals):
        return self.env['sms.sms'].create({'number': number, 'body': 'Hello', 'state': 'outgoing', **vals})


@tagged('post_install', '-at_install')
class TestSmsRouting(SmsGatewayCase):

    # -- which API is used ----------------------------------------------------

    def test_company_api_class_follows_setting(self):
        """Flows that talk to the SMS API directly (the marketing Test button)
        ask the company for the class."""
        self.assertIs(self.env.company._get_sms_api_class(), SmsApiEmalify)
        self._set_gateway(enabled=False)
        self.assertIs(self.env.company._get_sms_api_class(), SmsApi)

    def test_queue_routes_through_gateway(self):
        """send() and the SMS queue cron pick their API via _split_by_api, which
        in core is hard-wired to Odoo IAP."""
        sms = self.env['sms.sms'].new({'number': '0712345678', 'body': 'x'})
        (api, _records), = list(sms._split_by_api())
        self.assertIsInstance(api, SmsApiEmalify)

    # -- transactional SMS ----------------------------------------------------

    def test_transactional_sms_leaves_at_once(self):
        """Appointment confirmations are created as outgoing and must not wait for
        the queue cron."""
        with patch(REQUESTS_POST, return_value=vidatech_ok('vt-42')) as post:
            sms = self._create_sms()

        post.assert_called_once()
        payload = post.call_args.kwargs['json']
        self.assertEqual(payload[0]['phone'], '254712345678')
        self.assertEqual(payload[0]['sender'], 'LashByShazz')
        # 'success' from the adapter is core's "Sent" (pending delivery receipt).
        self.assertEqual(sms.state, 'pending')

        delivery = self.env['sms.emalify.delivery'].search([('sms_uuid', '=', sms.uuid)])
        self.assertEqual(delivery.emalify_message_id, 'vt-42')
        self.assertEqual(delivery.status, 'sent')

    def test_gateway_off_leaves_sms_to_odoo(self):
        self._set_gateway(enabled=False)
        with patch(REQUESTS_POST) as post:
            sms = self._create_sms()
        post.assert_not_called()
        self.assertEqual(sms.state, 'outgoing')

    def test_same_sms_is_never_sent_twice(self):
        """Any path that re-submits an already-accepted uuid is a no-op."""
        with patch(REQUESTS_POST, return_value=vidatech_ok()) as post:
            sms = self._create_sms()
            result = SmsApiEmalify(self.env)._send_sms_batch(
                [{'content': 'Hello', 'numbers': [{'number': sms.number, 'uuid': sms.uuid}]}])
        post.assert_called_once()
        self.assertEqual(result, [{'uuid': sms.uuid, 'state': 'success'}])

    # -- failures ---------------------------------------------------------------

    def test_gateway_error_is_reported(self):
        with patch(REQUESTS_POST, side_effect=Exception('Vidatech is down')):
            sms = self._create_sms()
        self.assertEqual(sms.state, 'error')
        self.assertEqual(sms.failure_type, 'sms_server')

    def test_missing_credentials_do_not_ask_for_odoo_credits(self):
        """sms_credit would make the UI offer to buy Odoo IAP credits, which is
        exactly the wrong advice when the fix is to configure the gateway."""
        self._set_gateway(token='')
        with patch(REQUESTS_POST) as post:
            sms = self._create_sms()
        post.assert_not_called()
        self.assertEqual(sms.state, 'error')
        self.assertEqual(sms.failure_type, 'sms_server')

    def test_unusable_number_is_reported(self):
        with patch(REQUESTS_POST) as post:
            sms = self._create_sms(number='123')
        post.assert_not_called()
        self.assertEqual(sms.failure_type, 'sms_number_format')


@tagged('post_install', '-at_install')
class TestSmsMarketingRouting(SmsGatewayCase):
    """SMS Marketing campaigns and their statistics. sms_emalify does not depend
    on SMS Marketing, so these only run where it is installed."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        if 'mailing.sms.test' not in cls.env:
            raise SkipTest('SMS Marketing (mass_mailing_sms) is not installed')
        cls.partner = cls.env['res.partner'].create({
            'name': 'Campaign Recipient',
            'phone': '+254712345678',
            'country_id': cls.env.ref('base.ke').id,
        })
        cls.mailing = cls.env['mailing.mailing'].create({
            'name': 'Promo',
            'subject': 'Promo',
            'mailing_type': 'sms',
            'body_plaintext': 'New lash sets this week',
            'mailing_model_id': cls.env['ir.model']._get_id('res.partner'),
            'mailing_domain': repr([('id', '=', cls.partner.id)]),
            'sms_allow_unsubscribe': False,
        })

    def _campaign_traces(self):
        return self.env['mailing.trace'].search([('mass_mailing_id', '=', self.mailing.id)])

    def test_campaign_goes_through_gateway_and_updates_statistics(self):
        with patch(REQUESTS_POST, return_value=vidatech_ok('vt-camp')) as post:
            self.mailing.action_send_sms()
            queued = self.env['sms.sms'].search([('mailing_id', '=', self.mailing.id)])
            # Marketing SMS wait for the queue rather than leaving on create.
            post.assert_not_called()
            self.assertTrue(queued)
            queued.send()

        post.assert_called_once()
        trace = self._campaign_traces()
        self.assertEqual(trace.trace_status, 'pending', "campaign should count it as Sent")
        self.assertTrue(trace.sent_datetime)

        # Vidatech's delivery receipt turns "Sent" into "Delivered".
        self.env['sms.emalify.delivery'].update_delivery_status(
            emalify_message_id='vt-camp', status='delivered')
        self.assertEqual(trace.trace_status, 'sent', "campaign should count it as Delivered")

    def test_test_button_goes_through_gateway_once(self):
        """The Test button calls the SMS API directly; before the gateway was
        plugged in at that level it went to Odoo IAP."""
        with patch(REQUESTS_POST, return_value=vidatech_ok()) as post:
            self.env['mailing.sms.test'].create({
                'mailing_id': self.mailing.id,
                'numbers': '+254712345678',
            }).action_send_sms()

        post.assert_called_once()
        log = self.mailing.message_ids[:1].body
        self.assertIn('successfully sent', log)
