# Module categories and banners (DEL-114, DEL-123)

Owner decisions (2026-10-26): **one category per module**; a module's banner is **painted, uploaded, or one of the
module's own pictures** (a published book's official art, such as its cover), **or none**, chosen per module; **a new
campaign starts with its module's banner** until it paints its own. The Modules list gets a **card view** beside the
table.

## 1. Categories (DEL-114)

- **What a category is:** a name in a short list the organisers keep, such as "Megadungeons", "One-shots" or
  "Campaign arcs", in an order they choose. A module has one category or none.
- **Data:**
  - a new table `module_categories (id, name, position)`;
  - a nullable `modules.category_id`, set to null when its category is deleted.
  - Names are unique in any case, at most 60 characters.
  - Migration 0025.
- **API** (organisers):
  - `GET /api/module-categories`, `POST` (name), `PUT /{id}` (name, position), `DELETE /{id}`;
  - `PATCH /api/modules/{id}` takes `category_id`, null for none;
  - the module summary carries `category: {id, name} | null`.
- **Modules list:**
  - modules are grouped under their category's heading, in the categories' order, with "No category" last; a heading
    shows its count;
  - the filter bar gets a Category choice, kept in the address like the other filters;
  - a **Categories** button opens a small dialog to add, rename, reorder (up/down) and delete them. Deleting a
    category moves its modules to "No category", after a confirmation that says how many.
- **Module page:** a Category menu beside the title, with "No category" and the list.
- **Elsewhere:**
  - New campaign's module picker uses the same headings.
  - Backups: `module_categories` goes with the settings (`.dset`) bundle's shared rows. A module restored onto an
    install without its category gets "No category". A module's `category_id` travels with it.
  - The library ignores categories: they are this install's own.

## 2. Module banners (DEL-123)

- **Where it comes from:** a module has at most one banner, and its page offers four ways to set it, or remove it:
  1. **Paint a banner:** from the module's title, summary, setting and tags, with the campaign banners' image choice
     (Preferences' scene model; paid only when paid images are allowed), at 21:9 like a campaign's. It paints in the
     background; the page shows "Painting…", then the banner, or the error with Paint again. An optional hint is
     added to the brief, as for a campaign's Paint again.
  2. **Upload a picture:** PNG, JPEG or WebP, at most 16 MB, checked and re-encoded like an avatar.
  3. **Use one of the module's pictures:** a grid of the module's picture attachments, such as the converted book's
     page 1 cover, or a handout.
  4. **None:** remove it.
- **Cropping:** an uploaded or picked picture is rarely 21:9. A **crop position** slider (top to bottom, default the
  middle) chooses which 21:9 band of it is kept, with a live preview. The server cuts and stores the band, so every
  view is the same picture.
- **Data:**
  - nullable columns on `modules`: `banner_blob`, `banner_mime`, and `banner_source` (`painted`, `uploaded`, or
    `picture:<attachment id>`);
  - for a painting, `banner_status` (`painting` or `failed`, with `banner_error`) and `banner_prompt` (never sent to
    players);
  - the bytes in the blob store, as everything else. Also migration 0025.
- **API** (organisers):
  - `GET /api/modules/{id}/banner` serves the picture (404 for none);
  - `POST /api/modules/{id}/banner/paint` (`{hint}`) answers 202; 409 while painting, 422 while paid images are off
    and the choice is paid;
  - `POST /api/modules/{id}/banner/upload?position=0..1` takes the raw picture: a sixth raw-body exception in the
    guard, with the avatar's types;
  - `PUT /api/modules/{id}/banner` with `{picture, position}` uses a module picture;
  - `DELETE /api/modules/{id}/banner`.
  - A `modules` event tells the pages.
- **Campaigns:**
  - A campaign of a module with a banner **shows the module's banner** while it has none of its own: on its empty
    story, at the Tavern's top, on its page and on the module's page.
  - A new campaign of such a module **doesn't paint one automatically** (today every new campaign does); its page's
    "Paint a banner" still gives it its own, which then replaces the module's for that campaign.
  - A module without a banner keeps today's behaviour.
  - Players' seats may read the module banner through the campaign's `…/banner` route, which falls back to it. The
    module route stays organiser-only.
- **Export, import and the library:** the banner goes into the `.dscn` as an asset of type image with the role
  `banner` (a format addition, version 2 stays readable). An imported or downloaded module brings its banner, and a
  published one carries it. An older bundle has none.

## 3. Card view (DEL-123)

- The Modules list gets a **Table | Cards** switch, remembered in this browser.
- **Cards:**
  - Each card shows the banner across its top, and below it the title, the setting and levels, and the draft and
    "Update available" tags. The category is the heading the card sits under.
  - A module without a banner gets a quiet placeholder: its title's first letter in the look's display face, on the
    look's sunken surface. No stand-in pictures.
  - Cards wrap in a grid, three or four across on a desktop and one on a phone.
- The filter, the category headings and the pager work the same in both views.

## Out of scope

- Several categories a module (the owner chose one).
- Sharing categories through the library.
- Free-form cropping with a box; the position slider covers the 21:9 band.
- Painting banners for every module at once (each one is its own button; painting costs money on Replicate).

## Order

1. Migration 0025 and the storage for categories and module banners.
2. Categories API.
3. Categories UI: headings, filter, dialog, module page.
4. Module banner storage and serving, upload, pick and crop.
5. Painting a module banner, reusing the campaign banner's brief and image job.
6. Campaign fallback, and no automatic painting.
7. Card view.
8. `.dscn` banner asset (export, import, library).
9. Backups.
10. Docs (data dictionary, glossary, README).
