from odoo import models


class MailComposeMessage(models.TransientModel):
    _inherit = 'mail.compose.message'

    def _action_send_mail_mass_mail(self, res_ids, auto_commit=False):
        """Everything created here is bulk: "Send email" from a list view, and Email
        Marketing, which sends through this same path."""
        return super(MailComposeMessage, self.with_context(mail_throttle_bulk=True)) \
            ._action_send_mail_mass_mail(res_ids, auto_commit=auto_commit)
