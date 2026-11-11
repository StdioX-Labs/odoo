from odoo.tests.common import TransactionCase


class TestStaffBookingLink(TransactionCase):

    def setUp(self):
        super().setUp()
        self.branch = self.env['custom.branch'].create({'name': 'Test Branch'})
        self.staff = self.env['custom.staff.member'].create({
            'name': 'Aisha Wanjiru', 'branch_id': self.branch.id,
            'email': 'aisha@test.com', 'phone': '254700000001',
        })
        self.Staff = self.env['custom.staff.member']

    def test_booking_url_uses_name_and_id(self):
        base = self.staff.get_base_url()
        self.assertEqual(
            self.staff.booking_url,
            f'{base}/book/aisha-wanjiru-{self.staff.id}')

    def test_slug_resolves_to_staff(self):
        slug = self.staff.booking_url.rsplit('/', 1)[1]
        self.assertEqual(self.Staff._from_booking_slug(slug), self.staff)

    def test_link_survives_rename(self):
        slug = self.staff.booking_url.rsplit('/', 1)[1]
        self.staff.name = 'Aisha K'
        self.assertEqual(self.Staff._from_booking_slug(slug), self.staff)

    def test_unbookable_or_archived_staff_not_resolved(self):
        slug = self.staff.booking_url.rsplit('/', 1)[1]
        self.staff.is_bookable = False
        self.assertFalse(self.Staff._from_booking_slug(slug))
        self.staff.write({'is_bookable': True, 'active': False})
        self.assertFalse(self.Staff._from_booking_slug(slug))

    def test_garbage_slug_not_resolved(self):
        self.assertFalse(self.Staff._from_booking_slug('nobody'))
        self.assertFalse(self.Staff._from_booking_slug('nobody-999999999'))
