# Enforce "Requires Specific Staff" Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Prevent booking a `requires_specific_staff` service with a staff member who isn't in its `allowed_staff_ids`, enforced server-side (online + backend), with a friendly "switch staff" dialog in the online flow.

**Architecture:** One rule helper on `company.service` (`is_staff_allowed`) is the single definition of the rule. A `@api.constrains` on `custom.appointment` enforces it on create/write (covering the online controller create and backend manual entry). The online service-selection page gets per-service data attributes and a Bootstrap modal that intercepts navigation when the chosen staff can't perform the chosen service.

**Tech Stack:** Odoo 18, Python, QWeb website templates, Bootstrap 5 modal + vanilla JS. All Odoo commands run inside Docker.

## Global Constraints

- Target **Odoo 18**. Use Odoo 18 idioms: `@api.constrains`, `ValidationError` from `odoo.exceptions`, translation via `_()`. The model file `models/appointment.py` already imports `from odoo import models, fields, api, _` and `from odoo.exceptions import ValidationError` — reuse those, do not re-import.
- Match the existing constraint style in `models/appointment.py` (see `_check_staff_availability`, which uses `raise ValidationError(_('...') % (...))`).
- The website uses Bootstrap 5 (Odoo 18 default). Modals use `data-bs-*` attributes / `new bootstrap.Modal(el)`.
- Do not change the staff-first/service-second flow or add admin config.

---

## Conventions

**Running the test suite** (throwaway DB `test_rss`; first run installs, later runs update):

```bash
# First run (install):
docker compose -f docker-compose-local.yml exec -T odoo odoo \
  --config=/etc/odoo/odoo-local.conf -d test_rss --without-demo=all \
  -i custom_appointments --test-enable --test-tags /custom_appointments \
  --stop-after-init --no-http --log-level=test

# Subsequent runs (update):
docker compose -f docker-compose-local.yml exec -T odoo odoo \
  --config=/etc/odoo/odoo-local.conf -d test_rss --without-demo=all \
  -u custom_appointments --test-enable --test-tags /custom_appointments \
  --stop-after-init --no-http --log-level=test
```

**Success:** log shows `odoo.tests.stats: custom_appointments: N tests` and NO `FAIL:` or `ERROR:` lines. When adding a new Python field/method or a new test file, you MUST run with `-i`/`-u` so the registry reloads.

---

## File Structure

- `models/service.py` (modify) — `is_staff_allowed(staff)` rule helper + `get_allowed_staff_json()` view helper.
- `models/appointment.py` (modify) — `@api.constrains` guard `_check_staff_allowed_for_service`.
- `views/website_templates.xml` (modify) — service-card data attributes; capture them on select; intercept in `proceedToBooking()`; the switch-staff modal markup.
- `tests/test_requires_specific_staff.py` (new) — automated tests for the helper, constraint, and controller path.
- `tests/__init__.py` (modify) — register the new test module.

---

## Task 1: Rule helper on `company.service`

**Files:**
- Modify: `addons/custom_appointments/models/service.py`
- Create: `addons/custom_appointments/tests/test_requires_specific_staff.py`
- Modify: `addons/custom_appointments/tests/__init__.py`

**Interfaces:**
- Produces: `company.service.is_staff_allowed(self, staff)` → bool. Returns `True` when `requires_specific_staff` is False; otherwise `True` iff `staff` is in `self.allowed_staff_ids`. (`ensure_one()`.)

- [ ] **Step 1: Write the failing test**

Create `addons/custom_appointments/tests/test_requires_specific_staff.py`:

```python
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
```

- [ ] **Step 2: Register the test module**

In `addons/custom_appointments/tests/__init__.py`, add:

```python
from . import test_requires_specific_staff
```

- [ ] **Step 3: Run the tests to verify they FAIL**

Run the **update** command. Expected: FAIL/ERROR — `'company.service' object has no attribute 'is_staff_allowed'`.

- [ ] **Step 4: Add the helper**

In `addons/custom_appointments/models/service.py`, add this method inside the
`CompanyService` class (e.g. after `get_available_services`):

```python
    def is_staff_allowed(self, staff):
        """Return True if `staff` may provide this service."""
        self.ensure_one()
        if not self.requires_specific_staff:
            return True
        return staff in self.allowed_staff_ids
```

