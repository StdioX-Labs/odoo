import logging

from odoo import _, api, fields, models, tools

from .ir_mail_server import QUOTA_MARKERS, TRANSIENT_MARKERS

_logger = logging.getLogger(__name__)


class MailMail(models.Model):
    _inherit = 'mail.mail'

    throttle_bulk = fields.Boolean(
        string="Bulk",
        index=True,
        copy=False,
        help="Sent as part of a mass send (list-view mass email, Email Marketing). Bulk "
             "mail only uses the part of a server's sending limit not reserved for "
             "transactional mail, and waits in the queue when that is used up.",
    )

    @api.model_create_multi
    def create(self, vals_list):
        # Marked explicitly at the source rather than guessed from volume: the mass
        # composer sets the context key, Email Marketing sets mailing_id.
        bulk_context = self.env.context.get('mail_throttle_bulk')
        for vals in vals_list:
            if bulk_context or vals.get('mailing_id'):
                vals.setdefault('throttle_bulk', True)
        return super().create(vals_list)

    # -- holding mail back ----------------------------------------------------------

    def _split_by_mail_configuration(self):
        """Drop, from each batch, the mails a limited server cannot take right now.

        ``send()`` gets its batches from here, already resolved to a mail server,
        so this covers both the queue cron and direct ``send()`` calls. Mails left
        out keep their ``outgoing`` state and are picked up by a later queue run.
        """
        batches = list(super()._split_by_mail_configuration())
        server_ids = {server_id for server_id, _alias, _from, _ids in batches if server_id}
        servers = self.env['ir.mail_server'].sudo().browse(server_ids).exists() \
            .filtered(lambda server: server.throttle_daily_limit > 0)
        if not servers:
            yield from batches
            return

        budgets = {server.id: server._throttle_budget() for server in servers}
        throttled_ids = [mail_id for server_id, _alias, _from, ids in batches
                         if server_id in budgets for mail_id in ids]
        info = {mail.id: (mail.throttle_bulk, mail._throttle_recipient_count())
                for mail in self.browse(throttled_ids).sudo()}

        held = 0
        for server_id, alias_domain_id, smtp_from, batch_ids in batches:
            budget = budgets.get(server_id)
            if budget is None:
                yield server_id, alias_domain_id, smtp_from, batch_ids
                continue
            allowed = []
            for mail_id in batch_ids:
                bulk, recipients = info.get(mail_id, (False, 1))
                if not bulk:
                    ok = budget['transactional']
                elif budget['bulk'] >= recipients:
                    budget['bulk'] -= recipients
                    ok = True
                else:
                    ok = False
                if ok:
                    allowed.append(mail_id)
                else:
                    held += 1
            if allowed:
                yield server_id, alias_domain_id, smtp_from, allowed
        if held:
            _logger.info("Sending limits: %s mail(s) left in the queue for a later run", held)

    def _send(self, auto_commit=False, raise_exception=False, smtp_session=None, alias_domain_id=False,
              mail_server=False, post_send_callback=None):
        limited = bool(mail_server) and mail_server.sudo().throttle_daily_limit > 0
        # Read before sending: successfully sent auto_delete mails are gone afterwards.
        meta = {mail.id: (mail._throttle_recipient_count(), mail.throttle_bulk)
                for mail in self.sudo()} if limited else {}
        res = super()._send(
            auto_commit=auto_commit, raise_exception=raise_exception, smtp_session=smtp_session,
            alias_domain_id=alias_domain_id, mail_server=mail_server, post_send_callback=post_send_callback,
        )
        if limited:
            mail_server.sudo()._throttle_after_send(self.ids, meta)
        return res

    # -- helpers ----------------------------------------------------------------------

    def _throttle_recipient_count(self):
        """Providers count recipients, not messages."""
        self.ensure_one()
        count = len(self.recipient_ids)
        count += len(tools.mail.email_split(self.email_to or ''))
        count += len(tools.mail.email_split(self.email_cc or ''))
        return max(count, 1)

    def _throttle_refusal(self):
        """'quota', 'transient' or False, from the failure reason Odoo stored."""
        self.ensure_one()
        reason = (self.failure_reason or '').lower()
        if any(marker in reason for marker in QUOTA_MARKERS):
            return 'quota'
        if any(marker in reason for marker in TRANSIENT_MARKERS):
            return 'transient'
        return False

    def _throttle_requeue(self, retry_at):
        """Undo a quota/rate refusal: back to the queue, and clear the failure that
        _send already reported on chatter notifications and campaign statistics, so
        nobody chases a failure that is only a delay."""
        for mail in self:
            mail.write({
                'state': 'outgoing',
                'scheduled_date': retry_at,
                'failure_reason': _("Deferred by the server's sending limit: %s",
                                    (mail.failure_reason or '')[:300]),
            })
        self.env['mail.notification'].sudo().search([
            ('mail_mail_id', 'in', self.ids), ('notification_status', '=', 'exception'),
        ]).write({'notification_status': 'ready', 'failure_type': False, 'failure_reason': False})
        if 'mailing.trace' in self.env:
            self.env['mailing.trace'].sudo().search([
                ('mail_mail_id', 'in', self.ids), ('trace_status', '=', 'error'),
            ]).write({'trace_status': 'outgoing', 'failure_type': False, 'failure_reason': False})
