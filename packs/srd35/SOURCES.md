# SRD 3.5: where the data comes from

## Source

- **The data:** the System Reference Document 3.5 (2000–2003), Open Game Content under the Open Game License 1.0a
  (`NOTICE.md` has its copyright notice).
- **The text used:** a Markdown conversion of it, DnD-3.5-SRD-Markdown by Obsidian-TTRPG-Community,
  <https://github.com/Obsidian-TTRPG-Community/DnD-3.5-SRD-Markdown>, at commit `70a6b26`.
  - The conversion calls itself "in progress".
  - It is kept outside this repository.
- **How it got here:** `scripts/extract.py` makes `src/delve_srd35/data/*.json` and `src/delve_srd35/rules/*.md` from
  the conversion, by script.
  - The same source gives the same bytes on every run.
  - No text was typed or rewritten.
  - Psionics, epic and divine material are left out.
- **The second source:** the SRD's original RTF release fills in what the conversion lost (see "Second source: the
  RTFs" below).
- **The check:** `scripts/check_rtf.py` compares the data with the SRD's original RTF release.
  - These are the 86 files of <https://archive.org/details/dnd35srd>, kept outside the repository and never shipped.
  - The check was run on 2026-11-16.

## Counts

| Kind | In the pack | In the RTFs | Matched by name |
|---|---|---|---|
| Spells | 605 | 605 | all 605 |
| Feats | 110 | 110 | all 110 |
| Skills | 36 | 36 | all 36 |
| Classes | 31 (11 base, 5 NPC, 15 prestige) | — | — |
| Races | 7 | — | — |
| Monsters | 592 (507 from the conversion, 85 from the RTFs) | 451 stat blocks read | about 326 |
| Items | 425 (magic items and the armor table) | — | — |
| Weapons | 72 (from the RTFs) | 72 rows with damage | all 72 |
| Rules | 116 sections | — | — |
| Carrying capacity | Strength 1–29, Tremendous Strength's ×4, the bipeds' size multipliers and the reduced speeds for base speeds 20–100 ft. (`data/carrying.json`, from the Carrying Capacity section) | — | — |

**The monster gap is mostly naming.** The RTFs head some entries one way and the conversion another ("BEAR, BLACK"
and "Black Bear"). The RTFs also give the dragons by age as columns of one table, which the report's parser doesn't
split. And they have the template text ("A ghost uses all the base creature's statistics…"), which isn't a monster.

**Spot-checks (seed 3835):**
- **Spells:** 20 compared on range, duration, saving throw and spell resistance. 19 are the same; for *scrying* the
  report's RTF parser missed the fields.
- **Monsters:** 20 compared on hit dice. All 11 found by name are the same; the 9 others are named differently in the
  RTFs.
  - The centipede swarm reads "9d8–9" in the pack and "9d89" in the report: the RTF's minus sign is a control word the
    report doesn't read, so the pack is right.

## Differences and how each was settled

- **The weapons and the goods and services tables** are grid tables whose cells the conversion broke into fragments
  ("W", "eight", "fi", "gures"). The weapons come from the RTFs instead (below); the goods and services are left out,
  so the pack has no mundane goods yet. The armor and shields table converted cleanly and is in.
- **The Mystic Theurge's class table** is a broken grid in the conversion, so the class has no level table in its
  data. Its entry's text shows the table, its cells joined again (below).
- **The text's layout (DEL-394):** the conversion is pandoc's Markdown, with tables in five forms (simple, multiline
  and grid tables, HTML tables and pipe tables) and lists whose items run over several paragraphs. The extraction
  (`scripts/srd35_extract/markdown.py`) gives every entry's text, and the rules, one layout:
  - each table a pipe table, its caption and any title row in bold above it and its footnotes as paragraphs under
    it; a header over two rows is one row, a group's label ("Spells per Day") on the first column it covers;
  - the conversion's styling dropped (`[]{style="…"}`, `<div>`, `::: {style=…}`), and its superscripts as ¹ ²;
  - a word a grid table broke over lines ("spe" / "llcasting", "Weig" / "ht") joined again when the whole is a word
    of the section's prose, or the start of one;
  - paragraphs and list items on one line each;
  - the words themselves unchanged.
