from datetime import datetime

from odoo.exceptions import ValidationError
from odoo.tests.common import TransactionCase


class TestRequiresSpecificStaff(TransactionCase):

    def setUp(self):
        super().setUp()
        self.branch = self.env['custom.branch'].create({'name': 'Test Branch'})
        self.category = self.env['service.category'].create({'name': 'Lashes'})
        self.allowed_staff = self.env['custom.staff.member'].create({
            'name': 'Aisha',
            'branch_id': self.branch.id,
            'email': 'aisha@test.com',
            'phone': '254700000001',
        })
        self.other_staff = self.env['custom.staff.member'].create({
            'name': 'Bob',
            'branch_id': self.branch.id,
            'email': 'bob@test.com',
            'phone': '254700000002',
        })
        self.open_service = self.env['company.service'].create({
            'name': 'Open Service',
            'category_id': self.category.id,
            'price': 100.0,
            'duration': 2.0,
        })
        self.restricted_service = self.env['company.service'].create({
            'name': 'Restricted Service',
            'category_id': self.category.id,
            'price': 100.0,
            'duration': 2.0,
            'requires_specific_staff': True,
            'allowed_staff_ids': [(6, 0, [self.allowed_staff.id])],
        })

    def _make_appointment(self, service, staff, **overrides):
        vals = {
            'name': 'Test Appt',
            'customer_name': 'Alice',
            'customer_email': 'alice@test.com',
            'customer_phone': '254711111111',
            'service_id': service.id,
            'staff_member_id': staff.id,
            'branch_id': self.branch.id,
            'start': datetime(2026, 1, 1, 9, 0),
            'stop': datetime(2026, 1, 1, 11, 0),
            'price': 100.0,
        }
        vals.update(overrides)
        return self.env['custom.appointment'].create(vals)

    def test_is_staff_allowed_open_service(self):
        self.assertTrue(self.open_service.is_staff_allowed(self.other_staff))

    def test_is_staff_allowed_restricted(self):
        self.assertTrue(self.restricted_service.is_staff_allowed(self.allowed_staff))
        self.assertFalse(self.restricted_service.is_staff_allowed(self.other_staff))
