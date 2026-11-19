import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { json, stubFetch } from "../play/testing";
import { owner, player, renderArea, rulesetInfo } from "./testing";

afterEach(() => {
  vi.unstubAllGlobals();
});

const web = {
  section: "spells",
  id: "412",
  name: "Web",
  fields: {
    level: "2",
    school: "Evocation",
    range: "5 yds/level",
    components: "V, S, M",
    materials: "a bit of spider web",
    casting_time: "2",
    duration: "2 turns/level",
    area: "8,000 cu. ft.",
    save: "Neg. or ½",
    source: "PHB",
    page: "189",
    glitter: "odd",
  },
  text: "A **web** spell creates a many-layered mass.\n\nCreatures caught within it are stuck.",
  table: null,
  house_rule: false,
};

/** The definition list's labels and values, in order. */
function fields(): [string, string][] {
  const list = document.querySelector("dl")!;
  const terms = within(list).getAllByRole("term").map((n) => n.textContent ?? "");
  const values = within(list).getAllByRole("definition").map((n) => n.textContent ?? "");
  return terms.map((term, i) => [term, values[i]]);
}

describe("An entry's page", () => {
  it("shows a spell's fields with their labels, and its text as Markdown", async () => {
    stubFetch({ "GET /api/me": player, ...rulesetInfo(), "GET /api/rulesets/adnd2e/spells/412": () => json(200, web) });
    renderArea("/rulesets/adnd2e/spells/412");
    expect(await screen.findByRole("heading", { level: 1, name: "Web" })).toBeTruthy();
    expect(fields()).toEqual([
      ["Level", "2"],
      ["School", "Evocation"],
      ["Range", "5 yds/level"],
      ["Components", "V, S, M"],
      ["Materials", "a bit of spider web"],
      ["Casting time", "2"],
      ["Duration", "2 turns/level"],
      ["Area of effect", "8,000 cu. ft."],
      ["Saving throw", "Neg. or ½"],
      ["Source", "PHB"],
      ["Page", "189"],
      // A field Delve has no words for shows its key.
      ["glitter", "odd"],
    ]);
    expect(screen.getByText("web", { selector: "strong" })).toBeTruthy();
    expect(screen.getByText("Creatures caught within it are stuck.")).toBeTruthy();
    expect(screen.getByRole("link", { name: "Spells" }).getAttribute("href")).toBe("/rulesets/adnd2e/spells");
  });

  it("labels an SRD 3.5 monster's fields (DEL-384)", async () => {
    stubFetch({
      "GET /api/me": owner,
      ...rulesetInfo(),
      "GET /api/rulesets/adnd2e/monsters/ogre": () =>
        json(200, {
          section: "monsters", id: "ogre", name: "Ogre", text: "", table: null, house_rule: false,
          fields: { base_attack_grapple: "+3/+12", cr: "3", level_adjustment: "+2", space_reach: "10 ft./10 ft." },
        }),
      "GET /api/monster-pictures?name=Ogre": () =>
        json(200, { slug: "ogre", picture: false, version: null, painting: false, error: null, paid: false }),
    });
    renderArea("/rulesets/adnd2e/monsters/ogre");
    await screen.findByRole("heading", { name: "Ogre" });
    expect(fields()).toEqual([
      ["Base attack/grapple", "+3/+12"],
      ["Challenge rating", "3"],
      ["Level adjustment", "+2"],
      ["Space/reach", "10 ft./10 ft."],
    ]);
  });

  it("labels the fields in Dutch, and keeps the book's words", async () => {
    stubFetch({ "GET /api/me": player, ...rulesetInfo(), "GET /api/rulesets/adnd2e/spells/412": () => json(200, web) });
    renderArea("/rulesets/adnd2e/spells/412", "nl");
    await screen.findByRole("heading", { level: 1, name: "Web" });
    expect(fields()[1]).toEqual(["School", "Evocation"]);
    expect(fields()[5]).toEqual(["Spreuktijd", "2"]);
  });

  it("shows an entry's table, and marks a house rule", async () => {
    stubFetch({
      "GET /api/me": player,
      ...rulesetInfo("cmp_00000000000b"),
      "GET /api/rulesets/adnd2e/classes/hr-7?campaign=cmp_00000000000b": () =>
        json(200, {
          section: "classes",
          id: "hr-7",
          name: "Witch hunter",
          fields: {},
          text: "## Mechanics\n\nHunts witches.",
          table: [
            { level: 1, xp_required: 0, thac0: 20 },
            { level: 2, xp_required: 2250, thac0: 19 },
          ],
          house_rule: true,
        }),
    });
    renderArea("/rulesets/adnd2e/classes/hr-7?campaign=cmp_00000000000b");
    expect(await screen.findByRole("heading", { level: 1, name: "Witch hunter" })).toBeTruthy();
    expect(screen.getByText("House rule")).toBeTruthy();
    expect(screen.getByText("Hunts witches.")).toBeTruthy();
    const table = screen.getByRole("table");
    expect(within(table).getByRole("columnheader", { name: "XP" })).toBeTruthy();
    expect(within(table).getByRole("cell", { name: "2250" })).toBeTruthy();
    expect(screen.getByRole("link", { name: "Classes" }).getAttribute("href")).toBe(
      "/rulesets/adnd2e/classes?campaign=cmp_00000000000b",
    );
  });

  it("says not found for an entry that isn't there, or that the reader may not see", async () => {
    stubFetch({ "GET /api/me": player, ...rulesetInfo() });
    renderArea("/rulesets/adnd2e/monsters/12");
    expect(await screen.findByText("This page isn't in the ruleset.")).toBeTruthy();
    expect(screen.queryByRole("link", { name: "Monsters" })).toBeNull();
    expect(screen.getByRole("link", { name: "AD&D 2nd Edition" }).getAttribute("href")).toBe("/rulesets/adnd2e");
  });
});

