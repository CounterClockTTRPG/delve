import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { createMemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import App, { routes as appRoutes } from "./App";

type Handler = () => Response;
let routes: Record<string, Handler>;
let fetchMock: ReturnType<typeof vi.fn>;

function json(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
}

class FakeEventSource {
  static instances: FakeEventSource[] = [];
  static CLOSED = 2;
  listeners: Record<string, ((e: MessageEvent) => void)[]> = {};
  closed = false;
  readyState = 1;
  constructor(public url: string) {
    FakeEventSource.instances.push(this);
  }
  addEventListener(type: string, fn: (e: MessageEvent) => void) {
    (this.listeners[type] ??= []).push(fn);
  }
  removeEventListener() {}
  close() {
    this.closed = true;
  }
  emit(type: string, data: unknown) {
    for (const fn of this.listeners[type] ?? []) fn(new MessageEvent(type, { data: JSON.stringify(data) }));
  }
}

const preferences = { choices: {}, language: "en", warnings: [] };
const backends = { jobs: [], providers: [] };

beforeEach(() => {
  FakeEventSource.instances = [];
  routes = {
    "/api/preferences": () => json(200, preferences),
    "/api/backends": () => json(200, backends),
    "/api/campaigns": () => json(200, []),
    "/api/modules": () => json(200, []),
    "/api/house-rules": () => json(200, []),
    "/api/house-rule-bundles": () => json(200, []),
  };
  fetchMock = vi.fn(async (path: string) => (routes[path] ?? (() => json(404, { error: "not found" })))());
  vi.stubGlobal("fetch", fetchMock);
  vi.stubGlobal("EventSource", FakeEventSource);
});

afterEach(() => {
  vi.unstubAllGlobals();
});

function renderAt(path: string) {
  return render(<App router={createMemoryRouter(appRoutes, { initialEntries: [path] })} />);
}

function preferencesCalls(): number {
  return fetchMock.mock.calls.filter(([p]) => p === "/api/preferences").length;
}

describe("App", () => {
  it("loads the organiser's screens when opened, and keeps Play and Join in the main bundle (DEL-240)", () => {
    const flat = (list: typeof appRoutes): typeof appRoutes => list.flatMap((r) => [r, ...flat(r.children ?? [])]);
    const byPath = new Map(flat(appRoutes).filter((r) => r.path).map((r) => [r.path!, r]));
    for (const path of ["/campaigns", "/campaigns/:id", "/modules", "/modules/:moduleId", "/maps", "/house-rules", "/settings", "/preferences", "/rulesets", "/novels/:id", "/modules/:moduleId/print"]) {
      expect(byPath.get(path)?.lazy, path).toBeTypeOf("function");
      expect(byPath.get(path)?.element, path).toBeUndefined();
    }
    for (const path of ["/play", "/play/:campaignId", "/join/:token", "/tables", "/"]) {
      expect(byPath.get(path)?.element, path).toBeTruthy();
      expect(byPath.get(path)?.lazy, path).toBeUndefined();
    }
  });

  it("a 401 shows the login page, not the token page", async () => {
    routes["/api/me"] = () => json(401, { error: "Log in to Delve." });
    routes["/api/preferences"] = () => json(401, { error: "Log in to Delve." });
    renderAt("/preferences");
    expect(await screen.findByRole("heading", { name: "Log in to Delve" })).toBeTruthy();
    expect(screen.getByTestId("login-username")).toBeTruthy();
    expect(screen.queryByText(/token/i)).toBeNull();
    expect(screen.queryByRole("navigation")).toBeNull();
  });

  it("shows the public front page at /, for anyone (DEL-144)", async () => {
    renderAt("/");
    expect(await screen.findByRole("heading", { level: 1, name: "Delve" })).toBeTruthy();
    expect(screen.queryByRole("navigation", { name: /areas/i })).toBeNull();
  });

  it("redirects /home to /campaigns", async () => {
    renderAt("/home");
    expect(await screen.findByRole("heading", { name: "Campaigns" })).toBeTruthy();
    // Nothing yet: the first-run guide.
    expect(await screen.findByRole("region", { name: "Getting started" })).toBeTruthy();
  });

  it("shows the nine areas in the nav, Rulesets between House rules and Settings, the Board before Preferences", async () => {
    renderAt("/play");
    const nav = await screen.findByRole("navigation");
    const labels = Array.from(nav.querySelectorAll("a")).map((a) => a.textContent);
    expect(labels).toEqual(["Play", "Campaigns", "Modules", "Maps", "House rules", "Rulesets", "Settings", "Board", "Preferences"]);
    expect(within(nav).getByRole("link", { name: "Rulesets" }).getAttribute("href")).toBe("/rulesets");
    expect(within(nav).getByRole("link", { name: "Board" }).getAttribute("href")).toBe("/board");
  });

  it("the first Tab reaches Skip to content", async () => {
    renderAt("/campaigns");
    await screen.findByRole("navigation");
    // The first thing a Tab reaches, in document order, before the nav.
    const tabbable = document.querySelectorAll<HTMLElement>(
      "a[href], button, input, select, textarea, [tabindex]:not([tabindex='-1'])",
    );
    const skip = screen.getByRole("link", { name: "Skip to content" });
    expect(tabbable[0]).toBe(skip);
    fireEvent.click(skip);
    const main = document.querySelector("main#content");
    expect(main).not.toBeNull();
    expect(document.activeElement).toBe(main);
  });

  it("renders the settings list at /settings", async () => {
    routes["/api/settings"] = () => json(200, [{ id: "greyhawk", title: "Greyhawk" }]);
    renderAt("/settings");
    expect(await screen.findByRole("heading", { level: 1, name: "Settings" })).toBeTruthy();
    expect((await screen.findByRole("link", { name: "Greyhawk" })).getAttribute("href")).toBe("/settings/greyhawk");
  });

  it("re-fetches a setting on the SSE setting event, and not another one's", async () => {
    let title = "Greyhawk";
    routes["/api/settings/greyhawk"] = () =>
      json(200, { id: "greyhawk", title, kinds: [], calendar: null, counts: { pages: 0, facts: 0, proposals: 0 }, maps_in_use: "built-in", built_in_maps: [] });
    renderAt("/settings/greyhawk");
    expect(await screen.findByRole("heading", { level: 1, name: "Greyhawk" })).toBeTruthy();
    const calls = () => fetchMock.mock.calls.filter(([p]) => p === "/api/settings/greyhawk").length;
    expect(calls()).toBe(1);
    title = "Oerth";
    FakeEventSource.instances[0].emit("setting", { id: "other" });
    FakeEventSource.instances[0].emit("setting", { id: "greyhawk" });
    expect(await screen.findByRole("heading", { level: 1, name: "Oerth" })).toBeTruthy();
    expect(calls()).toBe(2);
  });

  it("reads a novel at /novels/:id in the shell, and prints it at /novels/:id/print without the nav", async () => {
    const novel = {
      id: "nov_aaaaaaaaaaaa",
      title: "The Bones of Saint Vellis",
      campaign_id: "cmp_bbbbbbbbbbbb",
      module_id: null,
      length: "recap",
      tone: "classic",
      custom_tone: "",
      language: "en",
      chapters: [{ title: "Down the Stairs", summary: "", text: "Ned went first." }],
      status: "done",
      error: null,
      conversion_id: null,
      created_at: "2026-10-20T10:00:00Z",
    };
    routes["/api/novels/nov_aaaaaaaaaaaa"] = () => json(200, novel);
    const reader = renderAt("/novels/nov_aaaaaaaaaaaa");
    expect(await screen.findByRole("heading", { level: 1, name: "The Bones of Saint Vellis" })).toBeTruthy();
    expect(screen.getByRole("link", { name: "Campaigns" })).toBeTruthy();
    reader.unmount();

    renderAt("/novels/nov_aaaaaaaaaaaa/print");
    expect(await screen.findByRole("button", { name: "Print or save as PDF" })).toBeTruthy();
    expect(screen.getByRole("heading", { level: 2, name: "Down the Stairs" })).toBeTruthy();
    expect(screen.queryByRole("link", { name: "Campaigns" })).toBeNull();
  });

  it("renders Preferences at /preferences", async () => {
    renderAt("/preferences");
    expect(await screen.findByRole("heading", { level: 1, name: "Preferences" })).toBeTruthy();
  });

  it("speaks Dutch when the preferences say nl", async () => {
    routes["/api/preferences"] = () => json(200, { ...preferences, language: "nl" });
    renderAt("/house-rules");
    expect(await screen.findByRole("heading", { name: "Huisregels" })).toBeTruthy();
    expect(await screen.findByText("Nog geen huisregels. Schrijf er een met Nieuwe regel.")).toBeTruthy();
  });

  it("re-fetches the preferences on the SSE preferences event", async () => {
    renderAt("/preferences");
    await waitFor(() => expect(FakeEventSource.instances).toHaveLength(1));
    expect(FakeEventSource.instances[0].url).toBe("/api/events");
    await waitFor(() => expect(preferencesCalls()).toBe(1));

    routes["/api/preferences"] = () => json(200, { ...preferences, language: "nl" });
    FakeEventSource.instances[0].emit("preferences", { ...preferences, language: "nl" });

    expect(await screen.findByRole("heading", { name: "Voorkeuren" })).toBeTruthy();
    expect(preferencesCalls()).toBe(2);
  });

  it("re-fetches a map state and its view on the SSE map_state event", async () => {
    const { campaign, base, character } = campaignPage();
    const viewCalls = () => fetchMock.mock.calls.filter(([p]) => String(p).startsWith(`${base}/view`)).length;

    renderAt(`/campaigns/${campaign}?tab=maps`);
    expect(await screen.findByRole("heading", { name: "Tuesday group" })).toBeTruthy();
    const stateCalls = () => fetchMock.mock.calls.filter(([p]) => p === `${base}/state`).length;
    await waitFor(() => expect(viewCalls()).toBe(1));
    // The map state places the campaign's characters.
    expect(fetchMock.mock.calls.some(([p]) => p === `${base}/view?characters=${character.id}`)).toBe(true);
    // The page and its map state tool read the state, before the event.
    const before = stateCalls();

    FakeEventSource.instances[0].emit("map_state", { campaign_id: "cmp_other0000000", map: "crypt" });
    FakeEventSource.instances[0].emit("map_state", { campaign_id: campaign, map: "crypt" });

    await waitFor(() => expect(viewCalls()).toBe(2));
    expect(stateCalls()).toBe(before + 1);
  });

  it("re-fetches the characters on the SSE characters event, and the house rules on house_rules", async () => {
    const { campaign } = campaignPage();
    const calls = (path: string) => fetchMock.mock.calls.filter(([p]) => p === path).length;
    renderAt(`/campaigns/${campaign}`);
    expect(await screen.findByRole("heading", { name: "Tuesday group" })).toBeTruthy();
    await waitFor(() => expect(calls(`/api/campaigns/${campaign}/house-rules`)).toBe(1));
    expect(calls(`/api/campaigns/${campaign}/dm/characters`)).toBe(1);

    FakeEventSource.instances[0].emit("characters", { campaign_id: "cmp_other0000000" });
    FakeEventSource.instances[0].emit("characters", { campaign_id: campaign });
    await waitFor(() => expect(calls(`/api/campaigns/${campaign}/dm/characters`)).toBe(2));

    FakeEventSource.instances[0].emit("house_rules", { rule_id: "hr_00000000000a" });
    await waitFor(() => expect(calls(`/api/campaigns/${campaign}/house-rules`)).toBe(2));
    expect(calls("/api/house-rule-bundles")).toBe(2);
  });

  it("the campaign page has no character form: characters are made in play", async () => {
    const { campaign, character } = campaignPage();
    renderAt(`/campaigns/${campaign}?tab=party`);
    expect(await screen.findByRole("heading", { name: "Tuesday group" })).toBeTruthy();
    expect(screen.queryByLabelText("New character")).toBeNull();
    expect(screen.queryByRole("button", { name: "Add character" })).toBeNull();
    expect(screen.getByText(/Characters are made in play/)).toBeTruthy();
    expect(screen.getByRole("link", { name: "Play this campaign" }).getAttribute("href")).toBe(`/play/${campaign}`);
    expect(screen.getByRole("article", { name: character.name })).toBeTruthy();
  });

  it("a seat's browser shows only the Play screen of its campaign, in the seat's language", async () => {
    const campaign = "cmp_00000000000a";
    const seat = {
      id: "seat_00000000000a",
      campaign_id: campaign,
      campaign_name: "The Crypt",
      name: "Ana",
      language: "nl",
      role: "player",
      organiser: false,
    };
    const me = { principal: { id: `seat:${seat.id}`, roles: [] }, seat };
    routes["/api/me"] = () => json(200, me);
    routes[`/api/me?campaign=${campaign}`] = () => json(200, me);
    routes["/api/preferences"] = () => json(403, { error: "Only an organiser may." });
    routes[`/api/campaigns/${campaign}/story?limit=50&language=nl`] = () => json(200, { entries: [], has_more: false });
    routes[`/api/campaigns/${campaign}/play/state`] = () =>
      json(200, { beat: null, party: [], positions: [], combat: null, session_number: 1, time_of_day: "morning" });
    routes[`/api/campaigns/${campaign}/seats`] = () => json(200, []);
    const router = createMemoryRouter(appRoutes, { initialEntries: ["/modules"] });
    render(<App router={router} />);

    expect(await screen.findByTestId("composer")).toBeTruthy();
    expect(router.state.location.pathname).toBe(`/play/${campaign}`);
    expect(screen.queryByRole("navigation", { name: "Onderdelen" })).toBeNull();
    expect(screen.queryByRole("link", { name: "Modules" })).toBeNull();
    expect(await screen.findByRole("heading", { name: "The Crypt" })).toBeTruthy();
    expect(screen.getByTestId("act").textContent).toBe("Doen");
    // The organiser's routes aren't asked for.
    expect(fetchMock.mock.calls.some(([p]) => p === "/api/modules" || p === `/api/campaigns/${campaign}`)).toBe(false);
  });

  it("a seat may leave its table for the Rulesets area alone, with a way back", async () => {
    const campaign = "cmp_00000000000a";
    const seat = {
      id: "seat_00000000000a",
      campaign_id: campaign,
      campaign_name: "The Crypt",
      name: "Ana",
      language: "en",
      role: "player",
      organiser: false,
    };
    routes["/api/me"] = () => json(200, { principal: { id: `seat:${seat.id}`, roles: [] }, seat });
    routes["/api/preferences"] = () => json(403, { error: "Only an organiser may." });
    routes["/api/rulesets/adnd2e"] = () =>
      json(200, { id: "adnd2e", title: "AD&D 2nd edition", campaign_id: campaign, sections: [{ key: "spells", kind: "list", count: 1 }] });
    routes["/api/rulesets/adnd2e/spells"] = () =>
      json(200, {
        kind: "list",
        facets: [],
        total: 1,
        offset: 0,
        rows: [{ id: "412", name: "Web", caster: "wizard", level: "2", school: "Evocation", house_rule: false }],
      });
    const router = createMemoryRouter(appRoutes, { initialEntries: ["/rulesets/adnd2e/spells"] });
    render(<App router={router} />);

    expect(await screen.findByRole("link", { name: "Web" })).toBeTruthy();
    expect(router.state.location.pathname).toBe("/rulesets/adnd2e/spells");
    expect(screen.getByRole("link", { name: "Back to the table" }).getAttribute("href")).toBe(`/play/${campaign}`);
    // Still no nav: the area and the table are all a seat reaches.
    expect(screen.queryByRole("navigation", { name: "Areas" })).toBeNull();

    await act(() => router.navigate("/campaigns"));
    await waitFor(() => expect(router.state.location.pathname).toBe(`/play/${campaign}`));
  });

  it("a seat's browser opens the event stream only at its table, so the Rulesets tab doesn't keep it present", async () => {
    const campaign = "cmp_00000000000a";
    const seat = { id: "seat_00000000000a", campaign_id: campaign, campaign_name: "The Crypt", name: "Ana", language: "en", role: "player", organiser: false };
    const me = { principal: { id: `seat:${seat.id}`, roles: [] }, seat };
    routes["/api/me"] = () => json(200, me);
    routes[`/api/me?campaign=${campaign}`] = () => json(200, me);
    routes["/api/preferences"] = () => json(403, { error: "Only an organiser may." });
    routes["/api/rulesets"] = () => json(200, [{ id: "adnd2e", title: "AD&D 2nd edition" }]);
    routes[`/api/campaigns/${campaign}/story?limit=50`] = () => json(200, { entries: [], has_more: false });
    routes[`/api/campaigns/${campaign}/play/state`] = () =>
      json(200, { beat: null, party: [], positions: [], combat: null, session_number: 1, time_of_day: "morning" });
    routes[`/api/campaigns/${campaign}/seats`] = () => json(200, []);
    const router = createMemoryRouter(appRoutes, { initialEntries: ["/rulesets"] });
    render(<App router={router} />);

    expect(await screen.findByRole("link", { name: "AD&D 2nd edition" })).toBeTruthy();
    await act(() => new Promise((resolve) => setTimeout(resolve, 50)));
    expect(FakeEventSource.instances).toHaveLength(0);

    // Back at the table, it listens.
    await act(() => router.navigate(`/play/${campaign}`));
    expect(await screen.findByTestId("composer")).toBeTruthy();
    await waitFor(() => expect(FakeEventSource.instances).toHaveLength(1));
    expect(FakeEventSource.instances[0].closed).toBe(false);
  });

  it("the owner's Rulesets pages have no way back to a table", async () => {
    routes["/api/me"] = () => json(200, { principal: { id: "owner", roles: ["organiser"] }, seat: null });
    routes["/api/rulesets"] = () => json(200, [{ id: "adnd2e", title: "AD&D 2nd edition" }]);
    renderAt("/rulesets");
    expect(await screen.findByRole("link", { name: "AD&D 2nd edition" })).toBeTruthy();
    expect(screen.queryByRole("link", { name: "Back to the table" })).toBeNull();
  });

  it("re-fetches the rulesets on house_rules: the campaign's homebrew is beside the book's", async () => {
    routes["/api/me"] = () => json(200, { principal: { id: "owner", roles: ["organiser"] }, seat: null });
    routes["/api/rulesets"] = () => json(200, [{ id: "adnd2e", title: "AD&D 2nd edition" }]);
    const calls = () => fetchMock.mock.calls.filter(([p]) => p === "/api/rulesets").length;
    renderAt("/rulesets");
    expect(await screen.findByRole("link", { name: "AD&D 2nd edition" })).toBeTruthy();
    await waitFor(() => expect(FakeEventSource.instances).toHaveLength(1));
    expect(calls()).toBe(1);

    FakeEventSource.instances[0].emit("house_rules", { rule_id: "hr_00000000000a" });
    await waitFor(() => expect(calls()).toBe(2));
  });

  it("the play screen listens through the app's one event stream", async () => {
    const { campaign } = campaignPage();
    const storyPath = `/api/campaigns/${campaign}/story?limit=50`;
    routes[storyPath] = () => json(200, { entries: [], has_more: false });
    routes[`/api/campaigns/${campaign}/play/state`] = () =>
      json(200, { beat: null, party: [], positions: [], combat: null, session_number: 1, time_of_day: "morning" });
    routes[`/api/campaigns/${campaign}/play/options`] = () => json(200, { tone: "classic", detail: 2 });
    const storyCalls = () => fetchMock.mock.calls.filter(([p]) => p === storyPath).length;

    renderAt(`/play/${campaign}`);
    expect(await screen.findByTestId("composer")).toBeTruthy();
    await waitFor(() => expect(storyCalls()).toBe(1));
    expect(FakeEventSource.instances).toHaveLength(1);
    expect(FakeEventSource.instances[0].closed).toBe(false);

    FakeEventSource.instances[0].emit("beat", { campaign_id: campaign, beat: { id: "beat_1", status: "done" } });
    await waitFor(() => expect(storyCalls()).toBe(2));
  });

  it("on the play screen, reads each thing once for an event, and the story only when a beat ends or the stream is back (DEL-168)", async () => {
    const { campaign } = campaignPage();
    const path = (rest: string) => `/api/campaigns/${campaign}/${rest}`;
    routes[path("story?limit=50")] = () => json(200, { entries: [], has_more: false });
    routes[path("play/state")] = () =>
      json(200, { beat: null, party: [], positions: [], combat: null, session_number: 1, time_of_day: "morning" });
    routes[path("play/options")] = () => json(200, { tone: "classic", detail: 2 });
    routes[path("characters")] = () => json(200, []);
    const calls = (rest: string) => fetchMock.mock.calls.filter(([p]) => p === path(rest)).length;
    const settled = () => new Promise((resolve) => setTimeout(resolve, 50));

    renderAt(`/play/${campaign}`);
    expect(await screen.findByTestId("composer")).toBeTruthy();
    await waitFor(() => expect(calls("story?limit=50")).toBe(1));
    await waitFor(() => expect(calls("characters")).toBe(1));
    const stream = FakeEventSource.instances[0];

    // A characters event: the app's handler reads them; the play screen doesn't read them again (P15).
    stream.emit("characters", { campaign_id: campaign });
    await waitFor(() => expect(calls("characters")).toBe(2));
    await settled();
    expect(calls("characters")).toBe(2);

    // A DM's tool call: one event, the state read once, the characters once.
    const state = calls("play/state");
    stream.emit("changed", { campaign_id: campaign, areas: ["characters", "combat"], maps: [] });
    await waitFor(() => expect(calls("characters")).toBe(3));
    await settled();
    expect([calls("characters"), calls("play/state")]).toEqual([3, state + 1]);

    // An open beat's deadline and a running beat leave the story as it is; an ended one reads it again.
    stream.emit("beat", { campaign_id: campaign, beat: { id: "beat_1", status: "open" } });
    stream.emit("beat", { campaign_id: campaign, beat: { id: "beat_1", status: "running" } });
    await settled();
    expect(calls("story?limit=50")).toBe(1);
    stream.emit("beat", { campaign_id: campaign, beat: { id: "beat_1", status: "failed" } });
    await waitFor(() => expect(calls("story?limit=50")).toBe(2));

    // The stream lost and back: the story is read again, for what the replay may not have.
    stream.emit("error", null);
    await settled();
    expect(calls("story?limit=50")).toBe(2);
    stream.emit("open", null);
    await waitFor(() => expect(calls("story?limit=50")).toBe(3));
  });
});

describe("an account", () => {
  const campaign = "cmp_00000000000a";
  const player = { id: "acc_00000000000a", username: "ana", display_name: "Ana", language: "nl", organiser: false, owner: false };
  const seat = { id: "seat_00000000000a", campaign_id: campaign, campaign_name: "The Crypt", name: "Ana", language: "nl", role: "player", organiser: false };
  const me = (withSeat: boolean) => ({
    principal: { id: `account:${player.id}`, roles: [] },
    account: player,
    seat: withSeat ? seat : null,
    keepable_seat: null,
  });

  beforeEach(() => {
    routes["/api/me"] = () => json(200, me(false));
    routes[`/api/me?campaign=${campaign}`] = () => json(200, me(true));
    routes["/api/preferences"] = () => json(403, { error: "This needs the organiser role." });
    routes["/api/account/tables"] = () => json(200, []);
    routes[`/api/campaigns/${campaign}/story?limit=50&language=nl`] = () => json(200, { entries: [], has_more: false });
    routes[`/api/campaigns/${campaign}/play/state`] = () =>
      json(200, { beat: null, party: [], positions: [], combat: null, session_number: 1, time_of_day: "morning", pregame: false });
    routes[`/api/campaigns/${campaign}/seats`] = () => json(200, [{ ...seat, present: true, characters: [] }]);
  });

  it("a player account lands on My tables, in its own language", async () => {
    const router = createMemoryRouter(appRoutes, { initialEntries: ["/home"] });
    render(<App router={router} />);
    expect(await screen.findByRole("heading", { level: 1, name: "Mijn tafels" })).toBeTruthy();
    expect(router.state.location.pathname).toBe("/tables");
    // A player's nav, and nothing of the organiser's asked for.
    expect(screen.getByRole("link", { name: "Voorkeuren" })).toBeTruthy();
    expect(screen.queryByRole("link", { name: "Modules" })).toBeNull();
    expect(preferencesCalls()).toBe(0);
    // It listens nowhere but at a table.
    await act(() => new Promise((resolve) => setTimeout(resolve, 20)));
    expect(FakeEventSource.instances).toHaveLength(0);
  });

  it("a player account can't open Modules", async () => {
    const router = createMemoryRouter(appRoutes, { initialEntries: ["/modules"] });
    render(<App router={router} />);
    await waitFor(() => expect(router.state.location.pathname).toBe("/tables"));
    expect(fetchMock.mock.calls.some(([p]) => p === "/api/modules")).toBe(false);
    await act(() => router.navigate("/campaigns/cmp_00000000000a"));
    await waitFor(() => expect(router.state.location.pathname).toBe("/tables"));
    await act(() => router.navigate("/preferences/players"));
    await waitFor(() => expect(router.state.location.pathname).toBe("/tables"));
    expect(fetchMock.mock.calls.some(([p]) => p === "/api/accounts")).toBe(false);
  });

  it("an organiser reaches the Players page", async () => {
    routes["/api/me"] = () => json(200, { principal: { id: "owner", roles: ["organiser"] }, account: null, seat: null, keepable_seat: null });
    routes["/api/accounts"] = () => json(200, []);
    renderAt("/preferences/players");
    expect(await screen.findByRole("heading", { level: 1, name: "Players" })).toBeTruthy();
  });

  it("an account's stream names its campaign", async () => {
    const router = createMemoryRouter(appRoutes, { initialEntries: [`/play/${campaign}`] });
    render(<App router={router} />);
    expect(await screen.findByTestId("composer")).toBeTruthy();
    await waitFor(() => expect(FakeEventSource.instances).toHaveLength(1));
    expect(FakeEventSource.instances[0].url).toBe(`/api/events?campaign=${campaign}`);

    // Off to My tables: the stream closes.
    await act(() => router.navigate("/tables"));
    await waitFor(() => expect(FakeEventSource.instances[0].closed).toBe(true));
  });

  it("an organiser account keeps today's nav, with My tables and Log out", async () => {
    routes["/api/me"] = () => json(200, { ...me(false), principal: { id: `account:${player.id}`, roles: ["organiser"] }, account: { ...player, organiser: true } });
    routes["/api/preferences"] = () => json(200, preferences);
    renderAt("/campaigns");
    const nav = await screen.findByRole("navigation");
    await waitFor(() => expect(within(nav).getByRole("link", { name: "Mijn tafels" })).toBeTruthy());
    expect(within(nav).getByRole("link", { name: "Modules" })).toBeTruthy();
    expect(within(nav).getByRole("button", { name: "Uitloggen" })).toBeTruthy();
    // An organiser hears the organisers' events on every screen.
    await waitFor(() => expect(FakeEventSource.instances).toHaveLength(1));
    expect(FakeEventSource.instances[0].url).toBe("/api/events");
  });

  it("an owner account is an organiser, though its organiser flag is off (DEL-158)", async () => {
    // A fresh install's owner account: the server gives it the organiser role for being the owner.
    const owner = { ...player, owner: true };
    routes["/api/me"] = () => json(200, { ...me(false), principal: { id: `account:${owner.id}`, roles: ["organiser"] }, account: owner });
    routes["/api/preferences"] = () => json(200, preferences);
    const router = createMemoryRouter(appRoutes, { initialEntries: ["/home"] });
    render(<App router={router} />);
    const nav = await screen.findByRole("navigation");
    await waitFor(() => expect(within(nav).getByRole("link", { name: "Modules" })).toBeTruthy());
    expect(router.state.location.pathname).toBe("/campaigns");
  });
});

describe("a lost event stream", () => {
  it("shows the notice, with Reload, when the stream closed and Delve no longer knows this browser", async () => {
    routes["/api/me"] = () => json(200, { principal: { id: "owner", roles: ["organiser"] }, seat: null });
    renderAt("/campaigns");
    await waitFor(() => expect(FakeEventSource.instances).toHaveLength(1));
    const stream = FakeEventSource.instances[0];

    // An error the browser reconnects from says nothing.
    stream.emit("error", {});
    await waitFor(() => expect(fetchMock.mock.calls.filter(([p]) => p === "/api/me")).toHaveLength(1));
    expect(screen.queryByTestId("events-lost")).toBeNull();

    // Closed, but Delve still knows this browser (a proxy's 502 while Delve restarts): no notice, and a new stream is
    // opened a moment later, which hears the events the old one did.
    stream.readyState = FakeEventSource.CLOSED;
    stream.emit("error", {});
    await waitFor(() => expect(fetchMock.mock.calls.filter(([p]) => p === "/api/me")).toHaveLength(2));
    expect(screen.queryByTestId("events-lost")).toBeNull();
    await waitFor(() => expect(FakeEventSource.instances).toHaveLength(2), { timeout: 2500 });
    const again = FakeEventSource.instances[1];
    expect(again.url).toBe("/api/events");
    const listed = () => fetchMock.mock.calls.filter(([p]) => p === "/api/campaigns").length;
    const before = listed();
    again.emit("campaigns", { id: "cmp_00000000000a" });
    await waitFor(() => expect(listed()).toBe(before + 1));

    // The old stream is done with: what it says now is not listened to.
    stream.emit("error", {});
    expect(fetchMock.mock.calls.filter(([p]) => p === "/api/me")).toHaveLength(2);

    routes["/api/me"] = () => json(401, { error: "Who are you?" });
    again.readyState = FakeEventSource.CLOSED;
    again.emit("error", {});
    const notice = await screen.findByTestId("events-lost");
    expect(notice.textContent).toContain("Delve no longer knows this browser. Open the table's link again.");
    expect(within(notice).getByRole("button", { name: "Reload" })).toBeTruthy();
  });

  it("tells an account to reload or log in again; a seat keeps the table's link", async () => {
    const account = { id: "acc_00000000000b", username: "bo", display_name: "Bo", language: "en", organiser: true, owner: false };
    routes["/api/me"] = () => json(200, { principal: { id: `account:${account.id}`, roles: ["organiser"] }, account, seat: null, keepable_seat: null });
    routes["/api/preferences"] = () => json(200, preferences);
    renderAt("/campaigns");
    await waitFor(() => expect(FakeEventSource.instances).toHaveLength(1));
    const stream = FakeEventSource.instances[0];

    routes["/api/me"] = () => json(401, { error: "Who are you?" });
    stream.readyState = FakeEventSource.CLOSED;
    stream.emit("error", {});
    const notice = await screen.findByTestId("events-lost");
    expect(notice.textContent).toContain("Delve no longer knows this browser: you may have been logged out. Reload, or log in again.");
    expect(notice.textContent).not.toContain("table's link");
    expect(within(notice).getByRole("button", { name: "Reload" })).toBeTruthy();
  });

  it("refreshes the campaigns list on a campaigns event", async () => {
    renderAt("/campaigns");
    await waitFor(() => expect(FakeEventSource.instances).toHaveLength(1));
    const listed = () => fetchMock.mock.calls.filter(([p]) => p === "/api/campaigns").length;
    await waitFor(() => expect(listed()).toBe(1));
    FakeEventSource.instances[0].emit("campaigns", { id: "cmp_00000000000a" });
    await waitFor(() => expect(listed()).toBe(2));
  });
});

/** A campaign page's routes: the campaign, one character with an empty sheet, its house rules and one map. */
function campaignPage() {
  const campaign = "cmp_00000000000a";
  const base = `/api/campaigns/${campaign}/maps/crypt`;
  const character = {
    id: "chr_00000000000a",
    campaign_id: campaign,
    name: "Ash",
    kind: "pc",
    order: 0,
    encumbrance: null,
    created_at: "",
    sheet: {
      kind: "pc",
      label: "Ash",
      race: "",
      cls: "",
      levels: {},
      hp_max: 8,
      ac: 10,
      thac0: 20,
      saves: {},
      attacks: [],
      movement_rate: 12,
      alignment: "",
      spell_slots: {},
    },
    state: { hp: 8, xp: 0, conditions: [], effects: [] },
  };
  // Ash is on the map, so the page draws the map state tool.
  const state = {
    characters: { [character.id]: { location: "room.entry_hall", nodes: ["room.entry_hall"], doors: [] } },
    door_states: {},
    revealed: [],
    groups: [],
  };
  routes[`/api/campaigns/${campaign}/house-rules`] = () => json(200, { bundle_ids: [], rule_ids: [] });
  routes[`/api/campaigns/${campaign}`] = () =>
    json(200, {
      id: campaign,
      name: "Tuesday group",
      module_id: "mod_0123456789ab",
      revision: 1,
      created_at: "",
      module_title: "Crypt of Saint Vellis",
      maps: ["crypt"],
      upgrade_available: false,
    });
  // The campaign page is the organiser's: it reads every sheet from `…/dm/characters`.
  routes[`/api/campaigns/${campaign}/dm/characters`] = () => json(200, [character]);
  routes[`/api/campaigns/${campaign}/dm/log`] = () => json(200, { entries: [] });
  routes[`${base}/state`] = () => json(200, state);
  routes[`${base}/view?characters=${character.id}`] = () => json(200, { svg: "<svg></svg>" });
  routes[`${base}/doors-and-secrets`] = () => json(200, { doors: [], secrets: [] });
  return { campaign, base, character };
}
