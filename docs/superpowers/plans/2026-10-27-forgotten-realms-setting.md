# The Forgotten Realms setting (DEL-38)

**Goal:** the setting `forgotten-realms` gets what Greyhawk has: the Realms wiki in the reference store with its kinds,
pages and search, lore facts of its own (the Moonsea first, for Ruins of Adventure), and the Calendar of Harptos. The
world map is left for later: the wiki's maps are WotC artwork, not data.

**Source:** the Fandom wiki dump `forgottenrealms_pages_current.xml.7z` (21 Oct 2026, CC-BY-SA), kept at
`~/claude/refactoring-assets/forgottenrealms_pages_current-2026-10-21.xml.7z`. 62,294 articles, 14,536 redirects.
Chosen with the owner on 2026-10-27 over scraping pages.

## Decisions

1. **A snapshot made by a Delve script, not ttrpg2.** `scripts/import_realms_wiki.py` reads the unpacked dump and
   writes `reference/snapshots/forgotten_realms.sql.gz` in the Greyhawk wiki's shape (`fr_pages`, `fr_categories`,
   `fr_redirects`, one typed table per kind) and its line in `SHA256SUMS`. `snapshot_reference.py` keeps that file, as
   it keeps `corrections.sql.gz`. The tests run the importer over a tiny dump, so the tiny reference has a Realms too.
2. **In-world pages only.** Pages whose first infobox is a book, magazine, game, comic, organized-play or real-world
   person are left out; so are references (`<ref>`) and the `== Appendix ==` section, which list sources. The rest
   is kept whole, infobox included (`wiki_markdown` drops templates). Redirects are kept when they lead to a kept page.
3. **Kinds and tables.** The infoboxes map onto Greyhawk's kinds; a Location is a settlement, a realm or a location by
   its type; Body of water, Mountain and Road are locations with a subtype. Spells and the other infoboxes stay out
   of the kinds (the pages are still searchable and readable).

   | kind | tables | infobox |
   |---|---|---|
   | place | settlements, locations | Location (by type), Body of water, Mountain, Road |
   | realm | realms | Location whose type is a kingdom, country, nation, empire… |
   | deity | deities | Deity |
   | character | characters | Person |
   | organization | organizations | Organization |
   | creature | creatures | Creature |
   | item | items | Item |
   | plane | planes | Plane |
   | building | buildings | Building |
4. **Field values are cleaned to text.** Links become their label, `{{Former}}` "formerly", other templates go,
   `<br />` becomes "; ". A field kept per edition (`alignment2e`, `alignment3e`…) takes the 2e value first, then 1e,
   3e, 5e, 4e: Delve plays AD&D 2e. Image and caption go in `extra`, as Greyhawk's do; reference fields are dropped.
5. **Lore facts are curated, as Greyhawk's are.** `reference/sources/forgotten-realms-lore-facts.txt`, one fact per
   line, written from the wiki's pages, each true as of 1340 DR (Ruins of Adventure) so none spoils a later event. The
   importer adds them to `lore_facts` with category `forgotten-realms`, which the catalog entry claims.
6. **One wiki setting class.** `WikiSetting` holds what Greyhawk's setting did over the reference; `GreyhawkSetting`
   and `RealmsSetting` give their id, title, kinds, calendar and maps. `NamedSetting` stays for settings with no
   materials.
7. **The Calendar of Harptos:** twelve months of 30 days and five festival days (Midwinter, Greengrass, Midsummer,
   Highharvestide, Feast of the Moon), 365 days, era DR. A one-day festival reads "Midsummer, 1340 DR". Shieldmeet,
   the leap day of every fourth year, is left out: `Calendar` has a fixed year (noted on DEL-38). A campaign starts on
   1 Mirtul 1340 DR, the year of Ruins of Adventure.
8. **`BUILD` goes to 3**, so an old `reference.db` is rebuilt with the `fr_` tables.

## Tasks

1. Calendar of Harptos and the one-day festival label (`delve.setting.calendar`, `delve.domain.world`), with tests.
2. The importer: infobox parsing, value cleaning, page selection, kinds, redirects, categories, lore facts, a
   deterministic gzip; tests over a tiny dump.
3. The reference store: `forgotten_realms.sql.gz` in the build and the snapshot script, `fr_pages_fts`, the prefix
   and kinds, `BUILD = 3`; the tiny reference gets the Realms; real counts.
4. `WikiSetting`, `RealmsSetting`, the catalog entry; tests.
5. The lore facts file; run the importer on the dump; commit the snapshot; `make ci`.
6. Check in the running app (setting area: kinds, Phlan, search, a lore fact), then DEL-38 to review.
