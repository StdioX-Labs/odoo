import base64

from odoo.tests.common import TransactionCase


class TestNotificationPrivacy(TransactionCase):
    """Names may cross between customer and staff; contact details may not."""

    def setUp(self):
        super().setUp()
        self.branch = self.env['custom.branch'].create({
            'name': 'Westlands', 'email': 'westlands@salon.test',
            'phone': '254700000000', 'street': '1 Main St', 'city': 'Nairobi',
        })
        self.staff = self.env['custom.staff.member'].create({
            'name': 'Aisha', 'branch_id': self.branch.id,
            'email': 'aisha@salon.test', 'phone': '254700000001',
        })
        self.category = self.env['service.category'].create({'name': 'Lashes'})
        self.service = self.env['company.service'].create({
            'name': 'Volume Set', 'category_id': self.category.id,
            'price': 100.0, 'duration': 1.0,
        })
        self.appointment = self.env['custom.appointment'].create({
            'customer_name': 'Wanjiru',
            'customer_email': 'wanjiru@example.test',
            'customer_phone': '254724512285',
            'service_id': self.service.id,
            'staff_member_id': self.staff.id,
            'branch_id': self.branch.id,
            'start': '2030-01-01 09:00:00',
            'duration': 1.0,
        })

    def _ics(self, for_staff):
        attachment = self.appointment._generate_ics_attachment(for_staff=for_staff)
        return base64.b64decode(attachment.datas).decode()

    def test_staff_email_body_has_customer_name_but_no_contacts(self):
        body = self.appointment._generate_staff_notification_email_html()
        self.assertIn('Wanjiru', body)
        self.assertNotIn('wanjiru@example.test', body)
        self.assertNotIn('254724512285', body)

    def test_customer_invite_hides_staff_address(self):
        ics = self._ics(for_staff=False)
        self.assertIn('Aisha', ics)                       # the name is fine
        self.assertNotIn('aisha@salon.test', ics)         # the address is not
        self.assertIn('westlands@salon.test', ics)        # branch organises

    def test_staff_invite_hides_customer_address(self):
        ics = self._ics(for_staff=True)
        self.assertNotIn('wanjiru@example.test', ics)
        self.assertIn('aisha@salon.test', ics)
