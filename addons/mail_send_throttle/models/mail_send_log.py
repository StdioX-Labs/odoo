from datetime import timedelta

from odoo import api, fields, models


class MailSendLog(models.Model):
    """How many recipients each server has sent to, and when.

    ``mail.mail`` cannot be used for this: messages with ``auto_delete`` are
    removed as soon as they are sent, which would undercount exactly the
    transactional traffic the provider still counts against the limit.
    """
    _name = 'mail.send.log'
    _description = 'Outgoing Mail Send Log'
    _order = 'sent_at desc'

    mail_server_id = fields.Many2one('ir.mail_server', required=True, index=True, ondelete='cascade')
    recipients = fields.Integer(required=True, default=1)
    bulk = fields.Boolean(index=True)
    # Not create_date: the install hook back-fills the last 24 hours of traffic.
    sent_at = fields.Datetime(required=True, index=True, default=fields.Datetime.now)

    @api.model
    def _recipients_since(self, mail_server, since, bulk=None):
        domain = [('mail_server_id', '=', mail_server.id), ('sent_at', '>', since)]
        if bulk is not None:
            domain.append(('bulk', '=', bulk))
        return sum(self.search(domain).mapped('recipients'))

    @api.autovacuum
    def _gc_old_entries(self):
        self.search([('sent_at', '<', fields.Datetime.now() - timedelta(days=3))]).unlink()
