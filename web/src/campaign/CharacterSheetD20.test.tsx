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

  it("speaks the reader's language", () => {
    const sheet = renderSheet(thorin, { language: "fr" });
    expect(stat(sheet, "BBA")).toBe("+3");
    expect(stat(sheet, "Vig")).toBe("+5");
    expect(within(sheet).getByRole("list", { name: "Dons" })).toBeTruthy();
  });
});
