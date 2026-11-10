import { render, screen, within } from "@testing-library/react";
import { render as drawPortrait } from "portraitgen";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { Character } from "../api";
import { I18nProvider } from "../i18n";
import CharacterSheet from "./CharacterSheet";

// portraitgen as it is, with its drawings watched: the sheet's state goes into the render options.
vi.mock("portraitgen", async (importOriginal) => {
  const real = await importOriginal<typeof import("portraitgen")>();
  return { ...real, render: vi.fn(real.render) };
});

afterEach(() => {
  vi.unstubAllGlobals();
  vi.mocked(drawPortrait).mockClear();
});

export const anselm: Character = {
  id: "chr_00000000000a",
  campaign_id: "cmp_00000000000a",
  name: "Anselm",
  kind: "pc",
  order: 0,
  created_at: "2026-10-17T12:00:00Z",
  sheet: {
    kind: "pc",
    label: "Anselm",
    race: "human",
    gender: "male",
    cls: "Fighter/Mage",
    levels: { fighter: 3, mage: 2 },
    hp_max: 18,
    ac: 4,
    thac0: 18,
    saves: { paralysis_poison_death: 13, rod_staff_wand: 11, petrify_polymorph: 13, breath_weapon: 15, spell: 12 },
    ability_scores: { str: "18/76", dex: 15, con: 16, int: 14, wis: 9, cha: 11 },
    attacks: [
      {
        name: "long sword",
        speed: 5,
        attacks: "3/2",
        thac0: null,
        damage_sm: "1d8+3",
        damage_l: "1d12+3",
        range: null,
      },
      {
        name: "bastard sword (specialised)",
        speed: 6,
        attacks: "3/2",
        thac0: 16,
        damage_sm: "2d4+5",
        damage_l: "2d8+5",
        range: null,
      },
    ],
    weapon: "a notched long sword, his father's",
    weapon_profs: ["long sword", "bastard sword (specialised)"],
    nwps: ["riding", "blacksmithing"],
    natural_abilities: ["infravision 60 ft"],
    skills: { pick_pockets: 85, read_languages: 40 },
    size: "M",
    ac_vs_larger: 2,
    background: "A smith's son from Hommlet.",
    movement_rate: 12,
    alignment: "NG",
    spell_slots: { "1": 2 },
    spell_loadout: {
      known: { "1": ["Magic Missile", "Sleep", "Shield"] },
      default: { "1": ["Magic Missile", "Sleep"] },
    },
  },
  state: {
    hp: 11,
    xp: 4200,
    conditions: ["poisoned"],
    effects: [{ name: "bless", duration: 4, to_hit: 1 }],
    inventory: [
      { name: "long sword", qty: 1, weight_lb: 4, notes: "" },
      { name: "torch", qty: 3, weight_lb: null, notes: "" },
    ],
    memorized: [
      { name: "Magic Missile", level: 1, cast: true },
      { name: "Sleep", level: 1, cast: false },
    ],
  },
  encumbrance: { total_lb: 112, band: "heavy", movement: 6, penalty: -6 },
};

function renderSheet(character: Character = anselm, language = "en") {
  return render(
    <I18nProvider language={language}>
      <CharacterSheet character={character} />
    </I18nProvider>,
  );
}

