# Service-first "Store" Booking Flow Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a service-first booking entry (`/appointments/store` → service → staff → existing book form), gated by a per-service "Show in Service Store" flag, without touching the current flow.

**Architecture:** One boolean field + a query helper on `company.service`; two public routes that render two lean QWeb pages and then hand off to the existing `/appointments/book`. The staff step reuses the existing `is_staff_allowed` rule. Booking form, payment, and confirmation are untouched.

**Tech Stack:** Odoo 18, Python, QWeb website templates. All Odoo commands run inside Docker.

## Global Constraints

- Target **Odoo 18**. Routes: `type='http', auth='public', website=True`. Templates use `<t t-call="website.layout">`.
- Reuse `company.service.is_staff_allowed(staff)` (already exists) for staff filtering; do NOT reimplement it.
- Do not modify the existing `/appointments`, `/appointments/services`, or `/appointments/book` routes or their templates. The store flow ends by linking to the existing `/appointments/book?service_id=<id>&staff_id=<id>`.
- Inside QWeb `<script>`/inline HTML, raw `<`/`>`/`&` are invalid — but this plan builds pages with server-rendered QWeb (`t-foreach`), no inline JS string-building, so this does not arise.

---

## Conventions

**Test DB** `test_store` (first run `-i`, later `-u`):

```bash
docker compose -f docker-compose-local.yml exec -T odoo odoo \
  --config=/etc/odoo/odoo-local.conf -d test_store --without-demo=all \
  -u custom_appointments --test-enable --test-tags /custom_appointments \
  --stop-after-init --no-http --log-level=test
```
(Use `-i` instead of `-u` on the very first run.) **Success:** `custom_appointments: N tests` with no `FAIL:`/`ERROR:`.

**Smoke** (page rendering): after a `-u` on `LashesByShazz` + `docker compose -f docker-compose-local.yml restart odoo`, curl the routes (see Task 3 / Final Verification).

---

## File Structure

- `models/service.py` (modify) — `show_in_store` field + `_store_services()` helper.
- `views/service_views.xml` (modify) — checkbox in the "Booking Settings" page.
- `controllers/main.py` (modify) — `/appointments/store` and `/appointments/store/staff` routes.
- `views/website_templates.xml` (modify) — `store_service_page` + `store_staff_page` templates.
- `tests/test_service_store.py` (new) + `tests/__init__.py` (modify).

---

## Task 1: `show_in_store` field + `_store_services()` helper

**Files:**
- Modify: `addons/custom_appointments/models/service.py`
- Modify: `addons/custom_appointments/views/service_views.xml`
- Create: `addons/custom_appointments/tests/test_service_store.py`
- Modify: `addons/custom_appointments/tests/__init__.py`

**Interfaces:**
- Produces: `company.service.show_in_store` (Boolean). `company.service._store_services()` → recordset of services where `show_in_store AND published AND is_bookable`, ordered `sequence, name`.

- [ ] **Step 1: Write the failing test**

Create `addons/custom_appointments/tests/test_service_store.py`:

```python
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
```

- [ ] **Step 2: Register the test module**

In `addons/custom_appointments/tests/__init__.py`, add:

```python
from . import test_service_store
```

- [ ] **Step 3: Run the test to verify it FAILS**

Run the **update** command. Expected: FAIL/ERROR — `Invalid field 'show_in_store'` (field not defined yet).

- [ ] **Step 4: Add the field + helper**

In `addons/custom_appointments/models/service.py`, add the field next to
`is_bookable`/`published` (around line 33):

```python
    show_in_store = fields.Boolean(string='Show in Service Store', default=False)
```

And add this method to the `CompanyService` class (next to `get_available_services`):

```python
    @api.model
    def _store_services(self):
        """Services shown in the service-first store flow."""
        return self.search([
            ('show_in_store', '=', True),
            ('published', '=', True),
            ('is_bookable', '=', True),
        ], order='sequence, name')
```

