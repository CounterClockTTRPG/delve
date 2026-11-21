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
| Items | 428 (magic items and the armor table) | — | — |
| Magic item tables | 26 tables and the scrolls' spells by level (`data/magic_tables.json`, from the RTFs) | MagicItemsI–V.rtf | 1,780 of 1,925 rows name an entry |
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
- **The Mystic Theurge's class table** is a broken grid in the conversion, so the conversion gives the class no level
  table. `extract_rtf.py` reads its levels from PrestigeClasses.rtf's Table: The Mystic Theurge (DEL-389 part 4); its
  entry's text shows the same table, its cells joined again (below), and a test holds the two to each other.
- **The adept's, assassin's and blackguard's spell lists** are in their class text only, not in the spells' Level
  lines. `extract.py` adds them to the spells' `levels`. The assassin's "greater invisibility" is the spells'
  *invisibility, greater*, and the blackguard's "protection from elements" (3.0's name) 3.5's *protection from
  energy*. His *corrupt weapon* is described only in his class text, so it has no spell entry.
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
  - **What is kept as it is:** 48 records lack a proper size: the family records whose variants are rows of their own
    (the ten dragons, whose size field reads "Dragon", Air Elemental, Animated Object, Arrowhawk, Salamander), the
    templates (Ghost, Lich, Vampire, the lycanthropes) and the race entries (Elf, Drow, Duergar, Gnome).
  - **The dragons' challenge ratings** are on their family records, as text ("Wyrmling 3; very young 4; …"), not on
    each age. The dragons by age are made again from the RTFs' age tables (below, "Families by variant").
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
    order ("BEAR, BLACK" is had by "Black Bear"). The rows already there are kept, apart from what "Monsters'
    qualities" below completes.
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

