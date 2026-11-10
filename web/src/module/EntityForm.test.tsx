import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { EntityKind, EntityRecord, ModuleSource } from "../api";
import { I18nProvider } from "../i18n";
import EntityForm from "./EntityForm";

const MODULE = "mod_0123456789ab";

function source(): ModuleSource {
  return {
    texts: [],
    entities: {
      npcs: [
        { id: "ritualist", name: "Brother Kael" },
        { id: "prior-anselm", name: "Prior Anselm" },
      ],
      encounters: [{ id: "c2-saint", name: "The risen saint" }],
      factions: [{ id: "cult", name: "The Violet Circle" }],
      quests: [],
    },
    attachments: [
      { id: "kael-portrait", type: "image/png", sha256: "aa", size: 10, description: "Brother Kael, robed", audience: "gm" },
      { id: "crypt-plan", type: "application/pdf", sha256: "bb", size: 10, description: "The crypt plan", audience: "gm" },
    ],
    keys: [{ key: "C7", title: "The Pass", text: "text:road#c7", npcs: [] }],
    links: [
      { text_id: "crypt-key", anchor: "c1", key: "C1", map: "crypt", node: "room.entry_hall", label: "Entry Hall", explicit: true },
      { text_id: "crypt-key", anchor: "c2", key: "C2", map: "crypt", node: "room.throne_chamber", label: "Throne Chamber", explicit: true },
      // A sketched map labels its rooms like the heading, key and all.
      { text_id: "road", anchor: "4", key: "4", map: "road", node: "room.r4", label: "4. The Destroyed Caravan", explicit: false },
    ],
    warnings: [],
  };
}

let reply: (body: unknown) => Response;
let fetchMock: ReturnType<typeof vi.fn>;

function json(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
}

beforeEach(() => {
  reply = (body) => json(200, { record: body, warnings: [] });
  fetchMock = vi.fn(async (_path: string, init?: RequestInit) => reply(JSON.parse(String(init?.body ?? "{}"))));
  vi.stubGlobal("fetch", fetchMock);
});

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

function renderForm(kind: EntityKind, record: EntityRecord | null, onSaved = vi.fn(), withSource = source(), maps: string[] = []) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <I18nProvider language="en">
        <EntityForm moduleId={MODULE} kind={kind} record={record} source={withSource} maps={maps} onSaved={onSaved} />
      </I18nProvider>
    </QueryClientProvider>,
  );
  return onSaved;
}

const type = (label: string, value: string) => fireEvent.change(screen.getByLabelText(label), { target: { value } });

function sent() {
  const puts = fetchMock.mock.calls.filter(([, init]) => init?.method === "PUT");
  expect(puts).toHaveLength(1);
  return { path: puts[0][0] as string, body: JSON.parse(String(puts[0][1].body)) };
}

