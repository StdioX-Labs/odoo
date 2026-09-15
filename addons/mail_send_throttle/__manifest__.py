{
    'name': 'Mail: Sending Limits',
    'version': '18.0.1.0',
    'category': 'Hidden/Tools',
    'summary': "Keep bulk email under an SMTP provider's daily sending limit",
    'description': """
Sending limits per outgoing mail server
=======================================
Providers such as Gmail cap how many recipients an account may send to in a
rolling 24 hours (about 500 for a personal Gmail account). Past that, they
refuse *everything* from the account for up to a day - booking confirmations
and invoices included - and Odoo records each refusal as a permanent failure.

Per outgoing mail server, this module adds:

* a rolling 24-hour limit, with a reserve kept back for transactional mail;
* an hourly limit for bulk mail, so a campaign trickles out instead of bursting;
* bulk mail (mass emails from a list view, Email Marketing) waits in the queue
  for the next run instead of being sent over the limit;
* provider quota and rate-limit refusals are put back in the queue and the
  server is paused for a while, instead of being marked as failed.

Transactional mail is never held back by the bulk counters. It is only held
while the provider is actively refusing, and then goes out on the next run.
    """,
    'depends': ['mail'],
    'data': [
        'security/ir.model.access.csv',
        'views/ir_mail_server_views.xml',
    ],
    'post_init_hook': 'post_init_hook',
    'installable': True,
    'application': False,
    'auto_install': False,
    'license': 'LGPL-3',
}
