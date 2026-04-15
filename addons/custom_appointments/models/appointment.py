from odoo import models, fields, api, _
from odoo.exceptions import ValidationError
from datetime import datetime, timedelta
import base64
from icalendar import Calendar, Event as ICalEvent
import pytz
import logging

_logger = logging.getLogger(__name__)


class Appointment(models.Model):
    _name = 'custom.appointment'
    _description = 'Customer Appointment'
    _rec_name = 'name'
    _order = 'start desc'
    _inherit = ['mail.thread', 'mail.activity.mixin']

    name = fields.Char(string='Appointment Title', required=True)
    customer_name = fields.Char(string='Customer Name', required=True)
    customer_email = fields.Char(string='Customer Email', required=True)
    customer_phone = fields.Char(string='Customer Phone')
    partner_id = fields.Many2one('res.partner', string='Customer', ondelete='set null', 
                                 help='Customer partner record for CRM and payment tracking')
    
    service_id = fields.Many2one('company.service', string='Service', required=True, ondelete='cascade')
    staff_member_id = fields.Many2one('custom.staff.member', string='Staff Member', required=True, ondelete='cascade')
    branch_id = fields.Many2one('custom.branch', string='Branch', ondelete='set null')
    
    start = fields.Datetime(string='Start Time', required=True)
    stop = fields.Datetime(string='End Time', required=True)
    duration = fields.Float(string='Duration (Hours)', compute='_compute_duration', store=True)
    
    description = fields.Text(string='Description')
    
    calendar_event_id = fields.Many2one('calendar.event', string='Calendar Event')
    user_id = fields.Many2one('res.users', string='Responsible User')
    
    state = fields.Selection([
        ('draft', 'Draft'),
        ('confirmed', 'Confirmed'),
        ('in_progress', 'In Progress'),
        ('completed', 'Completed'),
        ('cancelled', 'Cancelled')
    ], string='Status', default='draft', required=True)
    
    price = fields.Monetary(string='Price', currency_field='currency_id')
    currency_id = fields.Many2one('res.currency', string='Currency', 
                                  default=lambda self: self.env.company.currency_id)
    
    internal_notes = fields.Text(string='Internal Notes')
    
    payment_status = fields.Selection([
        ('pending', 'Payment Pending'),
        ('paid', 'Paid'),
        ('failed', 'Payment Failed'),
        ('refunded', 'Refunded')
    ], string='Payment Status', default='pending', required=True)
    
    payment_transaction_id = fields.Many2one('payment.transaction', string='Payment Transaction')
    payment_method = fields.Char(string='Payment Method')
    payment_reference = fields.Char(string='Payment Reference')
    paid_amount = fields.Monetary(string='Paid Amount', currency_field='currency_id')
    payment_date = fields.Datetime(string='Payment Date')
    
    invoice_id = fields.Many2one('account.move', string='Invoice', domain="[('move_type', '=', 'out_invoice')]", copy=False)
    invoice_count = fields.Integer(string='Invoice Count', compute='_compute_invoice_count')
    payment_id = fields.Many2one('account.payment', string='Payment', copy=False, 
                                  help='The accounting payment record created for this appointment')
    payment_count = fields.Integer(string='Payment Count', compute='_compute_payment_count')
    
    customer_notification_sent = fields.Boolean(string='Customer Notification Sent', default=False)
    staff_notification_sent = fields.Boolean(string='Staff Notification Sent', default=False)
    
    promo_id = fields.Many2one('custom.appointment.promo', string='Promo Code', ondelete='set null',
                                help='Promo code applied to this appointment')
    promo_code_entered = fields.Char(string='Promo Code Entered', help='The promo code string entered by customer')
    discount_amount = fields.Monetary(string='Discount Amount', currency_field='currency_id', default=0)
    final_price = fields.Monetary(string='Final Price', currency_field='currency_id', 
                                   compute='_compute_final_price', store=True)
    
    # Health Disclosure Fields
    has_allergies = fields.Boolean(string='Has Allergies', default=False,
                                   help='Customer has allergies that staff should be aware of')
    allergies_details = fields.Char(string='Allergies Details',
                                    help='Specific allergies the customer has')
    has_eye_conditions = fields.Boolean(string='Has Eye Conditions', default=False,
                                        help='Customer has eye conditions')
    is_pregnant = fields.Boolean(string='Is Pregnant', default=False,
                                 help='Customer is pregnant')
    no_health_conditions = fields.Boolean(string='No Health Conditions', default=False,
                                          help='Customer confirmed no health conditions')
    
    # Desired Outcome Fields
    desired_lash_look = fields.Text(string='Desired Lash Look',
                                    help='What lash look the customer is hoping to achieve')
    has_previous_extensions = fields.Selection([
        ('yes', 'Yes'),
        ('no', 'No')
    ], string='Had Lash Extensions Before',
       help='Whether the customer has had lash extensions before')
    
    # Follow-up Tracking Fields
    followup_count = fields.Integer(
        string='Follow-up Count',
        default=0,
        help='Number of follow-up messages sent for this appointment'
    )
    last_followup_date = fields.Date(
        string='Last Follow-up Date',
        help='Date when the last follow-up message was sent'
    )
    followup_stopped = fields.Boolean(
        string='Stop Follow-ups',
        default=False,
        help='Manually stop sending follow-up messages for this appointment'
    )
    
    @api.depends('invoice_id')
    def _compute_invoice_count(self):
        for appointment in self:
            appointment.invoice_count = 1 if appointment.invoice_id else 0
    
    @api.depends('payment_id')
    def _compute_payment_count(self):
        for appointment in self:
            appointment.payment_count = 1 if appointment.payment_id else 0
    
    @api.depends('start', 'stop')
    def _compute_duration(self):
        for appointment in self:
            if appointment.start and appointment.stop:
                delta = appointment.stop - appointment.start
                appointment.duration = delta.total_seconds() / 3600.0
            else:
                appointment.duration = 0.0
    
    @api.depends('price', 'discount_amount')
    def _compute_final_price(self):
        for appointment in self:
            appointment.final_price = max(0, (appointment.price or 0) - (appointment.discount_amount or 0))
    
    @api.onchange('service_id')
    def _onchange_service_id(self):
        if self.service_id:
            self.price = self.service_id.price
            self.currency_id = self.service_id.currency_id
            if self.start and self.service_id.duration:
                self.stop = self.start + timedelta(hours=self.service_id.duration)
    
    @api.onchange('staff_member_id')
    def _onchange_staff_member_id(self):
        if self.staff_member_id:
            self.branch_id = self.staff_member_id.branch_id
            if self.staff_member_id.employee_id and self.staff_member_id.employee_id.user_id:
                self.user_id = self.staff_member_id.employee_id.user_id
    
    @api.onchange('start', 'service_id')
    def _onchange_start_time(self):
        if self.start and self.service_id and self.service_id.duration:
            self.stop = self.start + timedelta(hours=self.service_id.duration)
    
    @api.constrains('staff_member_id', 'start', 'stop', 'state')
    def _check_staff_availability(self):
        """Validate that the staff member doesn't have overlapping appointments"""
        for appointment in self:
            # Skip validation for cancelled appointments
            if appointment.state == 'cancelled':
                continue
            
            if not appointment.start or not appointment.stop or not appointment.staff_member_id:
                continue
            
            # Search for conflicting appointments
            domain = [
                ('staff_member_id', '=', appointment.staff_member_id.id),
                ('id', '!=', appointment.id),  # Exclude current appointment
                ('state', 'in', ['draft', 'confirmed', 'in_progress']),  # Only active appointments
                ('start', '<', appointment.stop),
                ('stop', '>', appointment.start),
            ]
            
            conflicting_appointments = self.search(domain, limit=1)
            
            if conflicting_appointments:
                raise ValidationError(_(
                    'The staff member "%s" already has an appointment scheduled from %s to %s. '
                    'Please choose a different time slot or staff member.'
                ) % (
                    appointment.staff_member_id.name,
                    conflicting_appointments.start.strftime('%Y-%m-%d %H:%M'),
                    conflicting_appointments.stop.strftime('%Y-%m-%d %H:%M')
                ))
    
    def _find_or_create_partner(self, name, email, phone=None):
        """Find existing partner by email or create a new one"""
        Partner = self.env['res.partner'].sudo()
        
        partner = Partner.search([('email', '=', email)], limit=1)
        
        if partner:
            if phone and not partner.phone:
                partner.write({'phone': phone})
            return partner
        
        partner_vals = {
            'name': name,
            'email': email,
            'phone': phone,
            'customer_rank': 1,
            'is_company': False,
        }
        
        return Partner.create(partner_vals)
    
    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if not vals.get('name') and vals.get('service_id') and vals.get('customer_name'):
                service = self.env['company.service'].browse(vals['service_id'])
                vals['name'] = f"{service.name} - {vals['customer_name']}"
            
            if vals.get('staff_member_id'):
                staff = self.env['custom.staff.member'].browse(vals['staff_member_id'])
                if staff.employee_id and staff.employee_id.user_id:
                    vals['user_id'] = staff.employee_id.user_id.id
            
            if not vals.get('partner_id') and vals.get('customer_email'):
                partner = self._find_or_create_partner(
                    vals.get('customer_name'),
                    vals.get('customer_email'),
                    vals.get('customer_phone')
                )
                vals['partner_id'] = partner.id
        
        appointments = super(Appointment, self).create(vals_list)
        appointments._create_calendar_event()
        return appointments
    
    def _create_calendar_event(self):
        """Create a corresponding calendar event for this appointment"""
        for appointment in self:
            if not appointment.calendar_event_id and appointment.start and appointment.stop:
                event_vals = {
                    'name': appointment.name,
                    'start': appointment.start,
                    'stop': appointment.stop,
                    'description': appointment.description or '',
                    'user_id': appointment.user_id.id if appointment.user_id else False,
                }
                calendar_event = self.env['calendar.event'].create(event_vals)
                appointment.calendar_event_id = calendar_event.id
    
    def write(self, vals):
        result = super(Appointment, self).write(vals)
        if any(field in vals for field in ['name', 'start', 'stop', 'description', 'user_id']):
            self._update_calendar_event()
        return result
    
    def _update_calendar_event(self):
        """Update the corresponding calendar event"""
        for appointment in self:
            if appointment.calendar_event_id:
                event_vals = {
                    'name': appointment.name,
                    'start': appointment.start,
                    'stop': appointment.stop,
                    'description': appointment.description or '',
                    'user_id': appointment.user_id.id if appointment.user_id else False,
                }
                appointment.calendar_event_id.write(event_vals)
    
    def action_confirm(self):
        _logger.info(f"=== action_confirm called for appointment {self.id} ===")
        _logger.info(f"Payment status: {self.payment_status}, State: {self.state}")
        _logger.info(f"Staff member: {self.staff_member_id.name} (ID: {self.staff_member_id.id})")
        _logger.info(f"Staff email: {self.staff_member_id.email if self.staff_member_id.email else 'NOT SET'}")
        
        if self.payment_status != 'paid':
            from odoo.exceptions import UserError
            raise UserError("Cannot confirm appointment without successful payment.")
        self.state = 'confirmed'
        
        if not self.invoice_id:
            if self.paid_amount and self.paid_amount > 0:
                _logger.info(f"Creating invoice for appointment {self.id}")
                self._create_and_pay_invoice()
            else:
                _logger.info(f"Skipping invoice creation for appointment {self.id} (paid_amount={self.paid_amount})")
        
        _logger.info(f"Calling _send_confirmation_notifications() for appointment {self.id}")
        self._send_confirmation_notifications()
        
        _logger.info(f"Calling _send_staff_notification() for appointment {self.id}")
        self._send_staff_notification()
        
        _logger.info(f"=== action_confirm completed for appointment {self.id} ===")
        return True
    
    def action_start(self):
        self.state = 'in_progress'
        return True
    
    def action_complete(self):
        self.state = 'completed'
        return True
    
    def action_cancel(self):
        self.state = 'cancelled'
        self._send_cancellation_notifications()
        return True
    
    def action_reset_to_draft(self):
        self.state = 'draft'
        return True
    
    def _create_and_pay_invoice(self):
        """Create invoice and mark as paid when payment is already completed.
        
        Uses account.payment.register wizard for proper payment creation which ensures:
        - Payment is properly linked to the invoice
        - Payment state is correctly computed (paid vs in_process)
        - Reconciliation is handled by Odoo's standard flow
        """
        self.ensure_one()
        
        _logger.info(f"=== _create_and_pay_invoice called for appointment {self.id} ===")
        _logger.info(f"Payment status: {self.payment_status}, Paid amount: {self.paid_amount}")
        _logger.info(f"Payment method: {self.payment_method}, Payment reference: {self.payment_reference}")
        
        try:
            if not self.partner_id:
                partner = self._find_or_create_partner(
                    self.customer_name,
                    self.customer_email,
                    self.customer_phone
                )
                self.partner_id = partner.id
                _logger.info(f"Created/found partner {partner.id} for appointment {self.id}")
            
            invoice_lines = [(0, 0, {
                'name': f"{self.service_id.name} - {self.name}",
                'quantity': 1,
                'price_unit': self.price,
            })]
            
            if self.promo_id and self.discount_amount > 0:
                invoice_lines.append((0, 0, {
                    'name': f"Discount ({self.promo_id.code})",
                    'quantity': 1,
                    'price_unit': -self.discount_amount,
                }))
            
            invoice_vals = {
                'move_type': 'out_invoice',
                'partner_id': self.partner_id.id,
                'invoice_date': fields.Date.today(),
                'invoice_line_ids': invoice_lines,
            }
            
            invoice = self.env['account.move'].create(invoice_vals)
            self.invoice_id = invoice.id
            _logger.info(f"Created invoice {invoice.name} (ID: {invoice.id}) for appointment {self.id}")
            
            invoice.action_post()
            _logger.info(f"Posted invoice {invoice.name}")
            
            if self.payment_status == 'paid' and self.paid_amount > 0:
                _logger.info(f"Registering payment for appointment {self.id}")
                # Use same company as invoice to avoid multi-company error
                bank_journal = self.env['account.journal'].search([
                    ('type', '=', 'bank'),
                    ('company_id', '=', invoice.company_id.id),
                ], limit=1)
                if not bank_journal:
                    _logger.error(f"No bank journal found! Cannot create payment for appointment {self.id}")
                    return invoice
                
                payment_method_line = self.env['account.payment.method.line'].search([
                    ('payment_type', '=', 'inbound'),
                    ('journal_id', '=', bank_journal.id)
                ], limit=1)
                
                if not payment_method_line:
                    _logger.error(f"No payment method line found for journal {bank_journal.name}! Cannot create payment for appointment {self.id}")
                    return invoice
                
                _logger.info(f"Using journal: {bank_journal.name} (ID: {bank_journal.id})")
                _logger.info(f"Using payment method line: {payment_method_line.name} (ID: {payment_method_line.id})")
                
                # Build memo with payment details from PesaPal/M-Pesa
                memo_parts = []
                if self.payment_method:
                    memo_parts.append(self.payment_method)
                if self.payment_reference:
                    memo_parts.append(self.payment_reference)
                if self.payment_transaction_id and self.payment_transaction_id.provider_reference:
                    memo_parts.append(f"Ref: {self.payment_transaction_id.provider_reference}")
                memo = ' - '.join(memo_parts) if memo_parts else self.name
                
                # Use account.payment.register wizard for proper payment creation
                # This ensures the payment is properly linked to the invoice and state is computed correctly
                payment_date = self.payment_date.date() if self.payment_date else fields.Date.today()
                
                payment_register = self.env['account.payment.register'].with_context(
                    active_model='account.move',
                    active_ids=invoice.ids,
                ).create({
                    'payment_date': payment_date,
                    'amount': self.paid_amount,
                    'journal_id': bank_journal.id,
                    'payment_method_line_id': payment_method_line.id,
                    'communication': memo,
                })
                
                payments = payment_register._create_payments()
                _logger.info(f"Created payment(s) via register wizard: {payments.mapped('name')}")
                
                if payments:
                    payment = payments[0]
                    self.payment_id = payment.id
                    _logger.info(f"Linked payment {payment.name} (ID: {payment.id}) to appointment {self.id}")
                    _logger.info(f"Payment state: {payment.state}, is_reconciled: {payment.is_reconciled}")
                    
                    # Link payment back to the transaction so the cron doesn't try to create another payment
                    if self.payment_transaction_id:
                        self.payment_transaction_id.payment_id = payment.id
                        _logger.info(f"Linked payment to transaction {self.payment_transaction_id.id} to prevent duplicate payment creation by cron")
            
            _logger.info(f"=== Invoice creation completed for appointment {self.id} ===")
            return invoice
            
        except Exception as e:
            _logger.error(f"Error creating invoice/payment for appointment {self.id}: {str(e)}")
            _logger.exception(e)
            raise
    
    def action_create_invoice(self):
        self.ensure_one()
        if self.invoice_id:
            return self.action_view_invoice()
        
        if not self.partner_id:
            partner = self._find_or_create_partner(
                self.customer_name,
                self.customer_email,
                self.customer_phone
            )
            self.partner_id = partner.id
        
        invoice_vals = {
            'move_type': 'out_invoice',
            'partner_id': self.partner_id.id,
            'invoice_date': fields.Date.today(),
            'invoice_line_ids': [(0, 0, {
                'name': f"{self.service_id.name} - {self.name}",
                'quantity': 1,
                'price_unit': self.price,
            })],
        }
        
        invoice = self.env['account.move'].create(invoice_vals)
        self.invoice_id = invoice.id
        
        return self.action_view_invoice()
    
    def action_view_invoice(self):
        self.ensure_one()
        return {
            'name': 'Invoice',
            'type': 'ir.actions.act_window',
            'res_model': 'account.move',
            'view_mode': 'form',
            'res_id': self.invoice_id.id,
            'context': {'default_move_type': 'out_invoice'},
        }
    
    def action_view_payment(self):
        self.ensure_one()
        return {
            'name': 'Payment',
            'type': 'ir.actions.act_window',
            'res_model': 'account.payment',
            'view_mode': 'form',
            'res_id': self.payment_id.id,
        }
    
    @api.model
    def get_my_appointments(self):
        """Get appointments for the current user"""
        if not self.env.user:
            return self.browse([])
        
        my_appointments = self.search([('user_id', '=', self.env.user.id)])
        
        staff_members = self.env['custom.staff.member'].search([
            ('employee_id.user_id', '=', self.env.user.id)
        ])
        if staff_members:
            staff_appointments = self.search([('staff_member_id', 'in', staff_members.ids)])
            my_appointments = my_appointments | staff_appointments
        
        return my_appointments
    
    def _generate_ics_attachment(self):
        """Generate .ics calendar invite file for the appointment"""
        self.ensure_one()
        import pytz
        
        cal = Calendar()
        cal.add('prodid', '-//Odoo Appointment System//EN')
        cal.add('version', '2.0')
        cal.add('method', 'REQUEST')
        
        try:
            local_tz = pytz.timezone(self.env.user.tz or 'Africa/Nairobi')
        except:
            local_tz = pytz.timezone('Africa/Nairobi')
        
        local_start = self._get_local_datetime(self.start)
        local_stop = self._get_local_datetime(self.stop)
        
        event = ICalEvent()
        event.add('summary', self.name)
        event.add('dtstart', local_start)
        event.add('dtend', local_stop)
        event.add('dtstamp', datetime.now(pytz.utc))
        
        location_parts = []
        if self.branch_id:
            if self.branch_id.name:
                location_parts.append(self.branch_id.name)
            if self.branch_id.street:
                location_parts.append(self.branch_id.street)
            if self.branch_id.city:
                location_parts.append(self.branch_id.city)
        
        if location_parts:
            event.add('location', ', '.join(location_parts))
        
        description_parts = [
            f"Service: {self.service_id.name}",
            f"Staff Member: {self.staff_member_id.name}",
            f"Duration: {self.duration} hours",
        ]
        
        if self.branch_id and self.branch_id.phone:
            description_parts.append(f"Contact: {self.branch_id.phone}")
        
        if self.description:
            description_parts.append(f"\nNotes: {self.description}")
        
        event.add('description', '\n'.join(description_parts))
        event.add('uid', f'appointment-{self.id}@{self.env.company.name.replace(" ", "-")}')
        event.add('priority', 5)
        event.add('sequence', 0)
        event.add('status', 'CONFIRMED')
        
        if self.customer_email:
            event.add('attendee', f'MAILTO:{self.customer_email}')
        
        if self.staff_member_id.email:
            event.add('organizer', f'MAILTO:{self.staff_member_id.email}')
        
        cal.add_component(event)
        
        ics_content = cal.to_ical()
        ics_base64 = base64.b64encode(ics_content)
        
        attachment = self.env['ir.attachment'].create({
            'name': f'appointment_{self.id}.ics',
            'datas': ics_base64,
            'res_model': 'custom.appointment',
            'res_id': self.id,
            'mimetype': 'text/calendar',
        })
        
        return attachment
    
    def _get_server_timezone(self):
        """Get the server timezone - defaults to Africa/Nairobi (EAT)"""
        tz_name = self.env['ir.config_parameter'].sudo().get_param('appointment.timezone', 'Africa/Nairobi')
        try:
            return pytz.timezone(tz_name)
        except:
            return pytz.timezone('Africa/Nairobi')
    
    def _get_local_datetime(self, utc_datetime):
        """Convert UTC datetime to server timezone"""
        if not utc_datetime:
            return None
        
        server_tz = self._get_server_timezone()
        
        if isinstance(utc_datetime, str):
            utc_datetime = datetime.strptime(utc_datetime, '%Y-%m-%d %H:%M:%S')
        
        if utc_datetime.tzinfo is None:
            utc_datetime = pytz.utc.localize(utc_datetime)
        
        return utc_datetime.astimezone(server_tz)
    
    def _localize_to_server_tz(self, naive_datetime):
        """Convert naive datetime (assumed to be in server timezone) to UTC for storage"""
        if not naive_datetime:
            return None
        
        server_tz = self._get_server_timezone()
        
        local_dt = server_tz.localize(naive_datetime)
        
        return local_dt.astimezone(pytz.utc).replace(tzinfo=None)
    
    def _load_email_template(self, template_name):
        """Load HTML email template from file"""
        import os
        module_path = os.path.dirname(os.path.dirname(__file__))
        template_path = os.path.join(module_path, 'templates', 'email', f'{template_name}.html')
        with open(template_path, 'r', encoding='utf-8') as f:
            return f.read()
    
    def _generate_confirmation_email_html(self):
        """Generate HTML for confirmation email"""
        self.ensure_one()
        template = self._load_email_template('confirmation')
        
        local_start = self._get_local_datetime(self.start)
        
        return template.format(
            customer_name=self.customer_name,
            service_name=self.service_id.name,
            staff_name=self.staff_member_id.name,
            start_formatted=local_start.strftime('%A, %B %d, %Y - %I:%M %p'),
            duration=self.duration,
            branch_name=self.branch_id.name,
            price=self.price,
            currency_symbol=self.currency_id.symbol,
            branch_phone=self.branch_id.phone or self.env.user.company_id.phone,
            branch_email=self.branch_id.email or self.env.user.company_id.email,
            company_name=self.env.user.company_id.name,
            branch_address=f"{self.branch_id.street}, {self.branch_id.city}"
        )
    
    def _send_confirmation_notifications(self):
        """Send confirmation email to customer and SMS if phone is provided"""
        for appointment in self:
            if appointment.customer_notification_sent:
                _logger.info(f"Customer notification already sent for appointment {appointment.id}, skipping")
                continue
                
            if appointment.customer_email:
                _logger.info(f"Sending confirmation email to customer {appointment.customer_name} ({appointment.customer_email}) for appointment {appointment.id}")
                try:
                    ics_attachment = appointment._generate_ics_attachment()
                    _logger.info(f"Generated calendar invite attachment (ID: {ics_attachment.id}) for appointment {appointment.id}")
                    
                    subject = f"Appointment Confirmed - {appointment.name}"
                    body_html = appointment._generate_confirmation_email_html()
                    email_from = appointment.branch_id.email or self.env.user.company_id.email or 'noreply@localhost'
                    
                    mail = self.env['mail.mail'].sudo().create({
                        'subject': subject,
                        'body_html': body_html,
                        'email_to': appointment.customer_email,
                        'email_from': email_from,
                        'attachment_ids': [(4, ics_attachment.id)],
                    })
                    mail.send()
                    _logger.info(f"Successfully sent confirmation email with calendar invite to {appointment.customer_email}")
                    appointment.customer_notification_sent = True
                except Exception as e:
                    _logger.error(f"Failed to send confirmation email to {appointment.customer_email}: {str(e)}", exc_info=True)
            
            if appointment.customer_phone:
                local_start = appointment._get_local_datetime(appointment.start)
                # Enhanced SMS with branch and appointment details
                sms_message = (
                    f"✓ Appointment Confirmed!\n"
                    f"Service: {appointment.service_id.name}\n"
                    f"Date: {local_start.strftime('%B %d, %Y')}\n"
                    f"Time: {local_start.strftime('%I:%M %p')}\n"
                    f"Duration: {appointment.duration} hrs\n"
                    f"Staff: {appointment.staff_member_id.name}\n"
                    f"Location: {appointment.branch_id.name}\n"
                    f"Address: {appointment.branch_id.street}, {appointment.branch_id.city}\n"
                    f"Phone: {appointment.branch_id.phone or self.env.user.company_id.phone}\n"
                    f"Ref: {appointment.name}"
                )
                self._send_sms_notification(appointment.customer_phone, sms_message)
    
    def _generate_cancellation_email_html(self):
        """Generate HTML for cancellation email"""
        self.ensure_one()
        template = self._load_email_template('cancellation')
        
        local_start = self._get_local_datetime(self.start)
        
        return template.format(
            customer_name=self.customer_name,
            service_name=self.service_id.name,
            staff_name=self.staff_member_id.name,
            start_formatted=local_start.strftime('%A, %B %d, %Y - %I:%M %p'),
            branch_name=self.branch_id.name,
            branch_phone=self.branch_id.phone or self.env.user.company_id.phone,
            branch_email=self.branch_id.email or self.env.user.company_id.email,
            company_name=self.env.user.company_id.name,
            branch_address=f"{self.branch_id.street}, {self.branch_id.city}"
        )
    
    def _send_cancellation_notifications(self):
        """Send cancellation email to customer and SMS if phone is provided"""
        for appointment in self:
            if appointment.customer_email:
                _logger.info(f"Sending cancellation email to customer {appointment.customer_name} ({appointment.customer_email}) for appointment {appointment.id}")
                try:
                    subject = f"Appointment Cancelled - {appointment.name}"
                    body_html = appointment._generate_cancellation_email_html()
                    email_from = appointment.branch_id.email or self.env.user.company_id.email or 'noreply@localhost'
                    
                    mail = self.env['mail.mail'].sudo().create({
                        'subject': subject,
                        'body_html': body_html,
                        'email_to': appointment.customer_email,
                        'email_from': email_from,
                    })
                    mail.send()
                    _logger.info(f"Successfully sent cancellation email to {appointment.customer_email}")
                except Exception as e:
                    _logger.error(f"Failed to send cancellation email to {appointment.customer_email}: {str(e)}", exc_info=True)
            
            if appointment.customer_phone:
                local_start = appointment._get_local_datetime(appointment.start)
                # Enhanced cancellation SMS with branch contact info
                sms_message = (
                    f"✗ Appointment Cancelled\n"
                    f"Service: {appointment.service_id.name}\n"
                    f"Was scheduled: {local_start.strftime('%B %d at %I:%M %p')}\n"
                    f"Ref: {appointment.name}\n\n"
                    f"To reschedule, contact:\n"
                    f"{appointment.branch_id.name}\n"
                    f"Phone: {appointment.branch_id.phone or self.env.user.company_id.phone}\n"
                    f"Email: {appointment.branch_id.email or self.env.user.company_id.email}"
                )
                self._send_sms_notification(appointment.customer_phone, sms_message)
    
    def _generate_staff_notification_email_html(self):
        """Generate HTML for staff notification email"""
        self.ensure_one()
        template = self._load_email_template('staff_notification')
        
        local_start = self._get_local_datetime(self.start)
        
        return template.format(
            staff_name=self.staff_member_id.name,
            customer_name=self.customer_name,
            customer_email=self.customer_email,
            customer_phone=self.customer_phone or 'Not provided',
            service_name=self.service_id.name,
            start_formatted=local_start.strftime('%A, %B %d, %Y - %I:%M %p'),
            duration=self.duration,
            branch_name=self.branch_id.name,
            company_name=self.env.user.company_id.name,
            branch_address=f"{self.branch_id.street}, {self.branch_id.city}"
        )
    
    def _send_staff_notification(self):
        """Send notification to staff member about new appointment"""
        for appointment in self:
            if appointment.staff_notification_sent:
                _logger.info(f"Staff notification already sent for appointment {appointment.id}, skipping")
                continue
                
            if appointment.staff_member_id.email:
                _logger.info(f"Sending notification email to staff {appointment.staff_member_id.name} ({appointment.staff_member_id.email}) for appointment {appointment.id}")
                try:
                    ics_attachment = appointment._generate_ics_attachment()
                    _logger.info(f"Generated calendar invite attachment (ID: {ics_attachment.id}, name: {ics_attachment.name}, mimetype: {ics_attachment.mimetype}) for staff notification")
                    
                    subject = f"New Appointment Booked - {appointment.name}"
                    body_html = appointment._generate_staff_notification_email_html()
                    email_from = self.env.user.company_id.email or 'noreply@localhost'
                    
                    mail = self.env['mail.mail'].sudo().create({
                        'subject': subject,
                        'body_html': body_html,
                        'email_to': appointment.staff_member_id.email,
                        'email_from': email_from,
                        'attachment_ids': [(4, ics_attachment.id)],
                    })
                    _logger.info(f"Created mail record (ID: {mail.id}) with attachment IDs: {mail.attachment_ids.ids}")
                    mail.send()
                    _logger.info(f"Successfully sent staff notification email with calendar invite to {appointment.staff_member_id.email}")
                    appointment.staff_notification_sent = True
                except Exception as e:
                    _logger.error(f"Failed to send staff notification to {appointment.staff_member_id.email}: {str(e)}", exc_info=True)
            else:
                _logger.warning(f"Staff member {appointment.staff_member_id.name} (ID: {appointment.staff_member_id.id}) has no email address set for appointment {appointment.id}")
            
            # Send SMS notification to staff member
            if appointment.staff_member_id.phone:
                local_start = appointment._get_local_datetime(appointment.start)
                sms_message = (
                    f"📅 New Appointment!\n"
                    f"Customer: {appointment.customer_name}\n"
                    f"Service: {appointment.service_id.name}\n"
                    f"Date: {local_start.strftime('%B %d, %Y')}\n"
                    f"Time: {local_start.strftime('%I:%M %p')}\n"
                    f"Duration: {appointment.duration} hrs\n"
                    f"Customer Phone: {appointment.customer_phone or 'Not provided'}\n"
                    f"Location: {appointment.branch_id.name}\n"
                    f"Ref: {appointment.name}"
                )
                _logger.info(f"Sending SMS notification to staff {appointment.staff_member_id.name} at {appointment.staff_member_id.phone}")
                self._send_sms_notification(appointment.staff_member_id.phone, sms_message)
    
    def _generate_reminder_email_html(self):
        """Generate HTML for reminder email"""
        self.ensure_one()
        template = self._load_email_template('reminder')
        
        local_start = self._get_local_datetime(self.start)
        
        return template.format(
            customer_name=self.customer_name,
            service_name=self.service_id.name,
            staff_name=self.staff_member_id.name,
            start_formatted=local_start.strftime('%A, %B %d, %Y - %I:%M %p'),
            duration=self.duration,
            branch_name=self.branch_id.name,
            branch_phone=self.branch_id.phone or self.env.user.company_id.phone,
            branch_email=self.branch_id.email or self.env.user.company_id.email,
            company_name=self.env.user.company_id.name,
            branch_address=f"{self.branch_id.street}, {self.branch_id.city}"
        )
    
    def _send_reminder_notifications(self):
        """Send reminder notifications (to be called by scheduled action)"""
        for appointment in self:
            if appointment.customer_email:
                subject = f"Reminder: Your appointment tomorrow - {appointment.name}"
                body_html = appointment._generate_reminder_email_html()
                email_from = appointment.branch_id.email or self.env.user.company_id.email or 'noreply@localhost'
                
                mail = self.env['mail.mail'].sudo().create({
                    'subject': subject,
                    'body_html': body_html,
                    'email_to': appointment.customer_email,
                    'email_from': email_from,
                })
                mail.send()
            
            if appointment.customer_phone:
                local_start = appointment._get_local_datetime(appointment.start)
                # Enhanced reminder SMS with full appointment details
                sms_message = (
                    f"⏰ Reminder: Appointment Tomorrow!\n"
                    f"Service: {appointment.service_id.name}\n"
                    f"Date: {local_start.strftime('%A, %B %d')}\n"
                    f"Time: {local_start.strftime('%I:%M %p')}\n"
                    f"Duration: {appointment.duration} hrs\n"
                    f"Staff: {appointment.staff_member_id.name}\n"
                    f"Location: {appointment.branch_id.name}\n"
                    f"Address: {appointment.branch_id.street}, {appointment.branch_id.city}\n"
                    f"Contact: {appointment.branch_id.phone or self.env.user.company_id.phone}\n"
                    f"See you tomorrow!"
                )
                self._send_sms_notification(appointment.customer_phone, sms_message)
    
    def _send_sms_notification(self, phone_number, message):
        """Send SMS notification using Odoo's SMS gateway"""
        try:
            self.env['sms.sms'].create({
                'number': phone_number,
                'body': message,
                'state': 'outgoing',
            })
        except Exception as e:
            import logging
            _logger = logging.getLogger(__name__)
            _logger.warning(f"Failed to send SMS to {phone_number}: {str(e)}")
    
    @api.model
    def send_appointment_reminders(self):
        """Scheduled method to send appointment reminders 24 hours before"""
        from datetime import datetime, timedelta
        
        tomorrow = datetime.now() + timedelta(days=1)
        start_of_day = tomorrow.replace(hour=0, minute=0, second=0, microsecond=0)
        end_of_day = tomorrow.replace(hour=23, minute=59, second=59, microsecond=999999)
        
        appointments = self.search([
            ('state', '=', 'confirmed'),
            ('start', '>=', start_of_day),
            ('start', '<=', end_of_day)
        ])
        
        for appointment in appointments:
            appointment._send_reminder_notifications()
    
    # ==================== FOLLOW-UP REMINDER METHODS ====================
    
    def _check_customer_rebooked(self):
        """Check if customer has booked a new appointment after this one"""
        self.ensure_one()
        newer_appointment = self.search([
            ('customer_email', '=', self.customer_email),
            ('start', '>', self.stop),
            ('state', 'in', ['draft', 'confirmed', 'in_progress', 'completed']),
            ('id', '!=', self.id)
        ], limit=1)
        return bool(newer_appointment)
    
    def _get_booking_link(self):
        """Generate the booking link for follow-up messages"""
        base_url = self.env['ir.config_parameter'].sudo().get_param('web.base.url', '')
        return f"{base_url}/appointments"
    
    def _generate_followup_email_html(self, settings):
        """Generate HTML for follow-up email"""
        self.ensure_one()
        template = self._load_email_template('followup')
        
        local_stop = self._get_local_datetime(self.stop)
        booking_link = self._get_booking_link()
        
        return template.format(
            customer_name=self.customer_name,
            service_name=self.service_id.name,
            appointment_date=local_stop.strftime('%B %d, %Y'),
            branch_name=self.branch_id.name if self.branch_id else '',
            booking_link=booking_link,
            branch_phone=self.branch_id.phone if self.branch_id else self.env.user.company_id.phone,
            branch_email=self.branch_id.email if self.branch_id else self.env.user.company_id.email,
            company_name=self.env.user.company_id.name,
        )
    
    def _generate_followup_sms(self, settings):
        """Generate SMS message for follow-up"""
        self.ensure_one()
        booking_link = self._get_booking_link()
        
        # Use custom template if provided, otherwise use default
        if settings.followup_sms_template:
            message = settings.followup_sms_template.format(
                customer_name=self.customer_name,
                service_name=self.service_id.name,
                branch_name=self.branch_id.name if self.branch_id else '',
                booking_link=booking_link,
            )
        else:
            message = (
                f"Hi {self.customer_name}! We hope you enjoyed your {self.service_id.name}. "
                f"Ready for your next session? Book now: {booking_link}"
            )
        
        return message
    
    def _send_followup_notifications(self, settings):
        """Send follow-up email and/or SMS to customer"""
        self.ensure_one()
        
        _logger.info(f"Sending follow-up notification for appointment {self.id} (count: {self.followup_count + 1})")
        
        try:
            # Send Email if enabled
            if settings.followup_channel in ['email', 'both'] and self.customer_email:
                _logger.info(f"Sending follow-up email to {self.customer_email}")
                try:
                    subject = settings.followup_email_subject or "We Miss You! Book Your Next Session"
                    body_html = self._generate_followup_email_html(settings)
                    email_from = self.branch_id.email if self.branch_id else self.env.user.company_id.email or 'noreply@localhost'
                    
                    mail = self.env['mail.mail'].sudo().create({
                        'subject': subject,
                        'body_html': body_html,
                        'email_to': self.customer_email,
                        'email_from': email_from,
                    })
                    mail.send()
                    _logger.info(f"Successfully sent follow-up email to {self.customer_email}")
                except Exception as e:
                    _logger.error(f"Failed to send follow-up email to {self.customer_email}: {str(e)}")
            
            # Send SMS if enabled
            if settings.followup_channel in ['sms', 'both'] and self.customer_phone:
                _logger.info(f"Sending follow-up SMS to {self.customer_phone}")
                sms_message = self._generate_followup_sms(settings)
                self._send_sms_notification(self.customer_phone, sms_message)
            
            # Update tracking fields
            self.write({
                'followup_count': self.followup_count + 1,
                'last_followup_date': fields.Date.today(),
            })
            
        except Exception as e:
            _logger.error(f"Error sending follow-up for appointment {self.id}: {str(e)}")
    
    @api.model
    def send_followup_reminders(self):
        """Scheduled method to send follow-up reminders to customers after their appointment"""
        _logger.info("=== Running send_followup_reminders cron job ===")
        
        # Get settings
        settings = self.env['custom.appointment.settings'].get_settings()
        
        if not settings.send_followup_messages:
            _logger.info("Follow-up messages are disabled in settings")
            return
        
        today = fields.Date.today()
        
        # Find eligible appointments (completed and not manually stopped)
        appointments = self.search([
            ('state', '=', 'completed'),
            ('followup_stopped', '=', False),
        ])
        
        _logger.info(f"Found {len(appointments)} completed appointments to check for follow-ups")
        
        for appt in appointments:
            try:
                # Skip if customer already rebooked
                if appt._check_customer_rebooked():
                    _logger.info(f"Skipping appointment {appt.id}: customer has rebooked")
                    continue
                
                # Check max count (unless until_rebooked is enabled)
                if not settings.followup_until_rebooked:
                    if appt.followup_count >= settings.max_followup_count:
                        _logger.info(f"Skipping appointment {appt.id}: max follow-ups reached ({appt.followup_count}/{settings.max_followup_count})")
                        continue
                
                # Calculate if it's time to send
                if not appt.stop:
                    continue
                    
                completion_date = appt.stop.date()
                
                if appt.followup_count == 0:
                    # First follow-up: start_days after completion
                    send_date = completion_date + timedelta(days=settings.followup_start_days)
                else:
                    # Subsequent: repeat_interval after last followup
                    if not appt.last_followup_date:
                        continue
                    send_date = appt.last_followup_date + timedelta(days=settings.followup_repeat_interval)
                
                if today >= send_date:
                    _logger.info(f"Sending follow-up for appointment {appt.id} (due date: {send_date})")
                    appt._send_followup_notifications(settings)
                else:
                    _logger.debug(f"Appointment {appt.id} not yet due for follow-up (due: {send_date})")
                    
            except Exception as e:
                _logger.error(f"Error processing follow-up for appointment {appt.id}: {str(e)}")
                continue
        
        _logger.info("=== Finished send_followup_reminders cron job ===")
