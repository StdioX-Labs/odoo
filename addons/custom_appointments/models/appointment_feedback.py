from odoo import models, fields, api
from datetime import timedelta
import secrets
import logging

_logger = logging.getLogger(__name__)


class AppointmentFeedback(models.Model):
    _name = 'custom.appointment.feedback'
    _description = 'Customer Appointment Feedback'
    _order = 'create_date desc'

    appointment_id = fields.Many2one(
        'custom.appointment', string='Appointment',
        required=True, ondelete='cascade', index=True)
    partner_id = fields.Many2one('res.partner', string='Customer')
    customer_name = fields.Char(string='Customer Name')
    customer_email = fields.Char(string='Customer Email')
    customer_phone = fields.Char(string='Customer Phone')
    staff_member_id = fields.Many2one('custom.staff.member', string='Staff Member')
    service_id = fields.Many2one('company.service', string='Service')
    branch_id = fields.Many2one('custom.branch', string='Branch')

    access_token = fields.Char(string='Access Token', index=True, copy=False)
    state = fields.Selection([
        ('pending', 'Pending'),
        ('submitted', 'Submitted'),
        ('expired', 'Expired'),
    ], string='Status', default='pending', required=True, index=True)

    request_count = fields.Integer(string='Requests Sent', default=0)
    last_request_date = fields.Datetime(string='Last Request Sent')
    submitted_date = fields.Datetime(string='Submitted On')

    # Curated answer fields (1-5 ratings: 0 = unanswered)
    staff_rating = fields.Integer(string='Staff Rating')
    service_rating = fields.Integer(string='Service Rating')
    recommend_score = fields.Selection(
        [(str(n), str(n)) for n in range(0, 11)],
        string='Recommend Score (NPS)')
    cleanliness_rating = fields.Integer(string='Cleanliness Rating')
    comfort_rating = fields.Integer(string='Comfort Rating')
    value_rating = fields.Integer(string='Value Rating')
    comments = fields.Text(string='Comments')

    reward_promo_id = fields.Many2one('custom.appointment.promo', string='Reward Promo Code')

    _sql_constraints = [
        ('appointment_unique', 'unique(appointment_id)',
         'Feedback already exists for this appointment.'),
    ]

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if not vals.get('access_token'):
                vals['access_token'] = secrets.token_urlsafe(24)
        return super().create(vals_list)

    @api.model
    def _create_for_appointment(self, appointment):
        """Create a pending feedback record copying appointment data."""
        return self.create({
            'appointment_id': appointment.id,
            'partner_id': appointment.partner_id.id,
            'customer_name': appointment.customer_name,
            'customer_email': appointment.customer_email,
            'customer_phone': appointment.customer_phone,
            'staff_member_id': appointment.staff_member_id.id,
            'service_id': appointment.service_id.id,
            'branch_id': appointment.branch_id.id,
        })

    @api.model
    def _backfill_feedback_records(self):
        """Create pending feedback records for completed appointments missing one."""
        Appointment = self.env['custom.appointment']
        completed = Appointment.search([
            ('state', '=', 'completed'),
            ('completed_date', '!=', False),
        ])
        if not completed:
            return
        existing = self.search([('appointment_id', 'in', completed.ids)])
        existing_appt_ids = set(existing.mapped('appointment_id').ids)
        for appt in completed:
            if appt.id not in existing_appt_ids:
                self._create_for_appointment(appt)

    @api.model
    def cron_send_feedback_requests(self):
        """Cron entrypoint: backfill records, then send any due feedback requests."""
        settings = self.env['custom.appointment.settings'].get_settings()
        if not settings.enable_feedback_requests:
            return
        self._backfill_feedback_records()
        self._send_due_requests(settings)

    def _get_feedback_link(self):
        self.ensure_one()
        settings = self.env['custom.appointment.settings'].sudo().get_settings()
        external = (settings.feedback_external_url or '').strip()
        if external:
            return external
        base_url = self.env['ir.config_parameter'].sudo().get_param('web.base.url', '')
        return f"{base_url}/appointments/feedback/{self.access_token}"

    @api.model
    def _send_due_requests(self, settings):
        now = fields.Datetime.now()
        first_delay = timedelta(minutes=settings.feedback_first_delay_minutes or 0)
        repeat = timedelta(minutes=settings.feedback_repeat_interval_minutes or 0)
        pending = self.search([('state', '=', 'pending')])
        for fb in pending:
            if fb.appointment_id.state == 'cancelled':
                continue
            if fb.request_count >= settings.feedback_max_requests:
                fb.state = 'expired'
                continue
            if fb.request_count == 0:
                anchor = fb.appointment_id.completed_date
                if not anchor:
                    continue
                due = anchor + first_delay
            else:
                if not fb.last_request_date:
                    continue
                due = fb.last_request_date + repeat
            if now >= due:
                fb._send_request(settings)

    def _feedback_request_body(self, settings):
        """Build the feedback request email body. Use the admin-configured
        template from settings when set, otherwise fall back to the bundled
        feedback_request.html file."""
        self.ensure_one()
        template = (settings.feedback_request_email_template or '').strip()
        if not template:
            template = self.appointment_id._load_email_template('feedback_request')
        return template.format(
            customer_name=self.customer_name or 'there',
            company_name=self.env.company.name,
            service_name=self.service_id.name or '',
            staff_name=self.staff_member_id.name or '',
            feedback_link=self._get_feedback_link(),
        )

    def _send_request(self, settings):
        self.ensure_one()
        link = self._get_feedback_link()
        company = self.env.company

        if settings.feedback_channel in ('email', 'both') and self.customer_email:
            try:
                body_html = self._feedback_request_body(settings)
                email_from = (self.branch_id.email or company.email or 'noreply@localhost')
                self.env['mail.mail'].sudo().create({
                    'subject': settings.feedback_request_email_subject or 'We value your feedback',
                    'body_html': body_html,
                    'email_to': self.customer_email,
                    'email_from': email_from,
                }).send()
            except Exception as e:
                _logger.error('Feedback: failed to send request email for %s: %s', self.id, str(e))

        if settings.feedback_channel in ('sms', 'both') and self.customer_phone:
            tmpl = settings.feedback_request_sms_template or (
                'Hi {customer_name}! How was your {service_name}? Share feedback: {feedback_link}')
            sms_body = tmpl.format(
                customer_name=self.customer_name or 'there',
                service_name=self.service_id.name or '',
                staff_name=self.staff_member_id.name or '',
                branch_name=self.branch_id.name or '',
                feedback_link=link,
            )
            self.appointment_id._send_sms_notification(self.customer_phone, sms_body)

        self.write({
            'request_count': self.request_count + 1,
            'last_request_date': fields.Datetime.now(),
        })

    ANSWER_FIELDS = [
        'staff_rating', 'service_rating', 'recommend_score',
        'cleanliness_rating', 'comfort_rating', 'value_rating', 'comments',
    ]

    def submit_feedback(self, values):
        """Save answers, mark submitted, generate reward promo. Idempotent."""
        self.ensure_one()
        if self.state == 'submitted':
            return self.reward_promo_id
        to_write = {k: values[k] for k in self.ANSWER_FIELDS if k in values}
        to_write['state'] = 'submitted'
        to_write['submitted_date'] = fields.Datetime.now()
        self.write(to_write)
        settings = self.env['custom.appointment.settings'].sudo().get_settings()
        if settings.feedback_reward_enabled and not self.reward_promo_id:
            self._generate_reward_promo(settings)
        return self.reward_promo_id

    def _reward_discount_label(self, settings):
        if settings.feedback_reward_discount_type == 'percentage':
            return f"{settings.feedback_reward_discount_value:g}%"
        if settings.feedback_reward_discount_type == 'free_booking':
            return "a free booking fee"
        currency = self.env.company.currency_id
        return f"{currency.symbol}{settings.feedback_reward_discount_value:g}"

    def _generate_reward_promo(self, settings):
        self.ensure_one()
        Promo = self.env['custom.appointment.promo'].sudo()
        code = (settings.feedback_reward_code_prefix or '') + Promo.generate_unique_code()
        valid_to = fields.Date.today() + timedelta(days=settings.feedback_reward_validity_days or 0)
        promo = Promo.create({
            'name': f"Feedback reward - {self.customer_name or 'Customer'}",
            'code': code,
            'discount_type': settings.feedback_reward_discount_type,
            'discount_value': settings.feedback_reward_discount_value,
            'applies_to': settings.feedback_reward_applies_to,
            'maximum_discount': settings.feedback_reward_max_discount,
            'valid_from': fields.Date.today(),
            'valid_to': valid_to,
            'max_uses': 1,
            'max_uses_per_customer': 1,
            'assigned_partner_id': self.partner_id.id if self.partner_id else False,
            'active': True,
        })
        self.reward_promo_id = promo.id
        self._send_reward_notification(settings, promo)
        return promo

    def _send_reward_notification(self, settings, promo):
        self.ensure_one()
        company = self.env.company
        base_url = self.env['ir.config_parameter'].sudo().get_param('web.base.url', '')
        booking_link = f"{base_url}/appointments"
        discount = self._reward_discount_label(settings)
        valid_to = promo.valid_to.strftime('%B %d, %Y') if promo.valid_to else ''

        if settings.feedback_channel in ('email', 'both') and self.customer_email:
            try:
                template = self.appointment_id._load_email_template('feedback_reward')
                body_html = template.format(
                    customer_name=self.customer_name or 'there',
                    promo_code=promo.code,
                    discount=discount,
                    valid_to=valid_to,
                    booking_link=booking_link,
                )
                email_from = (self.branch_id.email or company.email or 'noreply@localhost')
                self.env['mail.mail'].sudo().create({
                    'subject': 'Your feedback reward is here!',
                    'body_html': body_html,
                    'email_to': self.customer_email,
                    'email_from': email_from,
                }).send()
            except Exception as e:
                _logger.error('Feedback: failed to send reward email for %s: %s', self.id, str(e))

        if settings.feedback_channel in ('sms', 'both') and self.customer_phone:
            tmpl = settings.feedback_reward_sms_template or (
                'Thank you! Use code {promo_code} for {discount} off (valid until {valid_to}). {booking_link}')
            sms_body = tmpl.format(
                customer_name=self.customer_name or 'there',
                promo_code=promo.code,
                discount=discount,
                valid_to=valid_to,
                booking_link=booking_link,
            )
            self.appointment_id._send_sms_notification(self.customer_phone, sms_body)