(`api` is already imported at the top of the file.)

- [ ] **Step 5: Add the checkbox to the service form**

In `addons/custom_appointments/views/service_views.xml`, inside the "Booking
Settings" page group, after `<field name="published"/>` (around line 59), add:

```xml
                                    <field name="show_in_store"/>
```

- [ ] **Step 6: Run the tests to verify they PASS**

Run the **update** command. Expected: both new tests pass; `custom_appointments: N tests`, no `FAIL:`/`ERROR:`.

- [ ] **Step 7: Commit**

```bash
git add addons/custom_appointments/models/service.py \
        addons/custom_appointments/views/service_views.xml \
        addons/custom_appointments/tests/test_service_store.py \
        addons/custom_appointments/tests/__init__.py
git commit -m "feat: add show_in_store flag + _store_services helper"
```

---

## Task 2: Store templates + routes

**Files:**
- Modify: `addons/custom_appointments/controllers/main.py`
- Modify: `addons/custom_appointments/views/website_templates.xml`
- Modify: `addons/custom_appointments/tests/test_service_store.py`

**Interfaces:**
- Consumes: `company.service._store_services()`, `company.service.is_staff_allowed(staff)` (existing).
- Produces: routes `GET /appointments/store` and `GET /appointments/store/staff`; templates `custom_appointments.store_service_page`, `custom_appointments.store_staff_page`.

- [ ] **Step 1: Write the failing test (staff filtering the route relies on)**

In `addons/custom_appointments/tests/test_service_store.py`, add:

```python
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
```

- [ ] **Step 2: Run it to verify it PASSES already**

Run the **update** command. Expected: PASS (it exercises the existing
`is_staff_allowed` the route will use). This test locks the staff-filtering
contract the route depends on. `custom_appointments: N tests`, no `FAIL:`/`ERROR:`.

- [ ] **Step 3: Add the two templates**

In `addons/custom_appointments/views/website_templates.xml`, add before the
closing `</odoo>`:

```xml
    <!-- Service-first store: pick a service -->
    <template id="store_service_page" name="Service Store">
        <t t-call="website.layout">
            <div id="wrap_store" class="oe_structure">
                <div class="container py-5">
                    <h2 class="text-center mb-4" style="color:#c2185b;">Book a Service</h2>
                    <t t-if="not services">
                        <p class="text-center text-muted">No services are available right now.</p>
                    </t>
                    <div class="row">
                        <t t-foreach="services" t-as="service">
                            <div class="col-md-4 mb-4">
                                <a t-attf-href="/appointments/store/staff?service_id=#{service.id}"
                                   class="text-decoration-none">
                                    <div class="card h-100 shadow-sm" style="border-radius:16px;">
                                        <t t-if="service.image">
                                            <img t-att-src="'/web/image/company.service/%s/image/400x300' % service.id"
                                                 class="card-img-top" style="border-radius:16px 16px 0 0; object-fit:cover; height:180px;" alt="Service"/>
                                        </t>
                                        <div class="card-body">
                                            <h5 class="card-title" style="color:#333;"><t t-esc="service.name"/></h5>
                                            <p class="card-text text-muted" t-esc="service.description or ''"/>
                                            <span class="badge" style="background:#fff0f6; color:#c2185b;">
                                                <t t-esc="service.currency_id.symbol"/><t t-esc="service.price"/>
                                            </span>
                                        </div>
                                    </div>
                                </a>
                            </div>
                        </t>
                    </div>
                </div>
            </div>
        </t>
    </template>

    <!-- Service-first store: pick a staff member for the chosen service -->
    <template id="store_staff_page" name="Service Store - Staff">
        <t t-call="website.layout">
            <div id="wrap_store_staff" class="oe_structure">
                <div class="container py-5">
                    <h2 class="text-center mb-2" style="color:#c2185b;">Choose a Specialist</h2>
                    <p class="text-center text-muted mb-4">for <strong t-esc="service.name"/></p>
                    <t t-if="not staff_members">
                        <p class="text-center text-muted">No specialists are available for this service. Please contact us.</p>
                    </t>
                    <div class="row">
                        <t t-foreach="staff_members" t-as="staff">
                            <div class="col-md-3 mb-4">
                                <a t-attf-href="/appointments/book?service_id=#{service.id}&amp;staff_id=#{staff.id}"
                                   class="text-decoration-none">
                                    <div class="card h-100 text-center shadow-sm" style="border-radius:16px;">
                                        <div class="card-body">
                                            <t t-if="staff.image">
                                                <img t-att-src="'/web/image/custom.staff.member/%s/image/120x120' % staff.id"
                                                     class="rounded-circle mb-2" style="width:90px; height:90px; object-fit:cover;" alt="Staff"/>
                                            </t>
                                            <h6 style="color:#333;"><t t-esc="staff.name"/></h6>
                                            <p class="text-muted small" t-esc="staff.specialization or ''"/>
                                        </div>
                                    </div>
                                </a>
                            </div>
                        </t>
                    </div>
                </div>
            </div>
        </t>
    </template>
```

