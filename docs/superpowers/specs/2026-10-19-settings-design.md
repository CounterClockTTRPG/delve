# Settings: a first-class area for the worlds campaigns play in

Date: 2026-10-19. Status: design, for a Guild quest (app `delve`, edit mode).

## Intent

The owner wants the setting (today: Greyhawk) to be something you can open, consult and grow, not a hidden provider
behind the DM's tools. The owner said: "Settings should be a first-class member in the sidebar (allowing me to look up
lore, browse maps, add information etc)", and asked to "incorporate the Greyhawk information (moving world maps to
setting)". More settings will follow later ("we will add more"). They may eventually come from setting PDFs that Delve
structures into pages, facts and maps. That is not part of this quest, but the design must not hard-code Greyhawk.

Today Delve already has the following. File references come from a survey of master b8009a6.
- A `Setting` protocol (src/delve/setting/setting.py) with Greyhawk (`GreyhawkSetting`) and a fake.
- The Greyhawk wiki in the read-only `reference.db`: `gh_pages` 4240 pages, 13 typed tables, redirects and FTS.
- A global `lore_facts` pool of 460 facts. It has no setting column; 90 facts are in category `greyhawk`.
- The Common Year calendar.
- A hand-made built-in map, `greyhawk-region.map`.
- Settings are reached only through DM tools (`setting_lookup`, `setting_search`), the "Did you know" route and campaign
  seeding. Nobody can browse a setting in the UI.
- World maps belong to modules (in the module source) or campaigns (`world_maps`). A setting only *points at* a module's
  map (`setting_world_maps`, set from the module page).

## Decisions the owner took (2026-10-19)

1. **Naming.** The install's options page (today "Settings": backends, models, effort, language) is renamed
   **Preferences**. **Settings** now names the area for game worlds (Greyhawk and later others).
2. **Adding information** means three things:
   - writing **new wiki pages**;
   - **editing shipped pages**, where the edit overrides the shipped text and the original stays recoverable;
   - adding **lore facts**.
   Promoting a campaign's facts into the setting by hand was not chosen. The DM's proposals cover that need (point 5).
3. **World maps.** A setting **owns its world maps** directly. Modules may still bring their own regional maps.
   Campaigns copy from both, as today.
4. **Greyhawk starts with the Darlene Flanaess map**: the owner's greyhawk.jpg, 13706×10678 px, a hex grid of
   1 hex = 30 miles.
5. **Who edits.** Organisers edit by hand, and the AI DM may add during play. The DM's additions are **proposals**: they
   apply to the DM's own campaign at once, and to the setting (every campaign) only once an organiser accepts them.
6. **Visibility.** Everyone may read a setting's lore and maps, but players and organisers reach them differently:
   - **Organisers** use the sidebar **Settings** area, which shows everything, DM-only content included.
   - **Player seats** keep having no nav: a seat stays at its table (`SeatsStayAtTheirTable`). The play screen gets a
     **Setting** tab or panel. It shows the campaign's setting (lore, facts, maps), read-only and without DM-only
     content. The owner chose this after the builder check.
   - Pages, and parts of pages, can be **DM-only**.
   - Maps are shown whole, apart from DM-only content. The campaign's fog applies only to the campaign's copy, on the
     play screen's map.
7. **New settings** (blank homebrew, wiki import, PDF gazetteer) are **not in this quest**. Greyhawk stays the only real
   setting, but nothing may assume it is the only one.
8. **Quest.** Edit mode, unattended, design questions answered by recommendation ("proceed"), planning auto,
   $250 budget. Nothing is delivered without the owner's OK.

## Goals

