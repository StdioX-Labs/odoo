# -*- coding: utf-8 -*-
"""Odoo SMS API adapter for the Emalify module's gateways (Roamtech / Vidatech).

Odoo 18 routes every SMS through a pluggable API object: ``sms.sms.send()`` picks
one per batch via ``_split_by_api()``, and a few flows (the SMS Marketing "Test"
button, for one) call ``res.company._get_sms_api_class()`` and use it directly.
Plugging the gateway in at that level - the way Odoo's own ``sms_twilio`` does -
means core keeps doing its own bookkeeping: SMS states, marketing trace
statistics and chatter notification icons all update from the results below.
"""

import logging

from odoo import _
from odoo.addons.sms.tools.sms_api import SmsApiBase

_logger = logging.getLogger(__name__)


class SmsApiEmalify(SmsApiBase):
    """Send through whichever gateway is selected in Settings.

    ``_send_sms_batch`` returns one dict per recipient, keyed by the SMS uuid.
    ``state`` must be a value core understands:

    - ``'success'`` - accepted by the gateway. Core maps it to the ``pending``
      SMS state, shown as "Sent" (see ``sms.sms.IAP_TO_SMS_STATE_SUCCESS``).
      A later delivery receipt promotes it to "Delivered".
    - a key of ``PROVIDER_TO_SMS_FAILURE_TYPE`` - a failure with a known type.

    Failures reuse core's failure types on purpose. The value is written onto
    ``mail.notification`` and ``mailing.trace`` as well, so a custom one would
    need a selection extension in three modules. A missing configuration is
    reported as a server error with an explicit reason, rather than
    ``sms_credit``, which would prompt the user to buy Odoo IAP credits.
    """

    def _get_sms_api_error_messages(self):
        return {
            'server_error': _("The SMS gateway rejected the message or could not be reached."),
            'wrong_number_format': _("The phone number is not in a format the SMS gateway accepts."),
            'sms_number_missing': _("The recipient has no phone number."),
        }

    def _send_sms_batch(self, messages, delivery_reports_url=False):
        # `delivery_reports_url` points at Odoo IAP's /sms/status and is ignored:
        # the Vidatech gateway reports back to /sms/vidatech/callback instead.
        SmsSms = self.env['sms.sms'].sudo()
        Delivery = self.env['sms.emalify.delivery'].sudo()

        recipients = [
            (message.get('content') or '', number_info)
            for message in messages
            for number_info in (message.get('numbers') or [])
        ]

        missing = SmsSms._sms_gateway_missing_credentials()
        if missing:
            reason = _("SMS gateway is not configured (missing: %s). Set it up in "
                       "Settings > Emalify SMS Provider.", missing)
            _logger.error("SMS gateway not configured, missing: %s", missing)
            return [{'uuid': info['uuid'], 'state': 'server_error', 'failure_reason': reason}
                    for _body, info in recipients]

        # A uuid the gateway already accepted is never sent again. The SMS Marketing
        # "Test" wizard creates its sms.sms rows - which sms.sms.create() sends at
        # once - and then calls this method itself for the same uuids; without the
        # guard every test SMS would go out twice.
        already_sent = set(Delivery.search([
            ('sms_uuid', 'in', [info['uuid'] for _body, info in recipients]),
            ('status', 'in', ('sent', 'delivered')),
        ]).mapped('sms_uuid'))

        results = []
        for body, number_info in recipients:
            uuid = number_info['uuid']
            if uuid in already_sent:
                results.append({'uuid': uuid, 'state': 'success'})
                continue
            raw_number = number_info.get('number')
            if not raw_number:
                results.append({'uuid': uuid, 'state': 'sms_number_missing', 'failure_reason': False})
                continue

            number = SmsSms._emalify_format_phone_number(raw_number)
            if not number:
                results.append({
                    'uuid': uuid,
                    'state': 'wrong_number_format',
                    'failure_reason': _("Cannot format %s as a phone number.", raw_number),
                })
                continue

            try:
                message_id, response = SmsSms._sms_gateway_send(number, body)
            except Exception as e:  # noqa: BLE001 - any gateway failure is a per-recipient result
                _logger.warning("SMS %s to %s failed: %s", uuid, number, e)
                Delivery.create({
                    'phone_number': number,
                    'message_content': body,
                    'status': 'failed',
                    'error_message': str(e),
                    'sms_uuid': uuid,
                })
                results.append({'uuid': uuid, 'state': 'server_error', 'failure_reason': str(e)})
                continue

            Delivery.create({
                'phone_number': number,
                'message_content': body,
                'status': 'sent',
                'emalify_message_id': message_id,
                'api_response': str(response),
                'sms_uuid': uuid,
            })
            results.append({'uuid': uuid, 'state': 'success'})

        return results
