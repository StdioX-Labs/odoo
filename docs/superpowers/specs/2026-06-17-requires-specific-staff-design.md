# Enforce "Requires Specific Staff" — Design

**Date:** 2026-06-17
**Module:** `custom_appointments`
**Status:** Approved

## Problem

A `company.service` can be flagged `requires_specific_staff` with a set of
`allowed_staff_ids`. These fields exist on the model and in the service form, but
**nothing enforces them**. The public booking flow picks a staff member first and
a service second, so a customer can select any staff and then a service that
requires a different, specific staff — and the booking goes through with the wrong
staff. A staff member creating an appointment manually in the backend can do the
same.

## Goals

- A service flagged `requires_specific_staff` can only be booked with a staff
  member in its `allowed_staff_ids`, in **both** the online flow and the backend.
- When an online customer picks a disallowed staff for such a service, show a
  friendly dialog offering to switch the booking to an allowed staff member, then
  continue.
- The rule is enforced server-side as the single source of truth, so it cannot be
  bypassed by URL tampering or manual backend entry.

## Non-Goals (YAGNI)

- No change to the staff-first/service-second flow ordering.
- No automatic reassignment without user confirmation.
- No handling of the "Any staff" path beyond what exists (the service selection
  page already requires a concrete staff selection before continuing).
- No new admin configuration — the existing `requires_specific_staff` /
  `allowed_staff_ids` fields are sufficient.

## Design

### Part 1 — Server-side rule (source of truth)

**Helper on `company.service`:**

```python
def is_staff_allowed(self, staff):
    """True if `staff` may provide this service."""
    self.ensure_one()
    if not self.requires_specific_staff:
        return True
    return staff in self.allowed_staff_ids
```

One definition of the rule, reused by the constraint (and available to any caller).

**Constraint on `custom.appointment`:**

```python
@api.constrains('staff_member_id', 'service_id')
def _check_staff_allowed_for_service(self):
    for appt in self:
        service = appt.service_id
        staff = appt.staff_member_id
        if not service or not staff:
            continue
        if not service.requires_specific_staff:
            continue
        if not service.allowed_staff_ids:
            raise ValidationError(_(
                "No staff are currently configured to provide '%s'.",
                service.name))
        if staff not in service.allowed_staff_ids:
            names = ", ".join(service.allowed_staff_ids.mapped('name'))
            raise ValidationError(_(
                "This service can only be provided by: %s.", names))
```

Fires on create and on write (changing staff or service), covering the online
`create()` in the controller and any backend manual create/edit. The existing
controller booking handler already wraps creation in `try/except` and redirects to
`/appointments?error=<message>`, so a server rejection surfaces as a readable
message — including the URL-tampering case where a customer hits
`/appointments/book` directly with a disallowed staff/service pair.

### Part 2 — Online "switch staff" dialog (UX)

On the **service selection page** (`service_selection_page`), the staff member is
already chosen (`selected_staff_id` in context) and the user clicks a service to
proceed to `/appointments/book?service_id=X&staff_id=Y`.

- Each service card gains data attributes:
  - `data-requires-specific-staff` ("1"/"0")
  - `data-allowed-staff` — JSON array of `{id, name}` for the service's
    `allowed_staff_ids`.
- When the user selects a service, JS evaluates the rule against the currently
  selected staff id before navigating:
  - **Allowed (or no requirement):** navigate to `/appointments/book` as today.
  - **Disallowed, exactly one allowed staff:** show a modal —
    *"This service is only provided by `<Name>`."* with **[Switch to `<Name>` &
    continue]** (navigates to `/appointments/book` with that staff's id) and
    **[Cancel]**.
  - **Disallowed, multiple allowed staff:** show the modal listing them as radio
    choices — *"This service is provided by: A, B, C."* — with **[Continue with
    selected]** (navigates with the chosen staff id) and **[Cancel]**.

The modal is presentation only; the server rule in Part 1 is what guarantees
correctness.

## Error Handling

- Service requires specific staff but `allowed_staff_ids` is empty →
  `ValidationError` with a clear "no staff configured" message (both layers).
- Direct navigation / URL tampering to `/appointments/book` with a disallowed
  pair → booking POST raises → existing controller redirect shows the message.
- The dialog's "Cancel" leaves the user on the service selection page with their
  current staff selection unchanged.

## Testing

**Automated (TDD), in `tests/`:**

1. `is_staff_allowed` returns True when the service has no requirement.
2. `is_staff_allowed` returns True for a staff in `allowed_staff_ids`, False
   otherwise.
3. Creating an appointment with an allowed staff for a requires-specific-staff
   service succeeds.
4. Creating one with a disallowed staff raises `ValidationError`.
5. `requires_specific_staff` True with empty `allowed_staff_ids` raises
   `ValidationError`.
6. A service with `requires_specific_staff` False accepts any staff.
7. Controller path: a booking POST with a disallowed staff creates **no**
   appointment (and redirects to the error page).

**Manual smoke (local `LashesByShazz` DB):** configure a service to require one
staff; in the website flow pick a different staff, click the service, confirm the
dialog appears, "Switch & continue" reassigns and proceeds, and the booking
completes with the allowed staff.

## Files Touched

- `models/service.py` — add `is_staff_allowed` helper.
- `models/appointment.py` — add the `@api.constrains` guard (and `ValidationError`
  / `_` imports if not already present).
- `controllers/main.py` — no logic change expected; verify the existing
  try/except surfaces the message. (Tests confirm.)
- `views/website_templates.xml` — service cards: data attributes + the switch
  dialog modal and its JS.
- `tests/test_requires_specific_staff.py` (new) — automated tests above.
- `tests/__init__.py` — register the new test module.