- [ ] **Step 4: Add the two routes**

In `addons/custom_appointments/controllers/main.py`, add these methods to the
controller class (near the other `/appointments` routes, e.g. after the
`service_selection` route). `request` and `http` are already imported at the top
of the file:

```python
    @http.route('/appointments/store', type='http', auth='public', website=True)
    def store_services(self, **kwargs):
        """Service-first store: list services flagged Show in Service Store."""
        services = request.env['company.service'].sudo()._store_services()
        return request.render('custom_appointments.store_service_page', {
            'services': services,
        })

    @http.route('/appointments/store/staff', type='http', auth='public', website=True)
    def store_staff(self, service_id=None, **kwargs):
        """Store step 2: pick a staff member eligible for the chosen service."""
        service = request.env['company.service'].sudo().browse(
            int(service_id)) if service_id else None
        if not service or not service.exists() or not service.show_in_store:
            return request.redirect('/appointments/store')
        staff_members = request.env['custom.staff.member'].sudo().search([
            ('is_bookable', '=', True), ('active', '=', True),
        ]).filtered(lambda s: service.is_staff_allowed(s))
        return request.render('custom_appointments.store_staff_page', {
            'service': service,
            'staff_members': staff_members,
        })
```

- [ ] **Step 5: Update the module; confirm templates parse and suite passes**

Run the **update** command. Expected: module updates with NO `ParseError`/`QWeb`
error about the new templates; `custom_appointments: N tests`, no `FAIL:`/`ERROR:`.

- [ ] **Step 6: Commit**

```bash
git add addons/custom_appointments/controllers/main.py \
        addons/custom_appointments/views/website_templates.xml \
        addons/custom_appointments/tests/test_service_store.py
git commit -m "feat: service store routes and templates (service -> staff -> book)"
```

---

## Final Verification

- [ ] **Full suite** (update command): `custom_appointments: N tests`, no `FAIL:`/`ERROR:`.
- [ ] **Clean install**: `-i` on a fresh `-d` name to confirm from-scratch load.
- [ ] **Smoke (local LashesByShazz)**: `-u custom_appointments` then
  `docker compose -f docker-compose-local.yml restart odoo`. Then:
  - In the backend, tick **Show in Service Store** on one service (Booking Settings tab).
  - `curl -s -o /dev/null -w "%{http_code}" http://localhost:8069/appointments/store` → **200**, and the page lists that service.
  - Click it → `/appointments/store/staff?service_id=<id>` → **200**, lists eligible staff (for a Requires-Specific-Staff service, only allowed staff).
  - Click a staff → lands on the existing `/appointments/book?service_id=<id>&staff_id=<id>` form; complete a booking end to end.
  - `curl` `/appointments/store/staff?service_id=999999` (bad id) → redirects to `/appointments/store`.
```
