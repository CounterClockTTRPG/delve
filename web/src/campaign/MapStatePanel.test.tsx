import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { Character } from "../api";
import { I18nProvider } from "../i18n";
import MapStatePanel from "./MapStatePanel";

const CAMPAIGN = "cmp_00000000000a";
const base = `/api/campaigns/${CAMPAIGN}/maps/crypt`;
function pc(id: string, name: string, order: number): Character {
  return {
    id,
    campaign_id: CAMPAIGN,
    name,
    kind: "pc",
    order,
    encumbrance: null,
    created_at: "2026-10-17T12:00:00Z",
    sheet: {
      kind: "pc",
      label: name,
      race: "",
      gender: "",
      cls: "",
      levels: {},
      hp_max: 0,
      ac: 10,
      thac0: 20,
      saves: {},
      ability_scores: {},
      attacks: [],
      weapon: "",
      movement_rate: 12,
      alignment: "",
      spell_slots: {},
    },
    state: { hp: 0, xp: 0, conditions: [], effects: [] },
  };
}
const characters: Character[] = [
  pc("chr_00000000000a", "Ash", 0),
  pc("chr_00000000000b", "Birch", 1),
  pc("chr_00000000000c", "Cedar", 2),
];
const state = {
  characters: {
    chr_00000000000a: { location: "room.entry", nodes: ["room.entry"], doors: [] },
    chr_00000000000b: { location: "room.entry", nodes: ["room.entry"], doors: [] },
  },
  door_states: { "entry-hall": "open" },
  revealed: [],
  groups: [],
};
const doorsAndSecrets = {
  doors: [
    { key: "entry-hall", type: "wooden", nodes: ["room.entry", "corridor.hall"] },
    { key: "vault-door", type: "secret", nodes: ["room.entry", "room.vault"] },
    { key: "12,4", type: "iron", nodes: ["room.vault"] },
  ],
  secrets: [{ key: "room.vault/feature@3,3", kind: "feature", label: "lever", node: "room.vault" }],
};
const ALL = "chr_00000000000a,chr_00000000000b,chr_00000000000c";

type Handler = (init: RequestInit | undefined) => Response;
let routes: Record<string, Handler>;
let fetchMock: ReturnType<typeof vi.fn>;

function json(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
}

beforeEach(() => {
  routes = {
    [`GET ${base}/state`]: () => json(200, state),
    [`GET ${base}/view?characters=${ALL}`]: () => json(200, { svg: '<svg data-view="characters"></svg>' }),
    [`GET ${base}/dm-view`]: () => json(200, { svg: '<svg data-view="dm"></svg>' }),
    [`GET ${base}/doors-and-secrets`]: () => json(200, doorsAndSecrets),
  };
  fetchMock = vi.fn(async (path: string, init?: RequestInit) => {
    const handler = routes[`${init?.method ?? "GET"} ${path}`];
    return handler ? handler(init) : json(404, { error: "not found" });
  });
  vi.stubGlobal("fetch", fetchMock);
});

afterEach(() => {
  vi.unstubAllGlobals();
});

function renderPanel(language = "en") {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <I18nProvider language={language}>
        <MapStatePanel campaignId={CAMPAIGN} mapName="crypt" characters={characters} />
      </I18nProvider>
    </QueryClientProvider>,
  );
}

function paths(): string[] {
  return fetchMock.mock.calls.map(([p]) => String(p));
}

function posted(path: string): unknown[] {
  return fetchMock.mock.calls
    .filter(([p, init]) => p === path && init?.method === "POST")
    .map(([, init]) => JSON.parse(String(init.body)));
}