- **Monsters:**
  - **Size and type:** some records have these shifted. Two certain repairs are made:
    - a type split in two is joined ("Magical" + "Beast" is "Magical Beast"; "Monstrous Humanoid" likewise);
    - a size found in the type field is moved back (the basilisk, the ogre);
    - a monster given as a classed character drops its name and level from before its size ("Goblin", "1st-Level",
      "Warrior", "Small", "Humanoid" is a Small Humanoid; the aasimar, the kobold, the 4th-level ogre barbarian).
  - **What is kept as it is:** 66 records still lack a proper size, mostly the dragons by age (size "M"), the family
    records (Black Dragon, Air Elemental) and the templates.
  - **The dragons' challenge ratings** are on their family records, as text ("Wyrmling 3; very young 4; …"), not on
    each age.
- **A monster given twice:** the frost giant is in the conversion twice. The second record holds only the rest of its
  description, so the two are merged.
- **A spell's fields:** some spells print only the fields that differ from the spell they are based on (*charm
  monster*: "functions like *charm person*…"). Their other fields are empty, as in the SRD.
- **Ability scores:** the conversion's table of ability modifiers and bonus spells is mangled by HTML styling.
  - The pack computes both by the SRD's own rule:
    - the modifier is half of (score − 10), rounded down;
    - a modifier of at least a spell level gives 1 + (modifier − level) ÷ 4 bonus spells of that level.
  - A test checks the rule against every row of the table that came through clean.
- **The feat format example** ("Feat Name") is not a feat, and is left out.

## Second source: the RTFs

`scripts/extract_rtf.py` reads the 86 RTFs (the same release the check reads) and adds two things to the data. Run it
after `extract.py`, which rewrites `monsters.json` without them. The same RTFs give the same bytes on every run.

- **Weapons** (`data/weapons.json`, 72): Equipment.rtf's Table: Weapons.
  - **Category and kind:** the table's headings give them (simple, martial or exotic; unarmed, light, one-handed,
    two-handed or ranged).
  - **Critical:** "19–20/x2" is a threat of 19 and a multiplier of 2; "x3" alone is a threat of 20. A double weapon's
    "x3/x4" (the gnome hooked hammer) gives its first head's, x3.
  - **Left out:** the ammunition rows, which have no damage, and the net, whose row has no damage or critical.
  - **Footnote marks** (the reach and double weapon notes) are dropped from the names and damage ("Longspear", not
    "Longspear4"). A "—" cell is empty.