- **The sidebar.** A **Settings** entry (`/settings`) lists the install's settings. Each setting has a page with these
  parts:
  - **Lore.** Search the wiki (FTS) and browse by kind: places, realms, deities, people, organisations and the rest.
    Read a page with its typed fields and its links to other pages, following redirects.
  - **Facts.** The setting's lore facts. Add, edit and remove the install's own.
  - **Maps.** The setting's world maps. Open one in the existing world-map viewer and editor, and import one from
    GeoJSON or from a picture with the existing review step.
  - **Calendar.** Read-only: the months, festivals and seasons.
  - **Proposals**, for organisers only. The DM's proposed pages and facts, each showing the campaign it came from.
    Accept, edit then accept, or reject.
- **Install additions over shipped data.** The reference stays read-only and rebuildable. The install's additions live
  in Delve's own database and are layered over the reference. An addition is one of three things:
  - a **new page**;
  - an **override** of a shipped page, matched by title, which replaces its text and fields; reverting it brings back the
    shipped page;
  - a **fact**.
  Every reader goes through one setting layer, so no reader sees one source without the other: the DM's lookups and
  search, Ask the DM, "Did you know", and the Settings area.
- **DM-only content.** A page or a fact can be marked DM-only, and a page can hold DM-only sections. The DM sees all of
  it. Players see none of it: not in the Settings area, not in Ask, not in "Did you know". The shipped wiki is public lore
  and is all player-visible.
