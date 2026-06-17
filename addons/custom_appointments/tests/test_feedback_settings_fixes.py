from datetime import datetime

from odoo.tests.common import TransactionCase


class TestFeedbackSettingsFixes(TransactionCase):

    def setUp(self):
        super().setUp()
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

    def _make_feedback(self):
        appt = self.env['custom.appointment'].create({
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
        return self.env['custom.appointment.feedback']._create_for_appointment(appt)

    # --- Bug 1: settings must not be clobbered / must open the singleton ---

    def test_create_does_not_clobber_existing_settings(self):
        Settings = self.env['custom.appointment.settings']
        s = Settings.get_settings()
        s.write({'feedback_first_delay_minutes': 99})
        count_before = Settings.search_count([])
        # Simulate a stray create() (e.g. the web client saving a freshly
        # opened, defaults-filled settings form).
        returned = Settings.create({'feedback_first_delay_minutes': 5})
        self.assertEqual(Settings.search_count([]), count_before,
                         "create() must not add a second settings row")
        self.assertEqual(s.feedback_first_delay_minutes, 99,
                         "existing settings must not be reset to defaults")
        self.assertEqual(returned.id, s.id)

    def test_get_settings_is_singleton(self):
        Settings = self.env['custom.appointment.settings']
        a = Settings.get_settings()
        b = Settings.get_settings()
        self.assertEqual(a.id, b.id)
        self.assertEqual(Settings.search_count([]), 1)

    def test_action_open_settings_targets_singleton(self):
        Settings = self.env['custom.appointment.settings']
        singleton = Settings.get_settings()
        count_before = Settings.search_count([])
        action = Settings.action_open_settings()
        self.assertEqual(action['res_id'], singleton.id)
        self.assertEqual(action['res_model'], 'custom.appointment.settings')
        self.assertEqual(action['view_mode'], 'form')
        self.assertEqual(Settings.search_count([]), count_before,
                         "opening settings must not create a new row")

    # --- Bug 2: feedback request email body ---

    def test_feedback_request_body_uses_settings_template(self):
        fb = self._make_feedback()
        settings = self.env['custom.appointment.settings'].get_settings()
        settings.write({
            'feedback_request_email_template':
                '<p>Hi {customer_name}, rate us: {feedback_link}</p>',
        })
        body = fb._feedback_request_body(settings)
        self.assertIn('Alice', body)
        self.assertIn('rate us', body)

    def test_feedback_request_body_falls_back_to_file(self):
        fb = self._make_feedback()
        settings = self.env['custom.appointment.settings'].get_settings()
        settings.write({'feedback_request_email_template': ''})
        body = fb._feedback_request_body(settings)
        self.assertIn('Leave Feedback', body)
        self.assertIn('Alice', body)