- [ ] **Step 5: Run the tests to verify they PASS**

Run the **update** command. Expected: the two new tests pass; `custom_appointments: N tests` with no `FAIL:`/`ERROR:`.

- [ ] **Step 6: Commit**

```bash
git add addons/custom_appointments/models/service.py \
        addons/custom_appointments/tests/test_requires_specific_staff.py \
        addons/custom_appointments/tests/__init__.py
git commit -m "feat: add company.service.is_staff_allowed rule helper"
```

---

## Task 2: Constraint on `custom.appointment`

**Files:**
- Modify: `addons/custom_appointments/models/appointment.py`
- Modify: `addons/custom_appointments/tests/test_requires_specific_staff.py`

**Interfaces:**
- Consumes: `company.service.is_staff_allowed` (Task 1).
- Produces: `custom.appointment._check_staff_allowed_for_service` — an `@api.constrains('staff_member_id', 'service_id')` method that raises `ValidationError` when the service requires specific staff and the appointment's staff isn't allowed (or no allowed staff are configured).

- [ ] **Step 1: Write the failing tests**

In `addons/custom_appointments/tests/test_requires_specific_staff.py`, add these
methods to the `TestRequiresSpecificStaff` class:

```python
    def test_allowed_staff_can_be_booked(self):
        appt = self._make_appointment(self.restricted_service, self.allowed_staff)
        self.assertTrue(appt.exists())

    def test_disallowed_staff_raises(self):
        with self.assertRaises(ValidationError):
            self._make_appointment(self.restricted_service, self.other_staff)

    def test_open_service_accepts_any_staff(self):
        appt = self._make_appointment(self.open_service, self.other_staff)
        self.assertTrue(appt.exists())

    def test_requires_specific_but_no_allowed_staff_raises(self):
        empty_service = self.env['company.service'].create({
            'name': 'Misconfigured Service',
            'category_id': self.category.id,
            'price': 100.0,
            'duration': 2.0,
            'requires_specific_staff': True,
        })
        with self.assertRaises(ValidationError):
            self._make_appointment(empty_service, self.allowed_staff)

    def test_reassigning_to_disallowed_staff_raises(self):
        appt = self._make_appointment(self.restricted_service, self.allowed_staff)
        with self.assertRaises(ValidationError):
            appt.write({'staff_member_id': self.other_staff.id})
```

- [ ] **Step 2: Run the tests to verify they FAIL**

Run the **update** command. Expected: `test_disallowed_staff_raises`,
`test_requires_specific_but_no_allowed_staff_raises`, and
`test_reassigning_to_disallowed_staff_raises` FAIL (no `ValidationError` raised —
the appointment is created), because the constraint does not exist yet. The two
"allowed/open" tests should already pass.

- [ ] **Step 3: Add the constraint**

In `addons/custom_appointments/models/appointment.py`, add this method immediately
after the existing `_check_staff_availability` constraint (around line 205, after
its closing `raise`). Do NOT add new imports — `_`, `api`, and `ValidationError`
are already imported at the top of the file.

```python
    @api.constrains('staff_member_id', 'service_id')
    def _check_staff_allowed_for_service(self):
        """Enforce that a service requiring specific staff is only booked with
        one of its allowed staff members."""
        for appointment in self:
            service = appointment.service_id
            staff = appointment.staff_member_id
            if not service or not staff:
                continue
            if not service.requires_specific_staff:
                continue
            if not service.allowed_staff_ids:
                raise ValidationError(_(
                    "No staff are currently configured to provide '%s'. "
                    "Please contact us to book this service."
                ) % service.name)
            if not service.is_staff_allowed(staff):
                names = ", ".join(service.allowed_staff_ids.mapped('name'))
                raise ValidationError(_(
                    'The service "%s" can only be provided by: %s. '
                    'Please choose one of these staff members.'
                ) % (service.name, names))
```

- [ ] **Step 4: Run the tests to verify they PASS**

Run the **update** command. Expected: all five Task-2 tests pass;
`custom_appointments: N tests` with no `FAIL:`/`ERROR:`.

- [ ] **Step 5: Commit**

```bash
git add addons/custom_appointments/models/appointment.py \
        addons/custom_appointments/tests/test_requires_specific_staff.py
git commit -m "feat: enforce requires_specific_staff via appointment constraint"
```

