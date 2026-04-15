# One-time cleanup of demo data from production database.
#
# Run from Odoo shell (env must be available):
#   docker exec -it <odoo_container> odoo shell -d revive --config=/etc/odoo/odoo.conf
#   >>> exec(open('/mnt/extra-addons/custom_appointments/scripts/remove_demo_data.py').read())
#   >>> env.cr.commit()
#
# Or from project root with local Odoo:
#   python odoo-bin shell -d revive --addons-path=... --config=config/odoo.conf
#   >>> exec(open('addons/custom_appointments/scripts/remove_demo_data.py').read())
#   >>> env.cr.commit()

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

for xmlid in demo_xmlids:
    rec = env.ref(xmlid, raise_if_not_found=False)
    if rec and rec.exists():
        rec.unlink()
        print(f"Removed {xmlid}")

# Commit only after you have verified in shell; uncomment to auto-commit:
# env.cr.commit()
