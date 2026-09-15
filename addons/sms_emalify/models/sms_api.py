# -*- coding: utf-8 -*-

import logging
import requests
import re
from odoo import api, models, _
from odoo.exceptions import UserError

from odoo.addons.sms_emalify.tools.sms_api import SmsApiEmalify

_logger = logging.getLogger(__name__)


class SmsSms(models.Model):
    _inherit = 'sms.sms'

    @api.model
    def _emalify_enabled(self):
        return self.env['ir.config_parameter'].sudo().get_param('sms_emalify.enabled', 'False') == 'True'

    @api.model_create_multi
    def create(self, vals_list):
        """Send transactional SMS the moment they are created.

        Appointment confirmations and reminders are created straight into the
        ``outgoing`` state and are expected to leave immediately rather than wait
        for the SMS queue cron. Marketing SMS carry a ``mailing_id`` and are left to
        that cron, which sends them in batches and commits between each one.

        This goes through core ``send()`` so the gateway is reached via
        ``_split_by_api`` and core records the outcome on the SMS, its chatter
        notification and any marketing trace.
        """
        records = super().create(vals_list)
        if self._emalify_enabled():
            has_mailing = 'mailing_id' in records._fields
            immediate = records.filtered(
                lambda s: s.state == 'outgoing' and not (has_mailing and s.mailing_id)
            )
            if immediate:
                immediate.send(unlink_failed=False, unlink_sent=True,
                               auto_commit=False, raise_exception=False)
        return records

    # -- routing: plug the gateway in where core picks an SMS API ---------------

    def _split_by_api(self):
        """Route queued and batched SMS (``send()``, the SMS queue cron, SMS
        Marketing campaigns) through the configured gateway instead of Odoo IAP.
        Mirrors ``sms_twilio``'s override of the same method."""
        if self._emalify_enabled():
            yield SmsApiEmalify(self.env), self
        else:
            yield from super()._split_by_api()

    def _get_batch_size(self):
        """The gateway is called once per recipient, so keep batches small. The
        queue cron commits after each batch, which bounds how many messages would
        be resent if a run died between the gateway call and the commit."""
        if self._emalify_enabled():
            return int(self.env['ir.config_parameter'].sudo().get_param('sms_emalify.batch.size', 50))
        return super()._get_batch_size()

    # -- gateway helpers --------------------------------------------------------

    def _sms_gateway_provider(self):
        return self.env['ir.config_parameter'].sudo().get_param('sms_emalify.provider', 'roamtech')

    def _sms_gateway_missing_credentials(self):
        """Return a comma-separated list of unset credentials, or '' when configured."""
        param = self.env['ir.config_parameter'].sudo()
        if self._sms_gateway_provider() == 'vidatech':
            required = [('Vidatech Token', 'vidatech_token'), ('Vidatech Sender ID', 'vidatech_sender')]
        else:
            required = [('API Key', 'api_key'), ('Partner ID', 'partner_id'), ('Shortcode', 'shortcode')]
        return ', '.join(label for label, key in required
                         if not param.get_param('sms_emalify.%s' % key, ''))

    def _sms_gateway_send(self, mobile, message):
        """Send one SMS through the gateway selected in Settings.

        :return: tuple (message_id, raw_response)
        :raises: Exception if the gateway call fails
        """
        param = self.env['ir.config_parameter'].sudo()
        if self._sms_gateway_provider() == 'vidatech':
            base_url = param.get_param('web.base.url', '')
            response = self._vidatech_send_sms(
                token=param.get_param('sms_emalify.vidatech_token', ''),
                sender=param.get_param('sms_emalify.vidatech_sender', ''),
                mobile=mobile,
                message=message,
                endpoint=base_url and '%s/sms/vidatech/callback' % base_url.rstrip('/'),
            )
            message_id = ''
            if isinstance(response, list) and response:
                message_id = str((response[0].get('data') or {}).get('uniqueId', ''))
            return message_id, response

        response = self._emalify_send_sms(
            api_key=param.get_param('sms_emalify.api_key', ''),
            partner_id=param.get_param('sms_emalify.partner_id', ''),
            shortcode=param.get_param('sms_emalify.shortcode', ''),
            mobile=mobile,
            message=message,
            pass_type=param.get_param('sms_emalify.pass_type', 'plain'),
        )
        message_id = ''
        if isinstance(response, dict):
            if response.get('responses'):
                message_id = str(response['responses'][0].get('messageid', ''))
            else:
                message_id = str(response.get('message_id', ''))
        return message_id, response

    def _vidatech_send_sms(self, token, sender, mobile, message, endpoint=None):
        """Send SMS via the Vidatech bulk API. https://bulk.vidatech.co.ke/docs/1.0"""
        url = 'https://bulk.vidatech.co.ke/api/v1/send-sms'
        headers = {
            'Content-Type': 'application/json',
            'Accept': 'application/json',
            'Authorization': 'Bearer %s' % token,
        }
        payload = [{'sender': sender, 'message': message, 'phone': mobile}]
        if endpoint:
            payload[0]['endpoint'] = endpoint

        try:
            response = requests.post(url, json=payload, headers=headers, timeout=30)
            response.raise_for_status()
            data = response.json() if response.content else []
        except requests.exceptions.RequestException as e:
            _logger.error(f'Vidatech API request failed: {str(e)}')
            raise Exception(f'Failed to connect to Vidatech API: {str(e)}')
        except ValueError as e:
            _logger.error(f'Invalid JSON response from Vidatech: {str(e)}')
            raise Exception(f'Invalid response from Vidatech API: {str(e)}')

        # Vidatech answers with one result object per queued message
        for result in (data if isinstance(data, list) else [data]):
            if isinstance(result, dict) and result.get('status') is False:
                raise Exception(result.get('message', 'Unknown error from Vidatech API'))
        return data


    def _emalify_format_phone_number(self, number):
        """
        Format phone number for Emalify API.
        Removes spaces, dashes, and ensures international format.

        :param number: Phone number string
        :return: Formatted phone number or None if invalid
        """
        if not number:
            return None

        # Remove all non-digit characters except +
        cleaned = re.sub(r'[^\d+]', '', str(number))

        # Remove leading + if present
        if cleaned.startswith('+'):
            cleaned = cleaned[1:]

        # Remove leading 0 if present (common in local formats)
        if cleaned.startswith('0'):
            cleaned = cleaned[1:]

        # Ensure we have at least some digits
        if len(cleaned) < 9:
            return None

        # If number doesn't start with country code, try to add default (Kenya 254)
        # You can make this configurable via settings if needed
        if not cleaned.startswith('254') and len(cleaned) == 9:
            cleaned = '254' + cleaned

        return cleaned

    def _emalify_send_sms(self, api_key, partner_id, shortcode, mobile, message, pass_type='plain'):
        """
        Send SMS via Emalify API.

        :param api_key: Emalify API key
        :param partner_id: Emalify partner ID
        :param shortcode: Emalify shortcode
        :param mobile: Recipient phone number (formatted)
        :param message: SMS message content
        :param pass_type: Password type (plain or encrypted)
        :return: API response dict
        :raises: Exception if API call fails
        """
        url = 'https://api.v2.emalify.com/api/services/sendsms/'

        headers = {
            'Content-Type': 'application/json',
        }

        payload = {
            'apikey': api_key,
            'partnerID': partner_id,
            'mobile': mobile,
            'message': message,
            'shortcode': shortcode,
            'pass_type': pass_type,
        }

        try:
            response = requests.post(url, json=payload, headers=headers, timeout=30)
            response.raise_for_status()

            # Parse response
            response_data = response.json() if response.content else {}

            # Check if Emalify returned an error in the response body
            # Adjust this based on Emalify's actual error response format
            if isinstance(response_data, dict) and response_data.get('success') is False:
                error_msg = response_data.get('message', 'Unknown error from Emalify API')
                raise Exception(error_msg)

            return response_data

        except requests.exceptions.RequestException as e:
            _logger.error(f'Emalify API request failed: {str(e)}')
            raise Exception(f'Failed to connect to Emalify API: {str(e)}')
        except ValueError as e:
            _logger.error(f'Invalid JSON response from Emalify: {str(e)}')
            raise Exception(f'Invalid response from Emalify API: {str(e)}')

