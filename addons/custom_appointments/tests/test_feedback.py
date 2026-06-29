from datetime import datetime, timedelta

from odoo import fields
from odoo.tests.common import TransactionCase


class TestAppointmentFeedback(TransactionCase):

    def setUp(self):
        super().setUp()
        self.settings = self.env['custom.appointment.settings'].get_settings()
        self.branch = self.env['custom.branch'].create({'name': 'Test Branch'})
        self.category = self.env['service.category'].create({'name': 'Lashes'})
        self.service = self.env['company.service'].create({
            'name': 'Classic Set',
            'category_id': self.category.id,
            'price': 100.0,
            'duration': 2.0,
        })
        self.staff = self.env['custom.staff.member'].create({
            'name': 'Jane',
            'branch_id': self.branch.id,
            'email': 'jane@test.com',
            'phone': '254700000000',
        })

    def _make_appointment(self):
        return self.env['custom.appointment'].create({
            'name': 'Test Appt',
            'customer_name': 'Alice',
            'customer_email': 'alice@test.com',
            'customer_phone': '254711111111',
            'service_id': self.service.id,
            'staff_member_id': self.staff.id,
            'branch_id': self.branch.id,
            'start': datetime(2026, 1, 1, 9, 0),
            'stop': datetime(2026, 1, 1, 11, 0),
            'price': 100.0,
        })

    def test_fixtures_load(self):
        appt = self._make_appointment()
        self.assertEqual(appt.state, 'draft')

    def test_completed_date_stamped_on_action_complete(self):
        appt = self._make_appointment()
        self.assertFalse(appt.completed_date)
        appt.action_complete()
        self.assertEqual(appt.state, 'completed')
        self.assertTrue(appt.completed_date)

    def test_completed_date_stamped_on_write(self):
        appt = self._make_appointment()
        appt.write({'state': 'completed'})
        self.assertTrue(appt.completed_date)

    def test_feedback_token_generated_on_create(self):
        appt = self._make_appointment()
        fb = self.env['custom.appointment.feedback'].create({
            'appointment_id': appt.id,
        })
        self.assertTrue(fb.access_token)
        self.assertEqual(fb.state, 'pending')

    def test_feedback_appointment_unique(self):
        from psycopg2 import IntegrityError
        from odoo.tools import mute_logger
        appt = self._make_appointment()
        Feedback = self.env['custom.appointment.feedback']
        Feedback.create({'appointment_id': appt.id})
        with mute_logger('odoo.sql_db'), self.assertRaises(IntegrityError):
            Feedback.create({'appointment_id': appt.id})
            self.env.flush_all()

    def test_feedback_settings_defaults(self):
        s = self.env['custom.appointment.settings'].get_settings()
        self.assertFalse(s.enable_feedback_requests)
        self.assertEqual(s.feedback_channel, 'both')
        self.assertEqual(s.feedback_first_delay_minutes, 5)
        self.assertEqual(s.feedback_repeat_interval_minutes, 1440)
        self.assertEqual(s.feedback_max_requests, 3)
        self.assertTrue(s.feedback_ask_staff_rating)
        self.assertTrue(s.feedback_ask_comments)
        self.assertFalse(s.feedback_reward_enabled)
        self.assertEqual(s.feedback_reward_discount_type, 'percentage')
        self.assertEqual(s.feedback_reward_validity_days, 30)
        self.assertEqual(s.feedback_reward_code_prefix, 'LASH-')
        self.assertEqual(
            s.feedback_external_url,
            'https://docs.google.com/forms/d/e/1FAIpQLSdvOjRpoAz-C4Mnnbajcq-nAKskgVU94L5fwbuibfAaixpN0Q/viewform?usp=publish-editor')

    def test_feedback_link_uses_external_url_when_set(self):
        fb = self.env['custom.appointment.feedback']._create_for_appointment(self._make_appointment())
        self.settings.write({'feedback_external_url': 'https://example.com/review'})
        self.assertEqual(fb._get_feedback_link(), 'https://example.com/review')

    def test_feedback_link_falls_back_to_internal_when_blank(self):
        fb = self.env['custom.appointment.feedback']._create_for_appointment(self._make_appointment())
        self.settings.write({'feedback_external_url': ''})
        link = fb._get_feedback_link()
        self.assertIn('/appointments/feedback/', link)
        self.assertIn(fb.access_token, link)

    def test_backfill_creates_feedback_when_enabled(self):
        self.settings.write({'enable_feedback_requests': True})
        appt = self._make_appointment()
        appt.action_complete()
        Feedback = self.env['custom.appointment.feedback']
        Feedback.cron_send_feedback_requests()
        fb = Feedback.search([('appointment_id', '=', appt.id)])
        self.assertEqual(len(fb), 1)
        self.assertEqual(fb.customer_email, 'alice@test.com')
        self.assertEqual(fb.staff_member_id, self.staff)
        self.assertEqual(fb.state, 'pending')

    def test_backfill_skipped_when_disabled(self):
        self.settings.write({'enable_feedback_requests': False})
        appt = self._make_appointment()
        appt.action_complete()
        Feedback = self.env['custom.appointment.feedback']
        Feedback.cron_send_feedback_requests()
        self.assertFalse(Feedback.search([('appointment_id', '=', appt.id)]))

    def test_backfill_no_duplicate(self):
        self.settings.write({'enable_feedback_requests': True})
        appt = self._make_appointment()
        appt.action_complete()
        Feedback = self.env['custom.appointment.feedback']
        Feedback.cron_send_feedback_requests()
        Feedback.cron_send_feedback_requests()
        self.assertEqual(len(Feedback.search([('appointment_id', '=', appt.id)])), 1)

    def _completed_feedback(self, minutes_ago):
        """Helper: completed appointment + pending feedback with completed_date in the past."""
        self.settings.write({'enable_feedback_requests': True})
        appt = self._make_appointment()
        appt.action_complete()
        appt.completed_date = fields.Datetime.now() - timedelta(minutes=minutes_ago)
        fb = self.env['custom.appointment.feedback']._create_for_appointment(appt)
        return appt, fb

    def test_first_request_sent_when_due(self):
        appt, fb = self._completed_feedback(minutes_ago=10)  # delay default 5
        self.env['custom.appointment.feedback']._send_due_requests(self.settings)
        self.assertEqual(fb.request_count, 1)
        self.assertTrue(fb.last_request_date)
        sms = self.env['sms.sms'].search([('number', '=', '254711111111')])
        self.assertTrue(sms)
        self.assertIn('feedback', sms[0].body.lower())

    def test_first_request_not_sent_when_too_early(self):
        appt, fb = self._completed_feedback(minutes_ago=2)  # delay default 5
        self.env['custom.appointment.feedback']._send_due_requests(self.settings)
        self.assertEqual(fb.request_count, 0)

    def test_request_expires_at_max(self):
        appt, fb = self._completed_feedback(minutes_ago=10)
        fb.write({'request_count': 3, 'last_request_date': fields.Datetime.now() - timedelta(days=10)})
        self.env['custom.appointment.feedback']._send_due_requests(self.settings)
        self.assertEqual(fb.state, 'expired')

    def test_cancelled_appointment_not_requested(self):
        appt, fb = self._completed_feedback(minutes_ago=10)
        appt.write({'state': 'cancelled'})
        self.env['custom.appointment.feedback']._send_due_requests(self.settings)
        self.assertEqual(fb.request_count, 0)

    def test_submit_saves_answers_and_rewards(self):
        self.settings.write({
            'enable_feedback_requests': True,
            'feedback_reward_enabled': True,
            'feedback_reward_discount_type': 'percentage',
            'feedback_reward_discount_value': 15.0,
            'feedback_reward_validity_days': 30,
            'feedback_reward_code_prefix': 'LASH-',
        })
        appt = self._make_appointment()
        appt.action_complete()
        fb = self.env['custom.appointment.feedback']._create_for_appointment(appt)
        promo = fb.submit_feedback({
            'staff_rating': 5,
            'service_rating': 4,
            'recommend_score': '9',
            'comments': 'Loved it!',
        })
        self.assertEqual(fb.state, 'submitted')
        self.assertTrue(fb.submitted_date)
        self.assertEqual(fb.staff_rating, 5)
        self.assertEqual(fb.recommend_score, '9')
        self.assertEqual(fb.comments, 'Loved it!')
        self.assertTrue(promo)
        self.assertEqual(fb.reward_promo_id, promo)
        self.assertTrue(promo.code.startswith('LASH-'))
        self.assertEqual(promo.discount_type, 'percentage')
        self.assertEqual(promo.discount_value, 15.0)
        self.assertEqual(promo.max_uses, 1)
        self.assertEqual(promo.max_uses_per_customer, 1)
        self.assertEqual(promo.assigned_partner_id, appt.partner_id)

    def test_submit_no_reward_when_disabled(self):
        self.settings.write({'feedback_reward_enabled': False})
        appt = self._make_appointment()
        appt.action_complete()
        fb = self.env['custom.appointment.feedback']._create_for_appointment(appt)
        promo = fb.submit_feedback({'staff_rating': 5})
        self.assertEqual(fb.state, 'submitted')
        self.assertFalse(promo)
        self.assertFalse(fb.reward_promo_id)

    def test_submit_is_idempotent(self):
        self.settings.write({'feedback_reward_enabled': True})
        appt = self._make_appointment()
        appt.action_complete()
        fb = self.env['custom.appointment.feedback']._create_for_appointment(appt)
        promo1 = fb.submit_feedback({'staff_rating': 5})
        promo2 = fb.submit_feedback({'staff_rating': 1})
        self.assertEqual(promo1, promo2)
        self.assertEqual(fb.staff_rating, 5)  # second submit ignored