describe("MapStatePanel", () => {
  it("posts a move for the selected characters", async () => {
    routes[`POST ${base}/move`] = () => json(200, state);
    renderPanel();
    fireEvent.click(await screen.findByRole("checkbox", { name: "Cedar" }));
    fireEvent.change(screen.getByLabelText("Node"), { target: { value: "room.hall" } });
    fireEvent.click(screen.getByRole("button", { name: "Move to" }));

    await waitFor(() =>
      expect(posted(`${base}/move`)).toEqual([{ characters: ["chr_00000000000a", "chr_00000000000b"], to: "room.hall" }]),
    );
  });

  it("starts the selected characters at the map's start", async () => {
    routes[`POST ${base}/start`] = () => json(200, state);
    renderPanel();
    fireEvent.click(await screen.findByRole("button", { name: "Start" }));
    await waitFor(() =>
      expect(posted(`${base}/start`)).toEqual([
        { characters: ["chr_00000000000a", "chr_00000000000b", "chr_00000000000c"] },
      ]),
    );
  });

  it("offers the candidates from a 404 and moves to the one picked", async () => {
    routes[`POST ${base}/move`] = (init) =>
      JSON.parse(String(init?.body)).to === "hall"
        ? json(404, {
            error: "unknown node 'hall'",
            candidates: [
              { id: "room.hall", label: "Hall" },
              { id: "room.great_hall", label: "Great Hall" },
            ],
          })
        : json(200, state);
    renderPanel();
    fireEvent.change(await screen.findByLabelText("Node"), { target: { value: "hall" } });
    fireEvent.click(screen.getByRole("button", { name: "Move to" }));

    const pick = await screen.findByRole("group", { name: "Did you mean" });
    fireEvent.click(within(pick).getByRole("button", { name: "Great Hall (room.great_hall)" }));
    await waitFor(() => expect(posted(`${base}/move`).map((b) => (b as { to: string }).to)).toEqual(["hall", "room.great_hall"]));
    await waitFor(() => expect(screen.queryByRole("group", { name: "Did you mean" })).toBeNull());
  });

  it("reveals a node, sets a door and reveals a secret", async () => {
    routes[`POST ${base}/reveal`] = () => json(200, state);
    routes[`POST ${base}/door`] = () => json(200, state);
    routes[`POST ${base}/secret`] = () => json(200, state);
    renderPanel();
    fireEvent.change(await screen.findByLabelText("Node"), { target: { value: "room.vault" } });
    fireEvent.click(screen.getByRole("button", { name: "Reveal" }));
    await waitFor(() =>
      expect(posted(`${base}/reveal`)).toEqual([
        { characters: ["chr_00000000000a", "chr_00000000000b", "chr_00000000000c"], node: "room.vault", reveal_doors: true },
      ]),
    );

    // The controls wait for the change before them.
    const setDoorButton = screen.getByRole("button", { name: "Set door" }) as HTMLButtonElement;
    await waitFor(() => expect(setDoorButton.disabled).toBe(false));
    fireEvent.change(screen.getByLabelText("Door"), { target: { value: "vault-door" } });
    fireEvent.change(screen.getByLabelText("State"), { target: { value: "locked" } });
    fireEvent.click(setDoorButton);
    await waitFor(() => expect(posted(`${base}/door`)).toEqual([{ door: "vault-door", state: "locked" }]));

    const secretButton = screen.getByRole("button", { name: "Reveal secret" }) as HTMLButtonElement;
    await waitFor(() => expect(secretButton.disabled).toBe(false));
    fireEvent.change(screen.getByLabelText("Secret"), { target: { value: "room.vault/feature@3,3" } });
    fireEvent.click(secretButton);
    await waitFor(() => expect(posted(`${base}/secret`)).toEqual([{ key: "room.vault/feature@3,3" }]));
  });

  it("doors and secrets are picked from the map", async () => {
    renderPanel();
    const door = (await screen.findByLabelText("Door")) as HTMLSelectElement;
    const secret = screen.getByLabelText("Secret") as HTMLSelectElement;
    expect(door.tagName).toBe("SELECT");
    expect(secret.tagName).toBe("SELECT");
    await waitFor(() => expect([...door.options].map((o) => o.value)).toEqual(["entry-hall", "vault-door", "12,4"]));
    expect([...door.options].map((o) => o.textContent)).toEqual([
      "entry-hall (room.entry – corridor.hall, wooden)",
      "vault-door (room.entry – room.vault, secret)",
      "12,4 (room.vault, iron)",
    ]);
    expect([...secret.options].map((o) => [o.value, o.textContent])).toEqual([["room.vault/feature@3,3", "lever (room.vault/feature@3,3)"]]);
    const form = (field: HTMLElement) => field.closest("form") as HTMLFormElement;
    expect(within(form(door)).queryByRole("textbox")).toBeNull();
    expect(within(form(secret)).queryByRole("textbox")).toBeNull();
  });

  it("a map without doors or secrets offers none to pick", async () => {
    routes[`GET ${base}/doors-and-secrets`] = () => json(200, { doors: [], secrets: [] });
    renderPanel();
    const door = (await screen.findByLabelText("Door")) as HTMLSelectElement;
    await waitFor(() => expect([...door.options].map((o) => o.textContent)).toEqual(["None on this map"]));
    const secret = screen.getByLabelText("Secret") as HTMLSelectElement;
    expect([...secret.options].map((o) => o.textContent)).toEqual(["None on this map"]);
    expect(door.options[0].disabled).toBe(true);
    expect((screen.getByRole("button", { name: "Set door" }) as HTMLButtonElement).disabled).toBe(true);
    expect((screen.getByRole("button", { name: "Reveal secret" }) as HTMLButtonElement).disabled).toBe(true);
  });

  it("shows where each character is", async () => {
    renderPanel();
    const where = await screen.findByRole("list", { name: "Positions" });
    await waitFor(() => expect(within(where).getAllByRole("listitem")).toHaveLength(3));
    expect(within(where).getByText("Ash").parentElement?.textContent).toContain("room.entry");
    expect(within(where).getByText("Cedar").parentElement?.textContent).toContain("Not on this map");
  });

  it("a 409 shows Map offline", async () => {
    routes[`GET ${base}/view?characters=${ALL}`] = () => json(409, { error: "map offline" });
    renderPanel();
    expect(await screen.findByText("Map offline")).toBeTruthy();
  });

  it("says Map offline in Dutch too", async () => {
    routes[`GET ${base}/view?characters=${ALL}`] = () => json(409, { error: "map offline" });
    renderPanel("nl");
    expect(await screen.findByText("Kaart offline")).toBeTruthy();
  });

  it("the DM view tab calls dm-view and the characters' tab never does", async () => {
    routes[`POST ${base}/move`] = () => json(200, state);
    const { container } = renderPanel();
    const players = await screen.findByRole("tab", { name: "Characters' view" });
    expect(players.getAttribute("aria-selected")).toBe("true");
    await waitFor(() => expect(container.querySelector('svg[data-view="characters"]')).not.toBeNull());

    // Changing the selection and moving re-fetch the characters' view, still without the DM view.
    fireEvent.click(screen.getByRole("checkbox", { name: "Cedar" }));
    fireEvent.change(screen.getByLabelText("Node"), { target: { value: "room.hall" } });
    fireEvent.click(screen.getByRole("button", { name: "Move to" }));
    await waitFor(() => expect(posted(`${base}/move`)).toHaveLength(1));
    await waitFor(() => expect(paths()).toContain(`${base}/view?characters=chr_00000000000a,chr_00000000000b`));
    expect(paths().some((p) => p.includes("dm-view"))).toBe(false);

    const dm = screen.getByRole("tab", { name: "DM view" });
    fireEvent.click(dm);
    expect(dm.getAttribute("aria-selected")).toBe("true");
    await waitFor(() => expect(container.querySelector('svg[data-view="dm"]')).not.toBeNull());
    expect(paths().filter((p) => p.includes("dm-view"))).toEqual([`${base}/dm-view`]);
    expect(screen.getByRole("tabpanel").className).toContain("dm-view");
    expect(paths().every((p) => !/[?&](scope|full|view)=/.test(p))).toBe(true);
  });

  it("asks for characters before showing their view", async () => {
    renderPanel();
    for (const c of characters) fireEvent.click(await screen.findByRole("checkbox", { name: c.name }));
    expect(await screen.findByText("Pick one or more characters to see what they know.")).toBeTruthy();
    expect((screen.getByRole("button", { name: "Move to" }) as HTMLButtonElement).disabled).toBe(true);
  });
});