- **Monsters** (85 added to `data/monsters.json`): the Monsters*.rtf stat blocks of challenge rating 5 or less that the
  conversion lacks, mostly the animals and vermin, the orc, the wolf and the rust monster.
  - **What counts as had:** a monster's name, or its column's title, with the same words as a name already there, in any
    order ("BEAR, BLACK" is had by "Black Bear"). The rows already there are kept byte for byte.
  - **Names:** all-capital titles in title case, and "X, Y" turned to "Y X" as the conversion names its monsters
    ("Riding Dog", "Small Monstrous Spider"). A race's block of one 1st-level warrior is the race ("Orc").
  - **Fields:** the same as the conversion's rows, as the RTF prints them ("Fort +3, Ref +0, Will –2"), plus `touch`,
    the touch AC. The RTFs give no languages or senses lines, and the animals no alignment or treasure; those are
    empty. A bonus feat's superscript B is written "Track (B)", as the conversion writes it.
  - **Text:** what follows a block up to the next one; blocks printed one after another (the monstrous spiders by size)
    share the text after the last. A family's later sections (the orc's "Half-Orcs") come with it.
  - **Left out:** the psionic, epic and divine files; template text ("A ghost uses all the base creature's
    statistics…"); blocks laid out otherwise.
- **The dash rule:** the RTFs write the en and em dashes as the control words `\endash` and `\emdash`, and the quotes
  as `\lquote`, `\rquote`, `\ldblquote` and `\rdblquote`. The reader (`srd35_extract/rtf.py`) keeps them as "–",
  "—" and the curly quotes, so "18\endash 20" is "18–20" and "Will \endash 2" is "Will –2". (The check's own reader
  drops them, which is why it reads "9d89" for "9d8–9".) The rows from the RTFs therefore write a minus or a range
  with "–" where the conversion's rows write "-".

## Left out

- **SRD sections:** psionics, epic and divine.
- **Product Identity:** none of the names the SRD's legal text designates Product Identity is shipped, and
  `tests/test_no_product_identity.py` holds the pack to that.
  - The conversion gives the chaos beast's environment as the name of a Product Identity plane. The pack says "A
    chaotic neutral-aligned plane" instead (`kinds.PRODUCT_IDENTITY_SWAPS`).
  - A *sigil* (a magic symbol) and the spell *sepia snake sigil* are open content. The city of that name isn't in
    the data.
- **Other books:** nothing that isn't in the SRD.

## XP

The SRD has neither table: no XP needed per level, and no award per monster by challenge rating. The pack ships
`data/xp.json` (Phase 2: the two tables chosen below, exactly as listed, with `levels` and `by_cr`). The search on 2026-11-16 found:

| Candidate | What it has | Open Game Content? | Section 15 line |
|---|---|---|---|
| The SRD 3.5's original RTFs (archive.org `dnd35srd`) | Neither table, in the core or the epic files (epic level basics give the attack and save bonuses, not XP) | Yes, but nothing to use | (already in `NOTICE.md`) |
| *Unearthed Arcana* (2004), "Level-Independent XP Awards", Table 6-14 | XP by challenge rating, the same for any party level and divided among the party: CR 1 is 300 XP, CR 12 is 19,000, CR 20 is 310,000, and beyond CR 20 the award doubles every 2 CR | Reported to be, with the book's rules declared open: mirrored as SRD-style pages by d20srd.org (`/srd/variant/campaigns/levelIndependentXPAwards.htm`) and dandwiki; the publisher's own release was not found, so the designation is unverified | Unverified, so not written |
| d20 Modern SRD | A level-dependent benefits table, but no confirmed XP column | Not confirmed for an XP table | — |
| Pathfinder 1e (Paizo, OGL) | XP tables by CR and three level tracks | Yes, but they are Pathfinder's numbers, not 3.5's | — |

**What was chosen** (owner, 2026-11-17): Unearthed Arcana's level-independent XP, both of its tables, for Phase 2.

- **The pair:** Table 6-13 (XP needed per level) and Table 6-14 (XP per monster by CR) go together. Its levels match
  the standard ones up to 5th, then rise faster: 16,000 for 6th, 76,000 for 10th, 2,600,000 for 20th. Under the
  standard levels the flat awards would be far too large past about 6th level, so the standard levels are not used.
- **The values,** read on 2026-11-17 from d20srd.org's page (archived copy; the live site sits behind a browser check):
  - XP per level, 1st to 20th: 0, 1,000, 3,000, 6,000, 10,000, 16,000, 24,000, 36,000, 52,000, 76,000, 110,000,
    160,000, 220,000, 320,000, 440,000, 640,000, 890,000, 1,300,000, 1,800,000, 2,600,000. Beyond 20th, a level costs
    twice the step two levels before it.
  - XP per monster, CR 1 to 20: 300, 600, 900, 1,200, 1,800, 2,400, 3,600, 4,800, 7,200, 9,600, 14,000, 19,000, 29,000,
    38,000, 58,000, 77,000, 120,000, 150,000, 230,000, 310,000. Beyond CR 20, twice the award of CR − 2. The award is
    divided among those who took part, whatever their levels. A CR between two rows may get an award between them.
- **Why this one:** d20srd.org's "Changes from the Official d20 SRD" page names its Variant Rules section as open
  content from *Unearthed Arcana*, a clearer claim than any other candidate has. The pack cites *Unearthed Arcana*
  in the Section 15 of `NOTICE.md` and in `notice.md`, now that the data ships.
- **Not used:** d20srd.org's "Experience Points" page (`/srd/xp.htm`). It gives the standard levels (0 to 190,000),
  but none of the 86 RTFs holds that table, and it isn't one of the three tables the site says it added. Its columns
  match the books' Table 3-2 and their wealth by level, so it is taken to be book data. Its Open Game Content line is
  the footer every page of the site carries.
- **Later:** the books' own tables (XP by CR and party level) can come with the private books pack (Phase 6).