---

## Task 3: Controller path is covered by the constraint

**Files:**
- Modify: `addons/custom_appointments/tests/test_requires_specific_staff.py`

This task adds a regression test proving the public booking controller does NOT
create an appointment when the chosen staff is disallowed. The controller's
existing `try/except` around `create()` (in `_process_booking`, which redirects to
`/appointments?error=<message>` on exception) means no code change is needed — the
Task-2 constraint makes `create()` raise, which the controller already catches.
This task verifies that end-to-end at the model boundary the controller relies on.

**Interfaces:**
- Consumes: the constraint from Task 2.

- [ ] **Step 1: Write the failing/guard test**

In `addons/custom_appointments/tests/test_requires_specific_staff.py`, add this
method to the `TestRequiresSpecificStaff` class:

```python
    def test_no_appointment_created_for_disallowed_staff(self):
        """The booking create() the controller calls must not persist a row
        when the staff is disallowed (controller catches the ValidationError)."""
        Appointment = self.env['custom.appointment']
        before = Appointment.search_count([
            ('service_id', '=', self.restricted_service.id)])
        with self.assertRaises(ValidationError):
            self._make_appointment(self.restricted_service, self.other_staff)
        after = Appointment.search_count([
            ('service_id', '=', self.restricted_service.id)])
        self.assertEqual(before, after)
```

- [ ] **Step 2: Run the test**

Run the **update** command. Expected: this test PASSES immediately (the Task-2
constraint already prevents creation and rolls back). `custom_appointments: N
tests`, no `FAIL:`/`ERROR:`. (If it fails, the constraint is not firing on
create — revisit Task 2.)

- [ ] **Step 3: Commit**

```bash
git add addons/custom_appointments/tests/test_requires_specific_staff.py
git commit -m "test: assert disallowed-staff booking creates no appointment"
```

---

## Task 4: View helper for allowed-staff data

**Files:**
- Modify: `addons/custom_appointments/models/service.py`
- Modify: `addons/custom_appointments/tests/test_requires_specific_staff.py`

The online modal needs, per service, the list of allowed staff as `{id, name}`.
QWeb cannot call `json.dumps` in a `t-att-` expression, so the service exposes a
method that returns the JSON string directly.

**Interfaces:**
- Produces: `company.service.get_allowed_staff_json(self)` → str. A JSON array of
  `{"id": <int>, "name": <str>}` for `allowed_staff_ids` (empty list `"[]"` when
  none / not required). Used by the template's `t-att-data-allowed-staff`.

- [ ] **Step 1: Write the failing test**

In `addons/custom_appointments/tests/test_requires_specific_staff.py`, add at the
top of the file (with the other imports):

```python
import json
```

Then add this method to the `TestRequiresSpecificStaff` class:

```python
    def test_get_allowed_staff_json(self):
        data = json.loads(self.restricted_service.get_allowed_staff_json())
        self.assertEqual(data, [{'id': self.allowed_staff.id, 'name': 'Aisha'}])
        self.assertEqual(self.open_service.get_allowed_staff_json(), '[]')
```

- [ ] **Step 2: Run the test to verify it FAILS**

Run the **update** command. Expected: FAIL/ERROR — `'company.service' object has
no attribute 'get_allowed_staff_json'`.

- [ ] **Step 3: Add the helper**

In `addons/custom_appointments/models/service.py`, add `import json` at the top of
the file (after the existing `from odoo import ...` line), then add this method to
the `CompanyService` class (next to `is_staff_allowed`):

```python
    def get_allowed_staff_json(self):
        """JSON string of allowed staff [{id, name}] for the booking UI."""
        self.ensure_one()
        if not self.requires_specific_staff:
            return "[]"
        return json.dumps([
            {'id': s.id, 'name': s.name} for s in self.allowed_staff_ids
        ])
```

- [ ] **Step 4: Run the test to verify it PASSES**

Run the **update** command. Expected: pass; `custom_appointments: N tests`, no
`FAIL:`/`ERROR:`.

- [ ] **Step 5: Commit**

```bash
git add addons/custom_appointments/models/service.py \
        addons/custom_appointments/tests/test_requires_specific_staff.py
git commit -m "feat: add get_allowed_staff_json view helper"
```

