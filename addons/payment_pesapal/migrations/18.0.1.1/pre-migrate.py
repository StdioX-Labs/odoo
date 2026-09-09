"""Clear orphaned appointment references before the FK is created.

pesapal_ipn_log.appointment_id has always been declared ondelete='set null', but
the foreign key was never actually created in databases where payment_pesapal
loaded before custom_appointments -- at that point the custom_appointment table
did not exist yet, so Odoo skipped the constraint. Nothing then enforced the
'set null', and deleting an appointment left the log row pointing at a missing id.

Adding account_payment to this module's dependencies moves it later in the load
order, so Odoo now does create the FK -- and fails on those orphans:

    insert or update on table "pesapal_ipn_log" violates foreign key constraint
    DETAIL: Key (appointment_id)=(170) is not present in table "custom_appointment".

Null them first. That is precisely what ondelete='set null' would have done had
the constraint existed, so no information is lost that the schema intended to keep;
the IPN payload itself (raw_data, tracking_id, status) is untouched.
"""

import logging

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    cr.execute("""
        UPDATE pesapal_ipn_log l
           SET appointment_id = NULL
         WHERE l.appointment_id IS NOT NULL
           AND NOT EXISTS (
                 SELECT 1 FROM custom_appointment a WHERE a.id = l.appointment_id
           )
    """)
    if cr.rowcount:
        _logger.warning(
            "PesaPal: cleared %s orphaned appointment reference(s) on pesapal_ipn_log "
            "so the foreign key can be created.",
            cr.rowcount,
        )
