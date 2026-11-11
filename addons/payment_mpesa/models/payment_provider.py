import base64
import logging
from datetime import datetime

import pytz
import requests

from odoo import _, api, fields, models
from odoo.exceptions import ValidationError

_logger = logging.getLogger(__name__)

# Safaricom rejects result URLs containing words such as "mpesa" or "safaricom",
# so the default callback avoids them. /payment/mpesa/callback still works for
# providers configured with the older URL.
CALLBACK_ROUTE = '/payment/stk/callback'


class PaymentProvider(models.Model):
    _inherit = 'payment.provider'

    code = fields.Selection(
        selection_add=[('mpesa', 'M-Pesa')],
        ondelete={'mpesa': 'set default'}
    )

    mpesa_consumer_key = fields.Char(
        string='Consumer Key',
        required_if_provider='mpesa',
        groups='base.group_system',
    )
    mpesa_consumer_secret = fields.Char(
        string='Consumer Secret',
        required_if_provider='mpesa',
        groups='base.group_system',
    )
    mpesa_shortcode = fields.Char(
        string='Business Shortcode',
        required_if_provider='mpesa',
        help='Paybill number, or for a Till the store (head office) number used with the passkey',
    )
    mpesa_transaction_type = fields.Selection(
        string='Account Type',
        selection=[
            ('CustomerPayBillOnline', 'Paybill'),
            ('CustomerBuyGoodsOnline', 'Till Number (Buy Goods)'),
        ],
        default='CustomerPayBillOnline',
    )
    mpesa_till_number = fields.Char(
        string='Till Number',
        help='Till that receives the money. Leave empty if it is the same as the shortcode.',
    )
    mpesa_passkey = fields.Char(
        string='Passkey',
        required_if_provider='mpesa',
        groups='base.group_system',
        help='M-Pesa Online Passkey',
    )
    mpesa_callback_url = fields.Char(
        string='Callback URL',
        compute='_compute_mpesa_callback_url',
        store=True,
        readonly=False,
        help='URL where M-Pesa will send payment notifications. Auto-computed but can be overridden manually.',
    )

    @api.depends('code')
    def _compute_mpesa_callback_url(self):
        for provider in self:
            if provider.code == 'mpesa' and not provider.mpesa_callback_url:
                provider.mpesa_callback_url = f'{provider.get_base_url()}{CALLBACK_ROUTE}'
            elif provider.code != 'mpesa':
                provider.mpesa_callback_url = False

    def _get_supported_currencies(self):
        supported_currencies = super()._get_supported_currencies()
        if self.code == 'mpesa':
            supported_currencies = supported_currencies.filtered(lambda c: c.name == 'KES')
        return supported_currencies

    def _get_default_payment_method_codes(self):
        default_codes = super()._get_default_payment_method_codes()
        if self.code != 'mpesa':
            return default_codes
        return {'mpesa'}

    def _mpesa_get_api_url(self):
        self.ensure_one()
        if self.state == 'enabled':
            return 'https://api.safaricom.co.ke'
        else:
            return 'https://sandbox.safaricom.co.ke'

    def action_reset_callback_url(self):
        """Reset callback URL to the default computed value"""
        self.ensure_one()
        if self.code == 'mpesa':
            self.mpesa_callback_url = f'{self.get_base_url()}{CALLBACK_ROUTE}'
        return True

    def _mpesa_get_access_token(self):
        self.ensure_one()
        auth = base64.b64encode(
            f'{self.mpesa_consumer_key}:{self.mpesa_consumer_secret}'.encode()
        ).decode()
        try:
            response = requests.get(
                f'{self._mpesa_get_api_url()}/oauth/v1/generate?grant_type=client_credentials',
                headers={'Authorization': f'Basic {auth}'},
                timeout=10,
            )
            response.raise_for_status()
            return response.json()['access_token']
        except Exception as e:
            _logger.error("M-Pesa: Failed to get access token: %s", e)
            raise ValidationError(_("Failed to authenticate with M-Pesa. Please check your credentials."))

    def _mpesa_get_password(self):
        """Return (password, timestamp) for STK Push and STK Query requests.

        Daraja expects the timestamp in Kenyan time, not the server's UTC clock.
        """
        self.ensure_one()
        timestamp = datetime.now(pytz.timezone('Africa/Nairobi')).strftime('%Y%m%d%H%M%S')
        password = base64.b64encode(
            f'{self.mpesa_shortcode}{self.mpesa_passkey}{timestamp}'.encode()
        ).decode()
        return password, timestamp

    def _mpesa_make_request(self, endpoint, payload):
        """POST to a Daraja endpoint and return the decoded JSON body.

        Daraja answers business errors (bad phone, duplicate request, ...) with a
        4xx/5xx and a JSON body that explains them, so the body is returned rather
        than raising on the status code.
        """
        self.ensure_one()
        token = self._mpesa_get_access_token()
        try:
            response = requests.post(
                f'{self._mpesa_get_api_url()}{endpoint}',
                json=payload,
                headers={'Authorization': f'Bearer {token}'},
                timeout=30,
            )
            return response.json()
        except Exception as e:
            _logger.error("M-Pesa: request to %s failed: %s", endpoint, e)
            raise ValidationError(_("Could not reach M-Pesa. Please try again."))