describe("EntityForm", () => {
  it("saves a new NPC as the format's record", async () => {
    const onSaved = renderForm("npcs", null);
    type("Name", "Brother Ansel");
    type("Summary", "Keeps the abbey gate.");
    type("Who sees it", "player");
    type("Race", "human");
    type("Class", "cleric");
    type("Level", "3");
    type("AC", "5");
    type("HP", "14");
    type("Disposition", "40");
    type("Notes", "Serves the [[faction:cult]] in secret.");
    type("Portrait", "kael-portrait");
    // Only images can be a portrait.
    expect([...(screen.getByLabelText("Portrait") as HTMLSelectElement).options].map((o) => o.value)).toEqual(["", "kael-portrait"]);
    fireEvent.click(screen.getByRole("button", { name: "Save" }));

    await waitFor(() => expect(onSaved).toHaveBeenCalled());
    const { path, body } = sent();
    expect(path).toBe(`/api/modules/${MODULE}/entities/npcs/brother-ansel`);
    expect(body).toEqual({
      id: "brother-ansel",
      name: "Brother Ansel",
      audience: "player",
      summary: "Keeps the abbey gate.",
      description: "Serves the [[faction:cult]] in secret.",
      portrait: "asset:kael-portrait",
      disposition: 40,
      stats: { adnd2e: { race: "human", class: "cleric", level: 3, ac: 5, hp: 14 } },
    });
  });

  it("keeps what the form doesn't show, and the id, when an NPC is edited", async () => {
    const kael: EntityRecord = {
      id: "ritualist",
      name: "Brother Kael",
      role: "cult priest",
      location: "key:C2",
      stats: { adnd2e: { ac: 6, hd: 3, hp: 18, thac0: 18, attacks: "1d6+1 (mace)" } },
      "x-source": "p. 4",
    };
    renderForm("npcs", kael);
    expect((screen.getByLabelText("HD") as HTMLInputElement).value).toBe("3");
    expect((screen.getByLabelText("Who sees it") as HTMLSelectElement).value).toBe("gm");
    expect(screen.getByRole("option", { name: "DM only" })).toBeTruthy();
    type("Name", "Brother Kael the Younger");
    type("HP", "20");
    fireEvent.click(screen.getByRole("button", { name: "Save" }));
    await waitFor(() => expect(fetchMock).toHaveBeenCalled());
    const { path, body } = sent();
    expect(path).toBe(`/api/modules/${MODULE}/entities/npcs/ritualist`);
    expect(body).toEqual({
      id: "ritualist",
      name: "Brother Kael the Younger",
      role: "cult priest",
      location: "key:C2",
      stats: { adnd2e: { ac: 6, hd: 3, hp: 20, thac0: 18, attacks: "1d6+1 (mace)" } },
      "x-source": "p. 4",
    });
  });

  it("shows the server's refusal beside its field", async () => {
    reply = () =>
      json(422, {
        error: "The record doesn't fit the module schema.",
        diagnostics: [
          { severity: "error", code: "type", message: "'three' is not of type 'integer'", path: "stats/adnd2e/level" },
          { severity: "error", code: "type", message: "Something else is wrong", path: "x-other" },
        ],
      });
    const onSaved = renderForm("npcs", null);
    type("Name", "Brother Ansel");
    type("Level", "three");
    fireEvent.click(screen.getByRole("button", { name: "Save" }));
    const message = await screen.findByText("'three' is not of type 'integer'");
    const field = message.closest(".field") as HTMLElement;
    expect(within(field).getByLabelText("Level")).toBeTruthy();
    // One that is at no field of the form shows above it.
    expect(screen.getByText("x-other: Something else is wrong")).toBeTruthy();
    expect(onSaved).not.toHaveBeenCalled();
  });

  it("keeps a disposition between −100 and 100", async () => {
    renderForm("npcs", null);
    type("Name", "Brother Ansel");
    type("Disposition", "150");
    fireEvent.click(screen.getByRole("button", { name: "Save" }));
    const message = await screen.findByText("A disposition is from −100 to 100.");
    expect(within(message.closest(".field") as HTMLElement).getByLabelText("Disposition")).toBeTruthy();
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("saves an encounter with where it is and its monsters", async () => {
    renderForm("encounters", null);
    type("Name", "Rats in the hall");
    type("Where", "key:C1");
    type("Kind", "dungeon");
    type("Conditions", "Only at night.");
    fireEvent.click(screen.getByRole("button", { name: "Add a monster" }));
    type("Creature 1", "Giant rat");
    type("Count 1", "1d6");
    fireEvent.click(screen.getByRole("button", { name: "Add a monster" }));
    type("NPC 2", "ritualist");
    type("Count 2", "1");
    type("Notes 2", "Watches from the dark");
    fireEvent.click(screen.getByRole("button", { name: "Save" }));
    await waitFor(() => expect(fetchMock).toHaveBeenCalled());
    expect(sent().body).toEqual({
      id: "rats-in-the-hall",
      name: "Rats in the hall",
      key: "key:C1",
      kind: "dungeon",
      description: "Only at night.",
      fixed: [
        { creature: "monster:giant-rat", count: "1d6" },
        { creature: "npc:ritualist", count: 1, notes: "Watches from the dark" },
      ],
    });
    // Where: the module's keys, by their rooms.
    expect(screen.getByRole("option", { name: "C2. Throne Chamber" })).toBeTruthy();
  });

  it("marks a table as wandering and places it on a map or a text, keeping a room it was placed in (DEL-321)", async () => {
    const level: EntityRecord = {
      id: "level-2-wandering-monsters",
      name: "Level 2 wandering monsters",
      kind: "dungeon",
      table: [{ roll: "1", result: "1d4 giant rats" }],
      where: ["key:C1"],
    };
    const withTexts = { ...source(), texts: [{ id: "level-2-key", title: "Level 2", audience: "gm" as const, map: "level-2", markdown: "" }] };
    renderForm("encounters", level, vi.fn(), withTexts, ["level-1", "level-2"]);
    // An older module's table, named as one, reads as wandering.
    expect((screen.getByLabelText(/^Wandering monsters/) as HTMLInputElement).checked).toBe(true);
    fireEvent.click(screen.getByLabelText("Map level-2"));
    fireEvent.click(screen.getByLabelText("Level 2"));
    fireEvent.click(screen.getByRole("button", { name: "Save" }));
    await waitFor(() => expect(fetchMock).toHaveBeenCalled());
    expect(sent().body).toMatchObject({ wandering: true, where: ["key:C1", "map:level-2", "text:level-2-key"] });
  });

  it("leaves a room's own table out of the wandering checks", async () => {
    renderForm("encounters", { id: "pool", name: "The pool", key: "key:C2", table: [{ roll: "1", result: "a nixie" }] });
    const tick = screen.getByLabelText(/^Wandering monsters/) as HTMLInputElement;
    expect(tick.checked).toBe(false);
    expect(screen.queryByText("Rolled where")).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Save" }));
    await waitFor(() => expect(fetchMock).toHaveBeenCalled());
    expect(sent().body.wandering).toBe(false);
    expect(sent().body.where).toBeUndefined();
  });

  it("saves an NPC with the keyed room it is in", async () => {
    renderForm("npcs", { id: "jon", name: "Farmer Jon", location: "text:road#c7" });
    const where = screen.getByLabelText("Where") as HTMLSelectElement;
    expect(where.value).toBe("text:road#c7");
    // The module's keyed rooms, each number once.
    expect([...where.options].map((o) => o.text)).toEqual([
      "None",
      "C1. Entry Hall",
      "C2. Throne Chamber",
      "4. The Destroyed Caravan",
      "C7. The Pass",
    ]);
    type("Where", "text:road#4");
    fireEvent.click(screen.getByRole("button", { name: "Save" }));
    await waitFor(() => expect(fetchMock).toHaveBeenCalled());
    expect(sent().body).toEqual({ id: "jon", name: "Farmer Jon", location: "text:road#4" });
  });

  it("offers an encounter the rooms without doubled numbers", () => {
    renderForm("encounters", null);
    expect(screen.getByRole("option", { name: "4. The Destroyed Caravan" })).toBeTruthy();
    expect(screen.queryByRole("option", { name: "4. 4. The Destroyed Caravan" })).toBeNull();
  });

  it("shows and edits an NPC's stat line as printed", async () => {
    const sanbalet: EntityRecord = {
      id: "sanbalet",
      name: "Sanbalet",
      stats: { adnd2e: { ac: 10, line: "AC 10; MV 12; MU 3; hp 9; #AT 1; D 1-4 (dagger)" } },
    };
    renderForm("npcs", sanbalet);
    const line = screen.getByLabelText("Stat line") as HTMLTextAreaElement;
    expect(line.tagName).toBe("TEXTAREA");
    expect(line.value).toBe("AC 10; MV 12; MU 3; hp 9; #AT 1; D 1-4 (dagger)");
    type("Stat line", "AC 10; MV 12; MU 3; hp 10; #AT 1; D 1-4 (dagger)");
    fireEvent.click(screen.getByRole("button", { name: "Save" }));
    await waitFor(() => expect(fetchMock).toHaveBeenCalled());
    expect(sent().body.stats).toEqual({ adnd2e: { ac: 10, line: "AC 10; MV 12; MU 3; hp 10; #AT 1; D 1-4 (dagger)" } });
  });

  it("shows a monster's stat line in its notes", () => {
    const line = "AC 7; MV 9; HD 1-1; hp 4 each; #AT 1; D 1-6; AL LE; XP 7 each";
    renderForm("encounters", { id: "gnolls", name: "Gnolls", fixed: [{ creature: "monster:gnoll", count: 6, notes: line }] });
    const notes = screen.getByLabelText("Notes 1") as HTMLTextAreaElement;
    expect(notes.tagName).toBe("TEXTAREA");
    expect(notes.value).toBe(line);
  });

  it("offers every keyed heading as Where, linked to a room or not", async () => {
    const withHeadings = {
      ...source(),
      headings: [
        { key: "C1", title: "Entry Hall", text_id: "crypt-key", anchor: "c1" },
        { key: "haunted-house-19", title: "Cellar Stair", text_id: "house", anchor: "19" },
      ],
    };
    renderForm("encounters", null, vi.fn(), withHeadings);
    const where = screen.getByLabelText("Where") as HTMLSelectElement;
    expect([...where.options].map((o) => [o.value, o.text])).toContainEqual(["key:haunted-house-19", "haunted-house-19. Cellar Stair"]);
    // A heading linked to its room is offered once.
    expect([...where.options].filter((o) => o.value === "key:C1")).toHaveLength(1);
    type("Name", "Rats on the stair");
    type("Where", "key:haunted-house-19");
    fireEvent.click(screen.getByRole("button", { name: "Save" }));
    await waitFor(() => expect(fetchMock).toHaveBeenCalled());
    expect(sent().body.key).toBe("key:haunted-house-19");
    cleanup();
    renderForm("npcs", null, vi.fn(), withHeadings);
    expect(screen.getByRole("option", { name: "haunted-house-19. Cellar Stair" }).getAttribute("value")).toBe("text:house#19");
  });

  it("saves a pregen with its abilities and hit points in stats.adnd2e and its gear one per line", async () => {
    renderForm("pregens", null);
    expect((screen.getByLabelText("Who sees it") as HTMLSelectElement).value).toBe("player");
    type("Name", "Ned Shakeshaft");
    type("Race", "human");
    type("Class", "thief");
    type("Level", "3");
    type("Alignment", "CN");
    type("Background", "A young rogue from Saltmarsh.");
    type("Str", "18/76");
    type("Dex", "17");
    type("Con", "12");
    type("Int", "13");
    type("Wis", "9");
    type("Cha", "14");
    type("HP", "12");
    type("Gear", "leather armour\n short sword \n\nthieves' picks");
    fireEvent.click(screen.getByRole("button", { name: "Save" }));
    await waitFor(() => expect(fetchMock).toHaveBeenCalled());
    const { path, body } = sent();
    expect(path).toBe(`/api/modules/${MODULE}/entities/pregens/ned-shakeshaft`);
    expect(body).toEqual({
      id: "ned-shakeshaft",
      name: "Ned Shakeshaft",
      audience: "player",
      race: "human",
      class: "thief",
      level: 3,
      alignment: "CN",
      background: "A young rogue from Saltmarsh.",
      gear: ["leather armour", "short sword", "thieves' picks"],
      stats: { adnd2e: { ability_scores: { str: "18/76", dex: 17, con: 12, int: 13, wis: 9, cha: 14 }, hp_max: 12 } },
    });
  });

  it("keeps a pregen's other sheet fields and shows a multi-class level as printed", async () => {
    const ilsa: EntityRecord = {
      id: "ilsa",
      name: "Ilsa",
      audience: "gm",
      race: "½E",
      class: "fighter/mage",
      level: "3/3",
      stats: { adnd2e: { ability_scores: { str: 15 }, hp_max: 14, ac: 4, weapon_profs: ["long sword"] } },
    };
    renderForm("pregens", ilsa);
    expect((screen.getByLabelText("Level") as HTMLInputElement).value).toBe("3/3");
    expect((screen.getByLabelText("Who sees it") as HTMLSelectElement).value).toBe("gm");
    type("Dex", "16");
    fireEvent.click(screen.getByRole("button", { name: "Save" }));
    await waitFor(() => expect(fetchMock).toHaveBeenCalled());
    expect(sent().body).toEqual({
      ...ilsa,
      stats: { adnd2e: { ability_scores: { str: 15, dex: 16 }, hp_max: 14, ac: 4, weapon_profs: ["long sword"] } },
    });
  });

  it("saves a faction with its members", async () => {
    renderForm("factions", null);
    type("Name", "The Grey Lantern");
    type("Goals", "Keep the abbey sealed.");
    fireEvent.click(screen.getByLabelText("Prior Anselm"));
    type("Alignment", "lawful good");
    type("Scope", "local");
    fireEvent.click(screen.getByRole("button", { name: "Save" }));
    await waitFor(() => expect(fetchMock).toHaveBeenCalled());
    expect(sent().body).toEqual({
      id: "the-grey-lantern",
      name: "The Grey Lantern",
      goals: "Keep the abbey sealed.",
      members: ["npc:prior-anselm"],
      alignment: "lawful good",
      scope: "local",
    });
  });

  it("saves a quest with its giver and related refs", async () => {
    renderForm("quests", null);
    type("Name", "Stop the binding");
    type("Giver", "npc:prior-anselm");
    type("Stakes", "The saint wakes.");
    fireEvent.click(screen.getByLabelText("The risen saint"));
    fireEvent.click(screen.getByLabelText("The Violet Circle"));
    fireEvent.click(screen.getByRole("button", { name: "Save" }));
    await waitFor(() => expect(fetchMock).toHaveBeenCalled());
    expect(sent().body).toEqual({
      id: "stop-the-binding",
      name: "Stop the binding",
      giver: "npc:prior-anselm",
      stakes: "The saint wakes.",
      related: ["faction:cult", "encounter:c2-saint"],
    });
  });

  it("gives prose a text area and keeps short values on one line", () => {
    // Summaries run to several sentences in real modules (up to ~700 characters), and so do quest stakes.
    for (const kind of ["npcs", "encounters", "factions", "quests"] as EntityKind[]) {
      renderForm(kind, null);
      expect(screen.getByLabelText("Summary").tagName, kind).toBe("TEXTAREA");
      expect(screen.getByLabelText("Name").tagName, kind).toBe("INPUT");
      cleanup();
    }
    renderForm("quests", null);
    expect(screen.getByLabelText("Stakes").tagName).toBe("TEXTAREA");
    expect(screen.getByLabelText("Scope").tagName).toBe("INPUT");
  });

  it("gives a new entity an id that isn't taken", async () => {
    renderForm("npcs", null);
    type("Name", "Ritualist");
    fireEvent.click(screen.getByRole("button", { name: "Save" }));
    await waitFor(() => expect(fetchMock).toHaveBeenCalled());
    expect(sent().path).toBe(`/api/modules/${MODULE}/entities/npcs/ritualist-2`);
  });
});
