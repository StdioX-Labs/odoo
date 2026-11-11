import logging
import pprint

from werkzeug.exceptions import Forbidden

from odoo import _, http
from odoo.exceptions import ValidationError
from odoo.http import request
from odoo.addons.payment import utils as payment_utils

_logger = logging.getLogger(__name__)


def parse_stk_callback(payload):
    """Flatten Daraja's STK callback body into notification data.

    {"Body": {"stkCallback": {"CheckoutRequestID": ..., "ResultCode": 0,
     "CallbackMetadata": {"Item": [{"Name": "Amount", "Value": 1}, ...]}}}}
    becomes {"CheckoutRequestID": ..., "ResultCode": 0, "Amount": 1, ...}.
    """
    stk_callback = (payload or {}).get('Body', {}).get('stkCallback', {})
    data = {key: value for key, value in stk_callback.items() if key != 'CallbackMetadata'}
    for item in stk_callback.get('CallbackMetadata', {}).get('Item', []):
        if 'Value' in item:
            data[item['Name']] = item['Value']
    return data


class MpesaController(http.Controller):

    # Daraja posts plain JSON, not JSON-RPC, so this must be an http route: a
    # type='json' route would look for a "params" key and receive nothing.
    @http.route(
        ['/payment/stk/callback', '/payment/mpesa/callback'],
        type='http', auth='public', methods=['POST'], csrf=False, save_session=False,
    )
    def mpesa_callback(self, **_kwargs):
        payload = request.get_json_data()
        _logger.info('M-Pesa: callback received:\n%s', pprint.pformat(payload))
        notification_data = parse_stk_callback(payload)
        try:
            request.env['payment.transaction'].sudo()._handle_notification_data(
                'mpesa', notification_data
            )
        except ValidationError:
            _logger.exception('M-Pesa: unable to handle callback')
        # Daraja does not retry, so always acknowledge.
        return request.make_json_response({'ResultCode': 0, 'ResultDesc': 'Accepted'})

    @http.route('/payment/mpesa/stk_push', type='json', auth='public')
    def mpesa_stk_push(self, reference, access_token, phone_number):
        """Send the STK prompt for a checkout transaction (eCommerce, invoices)."""
        if not payment_utils.check_access_token(access_token, reference):
            raise Forbidden()
        tx = request.env['payment.transaction'].sudo().search([
            ('reference', '=', reference), ('provider_code', '=', 'mpesa'),
        ], limit=1)
        if not tx:
            raise ValidationError(_("Payment not found."))
        tx._mpesa_initiate_stk_push(phone_number)
