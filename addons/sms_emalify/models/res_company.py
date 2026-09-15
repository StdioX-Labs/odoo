# -*- coding: utf-8 -*-

from odoo import models

from odoo.addons.sms_emalify.tools.sms_api import SmsApiEmalify


class ResCompany(models.Model):
    _inherit = 'res.company'

    def _get_sms_api_class(self):
        """Used by flows that talk to the SMS API directly rather than through
        sms.sms.send() - notably the SMS Marketing "Test" button, which would
        otherwise go to Odoo IAP regardless of what is configured here."""
        self.ensure_one()
        if self.env['sms.sms']._emalify_enabled():
            return SmsApiEmalify
        return super()._get_sms_api_class()
