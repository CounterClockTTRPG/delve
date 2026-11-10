import { act, fireEvent, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { json, stubFetch } from "../play/testing";
import { asked, player, renderArea, rulesetInfo } from "./testing";

afterEach(() => {
  vi.unstubAllGlobals();
});

const facets = [
  {
    key: "caster",
    options: [
      { value: "wizard", count: 3 },
      { value: "priest", count: 1 },
    ],
  },
  {
    key: "level",
    options: [
      { value: 1, count: 2 },
      { value: 2, count: 2 },
    ],
  },
  {
    key: "school",
    options: [
      { value: "Alteration", count: 2 },
      { value: "Necromancy", count: 2 },
    ],
  },
];

const spell = (id: string, name: string, school: string, extra = {}) => ({
  id,
  name,
  caster: "wizard",
  level: 2,
  school,
  house_rule: false,
  ...extra,
});

const spells = (rows: unknown[], total = rows.length, offset = 0) =>
  json(200, { kind: "list", facets, total, offset, rows });

describe("A section's page", () => {
  it("shows the facets as value (count)", async () => {
    stubFetch({
      "GET /api/me": player,
      ...rulesetInfo(),
      "GET /api/rulesets/adnd2e/spells": () => spells([spell("412", "Web", "Evocation")]),
    });
    renderArea("/rulesets/adnd2e/spells");
    expect(await screen.findByRole("heading", { level: 1, name: "Spells" })).toBeTruthy();
    const school = (await screen.findByRole("combobox", { name: "School" })) as HTMLSelectElement;
    expect([...school.options].map((o) => o.textContent)).toEqual(["Any", "Alteration (2)", "Necromancy (2)"]);
    const caster = screen.getByRole("combobox", { name: "Caster" }) as HTMLSelectElement;
    expect([...caster.options].map((o) => o.textContent)).toEqual(["Any", "Wizard (3)", "Priest (1)"]);
    expect(screen.getByRole("link", { name: "Web" }).getAttribute("href")).toBe("/rulesets/adnd2e/spells/412");
  });

  it("puts a chosen filter in the address and asks the API with it", async () => {
    const fetchMock = stubFetch({
      "GET /api/me": player,
      ...rulesetInfo(),
      "GET /api/rulesets/adnd2e/spells": () => spells([spell("412", "Web", "Evocation")]),
      "GET /api/rulesets/adnd2e/spells?school=Necromancy": () =>
        spells([spell("5", "Chill touch", "Necromancy"), spell("9", "Ghoul touch", "Alteration/Necromancy")]),
    });
    const router = renderArea("/rulesets/adnd2e/spells");
    fireEvent.change(await screen.findByRole("combobox", { name: "School" }), { target: { value: "Necromancy" } });
    await waitFor(() => expect(router.state.location.search).toBe("?school=Necromancy"));
    expect(await screen.findByRole("link", { name: "Ghoul touch" })).toBeTruthy();
    expect(asked(fetchMock)).toContain("/api/rulesets/adnd2e/spells?school=Necromancy");
  });

  it("shows the same filter after a reload of its address", async () => {
    stubFetch({
      "GET /api/me": player,
      ...rulesetInfo(),
      "GET /api/rulesets/adnd2e/spells?school=Necromancy": () => spells([spell("5", "Chill touch", "Necromancy")]),
    });
    renderArea("/rulesets/adnd2e/spells?school=Necromancy");
    expect(await screen.findByRole("link", { name: "Chill touch" })).toBeTruthy();
    expect((screen.getByRole("combobox", { name: "School" }) as HTMLSelectElement).value).toBe("Necromancy");
  });

  it("filters by name 250 ms after typing, from the first page", async () => {
    const fetchMock = stubFetch({
      "GET /api/me": player,
      ...rulesetInfo(),
      "GET /api/rulesets/adnd2e/spells?offset=50": () => spells([spell("412", "Web", "Evocation")], 120, 50),
      "GET /api/rulesets/adnd2e/spells?q=web": () => spells([spell("412", "Web", "Evocation")]),
    });
    const router = renderArea("/rulesets/adnd2e/spells?offset=50");
    fireEvent.change(await screen.findByRole("searchbox", { name: "Filter by name" }), { target: { value: "web" } });
    expect(router.state.location.search).toBe("?offset=50");
    await waitFor(() => expect(router.state.location.search).toBe("?q=web"));
    await waitFor(() => expect(asked(fetchMock)).toContain("/api/rulesets/adnd2e/spells?q=web"));
  });

  it("pages on the server: Next asks for offset=50", async () => {
    const rows = Array.from({ length: 50 }, (_, i) => spell(String(i + 1), `Spell ${i + 1}`, "Alteration"));
    stubFetch({
      "GET /api/me": player,
      ...rulesetInfo(),
      "GET /api/rulesets/adnd2e/spells": () => spells(rows, 120),
      "GET /api/rulesets/adnd2e/spells?offset=50": () => spells([spell("99", "Spell 51", "Alteration")], 120, 50),
    });
    const router = renderArea("/rulesets/adnd2e/spells");
    const pager = await screen.findByRole("navigation", { name: "Spells pages" });
    expect(within(pager).getByText("1–50 of 120")).toBeTruthy();
    expect((within(pager).getByRole("button", { name: "Previous" }) as HTMLButtonElement).disabled).toBe(true);
    fireEvent.click(within(pager).getByRole("button", { name: "Next" }));
    await waitFor(() => expect(router.state.location.search).toBe("?offset=50"));
    expect(await screen.findByRole("link", { name: "Spell 51" })).toBeTruthy();
    expect(screen.getByText("51–51 of 120")).toBeTruthy();
  });

  it("marks a house rule's row", async () => {
    stubFetch({
      "GET /api/me": player,
      ...rulesetInfo(),
      "GET /api/rulesets/adnd2e/items": () =>
        json(200, {
          kind: "list",
          facets: [{ key: "item_type", options: [{ value: "misc_equipment", count: 1 }] }],
          total: 2,
          offset: 0,
          rows: [
            { id: "hr-12", name: "Sun blade of Pelor", item_type: "Magic Weapon", house_rule: true },
            { id: "3", name: "Rope", item_type: "misc_equipment", cost: "1 sp", weight: "8", rarity: 1, house_rule: false },
          ],
        }),
    });
    renderArea("/rulesets/adnd2e/items");
    const rule = (await screen.findByRole("link", { name: "Sun blade of Pelor" })).closest("li")!;
    expect(within(rule).getByText("House rule")).toBeTruthy();
    const rope = screen.getByRole("link", { name: "Rope" }).closest("li")!;
    expect(within(rope).queryByText("House rule")).toBeNull();
    // A mundane type in words; the item type's facet too.
    expect(within(rope).getByText(/Miscellaneous equipment/)).toBeTruthy();
    const type = screen.getByRole("combobox", { name: "Type" }) as HTMLSelectElement;
    expect([...type.options].map((o) => o.textContent)).toContain("Miscellaneous equipment (1)");
  });

  it("renders a table section's one table, with its note", async () => {
    stubFetch({
      "GET /api/me": player,
      ...rulesetInfo(),
      "GET /api/rulesets/adnd2e/turning": () =>
        json(200, {
          kind: "table",
          table: [
            {
              key: "turning",
              note: "Paladins turn undead as priests two levels lower.",
              rows: [
                { undead_type: "Skeleton", "1": "10", "2": "7", "14+": "D*" },
                { undead_type: "Zombie", "1": "13", "2": "10", "14+": "D*" },
              ],
            },
          ],
        }),
    });
    renderArea("/rulesets/adnd2e/turning");
    expect(await screen.findByRole("heading", { level: 1, name: "Turning undead" })).toBeTruthy();
    const table = await screen.findByRole("table");
    expect(within(table).getByRole("columnheader", { name: "Undead" })).toBeTruthy();
    // The levels' columns, as the book heads them.
    expect(within(table).getByRole("columnheader", { name: "14+" })).toBeTruthy();
    expect(within(table).getByRole("cell", { name: "Zombie" })).toBeTruthy();
    expect(within(table).queryByRole("columnheader", { name: /key|note|rows/i })).toBeNull();
    expect(screen.getByText("Paladins turn undead as priests two levels lower.")).toBeTruthy();
    // The section's one table needs no heading of its own, and its key isn't a field.
    expect(document.querySelector("dl")).toBeNull();
    expect(screen.queryByRole("heading", { level: 2 })).toBeNull();
    expect(screen.queryByRole("searchbox")).toBeNull();
  });

  it("heads each of a section's tables, and links the abilities to their pages", async () => {
    stubFetch({
      "GET /api/me": player,
      ...rulesetInfo(),
      "GET /api/rulesets/adnd2e/proficiencies": () =>
        json(200, {
          kind: "table",
          table: [
            {
              key: "proficiencies",
              note: "",
              rows: [{ name: "Riding, Land-based", group: "General", slots: "1", ability: "Wisdom", check_modifier: "+3" }],
            },
            { key: "crossover", note: "", rows: [{ class_name: "Fighter", groups: "Warrior, General" }] },
          ],
        }),
      "GET /api/rulesets/adnd2e/abilities": () =>
        json(200, {
          kind: "table",
          table: [
            {
              key: "abilities",
              note: "",
              rows: [
                { id: "strength", name: "Strength", headline: "Muscle and endurance" },
                { id: "wisdom", name: "Wisdom", headline: "Judgement" },
              ],
            },
          ],
        }),
    });
    const router = renderArea("/rulesets/adnd2e/proficiencies");
    expect(await screen.findByRole("heading", { level: 2, name: "Proficiencies" })).toBeTruthy();
    expect(screen.getByRole("heading", { level: 2, name: "Groups by class" })).toBeTruthy();
    const [proficiencies, crossover] = screen.getAllByRole("table");
    expect(within(proficiencies).getByRole("columnheader", { name: "Check modifier" })).toBeTruthy();
    expect(within(crossover).getByRole("cell", { name: "Warrior, General" })).toBeTruthy();

    await act(() => router.navigate("/rulesets/adnd2e/abilities"));
    const strength = await screen.findByRole("link", { name: "Strength" });
    expect(strength.getAttribute("href")).toBe("/rulesets/adnd2e/abilities/strength");
    expect(screen.getByRole("cell", { name: "Muscle and endurance" })).toBeTruthy();
    expect(screen.getByRole("columnheader", { name: "Summary" })).toBeTruthy();
  });

  it("says not found for a section the reader may not see", async () => {
    stubFetch({ "GET /api/me": player, ...rulesetInfo() });
    renderArea("/rulesets/adnd2e/monsters");
    expect(await screen.findByText("This page isn't in the ruleset.")).toBeTruthy();
    expect(screen.queryByRole("heading", { name: "Monsters" })).toBeNull();
  });
});
