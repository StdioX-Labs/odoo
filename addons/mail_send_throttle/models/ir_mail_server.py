import logging
from datetime import timedelta

from odoo import fields, models

_logger = logging.getLogger(__name__)

# Provider refusals that mean "not now" rather than "never". Matched against the
# failure reason Odoo stores, e.g.
#   SMTPDataError: (550, b'5.4.5 Daily user sending limit exceeded. ...')
QUOTA_MARKERS = ('5.4.5', 'sending limit exceeded')
TRANSIENT_MARKERS = ('4.4.5', '4.7.0', '4.7.28', '4.3.0', 'try again later', 'server busy')

# How long a server is paused after each kind of refusal. A daily-limit refusal
# is re-probed hourly: Gmail frees capacity gradually as old sends leave its
# rolling 24-hour window, not all at once.
QUOTA_PAUSE = timedelta(hours=1)
TRANSIENT_PAUSE = timedelta(minutes=15)


class IrMailServer(models.Model):
    _inherit = 'ir.mail_server'

    throttle_daily_limit = fields.Integer(
        string="Daily Limit",
        default=0,
        help="Recipients this server may send to in any rolling 24 hours. 0 means no "
             "limit. Keep it a little under the provider's real limit (Gmail: about 500 "
             "for a personal account, 2,000 for Google Workspace).",
    )
    throttle_transactional_reserve = fields.Integer(
        string="Reserved for Transactional Mail",
        default=0,
        help="Part of the daily limit that bulk mail may never use, so booking "
             "confirmations and invoices still go out on a busy campaign day.",
    )
    throttle_bulk_hourly_limit = fields.Integer(
        string="Bulk Mail per Hour",
        default=0,
        help="Maximum bulk recipients per rolling hour, so a campaign trickles out "
             "instead of bursting (bursts trigger rate-limit refusals). 0 means no hourly limit.",
    )
    throttle_paused_until = fields.Datetime(
        string="Paused Until",
        copy=False,
        help="Set when the provider refuses mail for quota or rate-limit reasons. "
             "Nothing is sent through this server until then; the refused mail waits "
             "in the queue.",
    )

    # -- budget -------------------------------------------------------------------

    def _throttle_budget(self):
        """What may be sent right now.

        :return: dict with ``transactional`` (bool, may transactional mail go out)
                 and ``bulk`` (int, bulk recipients still allowed).
        """
        self.ensure_one()
        now = fields.Datetime.now()
        if self.throttle_paused_until and self.throttle_paused_until > now:
            return {'transactional': False, 'bulk': 0}

        Log = self.env['mail.send.log'].sudo()
        if self.throttle_daily_limit:
            bulk = self.throttle_daily_limit - self.throttle_transactional_reserve \
                - Log._recipients_since(self, now - timedelta(hours=24))
        else:
            bulk = float('inf')
        if self.throttle_bulk_hourly_limit:
            bulk = min(bulk, self.throttle_bulk_hourly_limit
                       - Log._recipients_since(self, now - timedelta(hours=1), bulk=True))
        return {'transactional': True, 'bulk': max(0, bulk)}

    # -- after a send attempt -----------------------------------------------------

    def _throttle_after_send(self, mail_ids, meta):
        """Record what went out and put quota refusals back in the queue.

        :param list mail_ids: ids handed to ``mail.mail._send``
        :param dict meta: ``{mail_id: (recipients, bulk)}``, read before sending,
            since successfully sent ``auto_delete`` mails no longer exist afterwards
        """
        self.ensure_one()
        Mail = self.env['mail.mail'].sudo()
        remaining = Mail.browse(mail_ids).exists()
        state_by_id = {mail.id: mail.state for mail in remaining}

        sent = {'bulk': 0, 'transactional': 0}
        for mail_id in mail_ids:
            if state_by_id.get(mail_id, 'sent') == 'sent':  # gone = auto-deleted after success
                recipients, bulk = meta.get(mail_id, (1, False))
                sent['bulk' if bulk else 'transactional'] += recipients
        log_vals = [
            {'mail_server_id': self.id, 'recipients': count, 'bulk': kind == 'bulk'}
            for kind, count in sent.items() if count
        ]
        if log_vals:
            self.env['mail.send.log'].sudo().create(log_vals)

        refused = remaining.filtered(lambda m: m.state == 'exception' and m._throttle_refusal())
        if not refused:
            return

        pause = QUOTA_PAUSE if any(m._throttle_refusal() == 'quota' for m in refused) else TRANSIENT_PAUSE
        retry_at = fields.Datetime.now() + pause
        _logger.warning(
            "Mail server %s refused %s mail(s) for quota/rate reasons; pausing it until %s "
            "and queueing them for retry.", self.display_name, len(refused), retry_at)
        self.sudo().throttle_paused_until = retry_at
        refused._throttle_requeue(retry_at)
