import logging
from datetime import timedelta

from odoo import fields

from . import models
from .models.ir_mail_server import QUOTA_PAUSE

_logger = logging.getLogger(__name__)

# Personal Gmail allows roughly 500 recipients per rolling 24 hours. Stay under it,
# keep 100 of that for bookings/invoices, and let bulk trickle at 50 an hour.
GMAIL_DEFAULTS = {
    'throttle_daily_limit': 450,
    'throttle_transactional_reserve': 100,
    'throttle_bulk_hourly_limit': 50,
}


def post_init_hook(env):
    Server = env['ir.mail_server'].sudo()
    gmail = Server.with_context(active_test=False).search([
        ('throttle_daily_limit', '=', 0),
        '|', ('smtp_host', 'ilike', 'gmail.com'), ('smtp_host', 'ilike', 'googlemail.com'),
    ])
    if gmail:
        gmail.write(GMAIL_DEFAULTS)
        _logger.info("Sending limits: applied Gmail defaults to %s", gmail.mapped('name'))

    for server in Server.search([('throttle_daily_limit', '>', 0)]):
        _backfill_last_24h(env, server)


def _backfill_last_24h(env, server):
    """Seed the send log with the last 24 hours of traffic, and pause the server if
    the provider has been refusing.

    Without this the log starts empty and the first queue run would believe the
    whole daily limit is free - on a database installed mid-incident, that means
    sending straight into a provider that is already refusing.

    Most mail.mail rows carry no mail_server_id (the server is resolved at send
    time), so they can only be attributed when this is the only active server.
    Auto-deleted mails are gone and cannot be counted; the daily limit sits below
    the provider's real one partly to absorb that.
    """
    cr = env.cr
    only_server = env['ir.mail_server'].sudo().search_count([]) == 1
    since = fields.Datetime.now() - timedelta(hours=24)

    # mail_server_id lives on mail_message: mail.mail _inherits it.
    cr.execute("""
        SELECT date_trunc('hour', mm.write_date), count(*)
          FROM mail_mail mm
          JOIN mail_message msg ON msg.id = mm.mail_message_id
         WHERE mm.state = 'sent' AND mm.write_date > %s
           AND (msg.mail_server_id = %s OR (%s AND msg.mail_server_id IS NULL))
         GROUP BY 1
    """, (since, server.id, only_server))
    rows = cr.fetchall()
    if rows:
        env['mail.send.log'].sudo().create([
            {'mail_server_id': server.id, 'recipients': count, 'sent_at': hour, 'bulk': False}
            for hour, count in rows
        ])
        _logger.info("Sending limits: back-filled %s sends for %s", sum(c for _h, c in rows), server.name)

    cr.execute("""
        SELECT max(mm.write_date)
          FROM mail_mail mm
          JOIN mail_message msg ON msg.id = mm.mail_message_id
         WHERE mm.state = 'exception' AND mm.write_date > %s
           AND (msg.mail_server_id = %s OR (%s AND msg.mail_server_id IS NULL))
           AND (mm.failure_reason ILIKE '%%5.4.5%%' OR mm.failure_reason ILIKE '%%sending limit exceeded%%')
    """, (since, server.id, only_server))
    last_refusal = cr.fetchone()[0]
    if last_refusal and last_refusal + QUOTA_PAUSE > fields.Datetime.now():
        server.throttle_paused_until = last_refusal + QUOTA_PAUSE
        _logger.warning("Sending limits: %s refused mail for quota at %s; paused until %s",
                        server.name, last_refusal, server.throttle_paused_until)