const goblin = { section: "monsters", id: "77", name: "Goblin", fields: {}, text: "", table: null, house_rule: false };
const state = (picture: boolean) => () =>
  json(200, { slug: "goblin", picture, version: picture ? "v1" : null, painting: false, error: null, paid: false });

describe("A monster's entry (DEL-275)", () => {
  it("shows the picture of its kind, and an organiser may paint it again", async () => {
    const fetchMock = stubFetch({
      "GET /api/me": owner,
      ...rulesetInfo(),
      "GET /api/rulesets/adnd2e/monsters/77": () => json(200, goblin),
      "GET /api/monster-pictures?name=Goblin": state(true),
      "POST /api/monster-pictures": () =>
        json(202, { slug: "goblin", picture: true, version: "v1", painting: true, error: null, paid: false }),
    });
    renderArea("/rulesets/adnd2e/monsters/77");
    const figure = await screen.findByTestId("monster-picture");
    expect(within(figure).getByRole("img", { name: "Goblin" }).getAttribute("src")).toBe("/api/monster-pictures/goblin?v=v1");
    fireEvent.click(within(figure).getByRole("button", { name: /Paint again/ }));
    const dialog = await screen.findByTestId("paint-monster");
    expect(within(dialog).getByText("Paint Goblin again")).toBeTruthy();
    fireEvent.click(within(dialog).getByTestId("paint-monster-go"));
    await screen.findByTestId("monster-picture");
    const posted = fetchMock.mock.calls.find(([path, init]) => path === "/api/monster-pictures" && init?.method === "POST");
    expect(JSON.parse(String(posted?.[1]?.body))).toMatchObject({ name: "Goblin", ruleset: "adnd2e" }); // DEL-384
  });

  it("shows the shared picture but no Paint for a ruleset that reuses pictures (DEL-384)", async () => {
    stubFetch({
      "GET /api/me": owner,
      ...rulesetInfo(null, { playable: false, monster_pictures: "reuse" }),
      "GET /api/rulesets/adnd2e/monsters/77": () => json(200, goblin),
      "GET /api/monster-pictures?name=Goblin": state(true),
    });
    renderArea("/rulesets/adnd2e/monsters/77");
    const figure = await screen.findByTestId("monster-picture");
    expect(within(figure).getByRole("img", { name: "Goblin" })).toBeTruthy();
    expect(screen.queryByTestId("monster-paint")).toBeNull();
  });

  it("shows an organiser nothing for a kind without a picture when its ruleset reuses pictures", async () => {
    const fetchMock = stubFetch({
      "GET /api/me": owner,
      ...rulesetInfo(null, { monster_pictures: "reuse" }),
      "GET /api/rulesets/adnd2e/monsters/77": () => json(200, goblin),
      "GET /api/monster-pictures?name=Goblin": state(false),
    });
    renderArea("/rulesets/adnd2e/monsters/77");
    await waitFor(() =>
      expect(fetchMock.mock.calls.some(([path]) => path === "/api/monster-pictures?name=Goblin")).toBe(true),
    );
    await new Promise((settle) => setTimeout(settle, 50)); // the picture's state has been answered and rendered
    expect(screen.queryByTestId("monster-picture")).toBeNull();
  });

  it("shows a player nothing for a kind without a picture, and no Paint for one with", async () => {
    stubFetch({
      "GET /api/me": player,
      ...rulesetInfo(),
      "GET /api/rulesets/adnd2e/monsters/77": () => json(200, goblin),
      "GET /api/monster-pictures?name=Goblin": state(false),
    });
    renderArea("/rulesets/adnd2e/monsters/77");
    expect(await screen.findByRole("heading", { level: 1, name: "Goblin" })).toBeTruthy();
    expect(screen.queryByTestId("monster-picture")).toBeNull();
    expect(screen.queryByRole("button", { name: /Paint/ })).toBeNull();
  });
});
