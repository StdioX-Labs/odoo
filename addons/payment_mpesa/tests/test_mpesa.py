"""M-Pesa (Daraja STK Push) at checkout, on callbacks and for appointments.

No test here touches the network - Daraja requests are patched.
"""

import re
from pathlib import Path
from unittest.mock import patch

import odoo.modules
from odoo.exceptions import ValidationError
from odoo.tests import tagged
from odoo.tests.common import TransactionCase

from odoo.addons.payment_mpesa.controllers.main import parse_stk_callback
from odoo.addons.payment_mpesa.models.payment_transaction import normalize_phone

_REQUEST = 'odoo.addons.payment_mpesa.models.payment_provider.PaymentProvider._mpesa_make_request'
_CHECKOUT_ID = 'ws_CO_11112026101010123456789'

_STK_ACCEPTED = {
    'MerchantRequestID': '29115-34620561-1',
    'CheckoutRequestID': _CHECKOUT_ID,
    'ResponseCode': '0',
    'ResponseDescription': 'Success. Request accepted for processing',
    'CustomerMessage': 'Success. Request accepted for processing',
}


def _callback(result_code, amount=1500, desc='The service request is processed successfully.'):
    stk = {
        'MerchantRequestID': '29115-34620561-1',
        'CheckoutRequestID': _CHECKOUT_ID,
        'ResultCode': result_code,
        'ResultDesc': desc,
    }
    if result_code == 0:
        stk['CallbackMetadata'] = {'Item': [
            {'Name': 'Amount', 'Value': amount},
            {'Name': 'MpesaReceiptNumber', 'Value': 'TKB1XYZ123'},
            {'Name': 'Balance'},
            {'Name': 'TransactionDate', 'Value': 20261111101530},
            {'Name': 'PhoneNumber', 'Value': 254712345678},
        ]}
    return {'Body': {'stkCallback': stk}}


