import logging
import requests
from odoo import http, fields
from odoo.http import request

_logger = logging.getLogger(__name__)


class PesaPalController(http.Controller):

    @http.route('/payment/pesapal/return', type='http', auth='public', methods=['GET'], csrf=False)
    def pesapal_return(self, **data):
        """Handle return from PesaPal hosted checkout"""
        _logger.info('PesaPal: Customer returned from checkout with data: %s', data)
        
        tracking_id = data.get('OrderTrackingId')
        merchant_ref = data.get('OrderMerchantReference')
        
        if not tracking_id:
            return request.redirect('/payment/status')
        
        tx = request.env['payment.transaction'].sudo().search([
            ('pesapal_order_tracking_id', '=', tracking_id)
        ], limit=1)
        
        if not tx:
            _logger.warning('PesaPal: Transaction not found for tracking ID: %s', tracking_id)
            return request.redirect('/payment/status')
        
        status = self._get_transaction_status(tx.provider_id, tracking_id)
        
        if status:
            notification_data = {
                'OrderTrackingId': tracking_id,
                'OrderMerchantReference': merchant_ref,
                'status_code': status.get('status_code', 0),
                'status_description': status.get('payment_status_description')
            }
            
            _logger.info('PesaPal: Processing notification data: %s', notification_data)
            tx._handle_notification_data('pesapal', notification_data)
            tx.env.cr.commit()
            tx.invalidate_recordset()
            _logger.info('PesaPal: Transaction state after processing: %s', tx.state)
        
        appointment = request.env['custom.appointment'].sudo().search([
            ('payment_transaction_id', '=', tx.id)
        ], limit=1)
        
        if appointment:
            _logger.info('PesaPal: Found appointment %s with transaction state %s', appointment.id, tx.state)
            if tx.state == 'done':
                appointment.write({
                    'payment_status': 'paid',
                    'paid_amount': tx.amount,
                    'payment_date': fields.Datetime.now(),
                    'payment_method': tx.provider_id.name,
                    'payment_reference': tx.reference,
                })
                try:
                    appointment.action_confirm()
                    _logger.info('PesaPal: Appointment %s confirmed successfully', appointment.id)
                except Exception as e:
                    _logger.warning('Failed to confirm appointment: %s', str(e))
                
                return request.redirect(f'/appointments/payment/success?appointment_id={appointment.id}')
            elif tx.state in ['cancel', 'error']:
                appointment.write({
                    'payment_status': 'failed'
                })
                return request.redirect(f'/appointments/payment?appointment_id={appointment.id}&error=Payment failed. Please try again.')
        
        # Not an appointment payment (eCommerce order, portal invoice, ...): hand back
        # to Odoo's own status page, which honours the transaction's landing_route and
        # shows the right confirmation for whatever the payment was for.
        return request.redirect('/payment/status')

    @http.route('/payment/pesapal/ipn', type='http', auth='public', methods=['GET'], csrf=False)
    def pesapal_ipn(self, **data):
        """Handle IPN (Instant Payment Notification) from PesaPal"""
        _logger.info('PesaPal: IPN received with data: %s', data)
        
        tracking_id = data.get('OrderTrackingId')
        merchant_ref = data.get('OrderMerchantReference')
        
        if not tracking_id:
            _logger.warning('PesaPal IPN: No tracking ID provided')
            return 'Invalid notification'
        
        tx = request.env['payment.transaction'].sudo().search([
            ('pesapal_order_tracking_id', '=', tracking_id)
        ], limit=1)
        
        if not tx:
            _logger.warning('PesaPal IPN: Transaction not found for tracking ID: %s', tracking_id)
            request.env['pesapal.ipn.log'].sudo().create({
                'tracking_id': tracking_id,
                'merchant_reference': merchant_ref,
                'raw_data': str(data),
                'error_message': 'Transaction not found',
            })
            request.env.cr.commit()
            return 'Transaction not found'
        
        status = self._get_transaction_status(tx.provider_id, tracking_id)
        
        if not status:
            _logger.error('PesaPal IPN: Failed to get transaction status for %s', tracking_id)
            return 'Failed to verify transaction'
        
        status_code = status.get('status_code', 0)
        status_description = status.get('payment_status_description', '')
        
        existing_log = request.env['pesapal.ipn.log'].sudo().search([
            ('tracking_id', '=', tracking_id),
            ('processed', '=', True),
            ('status_code', '=', status_code),
        ], limit=1)
        
        if existing_log:
            _logger.info('PesaPal IPN: Duplicate IPN for tracking ID %s (already processed)', tracking_id)
            return 'OK - Already processed'
        
        ipn_log = request.env['pesapal.ipn.log'].sudo().create({
            'tracking_id': tracking_id,
            'merchant_reference': merchant_ref,
            'status_code': status_code,
            'status_description': status_description,
            'transaction_id': tx.id,
            'raw_data': str(data),
        })
        
        notification_data = {
            'OrderTrackingId': tracking_id,
            'OrderMerchantReference': merchant_ref,
            'status_code': status_code,
            'status_description': status_description
        }
        
        try:
            tx._handle_notification_data('pesapal', notification_data)
            tx.env.cr.commit()
            _logger.info('PesaPal IPN: Transaction %s processed successfully with state %s', tracking_id, tx.state)
            
            appointment = request.env['custom.appointment'].sudo().search([
                ('payment_transaction_id', '=', tx.id)
            ], limit=1)
            
            if appointment:
                _logger.info('PesaPal IPN: Found appointment %s for transaction %s', appointment.id, tx.id)
                
                if tx.state == 'done' and appointment.state != 'confirmed':
                    appointment.write({
                        'payment_status': 'paid',
                        'paid_amount': tx.amount,
                        'payment_date': fields.Datetime.now(),
                        'payment_method': tx.provider_id.name,
                        'payment_reference': tx.reference,
                    })
                    
                    try:
                        appointment.action_confirm()
                        _logger.info('PesaPal IPN: Appointment %s confirmed successfully via action_confirm()', appointment.id)
                    except Exception as e:
                        _logger.warning('PesaPal IPN: Failed to confirm appointment: %s', str(e))
                    
                    ipn_log.mark_processed(transaction=tx, appointment=appointment)
                    _logger.info('PesaPal IPN: Appointment %s confirmed successfully via IPN', appointment.id)
                elif tx.state in ['cancel', 'error']:
                    appointment.write({'payment_status': 'failed'})
                    ipn_log.mark_processed(transaction=tx, appointment=appointment)
                    _logger.info('PesaPal IPN: Appointment %s payment failed', appointment.id)
                else:
                    ipn_log.mark_processed(transaction=tx, appointment=appointment)
                    _logger.info('PesaPal IPN: Appointment %s already in state %s', appointment.id, appointment.state)
            else:
                ipn_log.mark_processed(transaction=tx)
                _logger.info('PesaPal IPN: No appointment found for transaction %s', tx.id)
            
            tx.env.cr.commit()
            return 'OK'
            
        except Exception as e:
            _logger.error('PesaPal IPN: Error processing transaction %s: %s', tracking_id, str(e), exc_info=True)
            ipn_log.mark_processed(transaction=tx, error=str(e))
            tx.env.cr.commit()
            return 'Error processing transaction'

    def _get_transaction_status(self, provider, tracking_id):
        """Get transaction status from PesaPal API"""
        api_url = provider._pesapal_get_api_url()
        auth_url = f'{api_url}/api/Auth/RequestToken'
        
        payload = {
            'consumer_key': provider.pesapal_consumer_key,
            'consumer_secret': provider.pesapal_consumer_secret
        }
        
        try:
            response = requests.post(auth_url, json=payload, headers={'Content-Type': 'application/json'})
            response.raise_for_status()
            token = response.json().get('token')
            
            if not token:
                _logger.error('PesaPal: Failed to get auth token')
                return None
            
            status_url = f'{api_url}/api/Transactions/GetTransactionStatus?orderTrackingId={tracking_id}'
            headers = {
                'Authorization': f'Bearer {token}',
                'Content-Type': 'application/json'
            }
            
            response = requests.get(status_url, headers=headers)
            response.raise_for_status()
            status_data = response.json()
            
            _logger.info('PesaPal: Transaction status for %s: %s', tracking_id, status_data)
            return status_data
            
        except Exception as e:
            _logger.error('PesaPal: Failed to get transaction status: %s', str(e))
            return None
