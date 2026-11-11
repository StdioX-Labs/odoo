import logging
import re
from datetime import timedelta

from odoo import _, api, fields, models
from odoo.exceptions import ValidationError
from odoo.tools import hmac

_logger = logging.getLogger(__name__)

# ResultCode Daraja sends when the customer dismisses the STK prompt.
RESULT_CODE_CANCELLED = 1032


def normalize_phone(phone):
    """Return a Kenyan mobile number as 2547XXXXXXXX / 2541XXXXXXXX, or False."""
    digits = re.sub(r'\D', '', phone or '')
    if digits.startswith('0'):
        digits = '254' + digits[1:]
    elif len(digits) == 9 and digits[0] in '17':
        digits = '254' + digits
    if re.fullmatch(r'254[17]\d{8}', digits):
        return digits
    return False


class PaymentTransaction(models.Model):
    _inherit = 'payment.transaction'

    mpesa_checkout_request_id = fields.Char(
        string='M-Pesa Checkout Request ID',
        readonly=True,
        index='btree_not_null',
    )
    mpesa_phone_number = fields.Char(
        string='M-Pesa Phone Number',
        help='Phone number used for M-Pesa payment',
    )

    def _get_specific_processing_values(self, processing_values):
        res = super()._get_specific_processing_values(processing_values)
        if self.provider_code != 'mpesa':
            return res
        # Lets the checkout page trigger the STK Push for this transaction only. Same
        # token as payment.utils.generate_access_token(reference), which the route
        # checks, but built from self.env so it also works outside a request.
        return {'mpesa_access_token': hmac(self.env(su=True), 'generate_access_token', self.reference)}

    def _mpesa_initiate_stk_push(self, phone_number):
        """Send the STK Push prompt to the customer's phone.

        Raises ValidationError with a message fit for the customer when the phone
        number is invalid or M-Pesa refuses the request.
        """
        self.ensure_one()
        provider = self.provider_id
        phone = normalize_phone(phone_number)
        if not phone:
            raise ValidationError(_(
                "Enter a valid Safaricom number, e.g. 0712345678 or 254712345678."
            ))
        if self.state not in ('draft', 'pending'):
            raise ValidationError(_("This payment has already been processed."))

        password, timestamp = provider._mpesa_get_password()
        payload = {
            'BusinessShortCode': provider.mpesa_shortcode,
            'Password': password,
            'Timestamp': timestamp,
            'TransactionType': provider.mpesa_transaction_type or 'CustomerPayBillOnline',
            'Amount': round(self.amount),
            'PartyA': phone,
            'PartyB': (provider.mpesa_transaction_type == 'CustomerBuyGoodsOnline'
                       and provider.mpesa_till_number) or provider.mpesa_shortcode,
            'PhoneNumber': phone,
            'CallBackURL': provider.mpesa_callback_url,
            # Daraja limits: 12 characters for the reference, 13 for the description.
            'AccountReference': self.reference[:12],
            'TransactionDesc': 'Payment',
        }
        result = provider._mpesa_make_request('/mpesa/stkpush/v1/processrequest', payload)

        if str(result.get('ResponseCode')) != '0':
            message = result.get('errorMessage') or result.get('ResponseDescription')
            _logger.error("M-Pesa STK Push failed for %s: %s", self.reference, result)
            raise ValidationError(_("M-Pesa could not send the payment request: %s", message))

        self.write({
            'mpesa_checkout_request_id': result['CheckoutRequestID'],
            'mpesa_phone_number': phone,
        })
        self._set_pending()
        return True

    def _mpesa_query_stk_status(self):
        """Ask Daraja for the outcome of the STK Push, for when no callback arrived.

        :return: notification data for _handle_notification_data, or None while the
                 customer has not answered the prompt yet.
        """
        self.ensure_one()
        provider = self.provider_id
        password, timestamp = provider._mpesa_get_password()
        result = provider._mpesa_make_request('/mpesa/stkpushquery/v1/query', {
            'BusinessShortCode': provider.mpesa_shortcode,
            'Password': password,
            'Timestamp': timestamp,
            'CheckoutRequestID': self.mpesa_checkout_request_id,
        })
        if 'ResultCode' not in result:
            # e.g. errorCode 500.001.1001 "The transaction is being processed".
            return None
        return {
            'CheckoutRequestID': self.mpesa_checkout_request_id,
            'ResultCode': result['ResultCode'],
            'ResultDesc': result.get('ResultDesc'),
        }

    def _get_tx_from_notification_data(self, provider_code, notification_data):
        tx = super()._get_tx_from_notification_data(provider_code, notification_data)
        if provider_code != 'mpesa' or len(tx) == 1:
            return tx

        checkout_request_id = notification_data.get('CheckoutRequestID')
        tx = checkout_request_id and self.search([
            ('mpesa_checkout_request_id', '=', checkout_request_id),
            ('provider_code', '=', 'mpesa'),
        ], limit=1)
        if not tx:
            raise ValidationError(
                "M-Pesa: " + _("No transaction found matching CheckoutRequestID %s.",
                               checkout_request_id)
            )
        return tx

    def _process_notification_data(self, notification_data):
        super()._process_notification_data(notification_data)
        if self.provider_code != 'mpesa':
            return

        result_code = int(notification_data.get('ResultCode', -1))
        result_desc = notification_data.get('ResultDesc') or _("Payment failed.")
        if result_code == 0:
            if notification_data.get('MpesaReceiptNumber'):
                self.provider_reference = notification_data['MpesaReceiptNumber']
            paid = notification_data.get('Amount')
            if paid is not None and round(float(paid)) != round(self.amount):
                self._set_error(_(
                    "M-Pesa amount %(paid)s does not match the expected %(expected)s.",
                    paid=paid, expected=round(self.amount),
                ))
            else:
                self._set_done()
        elif result_code == RESULT_CODE_CANCELLED:
            self._set_canceled(state_message=result_desc)
        else:
            self._set_error(result_desc)

        self._mpesa_update_appointment()

    def _mpesa_update_appointment(self):
        """Mirror the payment outcome onto a booking from custom_appointments."""
        if 'custom.appointment' not in self.env:
            return
        for tx in self:
            appointment = self.env['custom.appointment'].sudo().search([
                ('payment_transaction_id', '=', tx.id)
            ], limit=1)
            if not appointment or appointment.payment_status == 'paid':
                continue
            if tx.state == 'done':
                appointment.write({
                    'payment_status': 'paid',
                    'paid_amount': tx.amount,
                    'payment_date': fields.Datetime.now(),
                    'payment_method': tx.provider_id.name,
                    'payment_reference': tx.reference,
                })
                try:
                    with self.env.cr.savepoint():
                        appointment.action_confirm()
                except Exception:
                    _logger.exception("M-Pesa: failed to confirm appointment %s", appointment.id)
            elif tx.state in ('cancel', 'error'):
                appointment.write({'payment_status': 'failed'})
                _logger.info("M-Pesa: payment failed for appointment %s: %s",
                             appointment.id, tx.state_message)

    @api.model
    def _cron_mpesa_check_pending(self):
        """Settle STK Pushes whose callback never reached us."""
        now = fields.Datetime.now()
        txs = self.search([
            ('provider_code', '=', 'mpesa'),
            ('state', '=', 'pending'),
            ('mpesa_checkout_request_id', '!=', False),
            ('last_state_change', '<=', now - timedelta(minutes=1)),
            ('last_state_change', '>=', now - timedelta(days=1)),
        ])
        for tx in txs:
            try:
                notification_data = tx._mpesa_query_stk_status()
                if notification_data:
                    tx._handle_notification_data('mpesa', notification_data)
                self.env.cr.commit()
            except Exception:
                self.env.cr.rollback()
                _logger.exception("M-Pesa: status check failed for %s", tx.reference)