- **Symbol-font characters:** a few RTF paragraphs write a character of the Symbol font as `\u-4064\'3f` (a code
  in the private area, then its fallback "?"). The reader keeps the character: the space of "skill points equal to
  9 x (2 + Int modifier)" and the "×" of the grimlock's "1d8+3/×3", which read "x?(2" and "/?3" before (DEL-389).
- **A label spaced from its colon** ("Hit Dice :", the lantern archon's block) is read as the others are.

### Monsters' qualities and race data (DEL-389)

After adding the missing monsters, `extract_rtf.py` completes every row that a stat block has (by the same words as
above) from its block's column (`srd35_extract/rtf.py`, `qualities`). The pack's data is made with the SRD Markdown
copy as its third argument (`extract_rtf.py RTF_DIR DATA_DIR SRD_DIR`), for the garbled lines below. The same input
gives the same bytes, and a second run changes nothing. 335 of the 592 rows changed; 257 are byte for byte as they
were, the orc’s among them.

- **Special qualities** (323 rows): the conversion lost the link text ("Damage reduction 10/magic, darkvision 60 ft.,
  freeze" was " freeze"). The RTF's line is taken when it says all the conversion's does and more, word for word
  (two words run together, "abilitiesscent", count as both).
- **A garbled RTF line** (it ends in "resistance to" or "immunity to", a clause starts with an energy's number
  outside a "resistance to" list, or a run of four words comes twice) is not taken. The SRD Markdown copy's line
  (`3.5 Compendium/Monsters/*.md`) is, when it completes the conversion's: the three tojanidas (the RTF's adult
  "immunity to acid and cold, electricity 10 and fire 10", juvenile "… resistance to", elder with its resistances
  twice) all read "immunity to acid and cold, resistance to electricity 10 and fire 10".
- **Level adjustments** (113 rows that had none): the block's Level Adjustment, or else the entry's "Level adjustment
  +N" trait (the drow, duergar and svirfneblin). 76 of them are the SRD's "—"; 37 are numbers or "(cohort)": the ogre
  +2, the troll +5, the drow +2, the harpy +3, the frost giant +4, the lycanthropes' forms +3 and the classed
  monsters' columns (the 4th-level ogre barbarian +2). The data keeps them all, as the SRD gives them.
- **Which are races:** a row with a plain "+N" is a character race (61, from 55), except, as the engine rules
  (`numbers._not_a_race`), a sample character with class levels ("4th-level Barbarian Ogre": its numbers include the
  class's; play the ogre), a lycanthrope's form ("Human Form Werewolf") and a row with no stat block of its own (the
  drow, duergar and svirfneblin, subraces given as text: not playable as races yet). Since part 3's dragons by age
  (below) there are 96: the 35 young dragons whose colour gives their age a level adjustment ("Wyrmling +4; very
  young +5; young +6; others —"), as the SRD gives it.
- **Race traits** (22 rows): the entry's "… AS CHARACTERS" section, its heading and paragraphs up to its last trait
  line ("—Favored Class: Barbarian.", "—Level adjustment +2."), added to the text where it had none: aasimar, bugbear,
  centaur, gargoyle, gnoll, goblin, hill giant, hobgoblin, hound archon, janni, kobold, lizardfolk, minotaur, ogre,
  ogre mage, pixie, rakshasa, satyr, stone giant, tiefling, troglodyte, troll. The favoured class is that section's.
  The engine reads a section by its heading in any case, with or without "as" ("Jann as Characters", "KOBOLD
  CHARACTERS").
- **Special Attacks and Space/Reach:** read, and taken only where a row's were blank; none was.
- **New keys**, read from the completed special qualities (only where the SRD gives them):

| Key | Rows | Read from |
|---|---|---|
| `dr` | 124 (204 with the dragons by age) | "Damage reduction 10/magic": `[{"value": 10, "bypass": ["magic"]}]`; "5/cold iron and good" needs both; "10/magic or silver" is `bypass_any`; "5/—" (the RTFs' "–") is `["—"]` |
| `sr` | 60 (140 with the dragons by age) | "spell resistance 27"; the drow's and svirfneblin's "Spell resistance equal to 11 + class levels" trait is `sr: 11` with `sr_plus_class_levels: true`, and a race section's "spell resistance equal to 13 + class levels" sets the flag on the stat block's same SR 13 (6 rows: azer, drow, hound archon, pixie, rakshasa, svirfneblin) |
| `regeneration` | 11 | "regeneration 5", with what deals normal damage from the entry's "Regeneration (Ex):" text as a list of alternatives, any one of which will do, each a list of what it needs all of: the troll's `[["fire"], ["acid"]]`, the pit fiend's `[["good", "silver"], ["good", "spell"]]` (a weapon both good and silver, or a good spell: a spell's alternative, "spells or effects with the good descriptor", has the word `spell` besides its descriptor, which no weapon has). Unlike `dr`'s `bypass`, which is one list, all needed |
| `fast_healing` | 28 | "fast healing 2" |
| `resist` | 53 | "resistance to acid 10 and cold 10": `{"acid": 10, "cold": 10}` |
| `immune` | 116 (236 with the dragons by age) | "immunity to fire and poison", "immunity to poison, charm, and compulsion": `["fire", "poison"]`; "… effects" dropped ("sleep and charm effects" is `["sleep", "charm"]`) |

**What the RTFs didn't give cleanly:**

- **The two lines disagree, so the conversion's is kept:** the bat swarm (the conversion "immune to weapon damage",
  the RTF "half damage from slashing and piercing"), the ettin skeleton (the RTF's line is broken: "darkvision 60
  ft." twice, "superior twoweapon" and no "undead traits").
- **Given only in the text, not as keys:** the destrachan, the grimlock and the yrthak ("immunities", listed in their
  text); the dark naga's "resistance to charm" (not an energy); "+2 turn resistance" (not a key).
- **Regeneration whose stopping is more than one word:** the horned devil and the pit fiend take normal damage from
  "good-aligned silvered weapons" and good spells: `[["good", "silver"], ["good", "spell"]]`; the solar from "epic
  evil-aligned weapons" and evil spells: `[["epic", "evil"], ["evil", "spell"]]`; the planetar `[["evil"], ["evil",
  "spell"]]`; the tarrasque
  `[]` (no attack deals it lethal damage).
- **No stat block of their own** (174 rows, kept as they were, keys from their own lines only): the dragons by age
  (130; since part 3's families, below, 120 of them full stat blocks) and the ten dragon family records and True
  Dragon, which the RTFs give as columns of one table; the family and
  template records (the four elementals, Animated Object, Hydra, Arrowhawk, Salamander, Tojanida, Xorn, the five
  lycanthropes, Celestial Creature, Fiendish Creature, Ghost, Half-celestial, Half-dragon, Half-fiend, Lich, Skeleton,
  Vampire); the subraces given as text (Aquatic, Gray, Wild and Wood Elf, Deep and Mountain Dwarf, Duergar, Drow,
  Forest Gnome, Svirfneblin, Half-Elf, Half-orcs, and the Elf and Gnome records); the werewolf lord's three forms and
  the conversion's "Hybrid Boar Form Hill Giant Dire Wearboar".
- **Sections headed otherwise:** seven race sections are headed "Aasimar as Characters", "Jann as Characters",
  "Pixies as Characters", "Tieflings as Characters", "HOBGOBLIN CHARACTERS", "KOBOLD CHARACTERS" and "TROGLODYTE
  CHARACTERS". They are in the text as the SRD heads them, and read.

### Families by variant (DEL-389 part 3)

Some entries give their stat block as a column per variant: by age, size, heads or grade. Each variant is a row of its
own, named as the SRD's tables name it, with the keys of any monster row; the family's parent row stays as the
reference entry (its text) and names its variants, smallest first (`variants`). Asked for by its bare name ("red
dragon", "fire elemental", "hydra"), a family is refused as a combatant, and the refusal names the variants; "dragon"
alone is the true dragon's general entry, refused naming the colours and the ages. A variant is found by its words in
any order ("red dragon, young", "earth elemental, huge").

- **The true dragons by age** (120 rows, `srd35_extract/families.py`): the ten colours' "… Dragons by Age" and "…
  Dragon Abilities by Age" tables in MonstersDr-Dw.rtf, a row per age, replace the conversion's rows of the same id
  (which had the bite at the base attack, "Bite +13" for "+19", and no CR, qualities or attacks for 18 of them).
  - **Names:** the age in title case before the colour: "Very Young Red Dragon", "Great Wyrm Gold Dragon" (the
    conversion's "Very young Red Dragon"); the ids are unchanged.
  - **From the tables:** size, Hit Dice and hit points, abilities, base attack/grapple, the saves, speed,
    initiative, AC with touch and flat-footed, caster level and spell resistance; from the colour's block lines, the
    CR, advancement and level adjustment of the age ("Wyrmling +4; very young +5; young +6; others —"), and the
    environment, organization, treasure and alignment.
  - **The attacks:** the general entry's Dragon Space/Reach, Attacks, and Damage table by size. The bite is at the
    table's Attack, with the Strength bonus; the claws and wings (half the bonus) and the tail slap (one and a half
    times) are secondary attacks, 5 lower, as its text says: the young red dragon's "Bite +19 melee (2d6+7) and 2 claws
    +14 melee (1d8+3) and 2 wings +14 melee (1d6+3) and tail slap +14 melee (1d8+10)". A Huge or larger dragon's crush
    and a Gargantuan or larger one's tail sweep are special attacks, at the breath weapon's DC.
  - **The breath weapon:** its shape from the colour's text ("a cone of fire"; a metallic dragon's two), its length
    from the Dragon Breath Weapons table by size, the damage and DC from the age's row: "breath weapon (40-ft. cone of
    fire, 6d10, DC 19)".
  - **Special abilities:** an age has its own and every younger age's (the text: "It gains the abilities indicated
    for its age plus all previous ones"), and the damage reduction of its own or the last age that gave one. Those the
    colour's text names as spell-like ("Spell-Like Abilities: …", "Corrupt Water (Sp)") are special attacks; the rest
    special qualities. Every dragon has blindsense 60 ft., keen senses (darkvision 120 ft., low-light vision) and
    immunity to sleep and paralysis besides its colour's (the general entry). The keys (`dr`, `sr`, `immune`) are read
    from the qualities as any row's are.
  - **Two cells run together** in the RTFs, and are read apart: the very old brass dragon's "flat-footed 35 DR" /
    "15/magic", and a Special Abilities cell missing or run into the caster level (the juvenile green's and young
    gold's "1st", the ancient gold's "Sunburst 15th").
  - **Not in the tables, so empty:** skills, feats, languages and senses, and the text (the colour's parent row has
    it). Pyrohydras and cryohydras are text in the hydra's entry, not columns: no rows of their own.
- **The other families** were rows already, one per column (Task 1's blocks): the four elementals (Small to Elder),
  Animated Object (Tiny to Colossal), Hydra (five to twelve heads), Arrowhawk, Salamander and Tojanida (juvenile or
  flamebrother to elder or noble) and Xorn (minor to elder). Their parent rows name them.

### Rows with no attacks of their own

The rows with no `full_attack`, each with its reason (a test holds the data to this list):

- **Black Dragon:** a family: its variants are the twelve ages, Wyrmling Black Dragon to Great Wyrm Black Dragon.
- **Blue Dragon:** a family: its variants are the twelve ages, Wyrmling Blue Dragon to Great Wyrm Blue Dragon.
- **Brass Dragon:** a family: its variants are the twelve ages, Wyrmling Brass Dragon to Great Wyrm Brass Dragon.
- **Bronze Dragon:** a family: its variants are the twelve ages, Wyrmling Bronze Dragon to Great Wyrm Bronze Dragon.
- **Copper Dragon:** a family: its variants are the twelve ages, Wyrmling Copper Dragon to Great Wyrm Copper Dragon.
- **Gold Dragon:** a family: its variants are the twelve ages, Wyrmling Gold Dragon to Great Wyrm Gold Dragon.
- **Green Dragon:** a family: its variants are the twelve ages, Wyrmling Green Dragon to Great Wyrm Green Dragon.
- **Red Dragon:** a family: its variants are the twelve ages, Wyrmling Red Dragon to Great Wyrm Red Dragon.
- **Silver Dragon:** a family: its variants are the twelve ages, Wyrmling Silver Dragon to Great Wyrm Silver Dragon.
- **White Dragon:** a family: its variants are the twelve ages, Wyrmling White Dragon to Great Wyrm White Dragon.
- **True Dragon:** a family (a general entry): its variants are the ten colours, each by age.
- **Air Elemental:** a family: its variants are Small Air Elemental to Elder Air Elemental.
- **Earth Elemental:** a family: its variants are Small Earth Elemental to Elder Earth Elemental.
- **Fire Elemental:** a family: its variants are Small Fire Elemental to Elder Fire Elemental.
- **Water Elemental:** a family: its variants are Small Water Elemental to Elder Water Elemental.
- **Animated Object:** a family: its variants are Tiny Animated Object to Colossal Animated Object.
- **Hydra:** a family: its variants are Five-headed Hydra to Twelve-headed Hydra.
- **Arrowhawk:** a family: its variants are Juvenile, Adult and Elder Arrowhawk.
- **Salamander:** a family: its variants are Flamebrother, Average and Noble Salamander.
- **Tojanida:** a family: its variants are Juvenile, Adult and Elder Tojanida.
- **Xorn:** a family: its variants are Minor, Average and Elder Xorn.
- **Celestial Creature:** a template (or a general entry): no stat block of its own.
- **Fiendish Creature:** a template (or a general entry): no stat block of its own.
- **Ghost:** a template (or a general entry): no stat block of its own.
- **Half-celestial:** a template (or a general entry): no stat block of its own.
- **Half-dragon:** a template (or a general entry): no stat block of its own.
- **Half-fiend:** a template (or a general entry): no stat block of its own.
- **Lich:** a template (or a general entry): no stat block of its own.
- **Skeleton:** a template (or a general entry): no stat block of its own.
- **Vampire:** a template (or a general entry): no stat block of its own.
- **Werebear:** a template (or a general entry): no stat block of its own; its sample's forms are rows ("Human Form Werebear").
- **Wereboar:** a template (or a general entry): no stat block of its own; its sample's forms are rows ("Human Form Wereboar").
- **Wererat:** a template (or a general entry): no stat block of its own; its sample's forms are rows ("Human Form Wererat").
- **Weretiger:** a template (or a general entry): no stat block of its own; its sample's forms are rows ("Human Form Weretiger").
- **Werewolf:** a template (or a general entry): no stat block of its own; its sample's forms are rows ("Human Form Werewolf").
- **Elf:** a subrace (or race entry): no stat block of its own.
- **Aquatic Elf:** a subrace (or race entry): no stat block of its own.
- **Gray Elf:** a subrace (or race entry): no stat block of its own.
- **Wild Elf:** a subrace (or race entry): no stat block of its own.
- **Wood Elf:** a subrace (or race entry): no stat block of its own.
- **Gnome:** a subrace (or race entry): no stat block of its own.
- **Forest Gnome:** a subrace (or race entry): no stat block of its own.
- **Mountain Dwarf:** a subrace (or race entry): no stat block of its own.
- **Deep Dwarf:** a subrace (or race entry): no stat block of its own.
- **Duergar:** a subrace (or race entry): no stat block of its own.
- **Drow:** a subrace (or race entry): no stat block of its own.
- **Svirfneblin:** a subrace (or race entry): no stat block of its own.
- **Half-Elf:** a subrace (or race entry): no stat block of its own.
- **Half-orcs:** a subrace (or race entry): no stat block of its own.

In a fight (`setup_combat`), a family is refused, naming its variants. A template or race entry joins with no attack
(as Phase 2 had it, for the DM to give its numbers with update_combatant): its swing is refused until then, naming the
monsters built on it that have a stat block ("Human Form Werebear", "1st-level Warrior Drow").

### Monsters with no attack

Every other row's full attack reads as attack forms (a test holds every row to it). These rows' attack is "—" in the
SRD: they fight with no attack form, and a swing of theirs is refused, until the DM gives them one.

- **Bat:** its Attack and Full Attack are "—".
- **Formian Queen:** its Attack and Full Attack are "—".
- **Shrieker:** its Attack and Full Attack are "—".
- **Toad:** its Attack and Full Attack are "—".

**How the lines read:** one line, the pixie's "longbow +5 ranged (1d6–2)/x3", prints its critical after the
parentheses; the reader takes a critical there as one inside them. No line is left unread.

**Challenge ratings with a variant:** four rows give a second CR in parentheses or after "or": the stone giant's
"8 (elder 9)", the djinni's "5 (noble 8)", the pixie's "4 (5 with irresistible dance)" and the satyr's "2 (without
pipes) or 4 (with pipes)". The first number is the stat block's own CR, and the XP award is read from it.

### Size in combat

- **A character's size** (its race's: Small for a halfling, Large for a centaur, an ogre or a minotaur) is its size
  modifier on attack rolls as on AC (the SRD's Table: Size Modifiers: Fine +8, Diminutive +4, Tiny +2, Small +1,
  Medium 0, Large −1, Huge −2, Gargantuan −4, Colossal −8). A monster's own attack line has its size in it already,
  so it is never added to a monster's line, a companion's or a wild-shaped druid's form.
- **A weapon's size** is the wielder's (a centaur's longbow is a Large one), or the one its name gives ("large
  longsword"). Its damage: Small and Medium from the weapons table, Tiny and Large from Equipment's Table: Tiny and
  Large Weapon Damage, Huge and up the Large damage raised a step for each size by Improving Monsters' Table:
  Increased Damage By Size ("Repeat the adjustment if the creature moves up more than one size category"). Where that
  table stops (it has no row for 3d6, 1d12's Large damage), the damage stays and the engine says so. The SRD gives no
  weapon damage below Tiny: a Diminutive or Fine weapon deals the Tiny damage, said.
- **A weapon of the wrong size** (Equipment's Inappropriately Sized Weapons): −2 on attack rolls for each size of
  difference, and its effort a step for each (light, one-handed, two-handed); one beyond two-handed or below light
  can't be wielded, which the engine says.
- **The tables are in the engine** (`engine/attack_line.py`: `TINY`, `LARGE`, `STEP_UP`), typed from those two
  tables of the SRD Markdown copy, as the size modifiers are in `engine/numbers.py`.

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

## Class features

`data/features.json` (DEL-389): the 16 base and NPC classes' and the 15 prestige classes' features as rows the engine
reads, made by `scripts/extract_features.py` from `data/classes.json` (with `skills.json` and `feats.json` to check the
requirements' ids), the same bytes on every run.

- **Extracted:** each entry of a class table's "Special" column, with its value at each level the table gives it.
- **Hand-written:** structured rows, no prose, in `scripts/srd35_extract/features_hand.json`, read from the class text:
  proficiencies, casting, the monk's AC bonus, speed and unarmed damage, wild shape, favored enemy, turning, and the
  kinds, conditions and abilities laid over extracted rows.
- **Prestige classes (part 4):** a `requirement` row per entry of the "Requirements" section, read by pattern (a BAB,
  skill ranks, a feat, "Any nonlawful", "Able to cast 3rd-level arcane spells", a sneak attack) or hand-written (a race,
  a choice among feats or skills, a spell). The engine can't check some ("must kill someone for no other reason than
  to join the assassins", "speaks Draconic"): they are `{"special": …}`, which the DM confirms. A "+1 level of
  existing … class" column or entry is a `casting` row of the levels it comes at (the archmage's 3rd level reads
  "+1level" in the conversion), and the dragon disciple's Bonus Spells column a running count.
- **The check:** a test names every "Special" entry's row and every requirement's, and matches the monk's and the
  dwarven defender's hand-written rows to the columns of their tables in the class text.

## Magic items' numbers

`data/item_effects.json` (DEL-389 part 3): the numbers the engine applies for an `items.json` id, made by
`scripts/extract_item_effects.py` from `data/items.json`, the same bytes on every run.

- **Hand-written:** the eleven worn items' bonus type and what it adds to (ring of protection: deflection to AC;
  amulet of natural armor; cloak of resistance; bracers of armor; the seven ability items), in
  `scripts/srd35_extract/item_effects_hand.json`, and the SRD's limits on a magic weapon or armour ("enhancement
  bonuses ranging from +1 to +5", "an effective bonus ... higher than +10", Magic Items II).
- **Extracted from the item's text:** each worn item's bonuses ("+1 to +5", the price's "(+2)", "(+4)", "(+6)", or
  "a +2 enhancement bonus"), checked against the hand's type by its words ("deflection bonus", "natural armor"); the
  armour and shields of the armour table, by their entries without text; each weapon and armour special ability (a
  price of "+N bonus" or "+N gp") with its bonus equivalent, and for the weapon abilities the energy on a hit
  (flaming, frost, shock), the burst on a critical hit by the multiplier, the alignment it gives (holy, unholy,
  axiomatic, anarchic), the dice against an alignment, and keen's doubled threat range.
- **In the engine, not the table:** the special materials (`rules/18-01-special-weapons-materials.md`): alchemical
  silver's -1 damage, adamantine and mithral as masterwork, mithral armour's +2 maximum Dex, armour check penalty 3
  better, 10% less spell failure and a lighter category, adamantine armour's DR 1/—, 2/— or 3/—; and magic armour's
  masterwork check penalty ("All magic armor is masterwork armor (with an armor check penalty 1 less than normal)").
- **One name, two items:** the SRD names a weapon's ghost touch (+1) and an armour's (+3) alike, and a weapon ability
  and a ring both "Spell Storing", a weapon ability and a staff "Frost". `items.json` keeps both, the later of another
  type as `<id>-<type>` (`ghost-touch-weapon`, `spell-storing-ring`, `frost-staff`), and a weapon's ghost touch is
  read as its own.
- **Not yet:** carrying capacity still reads the unenhanced Strength (a belt of giant strength doesn't raise the
  load): core weighs the load from the sheet's score, and a hook for the engine's score is a core change, filed for
  later.

## Skill synergies

`data/synergies.json` (DEL-456): the SRD's skill synergies, made by `scripts/extract_synergies.py` from
`data/skills.json`, the same bytes on every run.

- **Extracted:** each sentence of a skill's "Synergy" section ("If you have 5 or more ranks in Tumble, you get a +2
  bonus on Balance and Jump checks"), a row per skill on each side, kept once though most are in both skills'
  sections, with the words after "checks" as its condition ("when escaping from rope bonds") where it has one. 29
  rows; the targets that are no skill are the turning check, bardic knowledge and wild empathy.
- **In the engine:** an unconditional row on a skill is added to its total (`numbers.derived`, an untrained check's
  too); the others are listed in `derived["skill_notes"]` by the skill or check they are on, for the DM; the turning
  check's is added by Turn Undead (`magic.turn_undead`). Jump's speed modifier ("-6 penalty for every 10 feet of
  speed less than 30 feet", "+4 bonus for every 10 feet beyond 30 feet") is the Jump skill's text, from the speed the
  engine derives (race, fast movement, armour); Toughness's "+3 hit points" is read from the feat's benefit.

## Treasure by encounter level

`src/delve_srd35/treasure.py` (DEL-389 part 3), the ruleset's `treasure` for core's `generate_treasure` and
`award_treasure`.

- **The level travels in the treasure line:** "EL 5, double standard", "EL 3, half standard", "EL 7, none", or a
  monster's own line ("EL 4, no coins; 50% goods; 50% items"). Without "EL n", the level is the CR of the monster the
  source names ("Ogre", "goblins"), and the result's first rolled entry says so: "EL 3 (Ogre's CR 3)". A CR below 1
  is the 1st level, given in the line too: "CR 1/2, standard" is "EL 1 (CR 1/2)".
- **A rolled item's special abilities** are rerolled when one repeats, is incompatible with one already rolled (holy
  and unholy, axiomatic and anarchic, a burst and the energy it functions as) or puts the item over +10 (Table: Melee
  Weapon Special Abilities' footnote). `set_build(items=…)` reads every weapon, armour, shield, ring, rod, staff and
  wondrous item as the treasure names it ("+1 longsword (flaming; keen)", "+2 composite longbow (+2 Str bonus)",
  "Feather token, tree"); the specific armours without an entry as the SRD describes them (a mithral shirt is a
  mithral chain shirt); potions, scrolls and wands as notes that belong in the inventory.
- **The ratings** (SRD, Treasure in Types, Subtypes, and Special Abilities): "standard" one d% per column, "double"
  to "quadruple" two to four, "1/10 coins" the coins divided, "50% goods" a d% chance before the roll. The SRD has no
  "half standard": it is read as "1/2 coins; 50% goods; 50% items". Parenthetical notes ("nonflammables only") are
  shown with the column and left to the DM; the things an entry names ("plus +1 vorpal greatsword") come with the
  hoard, as named.
- **Coins, goods and items:** read at run time from the pack's own `rules/20-01-monsters-with-treasure.md` (Table:
  Treasure, Gems, Art Objects and Mundane Items). The conversion closes up a column's empty cells, so a band sits in
  the column whose next band starts where it does: the 6th, 10th, 11th and 12th levels' last Items band is printed
  under Goods, and the 13th to 16th levels' under Coins. Mundane Items' subtables are printed in line under their row;
  a band starting again at 01 opens one. Above 20th level: the 20th-level row, plus the table's major items.
- **No XP for the gold:** 3.5 gives none, and a campaign's XP awards (DEL-113) don't include gold unless its owner
  turns that on.

### The random magic item tables

`data/magic_tables.json`, made by `scripts/extract_rtf.py` (`srd35_extract/magic.py`) from MagicItemsI–V.rtf, the
same bytes on every run: Table: Random Magic Item Generation and 25 tables of the kinds (armor and shields, their
types, special abilities and specific items; weapons, their type tables, special abilities and specific weapons;
potions and oils, rings, rods, scroll types and spell levels, the arcane and divine spell scrolls by level (0–9),
staffs, wands, and the minor, medium and major wondrous items, 100 rows each), by grade where the table has Minor,
Medium and Major columns. 1,780 of the 1,925 rows (a row per grade) name an `items.json`, `spells.json` or `weapons.json` entry: by the name as it
is, with a leading "greater" or "lesser" after the rest (the spells' "Magic Fang, Greater"), without a parenthesis
("Fireball (8th)", "Shuriken (5)") or a trailing qualifier ("Charm person, heightened"), in the singular ("Ioun
Stones"), or the longest name the words begin with ("Bag of holding type III" is the Bag of Holding).

- **The SRD's own overlaps,** kept as printed (the first row wins): Table: Rings' medium 47–51 (animal friendship)
  and 50–56 (minor energy resistance); Table: Scroll Spell Levels' major 86–95 (8th) and 95–100 (9th).
- **Names naming no entry** (32; the roll gives the table's words): `items.json` has no Mithral Shirt, Elven Chain,
  Dragonhide Plate, Dwarven Plate, Adamantine Breastplate, darkwood buckler or shield, mithral heavy shield,
  adamantine battleaxe or dagger, masterwork silver dagger or cold iron longsword (the nonmagical specific items), no
  ring of wizardry (I–IV); the table's "Manual of quickness in
  action" is the entry's "Manual of Quickness of Action"; `weapons.json` has no ammunition (arrows, bolts, bullets),
  net or repeating crossbow (it has the light and heavy); and the potions and scrolls of a choice of alignment
  ("protection from (alignment)", "magic circle against chaos/evil/good/law") name no one spell.
- **Not rolled:** an item's special qualities (intelligent, its markings), cursed items, special materials and the
  light a weapon sheds. A "special ability and roll again" followed by a specific item rolls again; a duplicate or an
  ability its weapon can't have (keen or vorpal on a bludgeoning weapon, disruption on another) is rolled again.
