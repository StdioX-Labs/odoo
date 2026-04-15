from . import models
from . import controllers
from . import wizard


def _post_init_hook(env):
    """Remove demo data if real data already exists (e.g. production reinstall)."""
    # Order matters: appointments -> services -> categories -> staff -> branches
    demo_xmlids = [
        'custom_appointments.appointment_1',
        'custom_appointments.appointment_2',
        'custom_appointments.appointment_3',
        'custom_appointments.appointment_4',
        'custom_appointments.appointment_5',
        'custom_appointments.appointment_6',
        'custom_appointments.service_business_consultation',
        'custom_appointments.service_technical_consultation',
        'custom_appointments.service_team_training',
        'custom_appointments.service_phone_support',
        'custom_appointments.service_onsite_support',
        'custom_appointments.category_consultation',
        'custom_appointments.category_training',
        'custom_appointments.category_support',
        'custom_appointments.staff_john',
        'custom_appointments.staff_sarah',
        'custom_appointments.staff_mike',
        'custom_appointments.branch_main',
        'custom_appointments.branch_downtown',
    ]
    # Heuristic: if counts exceed demo counts, assume real data exists
    n_branches = env['custom.branch'].search_count([])
    n_staff = env['custom.staff.member'].search_count([])
    n_services = env['company.service'].search_count([])
    n_appointments = env['custom.appointment'].search_count([])
    has_real_data = (
        n_branches > 2 or n_staff > 3 or n_services > 5 or n_appointments > 6
    )
    if not has_real_data:
        return
    for xmlid in demo_xmlids:
        try:
            record = env.ref(xmlid, raise_if_not_found=False)
            if record and record.exists():
                record.unlink()
        except Exception:
            pass
