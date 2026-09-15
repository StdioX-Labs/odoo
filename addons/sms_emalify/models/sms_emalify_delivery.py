# -*- coding: utf-8 -*-

import logging
from odoo import api, fields, models, _

_logger = logging.getLogger(__name__)


class SmsEmalifyDelivery(models.Model):
    _name = 'sms.emalify.delivery'
    _description = 'Emalify SMS Delivery Tracking'
    _order = 'create_date desc'
    _rec_name = 'phone_number'

    phone_number = fields.Char(
        string='Phone Number',
        required=True,
        index=True,
        help='Recipient phone number'
    )
    
    message_content = fields.Text(
        string='Message Content',
        required=True,
        help='SMS message text'
    )
    
    status = fields.Selection([
        ('pending', 'Pending'),
        ('sent', 'Sent'),
        ('delivered', 'Delivered'),
        ('failed', 'Failed'),
        ('rejected', 'Rejected'),
    ], string='Status', default='pending', required=True, index=True,
        help='Current delivery status of the SMS')
    
    emalify_message_id = fields.Char(
        string='Emalify Message ID',
        index=True,
        help='Unique message ID from Emalify API'
    )

    sms_uuid = fields.Char(
        string='SMS UUID',
        index=True,
        help="uuid of the Odoo SMS this row was sent for. Links a gateway delivery "
             "receipt back to the SMS tracker, and so to the marketing campaign "
             "statistics and chatter notification, after the SMS row itself has been "
             "garbage-collected."
    )
    
    api_response = fields.Text(
        string='API Response',
        help='Full API response from Emalify'
    )
    
    error_message = fields.Text(
        string='Error Message',
        help='Error message if sending failed'
    )
    
    sent_date = fields.Datetime(
        string='Sent Date',
        default=fields.Datetime.now,
        help='Date and time when SMS was sent'
    )
    
    delivered_date = fields.Datetime(
        string='Delivered Date',
        help='Date and time when SMS was delivered (from callback)'
    )
    
    res_model = fields.Char(
        string='Related Model',
        index=True,
        help='Model name of the related record'
    )
    
    res_id = fields.Integer(
        string='Related Record ID',
        index=True,
        help='ID of the related record'
    )
    
    callback_data = fields.Text(
        string='Callback Data',
        help='Raw callback data received from Emalify'
    )
    
    company_id = fields.Many2one(
        'res.company',
        string='Company',
        default=lambda self: self.env.company,
        help='Company that sent this SMS'
    )
    
    user_id = fields.Many2one(
        'res.users',
        string='Sent By',
        default=lambda self: self.env.user,
        help='User who triggered the SMS'
    )

    def name_get(self):
        """Custom display name"""
        result = []
        for record in self:
            name = f'{record.phone_number} - {record.status}'
            result.append((record.id, name))
        return result
    
    @api.model
    def update_delivery_status(self, emalify_message_id, status, callback_data=None, delivered_date=None):
        """
        Update delivery status from Emalify callback
        
        :param emalify_message_id: Emalify message ID
        :param status: New delivery status
        :param callback_data: Raw callback data
        :param delivered_date: Delivery timestamp
        :return: Updated record or False
        """
        delivery = self.search([('emalify_message_id', '=', emalify_message_id)], limit=1)
        
        if not delivery:
            _logger.warning(f'No delivery record found for Emalify message ID: {emalify_message_id}')
            return False
        
        update_vals = {
            'status': status,
            'callback_data': str(callback_data) if callback_data else delivery.callback_data,
        }
        
        if delivered_date:
            update_vals['delivered_date'] = delivered_date
        
        delivery.write(update_vals)
        delivery._propagate_to_sms_tracker()
        
        _logger.info(f'Updated delivery status for {delivery.phone_number} to {status}')
        
        return delivery
    
    # Gateway receipt status -> sms.sms state, as consumed by
    # sms.tracker._action_update_from_sms_state(). Core's own /sms/status route
    # does the same for IAP receipts.
    _RECEIPT_TO_SMS_STATE = {
        'delivered': 'sent',     # shown as "Delivered"
        'failed': 'error',
        'rejected': 'error',
    }

    def _propagate_to_sms_tracker(self):
        """Push a delivery receipt onto the Odoo SMS tracker, which updates the
        marketing trace (campaign statistics) and the chatter notification."""
        for delivery in self.filtered('sms_uuid'):
            sms_state = self._RECEIPT_TO_SMS_STATE.get(delivery.status)
            if not sms_state:
                continue
            trackers = self.env['sms.tracker'].sudo().search([('sms_uuid', '=', delivery.sms_uuid)])
            if not trackers:
                continue
            if sms_state == 'error':
                trackers._action_update_from_sms_state(
                    'error', failure_type='sms_server',
                    failure_reason=delivery.error_message or _('Rejected by the SMS gateway'),
                )
            else:
                trackers._action_update_from_sms_state(sms_state)

    def action_view_related_record(self):
        """Open the related record"""
        self.ensure_one()
        
        if not self.res_model or not self.res_id:
            return False
        
        return {
            'type': 'ir.actions.act_window',
            'name': _('Related Record'),
            'res_model': self.res_model,
            'res_id': self.res_id,
            'view_mode': 'form',
            'target': 'current',
        }

