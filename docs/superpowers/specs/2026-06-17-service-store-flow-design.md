# Service-first "Store" Booking Flow — Design

**Date:** 2026-06-17
**Module:** `custom_appointments`
**Status:** Approved

## Problem

The website booking flow is **branch → staff → service → book**. The salon wants
a second, service-first entry — **service → staff → book** — that runs alongside
the existing flow (both live), showing a chosen subset of services as a "store".

## Goals

- A separate entry (`/appointments/store`) running service → staff → book.
- The existing `/appointments` flow is unchanged.
- Per-service opt-in: only services flagged **Show in Service Store** appear.
- Staff step respects the existing `requires_specific_staff` rule.
- Reuse the existing booking form, payment, and confirmation with no changes.

## Non-Goals (YAGNI)

- No global on/off setting — the per-service flag *is* the switch (an empty store
  is just a store with nothing ticked).
- No separate branch-selection step (branch derives from the chosen staff, as the
  current book flow already does).
- No separate store theme/branding; reuse existing card styling.

## Design

### 1. Field

`company.service.show_in_store = fields.Boolean(string='Show in Service Store', default=False)`
— shown as a checkbox on the service form near the existing online/booking fields
(`is_bookable`, `published`).

### 2. Routes (in `controllers/main.py`, `auth='public', website=True`)

- `GET /appointments/store` — render a service grid of
  `company.service` where `show_in_store = True AND published = True AND is_bookable = True`
  (ordered by `sequence, name`). Each card links to
  `/appointments/store/staff?service_id=<id>`.
- `GET /appointments/store/staff?service_id=<id>` — load the service; render a
  staff grid of `custom.staff.member` where `is_bookable = True AND active = True`,
  filtered to `service.is_staff_allowed(staff)` (so restricted services only list
  their allowed staff). Each card links to the **existing**
  `/appointments/book?service_id=<id>&staff_id=<staff_id>`.
  - If the service id is invalid / not in-store → redirect to `/appointments/store`.

From `/appointments/book` onward, the current flow is untouched.

### 3. Templates (`views/website_templates.xml`)

- `store_service_page` — service card grid; cards link to the staff step.
- `store_staff_page` — staff card grid; cards link to `/appointments/book`.

Both reuse the existing card markup/CSS classes. Two small purpose-built
templates rather than forking the staff-coupled `service_selection_page`.

### 4. Testing

One `HttpCase`-free controller-level test is impractical for rendered pages;
instead a `TransactionCase` test on the query logic:

- A helper method `company.service._store_services()` returns services with
  `show_in_store=True` (published + bookable). Test: a flagged service is
  included, a non-flagged one is excluded, an unpublished flagged one is excluded.
- Staff filtering: reuse `is_staff_allowed` (already tested). One test that for a
  restricted service the store staff list excludes a disallowed staff and includes
  an allowed one — via the same `is_staff_allowed` helper the route uses.

The rendered templates are verified by the manual smoke below (routes return 200,
correct services/staff listed).

## Manual Smoke (local LashesByShazz)

Tick **Show in Service Store** on one service; visit `/appointments/store` → it
lists only that service; click it → staff step lists eligible staff; click a
staff → lands on the existing `/appointments/book` form; complete a booking.

## Files Touched

- `models/service.py` — `show_in_store` field + `_store_services()` helper.
- `views/service_views.xml` — checkbox on the service form.
- `controllers/main.py` — two routes.
- `views/website_templates.xml` — two templates.
- `tests/test_service_store.py` (new) + `tests/__init__.py`.
