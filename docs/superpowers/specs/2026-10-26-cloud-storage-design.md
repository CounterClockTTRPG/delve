# Cloud storage: backups and a shared module library (DEL-110)

Status: draft for the owner's approval, 2026-10-26.

## Intent

Cloud storage does two jobs for a Delve install:

1. **A safety net.** The owner's modules, campaigns and settings (worlds) are copied off the machine every day, so a
   dead disk loses at most a day of play.
2. **A shelf to share modules.** Friends who run their own Delve installs connect to a shared library, see which
   modules are on it, download one, and are told when a newer version is published.

The owner asked for both (2026-10-26): "it is both a safety net and a way to share modules", shared with "friends with
their own install".

## Goals

- **Two stores, configured separately** (owner: "support separate stores (configurable)"): a **backup store**,
  private to the owner, and a **library store**, shared with friends. Each has its own provider, location and
  credential, so a friend given the library's credential can never read the owner's campaigns. Either may be left
  unset: an install may have only a library (a friend's), only backups, or both.
- **The owner configures them in Delve**, in a Storage section only the owner sees (as Connections are today:
  `Owner`, an organiser gets 403). Hidden from non-admin users (owner's comment on DEL-110).
- **Daily backup at a configured time**, plus a Back up now button. Only items changed since their last backup are
  uploaded (owner's comment). **Latest copy only**: a backup replaces the previous copy of that item; no history
  (owner).
- **What is backed up:** modules, campaigns and **settings (worlds)** (owner: "backup settings").
- **Restore by choice:** a list of what's in the backup store, restored one at a time or several with checkboxes
  (owner).
- **A shared module library:** a module goes to the library only when someone presses **Publish** (owner: "only on
  publish"), never at backup time.
- **Library metadata:** each entry shows its **author, date created and date last updated** (owner), plus title,
  summary and version (my call).
- **Browse and download:** an install lists the library and downloads a module as a local module.
- **New versions shown in the GUI:** when the library has a newer version of a downloaded module, the install shows
  it, and the organiser chooses to update (owner: "show in the gui that there is a new version", "give the option to
  update"). Nothing changes until they do.
- **Rights on the library, by access** (owner: "depends on access settings (rw vs ro)", and "treat overwrite/delete
  as separate right from publish"). Three levels:
  - **read:** browse and download.
  - **publish:** also add new entries, and new versions of entries this install published.
  - **manage:** also overwrite or delete any entry or version, including other publishers'.
- **Two providers: Azure Blob Storage** (owner's comment on DEL-110) **and Cloudflare R2** (owner: "add cloudflare
  too"), behind one seam. R2 is reached through its S3-compatible API, so the same provider also works with Backblaze
  B2, AWS S3 and MinIO (offered as "S3-compatible", with R2 as a preset).

## Non-goals

- Older backup versions, point-in-time restore. Latest copy only.
- Sharing campaigns or settings through the library. The library holds modules only. Campaigns hold a table's
  characters, story and the DM's secrets; they go only to the backup store.
- Backing up accounts, login sessions, Preferences, Connections or any credential. A credential never leaves the
  machine.
- Live sync or merging. A library update becomes a new version of the local module; there is no three-way merge.
- Delve hosting the library. The storage service is the library; there is no Delve server in between.

## Anti-goals (a failure even if it works)

- A credential, token or SAS appearing in any answer to a browser, any log line, any error message or any uploaded
  file.
- A backup that silently uploads nothing (or half) and still says it succeeded.
- A friend's library credential being able to read the owner's backups (hence two stores).
- A library update that overwrites an organiser's own edits without warning.
- Buttons that can only fail: Publish on a read-only library, Delete without the manage right, Back up now without a
  backup store.
- Restoring over an existing campaign, module or setting without asking.
- A backup run holding up play: it runs in the background and never blocks a beat or a conversion.

## How it works

### The two stores

**Backup store** (one container or bucket, the owner's alone):

```
<install id>/index.json                       what this install backed up, and when
<install id>/modules/<module id>.dmod
<install id>/campaigns/<campaign id>.dcmp
<install id>/settings/<setting id>.dset
```

`<install id>` is a random id Delve makes once per install and keeps in its data dir, so two installs backing up to
one store never overwrite each other (my call). The index also carries the install's display name.

**Library store** (one container or bucket, shared):

```
<entry key>/v<N>/module.dscn                  version N of the module
<entry key>/v<N>/entry.json                   its metadata: title, summary, author, created, updated, version,
                                              size, hash, publisher install id
```

- `<entry key>` (`lib_…`) is made at the first publish and kept on the module, so a downloaded copy knows which
  entry it came from.
- **Every version is a new object.** Publishing never overwrites anything: a first publish creates `v1`, a new
  version creates `v<N+1>`. Browsing lists the store and reads each entry's newest `entry.json` (my call: no shared
  index file, because rewriting one would need the overwrite right for every publish). The builder may add a cache
  of the listing if browsing a large library is slow.
- Older versions stay until someone with the **manage** right removes them; the library shows only each entry's
  newest version (my call).

### Rights

**Backup store:** Delve needs read, list, write and delete. A credential that can't do all four is refused for
backups, with the reason.

**Library store:** the right comes from what the credential can do, checked by a Test button that probes it (list;
create a probe object; overwrite it; delete it):

| Probe succeeds | Right |
|---|---|
| list only | read |
| list + create | publish |
| list + create + overwrite + delete | manage |

- **Azure:** a container **SAS URL**. The owner gives a friend read+list (read), read+list+create (publish: Azure's
  `c` permission creates new blobs but can't overwrite), or read+list+create+write+delete (manage). The storage itself
  enforces it.
- **Cloudflare R2 / S3-compatible:** endpoint (for R2 `https://<account id>.r2.cloudflarestorage.com`), bucket,
  access key id and secret. R2's tokens are **Object Read only** or **Object Read & Write**, so the storage can only
  enforce read versus write. For a write token the owner picks **publish** or **manage** in the Storage section, and
  Delve enforces the difference on its own side (my call). The Storage section says so: on R2, a friend with a write
  token could get around it with other tools.
- **Own entries:** with the publish right, an install may add versions only to entries whose newest `entry.json`
  names its install id as the publisher. Publishing a module downloaded from someone else's entry creates a new
  entry under this install's author name (my call, from "overwrite/delete as a separate right").
- Each right shows only its own buttons: Publish (publish and up), New version (publish, own entries; manage, any),
  Delete entry or version (manage).

### Secrecy

Stored like the Replicate and assetgen tokens today (`delve.images.connections`): files in the data dir, mode 0600,
written in and never read back out. The routes answer `set`/`unset` and the right, never the SAS's query string or
the secret key. Errors are Delve's own words with the HTTP status, never the provider's body (which may echo the
SAS). The container URL without its query string, and R2's endpoint and bucket, may be shown.

### Backup

- **When:** daily at a time of day the owner sets (local time, default 04:00), and Back up now. A run due while Delve
  was down runs at the next start (my call). One run at a time.
- **What:** every module, campaign and setting whose content changed since its last successful backup, judged by a
  content hash of its bundle compared with the hash recorded at its last backup (my call: `updated_at` isn't touched
  by every change, and a story entry doesn't update the campaign row). The builder may use cheaper change markers if
  they are provably complete.
- **Modules** go in a lossless Delve-only bundle, `.dmod`: the module with **all its revisions** (a campaign is pinned
  to a `(module_id, revision)` and must restore onto that revision), its source (texts, keys, entities,
  attachments), maps, world maps including those in review, and the source PDF. This is not the `.dscn` export, which
  carries only the current working copy and leaves things out (my call, from the builder check).
- **Campaigns** go in a `.dcmp` bundle: every row of the campaign's tables (29 today: seats, characters, story,
  beats, combats, world, map states, images, possessions, quests, factions, notes, histories, novels, …) as JSON, the
  blobs those rows reference, **the house rules and house-rule bundles the campaign uses** (install-level rows it has
  foreign keys to, so it restores on a fresh machine; my call), and a manifest: format version, Delve version,
  migration head, the module id and pinned revision, the setting id if any. The module and setting are their own
  backup items, not duplicated inside.
- **Settings** go in a `.dset` bundle: the setting with its world maps, lore, calendar and everything stored under it,
  and the blobs they reference.
- **Deleted items:** an item deleted locally keeps its last backup (nothing pruned automatically). The Restore list
  marks it "no longer on this install". A Remove-from-backup action per item is fine (left to the builder).
- **Result:** the Storage section shows the last run: when, what was uploaded, what failed and why. A partial run
  lists each failure and isn't reported as success.
- Recorded per item: last backup time, hash, size, in Delve's DB (a migration).

### Restore

The Restore list reads `<install id>/index.json` and can switch to another install id in the same backup store (a new
machine has a new id). Each row: kind, title, last backed up, size, whether it exists here. Restore one, or tick
several.

- Items restore under their original ids. If one exists here, the owner confirms replacing it.
- A campaign whose module or setting isn't on this install brings it along from the same backup store (ticked
  automatically, shown in the list). Its house rules are restored with it; a house rule that already exists here under
  the same id is kept, not replaced (my call).
- Seats keep their roles and names. An account a seat was linked to that doesn't exist here is unlinked, and the host
  re-invites or reassigns (my call).
- A bundle from a newer format version than this Delve understands is refused with a clear message; an older one is
  upgraded on the way in.
- The test that matters: a module, a campaign and a setting backed up from one install restore identical (rows and
  blobs) into an empty one, and the campaign plays on its pinned revision.

### Publishing to the library

- A **Publish to library** action on a module, for the owner and organisers, on an install whose library right is
  publish or manage (my call: modules have no per-module owner today; any organiser may).
- The first publish shows the entry it will create: title, summary, author, created, version 1. **Author** is the
  publishing account's display name, editable before the first publish (my call).
- **Dates:** created is the first version's time; last updated is the newest version's time.
- **New version** on a module published from here: uploads `v<N+1>`. Unchanged content (same hash as the newest
  version) isn't uploaded; the button says it is up to date.
- **Delete** (manage only, with a confirmation): a whole entry, or one version.

### The Library tab

A Library tab on the Modules page, on every install with a library store:

- The entries, newest updated first: title, summary, author, created, last updated, version, size, and whether this
  install has it (downloaded, published from here, not here).
- **Download** makes it a local module, remembering the entry key and version it came from, and the hash of what was
  downloaded.
- **Update available:** a downloaded module whose entry has a newer version shows a badge in the module list and on
  the module's page, with **Update**. Update writes the new version as a **new revision of the same local module**:
  campaigns already running stay on their pinned revision, and new campaigns get the new content (my call, from the
  builder check; modules with campaigns can't be deleted). If the organiser edited their copy since downloading (its
  hash differs from what was downloaded), Update warns that their edits will be replaced, and offers to keep their
  version as a separate module first.
- The library is read on opening the tab and on Refresh, and checked for updates at start and with each daily
  schedule tick (my call: no constant polling).

### The provider seam

A small interface, `ObjectStore`: `list(prefix)`, `get(name)`, `create(name, bytes)` (fails if it exists),
`put(name, bytes)` (overwrite), `delete(name)`, `probe()` (the rights table above). Two implementations:

- `AzureBlobStore`, over the Blob REST API with `httpx`. `create` is a PUT with `If-None-Match: *`.
- `S3Store`, over the S3 API with SigV4 signing (R2, B2, S3, MinIO). `create` is a PUT with `If-None-Match: *`,
  which R2 and S3 support; for a provider that doesn't, a check before writing (left to the builder).

My call: no cloud SDKs, to keep dependencies small; the builder may use `azure-storage-blob` or `boto3`/`aiobotocore`
if hand-written signing turns out costly. A local-folder implementation backs the tests, and may be offered to the
owner as a third provider (left to the builder).

## Constraints

- Follow the codebase: SQLite with Alembic migrations (plain `ALTER TABLE … ADD COLUMN` where possible), FastAPI
  routes, React web, the existing `.dscn` exporter and importer for the library, the Connections pattern for secrets,
  the five UI languages (en, nl, de, fr, lv), `docs/style-guide.md`, `make ci` green.
- Never a real cloud call in tests: fake stores (a local folder, or an `httpx.MockTransport` playing Azure and S3,
  including the create-only and read-only refusals).
- Bundles may be large (pictures, PDFs): stream or chunk uploads (Azure block blobs, S3 multipart) where it matters;
  the builder decides the threshold.
- Play and conversions are never blocked by a backup run.

## Left to the builder

- The exact layout and versioning of `.dmod`, `.dcmp` and `.dset`, within the round-trip test above.
- How change detection is implemented, within the "never miss a change" rule.
- Screen layout of the Storage section, the Restore list and the Library tab.
- Whether the Storage section lives in Preferences or beside Connections.
- Order of work. A sensible order: the seam, both providers and the Storage section → module backup and restore →
  campaign and setting bundles, backup and restore → library publish, browse, download → rights and update notices.

## Open, for the owner

- Cloud cost: Azure Blob for a few GB is cents a month; R2 is free up to 10 GB with no download fees. A SAS URL with an
  expiry date stops working when it expires, and Delve says so in the Storage section.