describe("CharacterSheet", () => {
  it("shows each class's XP and what its next level needs", () => {
    renderSheet({ ...anselm, xp_progress: [{ class: "Fighter", level: 3, xp: 2600, xp_floor: 0, xp_next: 4000, total_next: null, earned_level: 3, ready: false }, { class: "Mage", level: 2, xp: 2600, xp_floor: 0, xp_next: 5000, total_next: null, earned_level: 2, ready: false }] });
    expect(screen.getByTestId("xp-progress").textContent).toBe("Fighter 2,600 / 4,000 · Mage 2,600 / 5,000");
  });

  it("shows one line for a single class, its share alone at the top level, and a level that is ready", () => {
    renderSheet({ ...anselm, xp_progress: [{ class: "Fighter", level: 3, xp: 9000, xp_floor: 0, xp_next: 8000, total_next: null, earned_level: 3, ready: true }] });
    expect(screen.getByTestId("xp-progress").textContent).toBe("Fighter 9,000 / 8,000 (ready to level)");
    renderSheet({ ...anselm, name: "Old", xp_progress: [{ class: "Fighter", level: 20, xp: 3000000, xp_floor: 0, xp_next: null, total_next: null, earned_level: 20, ready: false }] });
    expect(screen.getAllByTestId("xp-progress")[1].textContent).toBe("Fighter 3,000,000");
  });

  it("says a portrait is being painted, and its place in the painter's queue while it waits", () => {
    const { rerender } = render(
      <I18nProvider language="en">
        <CharacterSheet character={{ ...anselm, portrait_painting: { provider: "assetgen", queue: 2 } }} />
      </I18nProvider>,
    );
    expect(screen.getByRole("status").textContent).toBe("Waiting in assetgen's queue: number 2.");
    rerender(
      <I18nProvider language="en">
        <CharacterSheet character={{ ...anselm, portrait_painting: { provider: "assetgen", queue: null } }} />
      </I18nProvider>,
    );
    expect(screen.getByRole("status").textContent).toBe("The portrait is being painted…");
    rerender(
      <I18nProvider language="en">
        <CharacterSheet character={anselm} />
      </I18nProvider>,
    );
    expect(screen.queryByRole("status")).toBeNull();
  });

  it("shows no XP progress without it", () => {
    renderSheet();
    expect(screen.queryByTestId("xp-progress")).toBeNull();
  });

  it("shows HP, AC, THAC0, saves and attacks", () => {
    renderSheet();
    const sheet = screen.getByRole("article", { name: "Anselm" });
    expect(within(sheet).getByText("Fighter 3 / Mage 2")).toBeTruthy();
    expect(within(sheet).getByText("11 / 18")).toBeTruthy();
    expect(within(sheet).getByRole("cell", { name: "Breath weapon" }).nextElementSibling?.textContent).toBe("15");
    expect(within(sheet).getByRole("cell", { name: "long sword" })).toBeTruthy();
    expect(within(sheet).getByText("1d8+3 / 1d12+3")).toBeTruthy();
    expect(within(sheet).getByText("poisoned")).toBeTruthy();
  });

  it("shows any ruleset's saves in the sheet's order, an unknown one by its key", () => {
    const saves = { death_paralysis_poison: 14, petrification_polymorph: 15, aimed_magic_items: 16, house_save: 9 };
    renderSheet({ ...anselm, sheet: { ...anselm.sheet, saves } }, "nl");
    const sheet = screen.getByRole("article", { name: "Anselm" });
    const rows = within(sheet).getByRole("cell", { name: "Dood, verlamming, gif" }).closest("tbody")!;
    expect(within(rows).getAllByRole("row").map((row) => row.textContent)).toEqual([
      "Dood, verlamming, gif14",
      "Verstening, gedaanteverwisseling15",
      "Gerichte magische voorwerpen16",
      "house save9",
    ]);
  });

  it("formats XP and HP with the reader's separators", () => {
    const rich = { ...anselm, state: { ...anselm.state, xp: 12345, hp: 61 }, sheet: { ...anselm.sheet, hp_max: 62 } };
    renderSheet(rich);
    const en = screen.getByRole("article", { name: "Anselm" });
    expect(within(en).getByText("12,345")).toBeTruthy();
    expect(within(en).getByText("61 / 62").classList.contains("nowrap")).toBe(true);
    renderSheet({ ...rich, id: "chr_00000000000b", name: "Bertil" }, "nl");
    const nl = screen.getByRole("article", { name: "Bertil" });
    expect(within(nl).getByText("12.345")).toBeTruthy();
    expect(within(nl).getByText("61 / 62").classList.contains("nowrap")).toBe(true);
  });

  it("shows the portrait in the head of the sheet", () => {
    const portrait = { kind: "image", image_id: "img_00000000000a" } as const;
    renderSheet({ ...anselm, sheet: { ...anselm.sheet, portrait } });
    const sheet = screen.getByRole("article", { name: "Anselm" });
    expect(within(sheet).getByRole("img", { name: "Anselm" }).getAttribute("src")).toBe(
      "/api/campaigns/cmp_00000000000a/pictures/img_00000000000a",
    );
  });

  it("strikes through cast spells, and shows the encumbrance band", () => {
    renderSheet();
    const memorized = within(screen.getByRole("list", { name: "Memorized" })).getAllByRole("listitem");
    expect(memorized.map((li) => li.textContent)).toEqual(["Magic Missile (cast)", "Sleep"]);
    expect(memorized[0].querySelector("s")?.textContent).toBe("Magic Missile");
    expect(memorized[1].querySelector("s")).toBeNull();
    expect(screen.getByText("Heavy load: 112 lb, move 6")).toBeTruthy();
    expect(screen.getByText("Default loadout")).toBeTruthy();
    expect(screen.getByText("Magic Missile, Sleep")).toBeTruthy();
    expect(screen.getByText("3 × torch")).toBeTruthy();
  });

  it("lists known spells for a spellbook, but not for a priest, who may pray for any spell of their spheres", () => {
    renderSheet();
    expect(screen.getByRole("columnheader", { name: "Known" })).toBeTruthy();
    expect(screen.getByText("Magic Missile, Sleep, Shield")).toBeTruthy();

    const thrain: Character = {
      ...anselm,
      id: "chr_00000000000b",
      name: "Thrain",
      sheet: {
        ...anselm.sheet,
        cls: "Fighter/Cleric",
        levels: { fighter: 1, cleric: 1 },
        spell_slots: { "1": 3 },
        spell_loadout: {
          known: { "1": ["Cure Light Wounds", "Bless", "Command", "Sanctuary"] },
          default: { "1": ["Cure Light Wounds", "Bless", "Command"] },
        },
      },
    };
    renderSheet(thrain);
    const sheet = screen.getByRole("article", { name: "Thrain" });
    expect(within(sheet).queryByRole("columnheader", { name: "Known" })).toBeNull();
    expect(within(sheet).queryByText(/Sanctuary/)).toBeNull();
    expect(within(sheet).getByText("Cure Light Wounds, Bless, Command")).toBeTruthy();
  });

  it("shows an item's DM note, which only the organiser's data carries (DEL-181)", () => {
    const phial = { name: "glass phial", qty: 1, weight_lb: null, notes: "cloudy", dm_notes: "neutralize poison" };
    renderSheet({ ...anselm, state: { ...anselm.state, inventory: [phial] } });
    expect(screen.getByTestId("item-dm-notes").textContent).toBe("DM only: neutralize poison");
    expect(screen.getByText("cloudy")).toBeTruthy();
  });

  it("copes with a sheet that has no inventory or spells yet", () => {
    const { sheet, state } = anselm;
    const plain: Character = {
      ...anselm,
      encumbrance: null,
      sheet: { ...sheet, spell_loadout: undefined, spell_slots: {} },
      state: { hp: state.hp, xp: state.xp, conditions: [], effects: [] },
    };
    renderSheet(plain, "nl");
    expect(screen.getByText("Draagt niets.")).toBeTruthy();
    expect(screen.queryByRole("list", { name: "Gememoriseerd" })).toBeNull();
  });

  it("shows the whole sheet: abilities, proficiencies, thief skills, natural abilities and background", () => {
    renderSheet();
    const sheet = screen.getByRole("article", { name: "Anselm" });
    const abilities = within(sheet).getByRole("list", { name: "Abilities" });
    expect(within(abilities).getAllByRole("listitem").map((li) => li.textContent)).toEqual([
      "STR18/76", "DEX15", "CON16", "INT14", "WIS9", "CHA11",
    ]);
    expect(within(sheet).getByText("Human, Male, NG")).toBeTruthy();
    expect(within(sheet).getByText("Size M")).toBeTruthy();
    expect(within(sheet).getByText("+2 AC against larger attackers")).toBeTruthy();
    expect(within(sheet).getByText("In hand: a notched long sword, his father's")).toBeTruthy();
    expect(within(within(sheet).getByRole("list", { name: "Weapon proficiencies" })).getAllByRole("listitem").map((li) => li.textContent)).toEqual(["long sword", "bastard sword (specialised)"]);
    expect(within(within(sheet).getByRole("list", { name: "Nonweapon proficiencies" })).getAllByRole("listitem").map((li) => li.textContent)).toEqual(["riding", "blacksmithing"]);
    expect(within(sheet).getByRole("cell", { name: "Pick pockets" }).nextElementSibling?.textContent).toBe("85%");
    expect(within(sheet).getByText("infravision 60 ft")).toBeTruthy();
    expect(within(sheet).getByText("A smith's son from Hommlet.")).toBeTruthy();
  });

  it("gives each attack its own THAC0, else the sheet's", () => {
    renderSheet();
    const sheet = screen.getByRole("article", { name: "Anselm" });
    const thac0 = (attack: string) => {
      const row = within(sheet).getByRole("cell", { name: attack }).closest("tr") as HTMLElement;
      const column = [...(row.closest("table") as HTMLElement).querySelectorAll("th")].findIndex((th) => th.textContent === "THAC0");
      return row.children[column]?.textContent;
    };
    expect(thac0("bastard sword (specialised)")).toBe("16");
    expect(thac0("long sword")).toBe("18");
  });

  it("names the race, classes, gender and alignment in the reader's language (T7)", () => {
    renderSheet(anselm, "nl");
    const sheet = screen.getByRole("article", { name: "Anselm" });
    expect(within(sheet).getByText("Krijger 3 / Magiër 2")).toBeTruthy();
    expect(within(sheet).getByText("Mens, Man, Neutraal goed")).toBeTruthy();
    renderSheet({ ...anselm, id: "chr_00000000000z", sheet: { ...anselm.sheet, race: "Half-ogre", alignment: "?" } }, "nl");
    expect(screen.getByText("Half-ogre, Man, ?")).toBeTruthy();
  });

  it("shows the THAC0 the server worked out, with its parts as the title, unless the attack stores one", () => {
    const [sword, bastard] = anselm.sheet.attacks;
    renderSheet({
      ...anselm,
      sheet: {
        ...anselm.sheet,
        attacks: [
          { ...sword, thac0_worked: { value: 16, parts: [["base", 18], ["strength", -2]] } },
          { ...bastard, thac0_worked: { value: 16, parts: [["stored", 16]] } },
        ],
      },
    });
    const cell = (attack: string) =>
      (screen.getByRole("cell", { name: attack }).closest("tr") as HTMLElement).children[3] as HTMLElement;
    expect(cell("long sword").textContent).toBe("16");
    expect(cell("long sword").title).toBe("THAC0 18, Strength -2");
    expect(cell("bastard sword (specialised)").title).toBe("Set by the DM: 16");
  });

  it("shows an NPC's story and disposition to the organiser only", () => {
    const tira: Character = {
      ...anselm,
      id: "chr_00000000000t",
      name: "Tira",
      kind: "npc",
      order: null,
      sheet: { ...anselm.sheet, kind: "npc", notes_md: "She serves the Temple in secret.", disposition: 40 },
    };
    const organiser = render(
      <I18nProvider language="en">
        <CharacterSheet character={tira} organiser />
      </I18nProvider>,
    );
    expect(screen.getByText("She serves the Temple in secret.")).toBeTruthy();
    expect(screen.getByText("+40")).toBeTruthy();
    organiser.unmount();
    renderSheet(tira);
    expect(screen.queryByText("She serves the Temple in secret.")).toBeNull();
    expect(screen.queryByText("+40")).toBeNull();
  });

  describe("its portrait shows the character's state", () => {
    const drawn = { ...anselm, sheet: { ...anselm.sheet, portrait: { kind: "traits", describe: "a young man", seed: "s" } } } as const;
    const lastLook = () => {
      const { emotes, once } = vi.mocked(drawPortrait).mock.lastCall?.[1] ?? {};
      return { emotes, once };
    };

    it("idles, and plays a hurt or frightened state once, again when the state changes", () => {
      const sheet = render(
        <I18nProvider language="en">
          <CharacterSheet character={{ ...drawn, emote: "idle" }} />
        </I18nProvider>,
      );
      expect(lastLook()).toEqual({ emotes: ["blink", "breathe"], once: undefined });
      expect(screen.queryByText("Badly hurt")).toBeNull();

      const again = (character: Character) =>
        sheet.rerender(
          <I18nProvider language="en">
            <CharacterSheet character={character} />
          </I18nProvider>,
        );
      again({ ...drawn, emote: "upset", state: { ...drawn.state, hp: 6 } });
      expect(lastLook()).toEqual({ emotes: ["upset", "blink", "breathe"], once: true });
      expect(screen.getByRole("img", { name: "Anselm, badly hurt" })).toBeTruthy();

      vi.mocked(drawPortrait).mockClear();
      again({ ...drawn, emote: "upset", state: { ...drawn.state, hp: 5 } });
      expect(drawPortrait).not.toHaveBeenCalled(); // the same state plays nothing new

      again({ ...drawn, emote: "afraid", state: { ...drawn.state, conditions: ["frightened"] } });
      expect(lastLook()).toEqual({ emotes: ["afraid", "blink", "breathe"], once: true });
      expect(screen.getByRole("img", { name: "Anselm, frightened" })).toBeTruthy();
    });

    it("loops sleep at 0 HP", () => {
      renderSheet({ ...drawn, emote: "sleep", state: { ...drawn.state, hp: 0 } });
      expect(lastLook()).toEqual({ emotes: ["sleep", "breathe"], once: undefined });
      expect(screen.getByRole("img", { name: "Anselm, down" })).toBeTruthy();
    });

    it("idles without an emote from the server, and is still under reduced motion", () => {
      renderSheet(drawn);
      expect(lastLook()).toEqual({ emotes: ["blink", "breathe"], once: undefined });

      vi.stubGlobal("matchMedia", (query: string) => ({
        matches: query === "(prefers-reduced-motion: reduce)",
        addEventListener: () => {},
        removeEventListener: () => {},
      }));
      renderSheet({ ...drawn, id: "chr_00000000000b", emote: "sleep" }, "nl");
      expect(lastLook()).toEqual({ emotes: undefined, once: undefined });
      expect(screen.getByRole("img", { name: "Anselm, buiten westen" })).toBeTruthy();
    });
  });
});
