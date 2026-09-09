import logging
import requests
import base64
from datetime import datetime
from urllib.parse import parse_qsl, urlparse, urlunsplit

from odoo import _, api, fields, models
from odoo.exceptions import ValidationError

_logger = logging.getLogger(__name__)


class PaymentTransaction(models.Model):
    _inherit = 'payment.transaction'

    pesapal_order_tracking_id = fields.Char(
        string='PesaPal Order Tracking ID',
        help='Unique identifier for the PesaPal transaction'
    )
    pesapal_merchant_reference = fields.Char(
        string='PesaPal Merchant Reference',
        help='Merchant reference for the transaction'
    )

    def _get_specific_rendering_values(self, processing_values):
        """Override to add PesaPal-specific rendering values"""
        res = super()._get_specific_rendering_values(processing_values)
        if self.provider_code != 'pesapal':
            return res

        token = self._pesapal_get_auth_token()
        if not token:
            raise ValidationError(_('Failed to authenticate with PesaPal. Please check your credentials.'))

        ipn_id = self._pesapal_register_ipn(token)
        
        order_data = self._pesapal_submit_order(token, ipn_id, processing_values)
        
        if order_data and order_data.get('redirect_url'):
            self.pesapal_order_tracking_id = order_data.get('order_tracking_id')
            self.pesapal_merchant_reference = order_data.get('merchant_reference')

            redirect_url = order_data['redirect_url']
            parsed = urlparse(redirect_url)
            res.update({
                # Kept as-is: the appointments checkout reads this key directly and
                # redirects on it itself, without going through the payment form.
                'redirect_url': redirect_url,
                # Used by the redirect form template. A GET form drops the query
                # string of its action, so the params travel as hidden inputs.
                'api_url': urlunsplit((parsed.scheme, parsed.netloc, parsed.path, '', '')),
                'url_params': dict(parse_qsl(parsed.query)),
            })
        else:
            raise ValidationError(_('Failed to create PesaPal payment. Please try again.'))

        return res

    def _pesapal_get_auth_token(self):
        """Get authentication token from PesaPal"""
        api_url = self.provider_id._pesapal_get_api_url()
        auth_url = f'{api_url}/api/Auth/RequestToken'
        
        payload = {
            'consumer_key': self.provider_id.pesapal_consumer_key,
            'consumer_secret': self.provider_id.pesapal_consumer_secret
        }
        
        try:
            response = requests.post(auth_url, json=payload, headers={'Content-Type': 'application/json'})
            response.raise_for_status()
            data = response.json()
            return data.get('token')
        except Exception as e:
            _logger.error('PesaPal authentication failed: %s', str(e))
            return None

    def _pesapal_register_ipn(self, token):
        """Register IPN URL with PesaPal"""
        api_url = self.provider_id._pesapal_get_api_url()
        ipn_url = f'{api_url}/api/URLSetup/RegisterIPN'
        
        payload = {
            'url': self.provider_id.pesapal_ipn_url,
            'ipn_notification_type': 'GET'
        }
        
        headers = {
            'Authorization': f'Bearer {token}',
            'Content-Type': 'application/json'
        }
        
        try:
            response = requests.post(ipn_url, json=payload, headers=headers)
            response.raise_for_status()
            data = response.json()
            return data.get('ipn_id')
        except Exception as e:
            _logger.warning('PesaPal IPN registration failed: %s', str(e))
            return None

    def _pesapal_submit_order(self, token, ipn_id, processing_values):
        """Submit order to PesaPal for payment"""
        api_url = self.provider_id._pesapal_get_api_url()
        submit_url = f'{api_url}/api/Transactions/SubmitOrderRequest'
        
        merchant_ref = f'ODOO-{self.id}-{int(datetime.now().timestamp())}'
        
        payload = {
            'id': merchant_ref,
            'currency': self.currency_id.name,
            'amount': self.amount,
            'description': self.reference or 'Payment',
            'callback_url': f'{self.provider_id.get_base_url()}/payment/pesapal/return',
            'notification_id': ipn_id,
            'billing_address': {
                'email_address': self.partner_email or self.partner_id.email,
                'phone_number': self.partner_phone or self.partner_id.phone or '',
                'country_code': self.partner_country_id.code or 'KE',
                'first_name': self.partner_name or self.partner_id.name or 'Customer',
                'middle_name': '',
                'last_name': '',
                'line_1': self.partner_address or '',
                'line_2': '',
                'city': self.partner_city or '',
                'state': '',
                'postal_code': self.partner_zip or '',
                'zip_code': self.partner_zip or ''
            }
        }
        
        headers = {
            'Authorization': f'Bearer {token}',
            'Content-Type': 'application/json'
        }
        
        try:
            response = requests.post(submit_url, json=payload, headers=headers)
            response.raise_for_status()
            data = response.json()
            
            _logger.info('PesaPal order submitted: %s', data)
            
            redirect_url = data.get('redirect_url', '')
            if redirect_url and redirect_url.startswith('/'):
                pesapal_base = api_url.replace('/pesapalv3', '').replace('/v3', '')
                redirect_url = f'{pesapal_base}{redirect_url}'
            
            return {
                'order_tracking_id': data.get('order_tracking_id'),
                'merchant_reference': data.get('merchant_reference'),
                'redirect_url': redirect_url
            }
        except Exception as e:
            _logger.error('PesaPal order submission failed: %s', str(e))
            return None

    def _get_tx_from_notification_data(self, provider_code, notification_data):
        """Override to handle PesaPal notification data"""
        tx = super()._get_tx_from_notification_data(provider_code, notification_data)
        if provider_code != 'pesapal' or len(tx) == 1:
            return tx

        tracking_id = notification_data.get('OrderTrackingId')
        merchant_ref = notification_data.get('OrderMerchantReference')
        
        if tracking_id:
            tx = self.search([('pesapal_order_tracking_id', '=', tracking_id)])
        elif merchant_ref:
            tx = self.search([('pesapal_merchant_reference', '=', merchant_ref)])
        
        if not tx:
            raise ValidationError(_('PesaPal: No transaction found for tracking ID %s', tracking_id))
        
        return tx

    def _process_notification_data(self, notification_data):
        """Process PesaPal notification data"""
        super()._process_notification_data(notification_data)
        if self.provider_code != 'pesapal':
            return

        status_code = notification_data.get('status_code')
        
        if status_code == 1:  # Completed
            self._set_done()
        elif status_code == 2:  # Failed
            self._set_canceled()
        elif status_code == 3:  # Reversed
            self._set_canceled()
        else:  # Pending or unknown
            self._set_pending()
