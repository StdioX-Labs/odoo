# -*- coding: utf-8 -*-

import json
import logging
from odoo import fields, http
from odoo.http import request

_logger = logging.getLogger(__name__)


class VidatechController(http.Controller):

    # Vidatech does not document its delivery-receipt payload, so log the body
    # verbatim and match on whichever id field it turns out to use.
    @http.route('/sms/vidatech/callback', type='http', auth='public',
                methods=['POST', 'GET'], csrf=False, save_session=False)
    def vidatech_callback(self, **kwargs):
        raw = request.httprequest.get_data(as_text=True)
        _logger.info('Vidatech delivery receipt: params=%s body=%s', kwargs, raw)

        data = dict(kwargs)
        if raw:
            try:
                parsed = json.loads(raw)
                if isinstance(parsed, list) and parsed:
                    parsed = parsed[0]
                if isinstance(parsed, dict):
                    data.update(parsed)
            except ValueError:
                pass
        if isinstance(data.get('data'), dict):
            data.update(data['data'])

        message_id = data.get('uniqueId') or data.get('unique_id') or data.get('messageId')
        raw_status = str(data.get('status') or data.get('deliveryStatus') or '').lower()
        status = {
            'delivered': 'delivered', 'delivrd': 'delivered', 'success': 'delivered',
            'true': 'delivered',
            'failed': 'failed', 'undeliv': 'failed', 'undelivered': 'failed',
            'expired': 'failed', 'false': 'failed',
            'rejected': 'rejected', 'rejectd': 'rejected',
        }.get(raw_status, 'pending')

        if message_id:
            request.env['sms.emalify.delivery'].sudo().update_delivery_status(
                emalify_message_id=message_id,
                status=status,
                callback_data=raw or kwargs,
                delivered_date=fields.Datetime.now() if status == 'delivered' else None,
            )
        else:
            _logger.warning('Vidatech delivery receipt carried no message id: %s', data)

        return request.make_json_response({'status': True})


class EmalifyController(http.Controller):
    
    @http.route('/sms/emalify/callback', type='json', auth='public', methods=['POST'], csrf=False)
    def emalify_callback(self, **kwargs):
        """
        Webhook endpoint to receive delivery status updates from Emalify.
        
        Expected callback format (adjust based on actual Emalify callback structure):
        {
            "message_id": "...",
            "status": "delivered|failed|rejected",
            "mobile": "254...",
            "delivered_at": "2024-01-01 12:00:00",
            "error": "..." (optional)
        }
        """
        try:
            # Get callback data
            callback_data = request.httprequest.get_json() or kwargs
            
            _logger.info(f'Received Emalify callback: {callback_data}')
            
            # Extract relevant information
            # Adjust these field names based on actual Emalify callback format
            message_id = callback_data.get('message_id') or callback_data.get('messageId')
            status = callback_data.get('status', '').lower()
            mobile = callback_data.get('mobile') or callback_data.get('phone_number')
            delivered_at = callback_data.get('delivered_at') or callback_data.get('deliveredAt')
            error = callback_data.get('error') or callback_data.get('error_message')
            
            if not message_id:
                _logger.warning('Emalify callback missing message_id')
                return {'success': False, 'error': 'Missing message_id'}
            
            # Map Emalify status to our status
            status_mapping = {
                'delivered': 'delivered',
                'sent': 'sent',
                'failed': 'failed',
                'rejected': 'rejected',
                'pending': 'pending',
            }
            
            mapped_status = status_mapping.get(status, 'pending')
            
            # Update delivery record
            delivery_model = request.env['sms.emalify.delivery'].sudo()
            delivery = delivery_model.update_delivery_status(
                emalify_message_id=message_id,
                status=mapped_status,
                callback_data=callback_data,
                delivered_date=delivered_at,
            )
            
            if delivery:
                _logger.info(f'Successfully updated delivery status for message {message_id}')
                return {'success': True, 'message': 'Status updated'}
            else:
                _logger.warning(f'No delivery record found for message {message_id}')
                return {'success': False, 'error': 'Delivery record not found'}
                
        except Exception as e:
            _logger.error(f'Error processing Emalify callback: {str(e)}', exc_info=True)
            return {'success': False, 'error': str(e)}
    
    @http.route('/sms/emalify/callback', type='http', auth='public', methods=['POST'], csrf=False)
    def emalify_callback_http(self, **kwargs):
        """
        Alternative HTTP endpoint for Emalify callbacks (in case they use form data instead of JSON).
        """
        try:
            # Try to parse as JSON first
            try:
                callback_data = json.loads(request.httprequest.data.decode('utf-8'))
            except:
                # If not JSON, use POST parameters
                callback_data = kwargs
            
            _logger.info(f'Received Emalify HTTP callback: {callback_data}')
            
            # Extract relevant information
            message_id = callback_data.get('message_id') or callback_data.get('messageId')
            status = callback_data.get('status', '').lower()
            mobile = callback_data.get('mobile') or callback_data.get('phone_number')
            delivered_at = callback_data.get('delivered_at') or callback_data.get('deliveredAt')
            error = callback_data.get('error') or callback_data.get('error_message')
            
            if not message_id:
                _logger.warning('Emalify callback missing message_id')
                return 'Missing message_id'
            
            # Map Emalify status to our status
            status_mapping = {
                'delivered': 'delivered',
                'sent': 'sent',
                'failed': 'failed',
                'rejected': 'rejected',
                'pending': 'pending',
            }
            
            mapped_status = status_mapping.get(status, 'pending')
            
            # Update delivery record
            delivery_model = request.env['sms.emalify.delivery'].sudo()
            delivery = delivery_model.update_delivery_status(
                emalify_message_id=message_id,
                status=mapped_status,
                callback_data=callback_data,
                delivered_date=delivered_at,
            )
            
            if delivery:
                _logger.info(f'Successfully updated delivery status for message {message_id}')
                return 'OK'
            else:
                _logger.warning(f'No delivery record found for message {message_id}')
                return 'Delivery record not found'
                
        except Exception as e:
            _logger.error(f'Error processing Emalify HTTP callback: {str(e)}', exc_info=True)
            return f'Error: {str(e)}'

