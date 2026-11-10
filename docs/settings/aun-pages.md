# Aun: page format and the first core's pages

Each page is one file, `src/delve/setting/data/aun/pages/<slug>.md`, the slug being the title lower-cased with spaces
and punctuation as `-` ("Free City of Hask" → `free-city-of-hask.md`, "Isaine's Morning" → `isaines-morning.md`).

```
+++
title = "Pale Tower"
kind = "place"
aliases = ["The Pale Tower"]
categories = ["Hask", "Ruins"]

[fields]
type = "ruin"
realm = "Free City of Hask"
+++
Body in Markdown. `##` headings, short paragraphs, lists where they help.
Links: [[Exact Title]] or [[Exact Title|shown words]], to titles in the list below only.

::: dm
What only the DM knows: true causes, secrets, hooks. Several `::: dm` … `:::` blocks may appear.
:::
```

- The header is TOML between `+++` lines. `title` and `kind` are required; `aliases` (other names the page is found
  by, such as "The Pale Tower"), `categories` and `[fields]` are optional. Field values are short strings.
- A title has no leading "The"; give the "The …" form as an alias where people say it.
- `kind` is one of: `realm`, `place`, `deity`, `organization`, `character`, `people`, `item`, `holiday`, `history`,
  `lore`.
- Fields by kind (use those that apply, in this order):
  - realm: `ruler`, `capital`, `government`, `population`, `peoples`, `faiths`, `alignment`
  - place: `type`, `realm`, `population`, `ruler`
  - deity: `rank` (great or small), `titles`, `portfolio`, `alignment`, `symbol`, `worshippers`, `home` (a small god's
    place), `"holy day"` (quoted: a TOML key with a space)
  - organization: `type`, `leader`, `base`, `alignment`
  - character: `title`, `race`, `role`, `realm`, `alignment`
  - people: `lands`, `faiths`
  - item: `type`, `location`
  - holiday: `date`, `god`
  - history: `date`
- Length: most pages 200–500 words; realms 400–700; Hask 900–1300. Player-visible text first, the DM blocks last
  (one or two, with two or three concrete hooks).

## The pages

Writer groups in brackets: [A] world, [B] Hask, [C] west and north, [D] south and east, [E] gods and peoples.

**lore** [A]: Aun · Magic in the Reaches · Adventurers in the Reaches · Great Gods · Small Gods · Calendar of the
Reckoning

**history** [A]: Thaumarchy · Great Binding · Unmaking · Ash Centuries · Heirs' War · Bought Freedom ·
Seven Years' War

**holiday** [A]: Hollow Days · Isaine's Morning · Sun's Judgement · Harvest Home · Ferry Night

**item** [A]: Seven Lanterns · Ember Crown · Ferryman's Toe · Brass Servants

**realm**: Free City of Hask [B] · Kingdom of Calder [C] · Sunward Theocracy [C] · Margravate [C] · Northern Holds [C] ·
Horse Steppe [C] · Lantern Principalities [D] · Glass Waste [D] · Drowned Coast [D] · Greenmaw [D]

**place**:
- [B] Hask · Hask Ford · Tollside · Wetside · Stews · Lamp Quarter · Templegate · Tallow Lane · Drowned Toe ·
  Pale Tower · Undercroft
- [C] Aldmoor · Candor · Vaelholt · Skarnholm · Thousand Fires · Hornwall · Deephorn · Thornwold · Redmere
- [D] Corvanne · Tessarine · Amaranthe · Ishavel · Gullhaven · Zhaumal · Ambre

**deity**:
- [E] Aurel · Velis · Karsk · Marrah · Hollin · Sere · Fennick · Isaine · Vorm · Asheth · Oruun · Nhul ·
  Hill That Listens · Drowned Bell · Glass Saint · Grandmother Frost
- [B] Ferryman · Mother Gutter · Old Tallow · Lady of the Weir

**organization**:
- [B] Quiet Hand · Collegium of the Lamp · Ferrymen's Guild · Open Mouth
- [D] Sunward Church · Ember Court · Free Companies · Grey Legions · Glass-Pickers · Hold Moot

**character**:
- [B] Benedek Sallow · Widow · Ilse Varrow · Magdal Crane
- [C] Teodric Vael · Anselm IX · Bertil III · Ysmeine · Barrek Stonesong · Ulagh Khan · Sigrun Halfhand
- [D] Salt Annet · Old Mazzar · Serpent Oracle

**people** [E]: Humans of the Reaches · Elves · Dwarves · Halflings · Gnomes · Orcs

## Lore facts

Each writer also writes `src/delve/setting/data/aun/facts/<group letter>.toml`: 12–20 "Did you know" facts about their
pages, one or two sentences each, things a player would enjoy learning at the table:

```
[[fact]]
text = "Hask has no bridge: the Ferryman drowns anyone who tries to build one."
category = "places"
```

`category` is one of `history`, `gods`, `places`, `customs`, `people`; add `dm_only = true` for a secret.
