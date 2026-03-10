from odoo import http, fields
from odoo.http import request
from werkzeug.utils import redirect
from datetime import datetime, timedelta
import json


class AppointmentController(http.Controller):

    @http.route(['/home'], type='http', auth='public', website=True)
    def homepage(self, **kwargs):
        """Custom Revive Aesthetics homepage"""
        service_categories = request.env['service.category'].sudo().search([
            ('active', '=', True)
        ], order='sequence, name')

        staff_members = request.env['custom.staff.member'].sudo().search([
            ('is_bookable', '=', True),
            ('active', '=', True),
        ], order='name', limit=8)

        return request.render('custom_appointments.homepage', {
            'service_categories': service_categories,
            'staff_members': staff_members,
        })

    @http.route('/appointments', type='http', auth='public', website=True)
    def appointment_booking(self, **kwargs):
        """Main booking page - direct to service selection (branch and staff auto-assigned)"""
        services = request.env['company.service'].sudo().get_available_services()
        service_categories = request.env['service.category'].sudo().search([
            ('active', '=', True)
        ], order='sequence, name')
        return request.render('custom_appointments.service_selection_page', {
            'services': services,
            'service_categories': service_categories,
        })

    @http.route('/appointments/services', type='http', auth='public', website=True)
    def service_selection(self, **kwargs):
        """Redirect to main appointments page for backward compatibility"""
        params = request.httprequest.query_string.decode('utf-8')
        url = '/appointments' + (f'?{params}' if params else '')
        return request.redirect(url)

    @http.route('/appointments/book', type='http', auth='public', website=True, methods=['GET', 'POST'])
    def book_appointment(self, **kwargs):
        """Appointment booking form (branch and staff auto-assigned)"""
        if request.httprequest.method == 'GET':
            service_id = kwargs.get('service_id')
            if not service_id:
                return request.redirect('/appointments')

            service = request.env['company.service'].sudo().browse(int(service_id))
            if not service.exists():
                return request.redirect('/appointments')

            branch = self._get_default_branch()
            available_slots = self._get_available_slots_all_staff(service, branch)
            available_slots_json = json.dumps(available_slots)

            return request.render('custom_appointments.booking_form_page', {
                'service': service,
                'staff': None,
                'branch': branch,
                'available_slots': available_slots,
                'available_slots_json': available_slots_json,
            })

        elif request.httprequest.method == 'POST':
            return self._process_booking(kwargs)

    @http.route('/appointments/slots', type='json', auth='public', website=True)
    def get_available_slots(self, service_id, staff_id=None, date=None):
        """AJAX endpoint to get available time slots for a specific date.
        If staff_id is omitted, slots are aggregated across all eligible staff at default branch."""
        service = request.env['company.service'].sudo().browse(service_id)
        if not service.exists():
            return {'error': 'Invalid service'}

        if date:
            target_date = datetime.strptime(date, '%Y-%m-%d').date()
        else:
            target_date = datetime.now().date()

        if staff_id:
            staff = request.env['custom.staff.member'].sudo().browse(int(staff_id))
            if not staff.exists():
                return {'error': 'Invalid staff'}
            slots = self._get_slots_for_date(service, staff, target_date)
        else:
            branch = self._get_default_branch()
            eligible = self._get_eligible_staff(service, branch)
            seen_times = set()
            slots = []
            for staff in eligible:
                for slot in self._get_slots_for_date(service, staff, target_date):
                    if slot['time'] not in seen_times:
                        seen_times.add(slot['time'])
                        slots.append(slot)
            slots.sort(key=lambda x: x['time'])
        return {'slots': slots}

    @http.route('/appointments/validate-promo', type='json', auth='public', website=True, methods=['POST'], csrf=False)
    def validate_promo_code(self, **kwargs):
        """AJAX endpoint to validate a promo code and return discount info"""
        try:
            data = request.get_json_data() if hasattr(request, 'get_json_data') else kwargs
            promo_code = data.get('promo_code', '').strip().upper()
            service_id = data.get('service_id')
            branch_id = data.get('branch_id')
            amount = float(data.get('amount', 0))
            booking_fee = float(data.get('booking_fee', 0))
            
            if not promo_code:
                return {'valid': False, 'message': 'Please enter a promo code'}
            
            PromoCode = request.env['custom.appointment.promo'].sudo()
            promo = PromoCode.get_promo_by_code(promo_code)
            
            if not promo:
                return {'valid': False, 'message': 'Invalid promo code'}
            
            # Validate the promo code
            validation = promo.validate_promo(
                service_id=service_id,
                branch_id=branch_id,
                amount=amount,
                booking_fee=booking_fee
            )
            
            if not validation['valid']:
                return {'valid': False, 'message': validation['message']}
            
            # Get currency symbol
            currency = request.env['res.currency'].sudo().search([('name', '=', 'KES')], limit=1)
            if not currency:
                currency = request.env.company.currency_id
            
            return {
                'valid': True,
                'promo_id': promo.id,
                'promo_name': promo.name,
                'discount_type': promo.discount_type,
                'discount_value': promo.discount_value,
                'discount_amount': validation['discount_amount'],
                'applies_to': promo.applies_to,
                'currency_symbol': currency.symbol or 'KES ',
            }
            
        except Exception as e:
            return {'valid': False, 'message': f'Error validating promo code: {str(e)}'}

    def _get_available_slots(self, service, staff, days_ahead=30):
        """Get available time slots for the next N days"""
        slots_by_date = {}
        today = datetime.now().date()
        
        for i in range(days_ahead):
            date = today + timedelta(days=i)
            slots = self._get_slots_for_date(service, staff, date)
            if slots:
                slots_by_date[date.strftime('%Y-%m-%d')] = slots
        
        return slots_by_date

    def _get_slots_for_date(self, service, staff, date):
        """Get available time slots for a specific date based on staff availability and service duration"""
        import pytz
        
        weekday = date.weekday()
        day_fields = [
            'monday_available', 'tuesday_available', 'wednesday_available',
            'thursday_available', 'friday_available', 'saturday_available', 'sunday_available'
        ]
        
        if not getattr(staff, day_fields[weekday]):
            return []
        
        start_hour = staff.start_time
        end_hour = staff.end_time
        service_duration = service.duration
        
        tz_name = request.env['ir.config_parameter'].sudo().get_param('appointment.timezone', 'Africa/Nairobi')
        try:
            server_tz = pytz.timezone(tz_name)
        except:
            server_tz = pytz.timezone('Africa/Nairobi')
        
        now_server = datetime.now(server_tz)
        is_today = date == now_server.date()
        
        slots = []
        current_time = start_hour
        
        while current_time + service_duration <= end_hour:
            slot_datetime_naive = datetime.combine(date, datetime.min.time()) + timedelta(hours=current_time)
            
            if is_today and slot_datetime_naive <= now_server.replace(tzinfo=None):
                current_time += service_duration
                continue
            
            slot_datetime_local = server_tz.localize(slot_datetime_naive)
            slot_datetime_utc = slot_datetime_local.astimezone(pytz.utc).replace(tzinfo=None)
            
            if not self._has_conflict(staff, slot_datetime_utc, service_duration, service):
                slots.append({
                    'time': slot_datetime_naive.strftime('%H:%M'),
                    'datetime': slot_datetime_naive.isoformat(),
                    'display_time': slot_datetime_naive.strftime('%I:%M %p'),
                })
            
            current_time += service_duration
        
        return slots

    def _has_conflict(self, staff, start_datetime, duration_hours, service=None):
        """Check if a time slot conflicts with existing appointments including buffer time"""
        end_datetime = start_datetime + timedelta(hours=duration_hours)
        
        buffer_before = 0
        buffer_after = 0
        if service:
            buffer_before = service.preparation_time if hasattr(service, 'preparation_time') else 0
            buffer_after = service.cleanup_time if hasattr(service, 'cleanup_time') else 0
        
        check_start = start_datetime - timedelta(hours=buffer_before)
        check_end = end_datetime + timedelta(hours=buffer_after)
        
        existing_appointments = request.env['custom.appointment'].sudo().search([
            ('staff_member_id', '=', staff.id),
            ('state', 'in', ['draft', 'confirmed', 'in_progress']),
            ('start', '<', check_end),
            ('stop', '>', check_start),
        ])
        
        return len(existing_appointments) > 0

    def _get_default_branch(self):
        """Return the main branch or first active branch for auto-assignment."""
        main_branch = request.env['custom.branch'].sudo().search([
            ('is_main_branch', '=', True),
            ('active', '=', True)
        ], limit=1)
        if main_branch:
            return main_branch
        return request.env['custom.branch'].sudo().search([
            ('active', '=', True)
        ], order='name', limit=1)

    def _get_eligible_staff(self, service, branch):
        """Return staff eligible to perform the service at the branch."""
        if not branch:
            return request.env['custom.staff.member'].sudo()
        domain = [
            ('is_bookable', '=', True),
            ('active', '=', True),
            ('branch_id', '=', branch.id),
        ]
        staff = request.env['custom.staff.member'].sudo().search(domain, order='name')
        if service.requires_specific_staff and service.allowed_staff_ids:
            staff = staff.filtered(lambda s: s in service.allowed_staff_ids)
        return staff

    def _get_available_slots_all_staff(self, service, branch, days_ahead=30):
        """Aggregate available time slots across all eligible staff for the branch."""
        slots_by_date = {}
        today = datetime.now().date()
        eligible = self._get_eligible_staff(service, branch)
        if not eligible:
            return slots_by_date
        for i in range(days_ahead):
            date = today + timedelta(days=i)
            seen_times = set()
            date_slots = []
            for staff in eligible:
                slots = self._get_slots_for_date(service, staff, date)
                for slot in slots:
                    t = slot['time']
                    if t not in seen_times:
                        seen_times.add(t)
                        date_slots.append(slot)
            date_slots.sort(key=lambda x: x['time'])
            if date_slots:
                slots_by_date[date.strftime('%Y-%m-%d')] = date_slots
        return slots_by_date

    def _auto_assign_staff(self, service, branch, start_datetime):
        """Pick an available staff for the slot using load-balancing (fewest upcoming appointments)."""
        eligible = self._get_eligible_staff(service, branch)
        available = eligible.filtered(
            lambda s: not self._has_conflict(s, start_datetime, service.duration, service)
        )
        if not available:
            raise ValueError("No staff available for this time slot")
        Appointment = request.env['custom.appointment'].sudo()
        now_utc = fields.Datetime.now()
        def count_upcoming(staff):
            return Appointment.search_count([
                ('staff_member_id', '=', staff.id),
                ('state', 'in', ['draft', 'confirmed']),
                ('start', '>=', now_utc),
            ])
        best = min(available, key=count_upcoming)
        return best

    def _process_booking(self, data):
        """Process the booking form submission (staff auto-assigned)."""
        try:
            import pytz

            service_id = int(data.get('service_id'))
            appointment_datetime = data.get('appointment_datetime')
            customer_name = data.get('customer_name')
            customer_email = data.get('customer_email')
            customer_phone = data.get('customer_phone', '')
            notes = data.get('notes', '')
            promo_code = data.get('promo_code', '').strip().upper()

            # Desired Outcome fields
            desired_lash_look = data.get('desired_lash_look', '')

            service = request.env['company.service'].sudo().browse(service_id)
            if not service.exists():
                raise ValueError("Invalid service")

            branch = self._get_default_branch()
            if not branch:
                raise ValueError("No branch available for booking")

            tz_name = request.env['ir.config_parameter'].sudo().get_param('appointment.timezone', 'Africa/Nairobi')
            try:
                server_tz = pytz.timezone(tz_name)
            except Exception:
                server_tz = pytz.timezone('Africa/Nairobi')

            naive_dt = datetime.fromisoformat(appointment_datetime.replace('Z', '').replace('+00:00', ''))
            local_dt = server_tz.localize(naive_dt)
            start_dt = local_dt.astimezone(pytz.utc).replace(tzinfo=None)
            end_dt = start_dt + timedelta(hours=service.duration)

            staff = self._auto_assign_staff(service, branch, start_dt)

            # Handle promo code
            promo = None
            discount_amount = 0
            if promo_code:
                PromoCode = request.env['custom.appointment.promo'].sudo()
                promo = PromoCode.get_promo_by_code(promo_code)
                if promo:
                    validation = promo.validate_promo(
                        service_id=service_id,
                        branch_id=branch.id,
                        amount=service.price
                    )
                    if validation['valid']:
                        discount_amount = validation['discount_amount']

            appointment_vals = {
                'name': f"{service.name} - {customer_name}",
                'customer_name': customer_name,
                'customer_email': customer_email,
                'customer_phone': customer_phone,
                'service_id': service.id,
                'staff_member_id': staff.id,
                'branch_id': branch.id,
                'start': start_dt,
                'stop': end_dt,
                'description': notes,
                'price': service.price,
                'state': 'confirmed' if not service.requires_approval else 'draft',
                'promo_code_entered': promo_code if promo_code else False,
                'promo_id': promo.id if promo else False,
                'discount_amount': discount_amount,
                # Desired Outcome fields
                'desired_lash_look': desired_lash_look,
            }
            
            appointment_vals['state'] = 'draft'
            appointment_vals['payment_status'] = 'pending'
            appointment = request.env['custom.appointment'].sudo().create(appointment_vals)
            
            # Increment promo code usage if applied
            if promo and discount_amount > 0:
                promo.sudo().write({'current_uses': promo.current_uses + 1})

            # If no payment providers are configured/published, skip payment step and auto-confirm
            acquirers = request.env['payment.provider'].sudo().search([
                ('state', 'in', ['enabled', 'test']),
                ('is_published', '=', True)
            ])
            if not acquirers:
                amount_to_charge = appointment.service_id.get_amount_to_charge()
                appointment.write({
                    'payment_status': 'paid',
                    'paid_amount': amount_to_charge,
                    'payment_date': fields.Datetime.now(),
                    'payment_method': 'No Payment Required',
                    'payment_reference': f'FREE-{appointment.id}',
                })
                appointment.action_confirm()
                return request.redirect(f'/appointments/payment/success?appointment_id={appointment.id}')
            
            return request.redirect(f'/appointments/payment?appointment_id={appointment.id}')
            
        except Exception as e:
            return request.redirect(f'/appointments?error={str(e)}')
    
    @http.route('/appointments/payment', type='http', auth='public', website=True, methods=['GET', 'POST'])
    def payment_page(self, **kwargs):
        """Payment page for appointment booking"""
        if request.httprequest.method == 'GET':
            appointment_id = kwargs.get('appointment_id')
            if not appointment_id:
                return request.redirect('/appointments')

            appointment = request.env['custom.appointment'].sudo().browse(int(appointment_id))
            if not appointment.exists():
                return request.redirect('/appointments')
            if appointment.payment_status == 'paid':
                return request.redirect(f'/appointments/payment/success?appointment_id={appointment_id}')

            acquirers = request.env['payment.provider'].sudo().search([
                ('state', 'in', ['enabled', 'test']),
                ('is_published', '=', True)
            ])

            # No payment providers: auto-confirm and redirect to success (do not show payment page)
            if not acquirers:
                amount_to_charge = appointment.service_id.get_amount_to_charge()
                appointment.write({
                    'payment_status': 'paid',
                    'paid_amount': amount_to_charge,
                    'payment_date': fields.Datetime.now(),
                    'payment_method': 'No Payment Required',
                    'payment_reference': f'FREE-{appointment.id}',
                })
                appointment.action_confirm()
                return request.redirect(f'/appointments/payment/success?appointment_id={appointment.id}')

            amount_to_charge = appointment.service_id.get_amount_to_charge()

            return request.render('custom_appointments.payment_page', {
                'appointment': appointment,
                'acquirers': acquirers,
                'amount': amount_to_charge,
                'currency': appointment.currency_id,
            })
        
        elif request.httprequest.method == 'POST':
            return self._process_payment(kwargs)
    
    def _process_payment(self, data):
        """Process payment transaction"""
        try:
            appointment_id = int(data.get('appointment_id'))
            acquirer_id = int(data.get('acquirer_id'))
            
            appointment = request.env['custom.appointment'].sudo().browse(appointment_id)
            acquirer = request.env['payment.provider'].sudo().browse(acquirer_id)
            
            if not appointment.exists() or not acquirer.exists():
                raise ValueError("Invalid appointment or payment method")
            
            payment_method = request.env['payment.method'].sudo().search([
                ('code', '=', acquirer.code if acquirer.code != 'none' else 'card')
            ], limit=1)
            
            if not payment_method:
                payment_method = request.env['payment.method'].sudo().search([
                    ('code', '=', 'card')
                ], limit=1)
            
            if not payment_method:
                payment_method = request.env['payment.method'].sudo().search([], limit=1)
            
            if not payment_method:
                raise ValueError("No payment method available. Please contact support.")
            
            payment_method_line = request.env['account.payment.method.line'].sudo().search([
                ('payment_provider_id', '=', acquirer.id),
                ('payment_method_id', '=', payment_method.id),
            ], limit=1)
            
            if not payment_method_line:
                payment_method_line = request.env['account.payment.method.line'].sudo().search([
                    ('payment_method_id', '=', payment_method.id),
                    ('payment_type', '=', 'inbound'),
                ], limit=1)
            
            import time
            unique_ref = f"APPT-{appointment.id}-{int(time.time())}"
            
            amount_to_charge = appointment.service_id.get_amount_to_charge()
            
            if not appointment.partner_id:
                partner = appointment._find_or_create_partner(
                    appointment.customer_name,
                    appointment.customer_email,
                    appointment.customer_phone
                )
                appointment.partner_id = partner.id
            
            transaction_vals = {
                'amount': amount_to_charge,
                'currency_id': appointment.currency_id.id,
                'provider_id': acquirer.id,
                'payment_method_id': payment_method.id,
                'reference': unique_ref,
                'partner_id': appointment.partner_id.id,
                'partner_name': appointment.customer_name,
                'partner_email': appointment.customer_email,
            }
            
            if payment_method_line:
                transaction_vals['payment_method_line_id'] = payment_method_line.id
            
            transaction = request.env['payment.transaction'].sudo().create(transaction_vals)
            appointment.payment_transaction_id = transaction.id
            # Explicitly set appointment_id on transaction so it shows in Appointments Payments view
            # (the computed field runs before payment_transaction_id is set, so it would be False)
            transaction.appointment_id = appointment.id
            
            if acquirer.code == 'demo':
                transaction.write({'state': 'done'})
                appointment.write({
                    'payment_status': 'paid',
                    'paid_amount': transaction.amount,
                    'payment_date': fields.Datetime.now(),
                    'payment_method': acquirer.name,
                    'payment_reference': transaction.reference,
                })
                appointment.action_confirm()
                return request.redirect(f'/appointments/payment/success?appointment_id={appointment.id}')
            
            elif acquirer.code == 'mpesa':
                phone_number = data.get('mpesa_phone', '').strip()
                if not phone_number:
                    return request.redirect(f'/appointments/payment?appointment_id={appointment.id}&error=Phone number is required for M-Pesa payment')
                
                result = transaction._mpesa_initiate_stk_push(phone_number)
                if result:
                    return request.redirect(f'/appointments/payment/pending?appointment_id={appointment.id}')
                else:
                    return request.redirect(f'/appointments/payment?appointment_id={appointment.id}&error=Failed to initiate M-Pesa payment. Please try again.')
            
            elif acquirer.code == 'pesapal':
                processing_values = {
                    'reference': transaction.reference,
                    'amount': transaction.amount,
                    'currency': transaction.currency_id,
                    'partner_id': transaction.partner_id.id if transaction.partner_id else False,
                }
                
                try:
                    rendering_values = transaction._get_specific_rendering_values(processing_values)
                    redirect_url = rendering_values.get('redirect_url')
                    
                    if redirect_url:
                        return redirect(redirect_url, code=303)
                    else:
                        return request.redirect(f'/appointments/payment?appointment_id={appointment.id}&error=Failed to initialize PesaPal payment. Please try again.')
                except Exception as e:
                    error_msg = str(e).replace('\n', ' ').replace('\r', ' ')
                    return request.redirect(f'/appointments/payment?appointment_id={appointment.id}&error=PesaPal Error: {error_msg}')
            
            return request.redirect(f'/appointments/payment?appointment_id={appointment.id}&error=Payment method not yet fully configured')
            
        except Exception as e:
            error_msg = str(e).replace('\n', ' ').replace('\r', ' ')
            return request.redirect(f'/appointments/payment?appointment_id={appointment_id}&error={error_msg}')
    
    @http.route('/appointments/payment/webhook', type='http', auth='public', methods=['POST'], csrf=False)
    def payment_webhook(self, **kwargs):
        """Handle payment transaction status updates"""
        try:
            transaction_id = kwargs.get('transaction_id')
            if not transaction_id:
                return request.make_response('Missing transaction ID', status=400)
            
            transaction = request.env['payment.transaction'].sudo().browse(int(transaction_id))
            if not transaction.exists():
                return request.make_response('Transaction not found', status=404)
            
            appointment = request.env['custom.appointment'].sudo().search([
                ('payment_transaction_id', '=', transaction.id)
            ], limit=1)
            
            if appointment:
                if transaction.state == 'done':
                    appointment.write({
                        'payment_status': 'paid',
                        'paid_amount': transaction.amount,
                        'payment_date': fields.Datetime.now(),
                        'payment_method': transaction.provider_id.name,
                        'payment_reference': transaction.reference,
                    })
                    appointment.action_confirm()
                elif transaction.state in ['cancel', 'error']:
                    appointment.write({
                        'payment_status': 'failed'
                    })
            
            return request.make_response('OK', status=200)
            
        except Exception as e:
            return request.make_response(f'Error: {str(e)}', status=500)
    
    @http.route('/appointment/payment/status', type='json', auth='public')
    def check_payment_status(self, **kwargs):
        """Check payment status for appointment"""
        try:
            appointment_id = kwargs.get('appointment_id')
            if not appointment_id:
                return {'error': 'Missing appointment ID'}
            
            appointment = request.env['custom.appointment'].sudo().browse(int(appointment_id))
            if not appointment.exists():
                return {'error': 'Appointment not found'}
            
            return {
                'payment_status': appointment.payment_status,
                'state': appointment.state,
            }
        except Exception as e:
            return {'error': str(e)}
    
    @http.route('/appointments/payment/pending', type='http', auth='public', website=True)
    def payment_pending(self, **kwargs):
        """Payment pending page for M-Pesa"""
        appointment_id = kwargs.get('appointment_id')
        if not appointment_id:
            return request.redirect('/appointments')
        
        appointment = request.env['custom.appointment'].sudo().browse(int(appointment_id))
        if not appointment.exists():
            return request.redirect('/appointments')
        
        return request.render('custom_appointments.payment_pending_page', {
            'appointment': appointment,
        })
    
    @http.route('/appointments/payment/success', type='http', auth='public', website=True)
    def payment_success(self, **kwargs):
        """Payment success page"""
        appointment_id = kwargs.get('appointment_id')
        if not appointment_id:
            return request.redirect('/appointments')
        
        appointment = request.env['custom.appointment'].sudo().browse(int(appointment_id))
        if not appointment.exists():
            return request.redirect('/appointments')
        
        return request.render('custom_appointments.payment_success_page', {
            'appointment': appointment,
        })
    
    @http.route('/tcs', type='http', auth='public', website=True, sitemap=True)
    def terms_page(self, **kwargs):
        """Terms and Conditions page - editable in website editor"""
        return request.render('custom_appointments.terms_page', {})