- **DM proposals.** New DM tools let the DM propose a setting page, a page edit or a fact. A proposal:
  - is visible to that campaign's DM, and to Ask in that campaign when it isn't DM-only;
  - waits in the setting's Proposals list;
  - when accepted, becomes an ordinary addition for every campaign;
  - when rejected, stays as the campaign's own fact or page, so the campaign's continuity holds.
  `dm.md` gets a rule telling the DM when to propose:
  - propose a lasting fact of the world (a new village, an NPC's fate, a homebrew deity);
  - don't propose things that matter only to this table;
  - the module still wins over the setting.
- **Setting-owned world maps.** World maps get the owner kind `setting` alongside `module` and `campaign`, in the API,
  the editor route `/world-maps/setting/<id>/<name>`, the picture import (`check_worldmap` OWNERS) and review.
  A setting's maps are stored as maps of their own, no longer as a pointer to a module's map.
  A new campaign of the setting copies the module's maps first, then the setting's ready maps, as `seed` does today.
  The built-in `greyhawk-region` map is the fallback while the install has no map of its own for the setting.
  The existing "use as the setting's map" pointers are migrated into setting-owned copies, and the action on the module
  page becomes "Copy to <setting>'s maps".
- **Preferences.** The rename covers:
  - the route: `/settings` becomes `/preferences`;
  - the nav label and the page heading;
  - the i18n keys and strings: en "Preferences", nl "Voorkeuren", and "As in Preferences" in play;
  - the API: `/api/settings` becomes `/api/preferences`, and `/api/settings/...` is used for game settings;
  - the glossary (the Organiser row says "change Preferences");
  - the data dictionary, and the tests and e2e that name them.
  This is a rename, not a redesign.
- **One registry.** The DM's `CampaignContext` (`play/context.py` `SETTINGS`) and the web registries
  (`__main__.py build_registries`) get their setting from the same registry, so a second setting needs one registration.
- **Glossary.** Add or adjust these terms:
  - Settings (the area);
  - Preferences;
  - setting page;
  - addition / override;
  - proposal;
  - DM-only, for setting content;
  - the setting's map, rewritten now that settings own maps.
  Keep the glossary authoritative.

## Non-goals

- Creating a new setting in the UI, importing a wiki, or converting a setting PDF. Later, from a design of its own.
  Today's choice should leave room for it: a setting is an id, a title, a calendar, shipped data (optional) and install
  additions.
- Editing the calendar.
- Promoting campaign facts into the setting by hand (the owner didn't choose it). The DM's proposals cover the need.
- Shipping the Darlene picture in the repository (see "Constraints").
- Fog or per-campaign knowledge inside the Settings area.

## Anti-goals: failures even if it technically works

- DM-only content reaching a player through any path: the area, Ask, "Did you know", a search snippet, an export, or a
  map feature's label.
- The DM's proposals silently changing other campaigns before an organiser accepts them.
- Writing to `reference.db` or editing the snapshots. A `make install` rebuild must never lose the owner's additions.
- Two "settings" left that mean different things, in the UI, the API or the glossary.
- Greyhawk-specific branches in the generic code (`if setting == "greyhawk"`).
- Breaking existing campaigns: their world-map copies, knowledge and journeys stay as they are.

## Constraints

- The existing stack and patterns:
  - FastAPI routes under src/delve/web/routes;
  - repositories in storage/interfaces.py with SQLite tables, plus a new alembic migration after 0015_costs;
  - React Query and i18n en/nl in the web app;
  - the existing world-map viewer, editor and review screens, reused rather than rebuilt.
- Organiser rights work as for modules and house rules: organisers write, every seat reads player-visible content, and
  only the owner and organisers see DM-only content. The LAN token rules apply as on every route.
- `make ci` green on a fresh clone (Guild's check). The e2e browser specs are updated for the rename and get one spec for
  the Settings area: browse a page, add a fact, accept a proposal.
- **The Darlene map.** The picture's licence is not cleared for the repository, and reading it well needs the real
  claude and a person at the review. So:
  - The quest builds the path: a picture import targeted at a setting, plus a CLI command
    `delve setting import-map <setting> <picture> --name … --cell …` that starts the same conversion and leaves it in
    review.
  - The quest tests that path with the fake claude on a small picture.
  - Importing greyhawk.jpg on this install (1 hex = 30 miles) and reviewing it is a delivery step, done with the owner.
  - Once it is accepted, it becomes Greyhawk's map, and the built-in region map stays only as the fallback.

## What's left to the builder

- The table shapes for additions, overrides, facts and proposals. One table with a kind column, or several.
- How a DM-only section is marked in page text.
- How overrides are matched: titles, case and redirects.
- The search order between the FTS hits and the additions.
- The page layout of the Settings area and its phone version. It follows the Modules and House rules pages.
- Whether the lore-fact pool gets a setting column in the reference build, or a mapping from category to setting.
  Either way, "Did you know" for a Greyhawk campaign draws only Greyhawk-appropriate and general facts. Rules and monster
  facts stay general.
- The names and signatures of the DM proposal tools, kept in line with `add_fact`, `setting_lookup` and the other lore
  tools.
- How proposals by the same campaign for the same page are merged.
- How the migration turns the `setting_world_maps` pointers into copies.

## Calls made for the owner (to confirm or overrule)

- **Read routes.** The Settings area's routes require `Organiser` for writes and for DM-only content. The play screen's
  Setting tab uses table-seat routes scoped to the seat's campaign's setting, and they filter out DM-only content on the
  server.
- **Proposals are their own records** (a table of their own), not campaign facts. Each proposal carries a DM-only flag.
  A campaign's existing `campaign_facts` stay DM-only, as before.
  - In its campaign, a pending or rejected proposal that isn't DM-only is player-visible: in the Setting tab (marked "this
    campaign"), in Ask and in "Did you know".
  - A DM-only proposal reaches only the DM.
  - A rejected proposal stays the campaign's own, with the same visibility.
- **Ask the DM starts consulting the setting.** The glossary already says Ask answers "from the rules, the setting and
  what the asking player's characters know". Today `play/ask.py` gives it no setting. Ask gets a lookup over the setting
  layer: the shipped wiki, the additions, and the campaign's proposals, filtered to player-visible content. It works the
  way `_rules` does, by FTS on the question. Ask answers what is asked and doesn't volunteer more. The shipped wiki is
  public lore, so it may be used. The module's secrets still never reach Ask.
- **Hidden map features.** On setting maps, features tagged `hidden` (`maps/world/compile.py`) are DM-only. The play
  screen's Setting tab and the player-facing APIs leave them out, labels included. The organisers' Settings area shows
  them, marked.
- **nl translation.** Dutch tables say "setting", so the area is called "Settings" in nl too, alongside "Voorkeuren".
  The existing nl keys that say "Wereld" for a game setting are made consistent.
- **The Darlene picture is not committed**, because of its licence (backlog item 11). It is imported on this install as a
  delivery step, with the owner at the review.

## Hand checks for the owner after delivery

1. Settings in the sidebar, then Greyhawk. Search "Hardby", read the page, follow a link.
2. Add a page for a homebrew village, add a DM-only fact, and override a shipped page. Revert the override.
3. Look as a player seat. The play screen's Setting tab shows the lore and maps. No DM-only content shows there, in Ask,
   or in "Did you know", and that includes hidden map features.
4. In play, the DM proposes a fact. It shows in that campaign, and in no other campaign until it is accepted. Accept it,
   and a second campaign sees it.
5. Import greyhawk.jpg into Greyhawk (picture, 1 hex = 30 miles), review it, and accept it. A new Greyhawk campaign copies
   it. Then travel from Greyhawk to Hardby.
6. Preferences is where the old Settings were. Nothing else is still called "Settings" for options.

## Decided in the plan

The plan (`docs/superpowers/plans/2026-10-19-settings.md`, "Decisions taken in this plan") settled "What's left to the
builder" by recommendation, for the owner to confirm or overrule:

- **Tables:** four, in migration `0016_setting_content`: `setting_pages` (new pages and overrides alike; whether one is
  an override isn't stored, it is when the shipped setting has the title), `setting_facts`, `proposals` and
  `setting_maps`.
- **A DM-only section** is a fenced block, a line `::: dm`, the text, a line `:::`; a whole page or fact has its own
  `dm_only` flag. A DM-only override is the DM's version: seats keep reading the shipped page.
- **Overrides match by title,** whitespace collapsed and casefolded, after the shipped redirects, and are stored under
  the shipped page's title.
- **Search order:** this campaign's proposals, the install's additions, the shipped FTS hits (without the titles an
  addition replaced), then facts.
- **Lore facts per setting:** no reference change; the catalog entry names its fact categories (Greyhawk: `greyhawk`,
  `history`), and a setting leaves out the categories others claim. Rules, monster, spell, magic, class and planes
  facts stay general.
- **The DM's tools:** `propose_page(title, text, kind?, dm_only?, mode?)` (a new page, or an edit when the title
  exists; `append` by default, or `replace`) and `propose_fact(text, category?, dm_only?)`, both DM-only.
- **Merging:** one campaign's pending proposals of the same kind and title merge into one (an append joins, a new page
  or a replace replaces); facts never merge.
- **The pointers** (`setting_world_maps`) become setting-owned copies at start (`adopt_pointers`), not in the
  migration; what can't be copied is dropped. The table stays until a later clean-up (backlog).
- **Setting maps** are always Delve GeoJSON documents; the built-in `.map` stays the shipped setting's fallback.
- **The play screen's Setting tab** filters for every caller, the owner's seat too.
- **Wiki markup** is shown as Markdown (`wiki_markdown`); the DM's tools still get the raw text.
- **Table options:** the play screen's "Settings" label became "Table options" ("Tafelopties") and `…/play/settings`
  became `…/play/options`; the `play_settings` table keeps its name. Preferences' stored names (`settings`,
  `Storage.settings`, `delve.domain.settings.Settings`) keep theirs too: they aren't UI, API or glossary words.
- **The CLI** `delve setting import-map` is a thin client of the running Delve: it streams the picture to the same
  import route with the owner token, so the server's one-conversion-at-a-time rule holds.

The words are in `docs/glossary.md`, the stored values in `docs/data-dictionary.md`, and the rules for builders in
`GUILD.md`'s "Settings".
