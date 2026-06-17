from odoo import models, fields, api


class AppointmentSettings(models.Model):
    _name = 'custom.appointment.settings'
    _description = 'Appointment Communication Settings'
    _rec_name = 'id'

    # Master toggle
    send_followup_messages = fields.Boolean(
        string='Send Follow-up Messages',
        default=False,
        help='Enable or disable follow-up messages to customers after their appointment'
    )

    # Channel selection
    followup_channel = fields.Selection([
        ('sms', 'SMS Only'),
        ('email', 'Email Only'),
        ('both', 'Both SMS and Email')
    ], string='Communication Channel', default='both', required=True,
       help='Choose which channel(s) to use for follow-up messages')

    # Timing settings
    followup_start_days = fields.Integer(
        string='Start After (Days)',
        default=14,
        help='Number of days after appointment completion to send the first follow-up message'
    )

    followup_repeat_interval = fields.Integer(
        string='Repeat Every (Days)',
        default=7,
        help='Number of days between subsequent follow-up messages'
    )

    # Follow-up limits
    max_followup_count = fields.Integer(
        string='Maximum Follow-ups',
        default=3,
        help='Maximum number of follow-up messages to send per appointment'
    )

    followup_until_rebooked = fields.Boolean(
        string='Follow-up Until Rebooked',
        default=False,
        help='Keep sending follow-up messages until the customer books a new appointment (overrides maximum count)'
    )

    # Message templates
    followup_email_subject = fields.Char(
        string='Email Subject',
        default='We Miss You! Book Your Next Session',
        help='Subject line for follow-up emails'
    )

    followup_email_template = fields.Text(
        string='Email Message Template',
        help='Email template with placeholders: {customer_name}, {service_name}, {branch_name}, {booking_link}'
    )

    followup_sms_template = fields.Text(
        string='SMS Message Template',
        default='Hi {customer_name}! We hope you enjoyed your {service_name}. Ready for your next session? Book now: {booking_link}',
        help='SMS template with placeholders: {customer_name}, {service_name}, {branch_name}, {booking_link}'
    )

    # ==================== CUSTOMER FEEDBACK ====================

    enable_feedback_requests = fields.Boolean(
        string='Collect Customer Feedback', default=False,
        help='Enable requesting feedback from customers after their appointment is completed')

    feedback_channel = fields.Selection([
        ('sms', 'SMS Only'),
        ('email', 'Email Only'),
        ('both', 'Both SMS and Email'),
    ], string='Feedback Channel', default='both', required=True)

    feedback_first_delay_minutes = fields.Integer(
        string='First Request After (Minutes)', default=5,
        help='Minutes after appointment completion before the first feedback request is sent')
    feedback_repeat_interval_minutes = fields.Integer(
        string='Repeat Every (Minutes)', default=1440,
        help='Minutes between repeated feedback requests (1440 = 1 day)')
    feedback_max_requests = fields.Integer(
        string='Maximum Requests', default=3,
        help='Maximum number of feedback requests to send per appointment')

    # Which fields to ask
    feedback_ask_staff_rating = fields.Boolean(string='Ask Staff Rating', default=True)
    feedback_ask_service_rating = fields.Boolean(string='Ask Service Rating', default=True)
    feedback_ask_recommend = fields.Boolean(string='Ask Recommend Score (NPS)', default=True)
    feedback_ask_cleanliness = fields.Boolean(string='Ask Cleanliness Rating', default=True)
    feedback_ask_comfort = fields.Boolean(string='Ask Comfort Rating', default=True)
    feedback_ask_value = fields.Boolean(string='Ask Value Rating', default=True)
    feedback_ask_comments = fields.Boolean(string='Ask Comments', default=True)

    # Request messages
    feedback_request_email_subject = fields.Char(
        string='Feedback Email Subject',
        default="How was your visit? We'd love your feedback")
    feedback_request_email_template = fields.Text(string='Feedback Email Template')
    feedback_request_sms_template = fields.Text(
        string='Feedback SMS Template',
        default='Hi {customer_name}! How was your {service_name}? Share quick feedback: {feedback_link}')

    # Promo reward
    feedback_reward_enabled = fields.Boolean(
        string='Reward Feedback with Promo', default=False,
        help='Generate a unique promo code for customers who submit feedback')
    feedback_reward_discount_type = fields.Selection([
        ('percentage', 'Percentage'),
        ('fixed', 'Fixed Amount'),
        ('free_booking', 'Free Booking Fee'),
    ], string='Reward Discount Type', default='percentage')
    feedback_reward_discount_value = fields.Float(string='Reward Discount Value', default=10.0)
    feedback_reward_applies_to = fields.Selection([
        ('booking_fee', 'Booking Fee Only'),
        ('full_price', 'Full Service Price'),
        ('both', 'Both (Booking Fee + Balance)'),
    ], string='Reward Applies To', default='full_price')
    feedback_reward_max_discount = fields.Float(
        string='Reward Maximum Discount', default=0.0,
        help='Cap on discount amount for percentage rewards. 0 = no cap')
    feedback_reward_validity_days = fields.Integer(string='Reward Valid For (Days)', default=30)
    feedback_reward_code_prefix = fields.Char(string='Reward Code Prefix', default='LASH-')
    feedback_reward_email_template = fields.Text(string='Reward Email Template')
    feedback_reward_sms_template = fields.Text(
        string='Reward SMS Template',
        default='Thank you for your feedback! Enjoy {discount} off your next visit. '
                'Use code {promo_code} (valid until {valid_to}). Book: {booking_link}')

    @api.model
    def get_settings(self):
        """Get or create the singleton settings record"""
        settings = self.search([], limit=1)
        if not settings:
            settings = self.create({
                'followup_start_days': 14,
                'followup_repeat_interval': 7,
                'max_followup_count': 3,
                'followup_channel': 'both',
                'followup_email_subject': 'We Miss You! Book Your Next Session',
                'followup_sms_template': 'Hi {customer_name}! We hope you enjoyed your {service_name}. Ready for your next session? Book now: {booking_link}',
            })
        return settings

    @api.model_create_multi
    def create(self, vals_list):
        """Singleton guard: never create a second settings row, and never let a
        stray create() overwrite the existing record's values (that wiped
        user-configured settings back to defaults). Return the existing record
        untouched if one already exists."""
        existing = self.search([], limit=1)
        if existing:
            return existing
        return super(AppointmentSettings, self).create(vals_list)

    @api.model
    def action_open_settings(self):
        """Open the singleton settings record directly in edit mode.

        Opening the bare model action would land on a NEW (defaults-filled)
        record; saving that overwrote the real settings. Always target the
        existing singleton instead."""
        settings = self.get_settings()
        return {
            'type': 'ir.actions.act_window',
            'name': 'Communication Settings',
            'res_model': 'custom.appointment.settings',
            'view_mode': 'form',
            'res_id': settings.id,
            'target': 'current',
            'context': {'form_view_initial_mode': 'edit'},
        }
