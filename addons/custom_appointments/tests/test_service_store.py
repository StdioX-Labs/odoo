from odoo.tests.common import TransactionCase


class TestServiceStore(TransactionCase):

    def setUp(self):
        super().setUp()
        self.branch = self.env['custom.branch'].create({'name': 'Test Branch'})
        self.category = self.env['service.category'].create({'name': 'Lashes'})
        self.allowed_staff = self.env['custom.staff.member'].create({
            'name': 'Aisha', 'branch_id': self.branch.id,
            'email': 'aisha@test.com', 'phone': '254700000001',
        })
        self.other_staff = self.env['custom.staff.member'].create({
            'name': 'Bob', 'branch_id': self.branch.id,
            'email': 'bob@test.com', 'phone': '254700000002',
        })

    def _service(self, **kw):
        vals = {
            'name': 'Svc', 'category_id': self.category.id,
            'price': 100.0, 'duration': 1.0,
            'is_bookable': True, 'published': True,
        }
        vals.update(kw)
        return self.env['company.service'].create(vals)

    def test_store_services_only_flagged(self):
        in_store = self._service(name='In', show_in_store=True)
        self._service(name='Out', show_in_store=False)
        result = self.env['company.service']._store_services()
        self.assertIn(in_store, result)
        self.assertNotIn(self.env['company.service'].search(
            [('name', '=', 'Out')]), result)

    def test_store_services_excludes_unpublished(self):
        self._service(name='Hidden', show_in_store=True, published=False)
        result = self.env['company.service']._store_services()
        self.assertFalse(result.filtered(lambda s: s.name == 'Hidden'))

    def test_store_staff_respects_requires_specific_staff(self):
        svc = self._service(
            name='Restricted', show_in_store=True,
            requires_specific_staff=True,
            allowed_staff_ids=[(6, 0, [self.allowed_staff.id])],
        )
        eligible = self.env['custom.staff.member'].search([
            ('is_bookable', '=', True), ('active', '=', True),
        ]).filtered(lambda s: svc.is_staff_allowed(s))
        self.assertIn(self.allowed_staff, eligible)
        self.assertNotIn(self.other_staff, eligible)