---

## Task 5: Online switch-staff dialog (template + JS)

**Files:**
- Modify: `addons/custom_appointments/views/website_templates.xml`

This task is website XML/JS (no unit test — verified by clean module update + the
manual smoke in Final Verification). The service-selection page already: picks a
staff first (`selected_staff_id` in context; JS vars `selectedTeamMember`,
`defaultStaffId`), lets the user click a service (`selectService(element,
serviceId)` sets `selectedService`), and navigates on `proceedToBooking()` to
`/appointments/book?service_id=...&staff_id=...`.

**Interfaces:**
- Consumes: `company.service.get_allowed_staff_json()` (Task 4),
  `service.requires_specific_staff`.

- [ ] **Step 1: Add data attributes to the service card**

In `addons/custom_appointments/views/website_templates.xml`, find the service-item
`div` (around line 713):

```xml
                                                                <div class="service-item h-100" style="background: white; border: none; border-radius: 16px; cursor: pointer; transition: all 0.3s ease; box-shadow: 0 3px 15px rgba(0,0,0,0.05);" t-att-onclick="'selectService(this, ' + str(service.id) + ')'">
```

Add two `t-att-` attributes to that opening tag (keep everything else identical):

```xml
                                                                <div class="service-item h-100" style="background: white; border: none; border-radius: 16px; cursor: pointer; transition: all 0.3s ease; box-shadow: 0 3px 15px rgba(0,0,0,0.05);" t-att-data-requires-specific-staff="'1' if service.requires_specific_staff else '0'" t-att-data-allowed-staff="service.get_allowed_staff_json()" t-att-onclick="'selectService(this, ' + str(service.id) + ')'">
```

- [ ] **Step 2: Capture the data on selection**

In `selectService(element, serviceId)` (around line 1033), at the END of the
function (right after `selectedService = serviceId;`, before the closing `}`), add:

```javascript
                        selectedServiceRequiresStaff = element.getAttribute('data-requires-specific-staff') === '1';
                        try {
                            selectedServiceAllowedStaff = JSON.parse(element.getAttribute('data-allowed-staff') || '[]');
                        } catch (e) {
                            selectedServiceAllowedStaff = [];
                        }
```

And declare the two module-level vars next to the existing `let selectedService =
null;` (around line 1018):

```javascript
                    let selectedServiceRequiresStaff = false;
                    let selectedServiceAllowedStaff = [];
```

- [ ] **Step 3: Intercept in `proceedToBooking()`**

Replace the body of `proceedToBooking()` (around lines 1105–1120) with the version
below. It computes the concrete staff id (as today), and if the selected service
requires specific staff and that staff isn't allowed, opens the modal instead of
navigating. A `navigateToBooking(staffParam)` helper does the actual navigation so
the modal buttons can reuse it.

```javascript
                    function navigateToBooking(staffParam) {
                        let url = '/appointments/book?service_id=' + selectedService + '&amp;staff_id=' + staffParam;
                        const urlParams = new URLSearchParams(window.location.search);
                        const promo = urlParams.get('promo');
                        if (promo) {
                            url += '&amp;promo=' + encodeURIComponent(promo);
                        }
                        window.location.href = url;
                    }

                    function proceedToBooking() {
                        if (!selectedService) {
                            alert('Please select a service before continuing.');
                            return;
                        }
                        const staffParam = selectedTeamMember === 'any' ? defaultStaffId : selectedTeamMember;
                        if (selectedServiceRequiresStaff) {
                            const allowed = selectedServiceAllowedStaff || [];
                            const isAllowed = allowed.some(s => String(s.id) === String(staffParam));
                            if (!isAllowed) {
                                showStaffSwitchModal(allowed);
                                return;
                            }
                        }
                        navigateToBooking(staffParam);
                    }

                    function showStaffSwitchModal(allowed) {
                        const body = document.getElementById('staff-switch-body');
                        const confirmBtn = document.getElementById('staff-switch-confirm');
                        if (!allowed.length) {
                            body.innerHTML = '<p class="mb-0">This service is not currently available for online booking with the selected staff. Please contact us to book.</p>';
                            confirmBtn.style.display = 'none';
                        } else if (allowed.length === 1) {
                            body.innerHTML = '<p class="mb-0">This service is only provided by <strong>' + allowed[0].name + '</strong>.</p>';
                            confirmBtn.style.display = '';
                            confirmBtn.textContent = 'Switch to ' + allowed[0].name + ' &amp; continue';
                            confirmBtn.onclick = function () { navigateToBooking(allowed[0].id); };
                        } else {
                            let html = '<p>This service is provided by:</p>';
                            allowed.forEach(function (s, i) {
                                html += '<div class="form-check">'
                                    + '<input class="form-check-input" type="radio" name="staff-switch-choice" id="staff-switch-' + s.id + '" value="' + s.id + '"' + (i === 0 ? ' checked="checked"' : '') + '/>'
                                    + '<label class="form-check-label" for="staff-switch-' + s.id + '">' + s.name + '</label>'
                                    + '</div>';
                            });
                            body.innerHTML = html;
                            confirmBtn.style.display = '';
                            confirmBtn.textContent = 'Continue with selected';
                            confirmBtn.onclick = function () {
                                const chosen = document.querySelector('input[name="staff-switch-choice"]:checked');
                                if (chosen) { navigateToBooking(chosen.value); }
                            };
                        }
                        const modalEl = document.getElementById('staffSwitchModal');
                        const modal = bootstrap.Modal.getOrCreateInstance(modalEl);
                        modal.show();
                    }
```

