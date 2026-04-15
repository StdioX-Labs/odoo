#!/usr/bin/env python3
"""
Remove ir_attachment records whose filestore file is missing (e.g. after
filestore was lost on redeploy). Run once inside the Odoo container.

Usage (from host, with repo):
  docker exec -i <odoo_container> odoo shell -d revive --config=/etc/odoo/odoo.conf < scripts/clean_orphan_attachments.py

Or inside the container, run `odoo shell -d revive --config=/etc/odoo/odoo.conf`
then paste the code below (the part after "import os").
"""
import os

data_dir = odoo.tools.config['data_dir']
filestore = os.path.join(data_dir, 'filestore', env.cr.dbname)
unlinked = 0
for att in env['ir.attachment'].search([('store_fname', '!=', False)]):
    path = os.path.join(filestore, att.store_fname)
    if not os.path.exists(path):
        att.unlink()
        unlinked += 1
env.cr.commit()
print(f'Unlinked {unlinked} orphan attachments (missing filestore files).')

# Clear website logo/favicon so UI stops requesting missing files (stops 500 on /web/image/website/1/logo)
Website = env.get('website.website')
if Website:
    for w in Website.search([]):
        w.write({'logo': False, 'favicon': False})
    env.cr.commit()
    print('Cleared logo and favicon on all website records. Re-upload in Website Settings.')