@tagged('post_install', '-at_install')
class TestMpesa(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.provider = cls.env.ref('payment_mpesa.payment_provider_mpesa')
        cls.provider.write({
            'state': 'test',
            'mpesa_consumer_key': 'key',
            'mpesa_consumer_secret': 'secret',
            'mpesa_shortcode': '174379',
            'mpesa_passkey': 'passkey',
        })
        cls.method = cls.env.ref('payment_mpesa.payment_method_mpesa')
        cls.kes = cls.env.ref('base.KES')
        cls.kes.active = True

    def _tx(self, reference='S00042-1', amount=1500.0):
        return self.env['payment.transaction'].create({
            'provider_id': self.provider.id,
            'payment_method_id': self.method.id,
            'partner_id': self.env.ref('base.partner_admin').id,
            'currency_id': self.kes.id,
            'amount': amount,
            'reference': reference,
        })

    def _pushed_tx(self, **kw):
        tx = self._tx(**kw)
        with patch(_REQUEST, return_value=_STK_ACCEPTED):
            tx._mpesa_initiate_stk_push('0712 345 678')
        return tx

    def _notify(self, payload):
        return self.env['payment.transaction']._handle_notification_data(
            'mpesa', parse_stk_callback(payload))

    # -- Checkout wiring -------------------------------------------------------

    def test_payment_method_is_linked_to_provider(self):
        self.assertIn(self.method, self.provider.payment_method_ids)

    def test_card_method_is_not_linked(self):
        """The old install hook linked "card", showing a Card option that sent an STK Push."""
        self.assertFalse(self.provider.payment_method_ids.filtered(lambda m: m.code == 'card'))

    def test_provider_has_inline_form(self):
        """The inline form carries the phone field and makes checkout use the direct flow."""
        self.assertTrue(self.provider.inline_form_view_id)

    def test_only_kes_supported(self):
        self.assertEqual(self.provider._get_supported_currencies(), self.kes)

    def test_processing_values_carry_access_token(self):
        tx = self._tx()
        values = tx._get_specific_processing_values({})
        self.assertIn('mpesa_access_token', values)

    def test_provider_data_does_not_pin_operational_state(self):
        """Declaring state/is_published would reset a live provider on every upgrade."""
        path = Path(odoo.modules.get_module_path('payment_mpesa'),
                    'data', 'payment_provider_data.xml')
        content = re.sub(r'<!--.*?-->', '', path.read_text(), flags=re.DOTALL)
        for field in ('state', 'is_published'):
            self.assertNotIn(f'name="{field}"', content)

    def test_default_callback_url_avoids_blocked_keywords(self):
        self.provider.mpesa_callback_url = False
        self.provider.action_reset_callback_url()
        self.assertNotIn('mpesa', self.provider.mpesa_callback_url.lower())

    # -- STK Push --------------------------------------------------------------

    def test_normalize_phone(self):
        for raw in ('0712345678', '+254 712 345 678', '254712345678', '712345678',
                    '0712-345-678'):
            self.assertEqual(normalize_phone(raw), '254712345678', raw)
        self.assertEqual(normalize_phone('0110345678'), '254110345678')
        for raw in ('', None, '12345', '0812345678', '2547123456789'):
            self.assertFalse(normalize_phone(raw), raw)

    def test_stk_push_payload(self):
        tx = self._tx(reference='APPT-170-1762850000', amount=1500.0)
        with patch(_REQUEST, return_value=_STK_ACCEPTED) as request:
            tx._mpesa_initiate_stk_push('0712345678')
        endpoint, payload = request.call_args.args
        self.assertEqual(endpoint, '/mpesa/stkpush/v1/processrequest')
        self.assertEqual(payload['PhoneNumber'], '254712345678')
        self.assertEqual(payload['PartyA'], '254712345678')
        self.assertEqual(payload['Amount'], 1500)
        self.assertEqual(payload['TransactionType'], 'CustomerPayBillOnline')
        self.assertEqual(payload['PartyB'], '174379')
        self.assertLessEqual(len(payload['AccountReference']), 12)
        self.assertLessEqual(len(payload['TransactionDesc']), 13)
        self.assertEqual(tx.mpesa_checkout_request_id, _CHECKOUT_ID)
        self.assertEqual(tx.state, 'pending')

    def test_stk_push_till_sends_to_till_number(self):
        self.provider.write({
            'mpesa_transaction_type': 'CustomerBuyGoodsOnline',
            'mpesa_till_number': '5123456',
        })
        tx = self._tx()
        with patch(_REQUEST, return_value=_STK_ACCEPTED) as request:
            tx._mpesa_initiate_stk_push('0712345678')
        payload = request.call_args.args[1]
        self.assertEqual(payload['TransactionType'], 'CustomerBuyGoodsOnline')
        self.assertEqual(payload['BusinessShortCode'], '174379')
        self.assertEqual(payload['PartyB'], '5123456')

    def test_stk_push_rejects_bad_phone_without_calling_daraja(self):
        tx = self._tx()
        with patch(_REQUEST) as request, self.assertRaises(ValidationError):
            tx._mpesa_initiate_stk_push('12345')
        request.assert_not_called()
        self.assertEqual(tx.state, 'draft')

    def test_stk_push_surfaces_daraja_error(self):
        tx = self._tx()
        error = {'requestId': '1', 'errorCode': '400.002.02',
                 'errorMessage': 'Bad Request - Invalid PhoneNumber'}
        with patch(_REQUEST, return_value=error), \
                self.assertRaisesRegex(ValidationError, 'Invalid PhoneNumber'):
            tx._mpesa_initiate_stk_push('0712345678')
        self.assertEqual(tx.state, 'draft')

    # -- Callback --------------------------------------------------------------

    def test_parse_stk_callback(self):
        data = parse_stk_callback(_callback(0))
        self.assertEqual(data['CheckoutRequestID'], _CHECKOUT_ID)
        self.assertEqual(data['ResultCode'], 0)
        self.assertEqual(data['MpesaReceiptNumber'], 'TKB1XYZ123')
        self.assertEqual(data['Amount'], 1500)
        self.assertNotIn('Balance', data)

    def test_successful_callback_marks_done(self):
        tx = self._pushed_tx()
        self._notify(_callback(0))
        self.assertEqual(tx.state, 'done')
        self.assertEqual(tx.provider_reference, 'TKB1XYZ123')

    def test_underpaid_callback_is_an_error(self):
        tx = self._pushed_tx()
        self._notify(_callback(0, amount=1))
        self.assertEqual(tx.state, 'error')

    def test_cancelled_prompt_cancels(self):
        tx = self._pushed_tx()
        self._notify(_callback(1032, desc='Request cancelled by user'))
        self.assertEqual(tx.state, 'cancel')

    def test_failed_payment_is_an_error(self):
        tx = self._pushed_tx()
        self._notify(_callback(1, desc='The balance is insufficient for the transaction.'))
        self.assertEqual(tx.state, 'error')
        self.assertIn('insufficient', tx.state_message)

    def test_unknown_checkout_request_raises(self):
        with self.assertRaises(ValidationError):
            self.env['payment.transaction']._handle_notification_data(
                'mpesa', {'CheckoutRequestID': 'nope', 'ResultCode': 0})

    # -- Fallback when no callback arrives --------------------------------------

    def test_cron_settles_pending_via_stk_query(self):
        tx = self._pushed_tx()
        # The cron only queries STK Pushes older than a minute and younger than a day.
        self.env.cr.execute(
            "UPDATE payment_transaction SET last_state_change = now() at time zone 'utc'"
            " - interval '5 minutes' WHERE id = %s", [tx.id])
        tx.invalidate_recordset(['last_state_change'])
        query = {'ResponseCode': '0', 'CheckoutRequestID': _CHECKOUT_ID,
                 'ResultCode': '0', 'ResultDesc': 'The service request is processed successfully.'}
        with patch(_REQUEST, return_value=query), \
                patch.object(self.env.cr, 'commit'):
            self.env['payment.transaction']._cron_mpesa_check_pending()
        self.assertEqual(tx.state, 'done')

    def test_stk_query_still_processing_leaves_pending(self):
        tx = self._pushed_tx()
        processing = {'errorCode': '500.001.1001',
                      'errorMessage': 'The transaction is being processed'}
        with patch(_REQUEST, return_value=processing):
            self.assertIsNone(tx._mpesa_query_stk_status())
        self.assertEqual(tx.state, 'pending')


@tagged('post_install', '-at_install')
class TestMpesaAppointment(TransactionCase):
    """A paid STK Push confirms the booking it pays for (custom_appointments)."""

    def setUp(self):
        super().setUp()
        if 'custom.appointment' not in self.env:
            self.skipTest('custom_appointments not installed')
        provider = self.env.ref('payment_mpesa.payment_provider_mpesa')
        provider.write({
            'state': 'test', 'mpesa_consumer_key': 'k', 'mpesa_consumer_secret': 's',
            'mpesa_shortcode': '174379', 'mpesa_passkey': 'p',
        })
        kes = self.env.ref('base.KES')
        kes.active = True
        branch = self.env['custom.branch'].create({'name': 'Westlands'})
        staff = self.env['custom.staff.member'].create({
            'name': 'Aisha', 'branch_id': branch.id,
            'email': 'aisha@salon.test', 'phone': '254700000001',
        })
        category = self.env['service.category'].create({'name': 'Lashes'})
        service = self.env['company.service'].create({
            'name': 'Volume Set', 'category_id': category.id,
            'price': 1500.0, 'duration': 1.0,
        })
        self.appointment = self.env['custom.appointment'].create({
            'customer_name': 'Wanjiru',
            'customer_email': 'wanjiru@example.test',
            'customer_phone': '254724512285',
            'service_id': service.id,
            'staff_member_id': staff.id,
            'branch_id': branch.id,
            'start': '2030-01-01 09:00:00',
            'stop': '2030-01-01 10:00:00',
            'duration': 1.0,
        })
        self.tx = self.env['payment.transaction'].create({
            'provider_id': provider.id,
            'payment_method_id': self.env.ref('payment_mpesa.payment_method_mpesa').id,
            'partner_id': self.env.ref('base.partner_admin').id,
            'currency_id': kes.id,
            'amount': 1500.0,
            'reference': 'APPT-1-1762850000',
        })
        self.appointment.payment_transaction_id = self.tx
        with patch(_REQUEST, return_value=_STK_ACCEPTED):
            self.tx._mpesa_initiate_stk_push('0712345678')

    def _notify(self, payload):
        self.env['payment.transaction']._handle_notification_data(
            'mpesa', parse_stk_callback(payload))

    def test_paid_callback_confirms_appointment(self):
        with patch.object(type(self.appointment), 'action_confirm', autospec=True) as confirm:
            self._notify(_callback(0))
        self.assertEqual(self.appointment.payment_status, 'paid')
        self.assertEqual(self.appointment.paid_amount, 1500.0)
        confirm.assert_called_once()

    def test_failed_callback_marks_appointment_failed(self):
        self._notify(_callback(1032, desc='Request cancelled by user'))
        self.assertEqual(self.appointment.payment_status, 'failed')
