---
title: Storage and backup
audience: owner
summary: What Delve keeps on this machine, the backup store that copies it every day, and the library shared with friends.
screens: /preferences
order: 5
related: install-and-first-run, modules, connections
---
Delve keeps everything on this machine, in its data directory: `~/.local/share/delve`, or the folder that
`DELVE_DATA_DIR` names. That holds the database (accounts, campaigns, modules, Preferences), the owner token, the
connections' tokens and every uploaded file.

**Preferences → Storage**, which only the owner sees, adds two stores elsewhere. Each is its own container or bucket:
Delve refuses to put both in the same one.

## Choosing a store

For each store, pick a **Provider**:

- **Azure Blob Storage**: paste the container's **SAS URL**.
- **Cloudflare R2**: your **Account id**, the **Bucket**, the **Access key id** and the **Secret access key**.
- **S3-compatible**: the **Endpoint**, the **Bucket**, the **Access key id** and the **Secret access key**.

Choose **Save**, then **Test**: it shows what the credential may do. A SAS URL shows when it expires. The secrets
stay in this machine's files; Delve never shows them again, and no backup holds them.

## The backup store

The **Backup store** is yours alone. Its credential needs read, list, create, write and delete.

- Every day at the time in **Back up daily at** (04:00 at first, this machine's time), Delve copies the modules,
  campaigns and settings that changed. It keeps the latest copy of each. A backup missed while Delve was off runs
  when it starts.
- **Back up now** runs one at once. **Last backup** says how it went; what failed is tried again next time.
- **Restore** lists the backups of this install, or of another install that uses the same store. Tick what to bring
  back and choose **Restore selected**. A campaign brings its module along. Delve asks before it replaces anything
  already here.

<p class="note">The backup holds modules, campaigns and settings, not the accounts, Preferences or tokens. Those are
only in the data directory.</p>

<figure><img src="/help/backup-store.webp" alt="Storage: the backup store and the library store, each with its provider and SAS URL" width="1280" height="800" loading="lazy"></figure>

## The library store

The **Library store** is shared with friends: the modules you publish, and the ones you download, under **Library** on
the Modules page. Its credential's right decides what this install may do there: **Read** (browse and download),
**Publish** (add modules, and new versions of your own) or **Manage** (also change and delete anyone's).
