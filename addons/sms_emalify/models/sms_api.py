# -*- coding: utf-8 -*-

import logging
import requests
import re
from odoo import api, models, _
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class SmsSms(models.Model):
    _inherit = 'sms.sms'

    @api.model_create_multi
    def create(self, vals_list):
        """Override create to automatically send SMS via Emalify when enabled"""
        records = super().create(vals_list)

        # Check if Emalify is enabled
        IrConfigParam = self.env['ir.config_parameter'].sudo()
        emalify_enabled = IrConfigParam.get_param('sms_emalify.enabled', 'False') == 'True'

        if emalify_enabled:
            _logger.info(f'Emalify is enabled, processing {len(records)} SMS records')
            # Only auto-send for non-marketing SMS (SMS without mailing_id)
            # Marketing SMS will be sent via _send() method by the marketing cron
            # Check if mailing_id field exists (from mass_mailing_sms module)
            has_mailing = 'mailing_id' in records._fields
            if has_mailing:
                outgoing_sms = records.filtered(lambda s: s.state == 'outgoing' and not s.mailing_id)
            else:
                # If no mailing_id field, all SMS are non-marketing
                outgoing_sms = records.filtered(lambda s: s.state == 'outgoing')

            if outgoing_sms:
                _logger.info(f'Auto-sending {len(outgoing_sms)} non-marketing SMS')
                outgoing_sms._send_emalify()
            else:
                _logger.info(f'Skipping auto-send for {len(records)} SMS (marketing or not outgoing)')

        return records

    def _send(self, unlink_failed=False, unlink_sent=True, raise_exception=False):
        """
        Override the core SMS sending method to use Emalify API instead of IAP.
        """
        # Check if Emalify is enabled
        IrConfigParam = self.env['ir.config_parameter'].sudo()
        emalify_enabled = IrConfigParam.get_param('sms_emalify.enabled', 'False') == 'True'

        if not emalify_enabled:
            _logger.info('Emalify SMS is disabled in _send(), falling back to default IAP provider')
            return super()._send(unlink_failed=unlink_failed, unlink_sent=unlink_sent, raise_exception=raise_exception)

        _logger.info(f'Emalify _send() called for {len(self)} SMS records')
        return self._send_emalify(unlink_failed=unlink_failed, unlink_sent=unlink_sent, raise_exception=raise_exception)

    def _send_emalify(self, unlink_failed=False, unlink_sent=True, raise_exception=False):
        """
        Send SMS via Emalify API
        """
        _logger.info(f'=== _send_emalify called for {len(self)} SMS records ===')

        missing = self._sms_gateway_missing_credentials()
        if missing:
            _logger.error(f'SMS gateway credentials are not configured: {missing}')
            for sms in self:
                sms.write({'state': 'error', 'failure_type': 'sms_credit'})
            if raise_exception:
                raise UserError(_(
                    'SMS gateway is not configured (missing: %s). '
                    'Please go to Settings → General Settings → Emalify SMS and configure your credentials.'
                ) % missing)
            return False

        _logger.info(f'SMS gateway credentials configured, processing {len(self)} SMS')

        # Process each SMS record
        outgoing_sms = self.filtered(lambda s: s.state == 'outgoing')
        _logger.info(f'Found {len(outgoing_sms)} outgoing SMS to process')

        for sms in outgoing_sms:
            number = sms.number
            content = sms.body

            _logger.info(f'Processing SMS {sms.id}: to {number}, body length: {len(content) if content else 0}')

            # Format phone number
            formatted_number = self._emalify_format_phone_number(number)

            if not formatted_number:
                _logger.warning(f'Invalid phone number format: {number}')
                sms.write({'state': 'error', 'failure_type': 'sms_number_format'})
                continue

            _logger.info(f'Formatted number: {number} -> {formatted_number}')

            # Send SMS via the configured gateway
            try:
                _logger.info(f'Calling SMS gateway for {formatted_number}')
                message_id, response = self._sms_gateway_send(formatted_number, content)

                _logger.info(f'SMS gateway response: {response}')

                # Create delivery tracking record
                self.env['sms.emalify.delivery'].sudo().create({
                    'phone_number': formatted_number,
                    'message_content': content,
                    'status': 'sent',
                    'emalify_message_id': message_id,
                    'api_response': str(response),
                    'res_model': '',
                    'res_id': 0,
                })

                # Mark SMS as sent
                sms.write({'state': 'sent', 'failure_type': False})

                _logger.info(f'✓ SMS {sms.id} sent successfully to {formatted_number}')

            except Exception as e:
                _logger.error(f'✗ Failed to send SMS {sms.id} to {formatted_number}: {str(e)}', exc_info=True)

                # Create delivery tracking record for failed message
                self.env['sms.emalify.delivery'].sudo().create({
                    'phone_number': formatted_number,
                    'message_content': content,
                    'status': 'failed',
                    'error_message': str(e),
                    'res_model': '',
                    'res_id': 0,
                })

                # Mark SMS as failed
                sms.write({'state': 'error', 'failure_type': 'sms_server'})

                if raise_exception:
                    raise

        _logger.info(f'=== Completed processing {len(self)} SMS records ===')

        # Handle unlink based on parameters (only for non-marketing SMS)
        # Marketing SMS should be kept for tracking
        # Check if mailing_id field exists (from mass_mailing_sms module)
        has_mailing = 'mailing_id' in self._fields

        if unlink_failed:
            if has_mailing:
                to_unlink = self.filtered(lambda s: s.state == 'error' and not s.mailing_id)
            else:
                to_unlink = self.filtered(lambda s: s.state == 'error')

            if to_unlink:
                _logger.info(f'Unlinking {len(to_unlink)} failed SMS')
                to_unlink.unlink()

        if unlink_sent:
            if has_mailing:
                to_unlink = self.filtered(lambda s: s.state == 'sent' and not s.mailing_id)
            else:
                to_unlink = self.filtered(lambda s: s.state == 'sent')

            if to_unlink:
                _logger.info(f'Unlinking {len(to_unlink)} sent SMS')
                to_unlink.unlink()

        _logger.info(f'Returning True from _send_emalify')
        return True

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