- [ ] **Step 4: Add the modal markup**

In the SAME `service_selection_page` template, add the modal just before the
closing `</div>` of `wrap_services` — i.e. immediately before the `<script>` block
that contains these functions. (Find the `<script>` tag that wraps
`selectService`/`proceedToBooking`; place this `<div>` right before it.)

```xml
                    <!-- Staff switch dialog (requires_specific_staff) -->
                    <div class="modal fade" id="staffSwitchModal" tabindex="-1" aria-hidden="true">
                        <div class="modal-dialog modal-dialog-centered">
                            <div class="modal-content" style="border-radius: 16px;">
                                <div class="modal-header" style="border-bottom: 1px solid #fff0f6;">
                                    <h5 class="modal-title" style="color: #ff69b4;">Staff required for this service</h5>
                                    <button type="button" class="btn-close" data-bs-dismiss="modal" aria-label="Close"></button>
                                </div>
                                <div class="modal-body" id="staff-switch-body"></div>
                                <div class="modal-footer" style="border-top: 1px solid #fff0f6;">
                                    <button type="button" class="btn btn-light" data-bs-dismiss="modal">Cancel</button>
                                    <button type="button" class="btn" id="staff-switch-confirm" style="background: #ff69b4; color: white;" data-bs-dismiss="modal"></button>
                                </div>
                            </div>
                        </div>
                    </div>
```

- [ ] **Step 5: Update the module and confirm the template parses**

Run the **update** command. Expected: module updates with NO `ParseError` /
`QWeb` / `ValidationError` about the template; `custom_appointments: N tests` still
pass (the existing automated tests are unaffected). The template loading line for
`website_templates.xml` appears with no error.

- [ ] **Step 6: Commit**

```bash
git add addons/custom_appointments/views/website_templates.xml
git commit -m "feat: online switch-staff dialog for requires_specific_staff"
```

---

## Final Verification

- [ ] **Run the full suite** (update command). Confirm `custom_appointments: N
  tests` with no `FAIL:`/`ERROR:`.
- [ ] **Clean install check:** install on a fresh DB (`-i` on a new `-d` name) to
  confirm everything loads from scratch with no errors.
- [ ] **Manual smoke (local `LashesByShazz` DB):**
  1. In the backend, set a service to **Requires Specific Staff** with exactly one
     allowed staff member; update the module on `LashesByShazz`; restart odoo.
  2. On the website, pick a *different* staff, then click that service and press
     continue → the dialog appears: *"This service is only provided by `<Name>`"*
     with **Switch to `<Name>` &amp; continue**.
  3. Click switch → lands on `/appointments/book` with the allowed staff;
     completing the booking succeeds.
  4. Backend: try to manually create an appointment for that service with a
     disallowed staff → save is blocked with the validation message.
  5. (Optional) Configure two allowed staff and confirm the dialog shows the radio
     list and "Continue with selected".
