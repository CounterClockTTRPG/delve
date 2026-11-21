import { render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import type { Character } from "../api";
import { I18nProvider } from "../i18n";
import CharacterSheet from "./CharacterSheet";

// An SRD 3.5 character as `character_json` sends it: the stored build and its derived numbers in `sheet.d20`, and the
// engine's `sheet_numbers` beside the sheet in `d20`.
const thorin: Character = {
  id: "chr_0000000035a1",
  campaign_id: "cmp_0000000035a1",
  name: "Thorin",
  kind: "pc",
  order: 0,
  created_at: "2026-11-17T12:00:00Z",
  sheet: {
    kind: "pc",
    label: "Thorin",
    race: "dwarf",
    gender: "male",
    cls: "Fighter",
    levels: { fighter: 3 },
    hp_max: 28,
    ac: 17,
    thac0: 20,
    saves: {},
    ability_scores: { str: 16, dex: 12, con: 14, int: 10, wis: 12, cha: 8 },
    attacks: [
      { name: "warhammer", speed: null, attacks: "1", thac0: null, damage_sm: "1d8+3", damage_l: "1d8+3", range: null },
    ],
    weapon: "warhammer",
    movement_rate: 20,
    alignment: "LG",
    spell_slots: {},
    d20: {
      skills: { climb: 4, intimidate: 2, jump: 2 },
      feats: [{ id: "power-attack" }, { id: "cleave" }, { id: "weapon-focus", choice: "warhammer" }],
      domains: [],
      weapon: "warhammer",
      armor: "scale mail",
      shield: "shield, heavy steel",
      derived: {
        bab: 3, fort: 5, ref: 2, will: 1, ac: 17, touch: 10, flat_footed: 17, init: 1,
        acp: -4, max_dex: 3, spell_failure: 0,
        skills: { climb: 6, intimidate: 3, jump: 4 },
        slots: {}, dc: {}, sneak: "", turning_per_day: 0,
        warnings: ["Unknown armour 'mithral scale'."],
      },
    },
  },
  state: { hp: 28, xp: 3000, conditions: [], effects: [] },
  encumbrance: null,
  d20: {
    bab: 3, fort: 5, ref: 2, will: 1, ac: 17, touch: 10, flat_footed: 17, init: 1,
    skills: { jump: 4, climb: 6, intimidate: 3 },
    feats: [{ id: "power-attack" }, { id: "cleave" }, { id: "weapon-focus", choice: "warhammer" }],
    domains: [],
    slots: {},
    dc: {},
  },
};

const mira: Character = {
  ...thorin,
  id: "chr_0000000035a2",
  name: "Mira",
  sheet: {
    ...thorin.sheet,
    label: "Mira",
    race: "human",
    gender: "female",
    cls: "Cleric",
    levels: { cleric: 1 },
    spell_slots: { "0": 3, "1": 2 },
    d20: {
      skills: { concentration: 4 },
      feats: [{ id: "extra-turning" }],
      domains: ["war", "good"],
      derived: {
        bab: 0, fort: 2, ref: 0, will: 5, ac: 16, touch: 10, flat_footed: 16, init: 0,
        skills: { concentration: 6 },
        slots: { "0": 3, "1": 2 }, dc: { "0": 13, "1": 14 }, sneak: "", turning_per_day: 7,
      },
    },
  },
  d20: {
    bab: 0, fort: 2, ref: 0, will: 5, ac: 16, touch: 10, flat_footed: 16, init: 0,
    skills: { concentration: 6 },
    feats: [{ id: "extra-turning" }],
    domains: ["war", "good"],
    slots: { "0": 3, "1": 2 },
    dc: { "0": 13, "1": 14 },
  },
};

function renderSheet(character: Character, { language = "en", organiser = false } = {}) {
  render(
    <I18nProvider language={language}>
      <CharacterSheet character={character} organiser={organiser} />
    </I18nProvider>,
  );
  return screen.getByRole("article", { name: character.name });
}

/** A stat's value by its term: "BAB" → "+3". */
function stat(sheet: HTMLElement, term: string): string | null | undefined {
  return within(sheet).getByText(term, { selector: "dt, dt *" }).closest("div")?.querySelector("dd")?.textContent;
}

describe("CharacterSheet in an SRD 3.5 campaign", () => {
  it("shows 3.5 numbers instead of THAC0 when the sheet has d20", () => {
    const sheet = renderSheet(thorin);
    expect(stat(sheet, "AC")).toBe("17touch 10, flat-footed 17");
    expect(stat(sheet, "BAB")).toBe("+3");
    expect(stat(sheet, "Init")).toBe("+1");
    expect(stat(sheet, "Fort")).toBe("+5");
    expect(stat(sheet, "Ref")).toBe("+2");
    expect(stat(sheet, "Will")).toBe("+1");
    expect(within(sheet).queryByText("THAC0")).toBeNull();
    expect(within(sheet).queryByText("Saving throws")).toBeNull();
    expect(within(sheet).queryByText("Thief skills")).toBeNull();
    // The skills by name, each with its ranks and its total; the feats with their choice.
    const skills = within(sheet).getByRole("cell", { name: "Climb" }).closest("tbody")!;
    expect(within(skills).getAllByRole("row").map((row) => row.textContent)).toEqual([
      "Climb4+6",
      "Intimidate2+3",
      "Jump2+4",
    ]);
    const feats = within(within(sheet).getByRole("list", { name: "Feats" })).getAllByRole("listitem");
    expect(feats.map((li) => li.textContent)).toEqual(["Power Attack", "Cleave", "Weapon Focus (warhammer)"]);
    expect(within(sheet).getByRole("cell", { name: "warhammer" })).toBeTruthy();
    // 3.5 has no speed factor and one damage for every size: no Speed column, one Damage column.
    const attacks = within(sheet).getByRole("cell", { name: "warhammer" }).closest("table")!;
    expect(within(attacks).getAllByRole("columnheader").map((th) => th.textContent)).toEqual(["Attack", "Per round", "Damage"]);
    expect(within(attacks).getByRole("cell", { name: "warhammer" }).closest("tr")?.textContent).toBe("warhammer11d8+3");
    expect(within(sheet).queryByText("Domains")).toBeNull();
  });

  it("shows domains and DCs for a cleric", () => {
    const sheet = renderSheet(mira);
    expect(within(within(sheet).getByRole("list", { name: "Domains" })).getAllByRole("listitem").map((li) => li.textContent)).toEqual(["War", "Good"]);
    expect(within(sheet).getByText("Turn undead: 7 a day")).toBeTruthy();
    expect(within(sheet).getByRole("columnheader", { name: "DC" })).toBeTruthy();
    const level1 = within(sheet).getByRole("cell", { name: "Level 1" }).closest("tr")!;
    expect(within(level1).getAllByRole("cell").map((td) => td.textContent)).toEqual(["Level 1", "2", "", "14"]);
    const level0 = within(sheet).getByRole("cell", { name: "Level 0" }).closest("tr")!;
    expect(within(level0).getAllByRole("cell").map((td) => td.textContent)).toEqual(["Level 0", "3", "", "13"]);
  });

  it("shows a rogue's sneak attack dice", () => {
    const rogue: Character = {
      ...thorin,
      sheet: { ...thorin.sheet, d20: { ...thorin.sheet.d20, derived: { ...thorin.sheet.d20!.derived!, sneak: "2d6" } } },
    };
    const sheet = renderSheet(rogue);
    expect(within(sheet).getByText("Sneak attack +2d6")).toBeTruthy();
  });

  it("shows the engine's warnings to the organiser only", () => {
    expect(within(renderSheet(thorin)).queryByText("Unknown armour 'mithral scale'.")).toBeNull();
    const dm = renderSheet({ ...thorin, id: "chr_0000000035a3", name: "Thorin DM" }, { organiser: true });
    expect(within(dm).getByText("Unknown armour 'mithral scale'.")).toBeTruthy();
  });

  it("shows the speed in feet, and a medium load as 3.5 names it (DEL-404)", () => {
    const sheet = renderSheet(thorin);
    expect(stat(sheet, "Speed")).toBe("20 ft.");
    expect(within(sheet).queryByText("Move")).toBeNull();
    const loaded = renderSheet({
      ...thorin,
      id: "chr_0000000035a4",
      name: "Elowen",
      sheet: { ...thorin.sheet, label: "Elowen", race: "elf", movement_rate: 30 },
      encumbrance: { total_lb: 40, band: "moderate", movement: 20, penalty: -10 },
    });
    expect(stat(loaded, "Speed")).toBe("20 ft.(30 ft. unloaded)");
    expect(within(loaded).getByText("Medium load: 40 lb, move 20 ft.")).toBeTruthy();
  });

  it("lists a raging barbarian's class features with the uses spent (DEL-389)", () => {
    const features = [
      { id: "fast-movement", class: "barbarian", name: "Fast movement", kind: "bonus", per_day: null, value: 10 },
      { id: "rage", class: "barbarian", name: "Rage", kind: "uses", per_day: 1, value: 1 },
      { id: "uncanny-dodge", class: "barbarian", name: "Uncanny dodge", kind: "feat", per_day: null, value: null },
    ];
    const barbarian: Character = {
      ...thorin,
      id: "chr_0000000035a5",
      name: "Krusk",
      sheet: { ...thorin.sheet, label: "Krusk", cls: "Barbarian", levels: { barbarian: 2 } },
      state: { ...thorin.state, conditions: ["raging"], d20: { used: { rage: 1 } } },
      d20: { ...thorin.d20!, features },
    };
    const sheet = renderSheet(barbarian);
    const list = within(sheet).getByRole("list", { name: "Class features" });
    expect(within(list).getAllByRole("listitem").map((li) => li.textContent)).toEqual([
      "Fast movement",
      "Rage: 1 a day, 1 used",
      "Uncanny dodge",
    ]);
    const dutch = renderSheet({ ...barbarian, id: "chr_0000000035a6", name: "Krusk nl" }, { language: "nl" });
    const lijst = within(dutch).getByRole("list", { name: "Klassekenmerken" });
    expect(within(lijst).getAllByRole("listitem")[1].textContent).toBe("Woede: 1 per dag, 1 gebruikt");
    // Turning's attempts are the state's `turning_used`.
    const paladin: Character = {
      ...barbarian,
      id: "chr_0000000035a7",
      name: "Aldric",
      state: { ...thorin.state, d20: { turning_used: 2 } },
      d20: { ...thorin.d20!, features: [{ id: "turn-undead", class: "paladin", name: "Turn undead", kind: "uses", per_day: 4, value: 3 }] },
    };
    const turning = within(renderSheet(paladin)).getByRole("list", { name: "Class features" });
    expect(turning.textContent).toBe("Turn undead: 4 a day, 2 used");
    // Remove disease is counted a week (DEL-389 part 2).
    const weekly: Character = {
      ...barbarian,
      id: "chr_0000000035a8",
      name: "Aldra",
      state: { ...thorin.state, d20: { used: { "remove-disease": 1 } } },
      d20: { ...thorin.d20!, features: [{ id: "remove-disease", class: "paladin", name: "Remove disease", kind: "uses", per_day: 1, per: "week", value: 1 }] },
    };
    expect(within(renderSheet(weekly)).getByRole("list", { name: "Class features" }).textContent).toBe(
      "Remove disease: 1 a week, 1 used",
    );
    // A sheet from before the features (a Phase 2 build) shows no list.
    expect(within(renderSheet(thorin)).queryByRole("list", { name: "Class features" })).toBeNull();
  });

  it("shows a sorcerer's spells a day, those cast today and the spells known (DEL-389)", () => {
    const sorcerer: Character = {
      ...mira,
      id: "chr_0000000035b1",
      name: "Sable",
      sheet: { ...mira.sheet, label: "Sable", cls: "Sorcerer", levels: { sorcerer: 3 }, spell_slots: {} },
      state: { ...mira.state, d20: { cast: { sorcerer: { "1": 2 } } } },
      d20: {
        ...mira.d20!,
        domains: [],
        slots: {},
        dc: {},
        casting: {
          sorcerer: { ability: "cha", caster_level: 3, prepared: false, per_day: { "0": 6, "1": 6 }, known: { "0": 5, "1": 3 }, dc: { "0": 13, "1": 14 } },
        },
        known: { sorcerer: ["detect magic", "magic missile", "shield"] },
      },
    };
    const sheet = renderSheet(sorcerer);
    const pool = within(sheet).getByRole("region", { name: "Sorcerer: caster level 3, CHA" });
    expect(within(pool).getAllByRole("columnheader").map((th) => th.textContent)).toEqual(["", "A day", "Known", "DC"]);
    const rows = within(pool).getAllByRole("row").slice(1);
    expect(rows.map((row) => row.textContent)).toEqual(["Level 06513", "Level 16 (2 cast)314"]);
    expect(within(pool).getByText("Spells known: detect magic, magic missile, shield")).toBeTruthy();
    // No slots table of the first class's beside the pool.
    expect(within(sheet).queryByRole("columnheader", { name: "Slots" })).toBeNull();
    const dutch = renderSheet({ ...sorcerer, id: "chr_0000000035b2", name: "Sable nl" }, { language: "nl" });
    const poel = within(dutch).getByRole("region", { name: "Sorcerer: toverniveau 3, CHA" });
    expect(within(poel).getByText("Bekende spreuken: detect magic, magic missile, shield")).toBeTruthy();
    expect(within(poel).getByRole("cell", { name: "6 (2 gebruikt)" })).toBeTruthy();
  });

  it("shows a cleric 3/wizard 3's two pools, each with its slots and DCs (DEL-389)", () => {
    const multiclass: Character = {
      ...mira,
      id: "chr_0000000035b3",
      name: "Oswin",
      sheet: { ...mira.sheet, label: "Oswin", cls: "Cleric/Wizard", levels: { cleric: 3, wizard: 3 }, spell_slots: { "0": 8, "1": 7, "2": 3 } },
      d20: {
        ...mira.d20!,
        slots: { "0": 4, "1": 4, "2": 2 },
        dc: { "0": 13, "1": 14, "2": 15 },
        casting: {
          cleric: { ability: "wis", caster_level: 3, prepared: true, slots: { "0": 4, "1": 4, "2": 2 }, dc: { "0": 13, "1": 14, "2": 15 } },
          wizard: { ability: "int", caster_level: 3, prepared: true, slots: { "0": 4, "1": 3, "2": 1 }, dc: { "0": 12, "1": 13, "2": 14 } },
        },
      },
    };
    const sheet = renderSheet(multiclass);
    const cleric = within(sheet).getByRole("region", { name: "Cleric: caster level 3, WIS" });
    expect(within(cleric).getAllByRole("columnheader").map((th) => th.textContent)).toEqual(["", "Slots", "DC"]);
    expect(within(cleric).getAllByRole("row").slice(1).map((row) => row.textContent)).toEqual([
      "Level 0413",
      "Level 1414",
      "Level 2215",
    ]);
    const wizard = within(sheet).getByRole("region", { name: "Wizard: caster level 3, INT" });
    expect(within(wizard).getAllByRole("row").slice(1).map((row) => row.textContent)).toEqual([
      "Level 0412",
      "Level 1313",
      "Level 2114",
    ]);
    expect(within(wizard).queryByText(/Spells known/)).toBeNull();
  });

  it("marks a prestige class and heads a pool with the levels prestige classes add (DEL-389 part 4)", () => {
    const knight: Character = {
      ...mira,
      id: "chr_0000000035b4",
      name: "Ansel",
      sheet: {
        ...mira.sheet,
        label: "Ansel",
        cls: "Wizard/Fighter/Eldritch-Knight",
        levels: { wizard: 5, fighter: 1, "eldritch-knight": 3 },
        spell_slots: { "0": 4, "1": 5 },
      },
      d20: {
        ...mira.d20!,
        prestige: ["eldritch-knight"],
        advanced: { wizard: { "eldritch-knight": 2 } },
        casting: {
          wizard: { ability: "int", caster_level: 7, prepared: true, slots: { "0": 4, "1": 5 }, dc: { "0": 13, "1": 14 } },
        },
      },
    };
    const sheet = renderSheet(knight);
    expect(within(sheet).getByText("Wizard 5 / Fighter 1 / Eldritch Knight 3 (prestige)")).toBeTruthy();
    const wizard = within(sheet).getByRole("region", { name: "Wizard: caster level 7, INT" });
    expect(within(wizard).getByText("Advanced: +2 from Eldritch Knight")).toBeTruthy();
    const dutch = renderSheet({ ...knight, id: "chr_0000000035b5", name: "Ansel nl" }, { language: "nl" });
    expect(within(dutch).getByText(/\(prestigeklasse\)$/)).toBeTruthy();
    expect(within(dutch).getByText("Gevorderd: +2 van Eldritch Knight")).toBeTruthy();
  });

  it("shows a Phase 2 single-class caster as before, with no pool by class", () => {
    const sheet = renderSheet(mira);
    expect(within(sheet).queryByRole("region", { name: /caster level/ })).toBeNull();
    expect(within(sheet).getByRole("columnheader", { name: "Slots" })).toBeTruthy();
  });

  it("lists the magic items with their bonuses, a carried weapon, a note and the DM's abilities (DEL-389)", () => {
    const items = [
      { id: "protection", kind: "worn" as const, name: "Ring of Protection +2", bonus: 2 },
      { id: "longsword", kind: "weapon" as const, name: "+1 flaming longsword", bonus: 1, in_use: true },
      { id: "dagger", kind: "weapon" as const, name: "+1 dagger", bonus: 1, in_use: false },
      { id: "warhammer", kind: "weapon" as const, name: "+1 speed warhammer", bonus: 1, in_use: true, dm: ["speed"] },
      { id: "bag-of-holding", kind: "note" as const, name: "Bag of Holding", note: true },
    ];
    const sheet = renderSheet({ ...thorin, d20: { ...thorin.d20!, items } });
    const listed = within(within(sheet).getByRole("list", { name: "Magic items" })).getAllByRole("listitem");
    expect(listed.map((li) => li.textContent)).toEqual([
      "Ring of Protection +2",
      "+1 flaming longsword",
      "+1 dagger (carried, not in use)",
      "+1 speed warhammer; the DM rules Speed",
      "Bag of Holding (no numbers on the sheet: the DM's)",
    ]);
  });

  it("shows a score an item enhances beside the base (DEL-389)", () => {
    const sheet = renderSheet({ ...thorin, d20: { ...thorin.d20!, abilities: { str: 20 } } });
    const scores = within(sheet).getByRole("list", { name: "Abilities" });
    const str = within(scores).getAllByRole("listitem")[0];
    expect(within(str).getByTitle("With the enhancement bonus of a magic item worn").textContent).toBe("16 (20)");
    expect(within(scores).getAllByRole("listitem")[1].textContent).not.toContain("(");
  });

  it("has no magic items section without items", () => {
    expect(within(renderSheet(thorin)).queryByText("Magic items")).toBeNull();
  });

  it("names the magic items in Dutch", () => {
    const items = [{ id: "protection", kind: "worn" as const, name: "Ring of Protection +2", bonus: 2 }];
    const sheet = renderSheet({ ...thorin, d20: { ...thorin.d20!, items } }, { language: "nl" });
    expect(within(sheet).getByRole("list", { name: "Magische voorwerpen" })).toBeTruthy();
  });

  it("speaks the reader's language", () => {
    const sheet = renderSheet(thorin, { language: "fr" });
    expect(stat(sheet, "BBA")).toBe("+3");
    expect(stat(sheet, "Vig")).toBe("+5");
    expect(within(sheet).getByRole("list", { name: "Dons" })).toBeTruthy();
  });
});
