"""Bulk mail must stay inside a server's sending limit, transactional mail must not
be starved by it, and provider quota refusals must become delays, not failures.

In test mode Odoo's SMTP layer connects to nothing and sends nothing, so a mail
"succeeds" unless send_email is patched to raise.
"""

import smtplib
from datetime import timedelta
from unittest.mock import patch

from odoo import fields
from odoo.tests import tagged
from odoo.tests.common import TransactionCase

SEND_EMAIL = 'odoo.addons.base.models.ir_mail_server.IrMailServer.send_email'
GMAIL_DAILY_LIMIT = smtplib.SMTPDataError(
    550, b'5.4.5 Daily user sending limit exceeded. For more information on Gmail')


@tagged('post_install', '-at_install')
class TestSendingLimits(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.server = cls.env['ir.mail_server'].create({
            'name': 'Limited', 'smtp_host': 'smtp.example.com', 'smtp_port': 465,
            'throttle_daily_limit': 10,
            'throttle_transactional_reserve': 2,
        })
        cls.Log = cls.env['mail.send.log']

    def _mails(self, count, bulk):
        return self.env['mail.mail'].create([{
            'subject': f'm{i}', 'body_html': '<p>x</p>',
            'email_to': f'r{i}@example.com',
            'mail_server_id': self.server.id,
            'throttle_bulk': bulk,
            'auto_delete': False,
        } for i in range(count)])

    def _already_sent(self, recipients, hours_ago=1, bulk=False):
        self.Log.create({'mail_server_id': self.server.id, 'recipients': recipients, 'bulk': bulk,
                         'sent_at': fields.Datetime.now() - timedelta(hours=hours_ago)})

    # -- marking bulk -------------------------------------------------------------

    def test_mass_composer_marks_mail_as_bulk(self):
        partners = self.env['res.partner'].create([
            {'name': 'A', 'email': 'a@example.com'}, {'name': 'B', 'email': 'b@example.com'}])
        composer = self.env['mail.compose.message'].with_context(
            default_model='res.partner', active_ids=partners.ids,
        ).create({'composition_mode': 'mass_mail', 'subject': 'VAT notice', 'body': '<p>Hi</p>',
                  'res_ids': repr(partners.ids)})
        composer._action_send_mail()
        mails = self.env['mail.mail'].search([('subject', '=', 'VAT notice')])
        self.assertEqual(len(mails), 2)
        self.assertTrue(all(mails.mapped('throttle_bulk')))

    def test_single_mail_is_transactional(self):
        mail = self.env['mail.mail'].create({'subject': 'Booking', 'email_to': 'x@example.com'})
        self.assertFalse(mail.throttle_bulk)

    # -- daily and hourly limits --------------------------------------------------

    def test_bulk_stops_at_daily_limit_minus_reserve(self):
        # limit 10 - reserve 2 - 5 already sent = 3 bulk recipients left
        self._already_sent(5)
        mails = self._mails(5, bulk=True)
        mails.send()
        self.assertEqual(mails.mapped('state').count('sent'), 3)
        self.assertEqual(mails.mapped('state').count('outgoing'), 2, "the rest waits in the queue")

    def test_transactional_is_not_held_by_the_bulk_limit(self):
        self._already_sent(50)  # far over the daily limit
        transactional = self._mails(2, bulk=False)
        bulk = self._mails(2, bulk=True)
        (transactional + bulk).send()
        self.assertEqual(set(transactional.mapped('state')), {'sent'})
        self.assertEqual(set(bulk.mapped('state')), {'outgoing'})

    def test_sends_older_than_a_day_do_not_count(self):
        self._already_sent(50, hours_ago=25)
        mails = self._mails(3, bulk=True)
        mails.send()
        self.assertEqual(set(mails.mapped('state')), {'sent'})

    def test_hourly_limit_spreads_bulk(self):
        self.server.throttle_bulk_hourly_limit = 2
        mails = self._mails(5, bulk=True)
        mails.send()
        self.assertEqual(mails.mapped('state').count('sent'), 2)

    def test_queue_run_respects_the_limit(self):
        self._already_sent(6)  # 10 - 2 - 6 = 2 left
        mails = self._mails(4, bulk=True)
        self.env['mail.mail'].process_email_queue(ids=mails.ids)
        self.assertEqual(mails.mapped('state').count('sent'), 2)

    def test_sends_are_logged(self):
        self._mails(2, bulk=True).send()
        self.assertEqual(self.Log._recipients_since(self.server, fields.Datetime.now() - timedelta(minutes=5)), 2)

    def test_unlimited_server_is_untouched(self):
        self.server.throttle_daily_limit = 0
        self._already_sent(1000)
        mails = self._mails(3, bulk=True)
        mails.send()
        self.assertEqual(set(mails.mapped('state')), {'sent'})

    # -- provider refusals ----------------------------------------------------------

    def test_quota_refusal_is_a_delay_not_a_failure(self):
        mail = self._mails(1, bulk=False)
        with patch(SEND_EMAIL, side_effect=GMAIL_DAILY_LIMIT):
            mail.send()
        self.assertEqual(mail.state, 'outgoing', "must go back to the queue, not to exception")
        self.assertGreater(mail.scheduled_date, fields.Datetime.now())
        self.assertIn('5.4.5', mail.failure_reason)
        self.assertGreater(self.server.throttle_paused_until, fields.Datetime.now())

    def test_paused_server_holds_even_transactional_mail(self):
        """While the provider refuses, sending would only produce more refusals."""
        self.server.throttle_paused_until = fields.Datetime.now() + timedelta(minutes=30)
        mail = self._mails(1, bulk=False)
        mail.send()
        self.assertEqual(mail.state, 'outgoing')

    # -- installing on a database that is already sending ---------------------------

    def test_install_hook_seeds_usage_and_pauses_after_recent_refusal(self):
        """Runs the real install hook against an active Gmail server, which is the
        production path: the hook's SQL must work on the live schema (mail_server_id
        is inherited from mail_message), and an install mid-incident must not see an
        empty log and start sending into a provider that is refusing."""
        from odoo.addons.mail_send_throttle import GMAIL_DEFAULTS, post_init_hook

        gmail = self.env['ir.mail_server'].create({
            'name': 'Gmail', 'smtp_host': 'smtp.gmail.com', 'smtp_port': 465})
        sent = self.env['mail.mail'].create([{
            'subject': f's{i}', 'email_to': f's{i}@example.com',
            'mail_server_id': gmail.id, 'auto_delete': False,
        } for i in range(3)])
        sent.write({'state': 'sent'})
        refused = self.env['mail.mail'].create({
            'subject': 'r', 'email_to': 'r@example.com', 'mail_server_id': gmail.id})
        refused.write({'state': 'exception', 'failure_reason':
                       "SMTPDataError: (550, b'5.4.5 Daily user sending limit exceeded.')"})
        self.env.flush_all()

        post_init_hook(self.env)

        self.assertEqual(gmail.throttle_daily_limit, GMAIL_DEFAULTS['throttle_daily_limit'])
        self.assertEqual(
            self.Log._recipients_since(gmail, fields.Datetime.now() - timedelta(hours=24)), 3,
            "the last 24 hours of traffic must be counted")
        self.assertGreater(gmail.throttle_paused_until, fields.Datetime.now(),
                           "a recent quota refusal must pause the server")

    def test_real_failures_still_fail(self):
        mail = self._mails(1, bulk=False)
        with patch(SEND_EMAIL, side_effect=smtplib.SMTPRecipientsRefused(
                {'r0@example.com': (550, b'5.1.1 No such user')})):
            mail.send()
        self.assertEqual(mail.state, 'exception')
        self.assertFalse(self.server.throttle_paused_until)
