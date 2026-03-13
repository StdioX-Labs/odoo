# One-time cleanup after enabling filestore persistence

After you deploy with `data_dir = /var/lib/odoo`, the database may still contain `ir_attachment` records that point to files that no longer exist (they were in the old ephemeral filestore). That causes `FileNotFoundError` for `/var/lib/odoo/filestore/revive/...` when opening images (e.g. company.service, website logo). Follow these steps once.

## 1. Remove orphan attachments (missing filestore files)

This removes every `ir_attachment` whose file is missing on disk so Odoo stops trying to serve them. **Run this inside the Odoo container.**

**Option A – Odoo shell (paste this):**

Open a shell in the Odoo container (e.g. Coolify “Execute Command” or `docker exec -it <container> bash`), then:

```bash
odoo shell -d revive --config=/etc/odoo/odoo.conf
```

At the `>>>` prompt, paste:

```python
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

# Clear website logo/favicon so the UI stops requesting missing files
Website = env.get('website.website')
if Website:
    for w in Website.search([]):
        w.write({'logo': False, 'favicon': False})
    env.cr.commit()
    print('Cleared logo and favicon on all website records. Re-upload in Website Settings.')
```

**Option B – if you have the repo in the container:**

```bash
odoo shell -d revive --config=/etc/odoo/odoo.conf < scripts/clean_orphan_attachments.py
```

After this, broken image requests (e.g. `/web/image/company.service/24/image`) will stop raising 500; Odoo will show placeholder or empty for those fields.

**If you still get 500 for `/web/image/website/1/logo/Home`**, the website record is still pointing at a missing image. In Odoo shell run this to clear logo and favicon so the UI stops requesting them:

```python
if env.get('website.website'):
    env['website.website'].search([]).write({'logo': False, 'favicon': False})
env.cr.commit()
print('Cleared. Re-upload logo/favicon in Website Settings.')
```

## 2. Clear stale asset bundles (optional, SQL)

If you still see asset/bundle errors, run against the `revive` database:

```bash
psql -U odoo -h <db_host> -d revive -f fix_assets.sql
```

Or run this SQL:

```sql
DELETE FROM ir_attachment
WHERE res_model = 'ir.ui.view'
  AND type = 'binary'
  AND (name LIKE '%.js' OR name LIKE '%.css' OR name LIKE '%.min.js' OR name LIKE '%.min.css');
DELETE FROM ir_attachment WHERE url LIKE '/web/content/%';
```

Odoo will regenerate JS/CSS bundles on the next page load.

## 3. Re-upload logo, favicon, and other images

Any image that was stored in the old filestore is gone. Re-upload as needed:

- **Website:** Settings → Website → Logo and Favicon.
- **Services / other models:** Edit the record and upload the image again.

From then on, new uploads and assets will be stored under `/var/lib/odoo` (your Docker volume) and will persist across redeployments.
