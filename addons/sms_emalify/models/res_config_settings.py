# -*- coding: utf-8 -*-

import logging
from odoo import api, fields, models, _
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    # Emalify SMS Configuration Fields
    sms_emalify_provider = fields.Selection(
        [('roamtech', 'Roamtech'), ('vidatech', 'Vidatech')],
        string='SMS Gateway',
        default='roamtech',
        config_parameter='sms_emalify.provider',
        help='Which gateway to use for outgoing SMS'
    )

    sms_emalify_vidatech_token = fields.Char(
        string='Vidatech Token',
        config_parameter='sms_emalify.vidatech_token',
        help='Vidatech bulk API bearer token'
    )

    sms_emalify_vidatech_sender = fields.Char(
        string='Vidatech Sender ID',
        config_parameter='sms_emalify.vidatech_sender',
        help='Vidatech sender ID (e.g., EMALIFY)'
    )

    sms_emalify_enabled = fields.Boolean(
        string='Enable Emalify SMS',
        config_parameter='sms_emalify.enabled',
        help='Enable or disable Emalify SMS provider for all SMS communications'
    )
    
    sms_emalify_api_key = fields.Char(
        string='API Key',
        config_parameter='sms_emalify.api_key',
        help='Your Emalify API key'
    )
    
    sms_emalify_partner_id = fields.Char(
        string='Partner ID',
        config_parameter='sms_emalify.partner_id',
        help='Your Emalify partner ID'
    )
    
    sms_emalify_shortcode = fields.Char(
        string='Shortcode',
        config_parameter='sms_emalify.shortcode',
        help='Your Emalify SMS shortcode (sender name)'
    )
    
    sms_emalify_pass_type = fields.Selection(
        [('plain', 'Plain'), ('encrypted', 'Encrypted')],
        string='Password Type',
        default='plain',
        config_parameter='sms_emalify.pass_type',
        help='Password type for Emalify API'
    )
    
    sms_emalify_callback_url = fields.Char(
        string='Callback URL',
        compute='_compute_sms_emalify_callback_url',
        help='Use this URL in your Emalify dashboard to receive delivery status updates'
    )
    
    sms_emalify_default_country_code = fields.Char(
        string='Default Country Code',
        default='254',
        config_parameter='sms_emalify.default_country_code',
        help='Default country code to prepend to phone numbers (e.g., 254 for Kenya)'
    )

    def _compute_sms_emalify_callback_url(self):
        """Compute the callback URL for Emalify delivery status updates"""
        for record in self:
            base_url = self.env['ir.config_parameter'].sudo().get_param('web.base.url')
            record.sms_emalify_callback_url = f'{base_url}/sms/emalify/callback'
    
    def action_test_emalify_connection(self):
        """Test the Emalify API connection"""
        self.ensure_one()
        
        # Check if required fields are filled
        if self.sms_emalify_provider == 'vidatech':
            if not all([self.sms_emalify_vidatech_token, self.sms_emalify_vidatech_sender]):
                raise UserError(_('Please fill in the Vidatech Token and Sender ID before testing the connection.'))
        elif not all([self.sms_emalify_api_key, self.sms_emalify_partner_id, self.sms_emalify_shortcode]):
            raise UserError(_(
                'Please fill in all required fields (API Key, Partner ID, and Shortcode) before testing the connection.'
            ))
        
        # Save settings first
        self.execute()
        
        # Open the test wizard
        return {
            'type': 'ir.actions.act_window',
            'name': _('Test Emalify SMS'),
            'res_model': 'sms.emalify.test.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': self.env.context,
        }
    
    def action_open_delivery_logs(self):
        """Open Emalify SMS delivery logs"""
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Emalify SMS Delivery Logs'),
            'res_model': 'sms.emalify.delivery',
            'view_mode': 'tree,form',
            'target': 'current',
            'context': {'create': False},
        }

