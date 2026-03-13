# Fix "No such file or directory" filestore errors on Coolify (Odoo 18)

Your logs show `FileNotFoundError` for paths like `/var/lib/odoo/filestore/revive/d5/d56df55...`. The database has attachment records pointing to files that no longer exist on disk (orphan attachments). Fix it by cleaning those records **inside the Odoo container** and ensuring filestore is persisted.

## Step 1: Run the orphan cleanup inside the Odoo container

You must run this **inside the same environment where Odoo runs** (Coolify’s Odoo container), so it uses the same `data_dir` and database.

### Option A – Coolify "Execute Command" (recommended)

1. In Coolify, open your Odoo application.
2. Use **Execute Command** (or equivalent) to get a shell in the **Odoo** container (not the Postgres container).
3. Run the Odoo shell for database `revive` (change `-d revive` if your DB name is different):

   ```bash
   odoo shell -d revive --config=/etc/odoo/odoo.conf
   ```

4. At the `>>>` prompt, paste this block and press Enter:

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

   Website = env.get('website.website')
   if Website:
       for w in Website.search([]):
           w.write({'logo': False, 'favicon': False})
       env.cr.commit()
       print('Cleared logo and favicon on all websites. Re-upload in Website Settings.')
   ```

5. Exit the shell: `exit()` or Ctrl+D.

### Option B – If the repo is available inside the container

If your project (including `scripts/clean_orphan_attachments.py`) is mounted or copied into the container:

```bash
odoo shell -d revive --config=/etc/odoo/odoo.conf < scripts/clean_orphan_attachments.py
```

(Adjust path to the script if needed.)

---

## Step 2: Ensure filestore is persisted in Coolify

To avoid losing filestore again on redeploy:

1. In Coolify, check your Odoo service **Volumes**.
2. Ensure a persistent volume is mounted at Odoo’s **data directory** (where filestore lives). For many setups this is:
   - **Mount path (in container):** `/var/lib/odoo`
   - Use a **persistent** volume (not a tmpfs or ephemeral path).

3. In Odoo config, `data_dir` should match that path (e.g. `data_dir = /var/lib/odoo`). Your logs already show `/var/lib/odoo/filestore/revive`, so the app is using that; the important part is that `/var/lib/odoo` is a Coolify persistent volume.

If this volume was missing or recreated empty, that would explain the missing files and the need for this cleanup.

---

## Step 3: Re-upload logo and favicon

After the cleanup, website logo and favicon are cleared. Re-upload them:

- **Odoo:** Website (or Settings) → Website → Configuration → **Logo** and **Favicon**.

Other missing images (e.g. on company, services) need to be re-uploaded on their respective forms.

---

## If you still get 500 on /web/image/...

If after the cleanup you still see 500 for `/web/image/website/1/logo/Home` or favicon, clear website images again in shell:

```python
if env.get('website.website'):
    env['website.website'].search([]).write({'logo': False, 'favicon': False})
env.cr.commit()
```

Then re-upload logo/favicon in Website Settings.

---

## Summary

| What you see | Cause | Fix |
|--------------|--------|-----|
| `FileNotFoundError` for `/var/lib/odoo/filestore/revive/...` | Orphan attachments (DB points to missing files) | Run cleanup in Odoo shell (Step 1) |
| 500 on `/web/image/website/1/logo/Home` or favicon | Website record points to missing image | Cleanup clears these; re-upload in Website Settings |
| Filestore errors after every redeploy | Filestore not persisted | Mount persistent volume at `/var/lib/odoo` (Step 2) |

The "Mail: Fetchmail Service" and "Fetched 0 email(s)" lines in your logs are normal when there are no new emails; they are unrelated to the filestore errors.
