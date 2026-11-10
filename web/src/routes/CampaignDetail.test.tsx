import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";
import { portraitSvg } from "../components/Portrait";
import { DialogsProvider } from "../components/dialogs";
import { PORTRAIT_STYLES, SAMPLE_PORTRAIT } from "../components/portraitStyle";
import { I18nProvider } from "../i18n";
import { boardZone } from "../board/testing";
import { CAMPAIGN, HOST_SEAT, base, character, json, playState, seat, sent, stubFetch } from "../play/testing";
import CampaignDetail from "./CampaignDetail";

afterEach(() => {
  vi.unstubAllGlobals();
});

const campaign = {
  id: CAMPAIGN,
  name: "Tuesday",
  module_id: "mod_00000000000a",
  revision: 1,
  created_at: "2026-10-17T12:00:00Z",
  ruleset: "adnd2e",
  setting: null,
  status: "in_progress",
  module_title: "The Crypt",
  maps: [],
  upgrade_available: false,
  banner: { image_id: null, pending: null, can_paint: true, why_not: null },
};

const PAID_HINT = "Paid images are off: the host turns them on in the table options.";

function renderPage(entry = `/campaigns/${CAMPAIGN}`, language = "en") {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <I18nProvider language={language}>
        <DialogsProvider>
          <MemoryRouter initialEntries={[entry]}>
            <Routes>
              <Route path="/campaigns/:id" element={<CampaignDetail />} />
            </Routes>
          </MemoryRouter>
        </DialogsProvider>
      </I18nProvider>
    </QueryClientProvider>,
  );
}

const grik = {
  ...character("chr_00000000000g", "Grik"),
  kind: "npc" as const,
  order: null,
  sheet: { ...character("chr_00000000000g", "Grik").sheet, kind: "npc" as const, notes_md: "Grik sold the party out.", disposition: -30 },
};

function routes(costs: unknown[] = []) {
  return {
    [`GET ${base}`]: () => json(200, campaign),
    [`GET ${base}/dm/characters`]: () => json(200, [character("chr_00000000000a", "Ash"), grik]),
    [`GET ${base}/dm/costs`]: () => json(200, { rows: costs }),
    [`GET ${base}/house-rules`]: () => json(200, { bundle_ids: [], rule_ids: [] }),
    "GET /api/worlds": () => json(200, { rulesets: [], settings: [] }),
  };
}

describe("CampaignDetail", () => {
  it("shows the organiser every sheet, an NPC's story too, from the organiser's route", async () => {
    const fetchMock = stubFetch(routes());
    renderPage(`/campaigns/${CAMPAIGN}?tab=party`);
    expect(await screen.findByText("Grik sold the party out.")).toBeTruthy();
    const sheets = document.querySelectorAll("article.sheet");
    expect([...sheets].map((sheet) => within(sheet as HTMLElement).getByRole("heading", { level: 3 }).textContent)).toEqual(["Ash", "Grik"]);
    expect(fetchMock.mock.calls.some(([path]) => path === `${base}/characters`)).toBe(false);
  });

  it("shows the DM log: a row per beat with its tools, tokens and cost, and the campaign's total", async () => {
    // Summed by the server (DEL-172), which the campaign page no longer downloads the whole log for.
    const row = { ask: false, tools: 0, input: 0, output: 0, cost: null };
    stubFetch(
      routes([
        { ...row, beat: "bt_1", at: "2026-10-18T10:00:00Z", tools: 2, input: 12000, output: 800, cost: 0.12 },
        { ...row, beat: "ask-3", at: "2026-10-18T10:02:00Z", ask: true, input: 300, output: 20 },
        { ...row, beat: "bt_2", at: "2026-10-18T10:05:00Z", tools: 1, input: 13000, output: 500, cost: 0.05 },
      ]),
    );
    renderPage(`/campaigns/${CAMPAIGN}?tab=log`);
    const table = await screen.findByRole("table", { name: "DM log" });
    const rows = within(table).getAllByRole("row").map((row) => [...row.children].map((cell) => cell.textContent));
    expect(rows.slice(1, 4).map((row) => row.slice(1))).toEqual([
      ["2", "12000", "800", "$0.12"],
      ["0", "300", "20", "—"],
      ["1", "13000", "500", "$0.05"],
    ]);
    expect(rows[2][0]).toMatch(/^Ask/);
    expect(rows[4]).toEqual(["Total", "3", "25300", "1320", "$0.17"]);
  });

  it("pages the DM log by 20 beats, with the total over all of them", async () => {
    const costs = Array.from({ length: 25 }, (_, i) => ({
      beat: `bt_${i + 1}`,
      at: `2026-10-18T10:${String(i).padStart(2, "0")}:00Z`,
      ask: false,
      tools: 0,
      input: 100,
      output: 10,
      cost: 0.01,
    }));
    stubFetch(routes(costs));
    renderPage(`/campaigns/${CAMPAIGN}?tab=log`);
    const table = await screen.findByRole("table", { name: "DM log" });
    const body = () => table.querySelectorAll("tbody tr").length;
    expect(body()).toBe(20);
    const total = () => [...table.querySelectorAll("tfoot td")].map((cell) => cell.textContent);
    expect(total()).toEqual(["0", "2500", "250", "$0.25"]);
    const pager = screen.getByRole("navigation", { name: "DM log pages" });
    fireEvent.click(within(pager).getByRole("button", { name: "Next" }));
    expect(body()).toBe(5);
    expect(total()).toEqual(["0", "2500", "250", "$0.25"]);
  });

  it("the status picker sets the campaign's status", async () => {
    let sent: unknown;
    const fetchMock = stubFetch({
      ...routes(),
      [`PATCH ${base}`]: (init?: RequestInit) => {
        sent = JSON.parse(String(init?.body));
        return json(200, { ...campaign, status: "paused" });
      },
    });
    renderPage();
    const picker = (await screen.findByLabelText("Status")) as HTMLSelectElement;
    expect(picker.value).toBe("in_progress");
    expect([...picker.options].map((o) => o.text)).toEqual(["In progress", "Paused", "Complete"]);
    fireEvent.change(picker, { target: { value: "paused" } });
    await waitFor(() => expect(sent).toEqual({ status: "paused" }));
    expect(fetchMock.mock.calls.some(([path, init]) => path === base && init?.method === "PATCH")).toBe(true);
  });

  it("offers Generate a map, to the module's Maps tab, when its module has no map", async () => {
    stubFetch(routes());
    renderPage(`/campaigns/${CAMPAIGN}?tab=maps`);
    const link = await screen.findByRole("link", { name: "Generate a map" });
    expect(link.getAttribute("href")).toBe("/modules/mod_00000000000a?tab=maps");
  });

  it("offers no Generate a map when its module has a map", async () => {
    stubFetch({ ...routes(), [`GET ${base}`]: () => json(200, { ...campaign, maps: ["crypt"] }) });
    renderPage(`/campaigns/${CAMPAIGN}?tab=maps`);
    await screen.findByRole("heading", { name: "World maps" });
    expect(screen.queryByRole("link", { name: "Generate a map" })).toBeNull();
  });

  it("chooses the campaign's portrait style, with a sample portrait in it", async () => {
    let style: string | null = "illustrated";
    // Preferences' style for PCs, which the play state answers while the campaign has none of its own (DEL-252).
    const preferred = "realistic";
    const options = () => ({ tone: "classic", detail: 2, effort: null, model: null, beat_timer_s: null, fallback: "hold_back", paid_images: false, portrait_style: style });
    const fetchMock = stubFetch({
      ...routes(),
      [`GET ${base}/play/options`]: () => json(200, options()),
      [`PUT ${base}/play/options`]: (init) => {
        style = JSON.parse(String(init?.body)).portrait_style;
        return json(200, options());
      },
      [`GET ${base}/play/state`]: () => json(200, { ...playState(), portrait_style: style ?? preferred }),
    });
    renderPage(`/campaigns/${CAMPAIGN}?tab=party`);
    const select = (await screen.findByLabelText("Portrait style")) as HTMLSelectElement;
    await waitFor(() => expect(select.value).toBe("illustrated"));
    expect([...select.options].map((o) => o.value)).toEqual(["", ...PORTRAIT_STYLES]);
    expect(select.options[0].textContent).toBe("As in Preferences");
    expect([...select.options].map((o) => o.textContent)).toContain("Ink and wash");
    const sample = () => screen.getByRole("img", { name: "A sample portrait" });
    const drawn = () => sample().innerHTML.replaceAll(/id="([^"-]+)-/.exec(sample().innerHTML)?.[1] ?? "", "ID");
    const asDrawn = (svg: string) => Object.assign(document.createElement("span"), { innerHTML: svg }).innerHTML;
    expect(drawn()).toBe(asDrawn(portraitSvg(SAMPLE_PORTRAIT, 96, "ID")));

    fireEvent.change(select, { target: { value: "inkwash" } });
    await waitFor(() => expect(drawn()).toBe(asDrawn(portraitSvg(SAMPLE_PORTRAIT, 96, "ID", { style: "inkwash" }))));
    expect(sent(fetchMock, "PUT", `${base}/play/options`)).toEqual([{ portrait_style: "inkwash" }]);
    expect(select.value).toBe("inkwash");

    // As in Preferences: null is sent, and the sample is drawn in Preferences' style.
    fireEvent.change(select, { target: { value: "" } });
    await waitFor(() => expect(drawn()).toBe(asDrawn(portraitSvg(SAMPLE_PORTRAIT, 96, "ID", { style: preferred }))));
    expect(sent(fetchMock, "PUT", `${base}/play/options`).at(-1)).toEqual({ portrait_style: null });
    expect(select.value).toBe("");
  });

  it("an empty campaign's first step opens the table, and says what comes next (DEL-187)", async () => {
    stubFetch({ ...routes(), [`GET ${base}/dm/characters`]: () => json(200, []) });
    renderPage();
    const first = await screen.findByRole("link", { name: "Open the table" });
    expect(first.getAttribute("aria-describedby")).toBe("first-step-how");
    expect(document.getElementById("first-step-how")!.textContent).toContain("Start the session there");
    expect(first.getAttribute("href")).toBe(`/play/${CAMPAIGN}`);
    expect(first.className).toContain("primary");
  });

  const mapState = (location: string | null) => ({
    characters: location ? { chr_00000000000a: { location, nodes: [location], doors: [] } } : {},
    door_states: {},
    revealed: [],
    groups: [],
  });

  it("the map state tool waits for a placed party", async () => {
    const withMap = { ...routes(), [`GET ${base}`]: () => json(200, { ...campaign, maps: ["crypt"] }) };
    stubFetch({ ...withMap, [`GET ${base}/maps/crypt/state`]: () => json(200, mapState(null)) });
    renderPage(`/campaigns/${CAMPAIGN}?tab=maps`);
    await screen.findByText("The map state shows up here once the party is on a map in play.");
    expect(screen.queryByRole("region", { name: "Map state of crypt" })).toBeNull();
    expect(screen.queryByText("Fix a map by hand")).toBeNull();
    cleanup();

    stubFetch({
      ...withMap,
      [`GET ${base}/maps/crypt/state`]: () => json(200, mapState("room.entry_hall")),
      [`GET ${base}/maps/crypt/doors-and-secrets`]: () => json(200, { doors: [], secrets: [] }),
    });
    renderPage(`/campaigns/${CAMPAIGN}?tab=maps`);
    const summary = await screen.findByText("Fix a map by hand");
    const details = summary.closest("details") as HTMLDetailsElement;
    expect(summary.tagName).toBe("SUMMARY");
    expect(details.open).toBe(false);
    expect(within(details).getByRole("region", { name: "Map state of crypt", hidden: true })).toBeTruthy();
  });

  it("the map state tool is there, closed, when the party is on another map", async () => {
    stubFetch({
      ...routes(),
      [`GET ${base}`]: () => json(200, { ...campaign, maps: ["ground-floor", "cellar"] }),
      [`GET ${base}/maps/ground-floor/state`]: () => json(200, mapState(null)),
      [`GET ${base}/maps/cellar/state`]: () => json(200, mapState("room.wine_racks")),
      [`GET ${base}/maps/ground-floor/doors-and-secrets`]: () => json(200, { doors: [], secrets: [] }),
    });
    renderPage(`/campaigns/${CAMPAIGN}?tab=maps`);
    const summary = await screen.findByText("Fix a map by hand");
    const details = summary.closest("details") as HTMLDetailsElement;
    expect(details.open).toBe(false);
    expect(within(details).getByRole("region", { name: "Map state of ground-floor", hidden: true })).toBeTruthy();
    expect(screen.queryByText("The map state shows up here once the party is on a map in play.")).toBeNull();
  });

  it("nobody placed on any map shows the waiting text and no tool", async () => {
    stubFetch({
      ...routes(),
      [`GET ${base}`]: () => json(200, { ...campaign, maps: ["ground-floor", "cellar"] }),
      [`GET ${base}/maps/ground-floor/state`]: () => json(200, mapState(null)),
      [`GET ${base}/maps/cellar/state`]: () => json(200, mapState(null)),
    });
    renderPage(`/campaigns/${CAMPAIGN}?tab=maps`);
    await screen.findByText("The map state shows up here once the party is on a map in play.");
    expect(screen.queryByText("Fix a map by hand")).toBeNull();
  });

  it("a map state that doesn't load shows its error", async () => {
    stubFetch({
      ...routes(),
      [`GET ${base}`]: () => json(200, { ...campaign, maps: ["crypt"] }),
      [`GET ${base}/maps/crypt/state`]: () => json(409, { error: "map offline" }),
    });
    renderPage(`/campaigns/${CAMPAIGN}?tab=maps`);
    const alert = await screen.findByText("The map state didn't load: map offline");
    expect(alert.getAttribute("role")).toBe("alert");
    expect(screen.queryByText("Fix a map by hand")).toBeNull();
    expect(screen.queryByText("The map state shows up here once the party is on a map in play.")).toBeNull();
  });

  it("opens the map that ?map= names, as the Maps page's DM view links do", async () => {
    stubFetch({ ...routes(), [`GET ${base}`]: () => json(200, { ...campaign, maps: ["ground-floor", "cellar"] }) });
    renderPage(`/campaigns/${CAMPAIGN}?map=cellar`);
    const picker = (await screen.findByLabelText("Map")) as HTMLSelectElement;
    expect(picker.value).toBe("cellar");
  });

  it("a waiting banner says why and offers no Paint again", async () => {
    stubFetch({
      ...routes(),
      [`GET ${base}`]: () =>
        json(200, { ...campaign, banner: { image_id: null, pending: { status: "waiting", error: null }, can_paint: false, why_not: PAID_HINT } }),
    });
    renderPage();
    expect(await screen.findByText("The banner waits until paid images are on.")).toBeTruthy();
    expect(screen.getByText(PAID_HINT)).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Paint again" })).toBeNull();
    expect(screen.queryByLabelText("Hint (optional)")).toBeNull();
    expect(document.querySelector(".banner img")).toBeNull();
  });

  it("words the server's reason in the reader's language, not the API's English (DEL-97)", async () => {
    const banner = { image_id: null, pending: null, can_paint: false, why_not: PAID_HINT, why_not_code: "paid_images_off" };
    stubFetch({ ...routes(), [`GET ${base}`]: () => json(200, { ...campaign, banner }) });
    renderPage(`/campaigns/${CAMPAIGN}`, "nl");
    expect(await screen.findByText(/Het beeldmodel van de banner kost geld/)).toBeTruthy();
    expect(screen.queryByText(PAID_HINT)).toBeNull();
  });

  it("Paint again sends the hint", async () => {
    const fetchMock = stubFetch({
      ...routes(),
      [`POST ${base}/banner`]: () => json(202, { image_id: "img_00000000000b", status: "painting" }),
    });
    renderPage();
    expect(await screen.findByText("No banner yet.")).toBeTruthy();
    fireEvent.change(screen.getByLabelText("Hint (optional)"), { target: { value: "the barrow mounds in mist" } });
    fireEvent.click(screen.getByRole("button", { name: "Paint again" }));
    await waitFor(() => expect(sent(fetchMock, "POST", `${base}/banner`)).toEqual([{ hint: "the barrow mounds in mist" }]));
  });

  it("a failed banner shows its error under the old one", async () => {
    stubFetch({
      ...routes(),
      [`GET ${base}`]: () =>
        json(200, {
          ...campaign,
          banner: { image_id: "img_00000000000a", pending: { status: "failed", error: "the painter said no" }, can_paint: true, why_not: null },
        }),
    });
    renderPage();
    const img = (await screen.findByRole("img", { name: "Tuesday's banner" })) as HTMLImageElement;
    expect(img.getAttribute("src")).toBe(`${base}/banner?v=img_00000000000a`);
    const error = screen.getByText(/the painter said no/);
    expect(error.textContent).toContain("The banner couldn't be painted:");
    expect(img.compareDocumentPosition(error) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(screen.getByRole("button", { name: "Paint again" })).toBeTruthy();
  });

  it("a painting banner keeps the old one shown, and says so", async () => {
    stubFetch({
      ...routes(),
      [`GET ${base}`]: () =>
        json(200, {
          ...campaign,
          banner: { image_id: "img_00000000000a", pending: { status: "painting", error: null }, can_paint: true, why_not: null },
        }),
    });
    renderPage();
    expect(await screen.findByRole("img", { name: "Tuesday's banner" })).toBeTruthy();
    expect(screen.getByText("The banner is being painted…")).toBeTruthy();
  });

  it("shows the owner a Novels section, and an organiser seat none", async () => {
    const me = (seat: unknown) => ({ "GET /api/me": () => json(200, { principal: { id: seat ? "p" : "owner", roles: [] }, seat }) });
    const novels = { [`GET /api/novels?campaign_id=${CAMPAIGN}`]: () => json(200, []), "GET /api/conversions": () => json(200, []) };
    stubFetch({ ...routes(), ...novels, ...me(null) });
    renderPage(`/campaigns/${CAMPAIGN}?tab=novels`);
    expect(await screen.findByRole("heading", { name: "Novels" })).toBeTruthy();
    cleanup();
    const seat = { id: "seat_1", campaign_id: CAMPAIGN, campaign_name: "Tuesday", name: "Ann", language: "en", role: "host", organiser: true };
    const fetchMock = stubFetch({ ...routes(), ...novels, ...me(seat) });
    renderPage(`/campaigns/${CAMPAIGN}?tab=party`);
    expect(await screen.findByText("Grik sold the party out.")).toBeTruthy();
    await waitFor(() => expect(fetchMock).toHaveBeenCalledWith("/api/me", expect.anything()));
    expect(screen.queryByRole("heading", { name: "Novels" })).toBeNull();
    expect(fetchMock.mock.calls.some(([path]) => String(path).startsWith("/api/novels"))).toBe(false);
  });
});

describe("CampaignDetail and the board", () => {
  const withZone = { "GET /api/board": () => json(200, { zones: [boardZone({ id: "zon_00000000000b", campaign_id: CAMPAIGN })], may_create: true, signed_in: true }) };

  it("links to the campaign's zone on the board once it has one", async () => {
    stubFetch({ ...routes(), ...withZone });
    renderPage();
    expect((await screen.findByRole("link", { name: "Board" })).getAttribute("href")).toBe("/board/zon_00000000000b");
    cleanup();
    stubFetch({ ...routes(), "GET /api/board": () => json(200, { zones: [boardZone({ campaign_id: "cmp_other" })], may_create: true, signed_in: true }) });
    renderPage();
    await screen.findByLabelText("Status");
    await waitFor(() => expect(screen.queryByRole("link", { name: "Board" })).toBeNull());
  });

  it("says in the delete confirmation that the campaign's zone stays, for its members", async () => {
    stubFetch({ ...routes(), ...withZone });
    renderPage();
    await screen.findByRole("link", { name: "Board" });
    fireEvent.click(screen.getByRole("button", { name: "Delete campaign" }));
    const dialog = await screen.findByRole("alertdialog");
    expect(dialog.textContent).toContain("Its zone on the board stays, open to its members only");
    fireEvent.click(within(dialog).getByRole("button", { name: "Cancel" }));
    cleanup();
    stubFetch(routes());
    renderPage();
    await screen.findByLabelText("Status");
    fireEvent.click(screen.getByRole("button", { name: "Delete campaign" }));
    expect((await screen.findByRole("alertdialog")).textContent).not.toContain("zone");
  });
});

describe("CampaignDetail's tabs", () => {
  const tabNames = () => screen.getAllByRole("tab").map((tab) => tab.textContent);

  it("opens on Overview: the status and the house rules, and no sheet or DM log", async () => {
    stubFetch(routes());
    renderPage();
    expect(await screen.findByLabelText("Status")).toBeTruthy();
    expect(screen.getByRole("heading", { name: "House rules" })).toBeTruthy();
    expect(screen.getByRole("tab", { name: "Overview" }).getAttribute("aria-selected")).toBe("true");
    expect(document.querySelectorAll("article.sheet")).toHaveLength(0);
    expect(screen.queryByRole("heading", { name: "DM log" })).toBeNull();
  });

  it("has Overview, Party, Maps, World and DM log for an organiser seat, and Novels for the owner too", async () => {
    const me = (seat: unknown) => ({ "GET /api/me": () => json(200, { principal: { id: seat ? "p" : "owner", roles: [] }, seat }) });
    stubFetch({ ...routes(), ...me(null) });
    renderPage();
    await waitFor(() => expect(tabNames()).toEqual(["Overview", "Party", "Maps", "World", "DM log", "Novels"]));
    cleanup();
    const seat = { id: "seat_1", campaign_id: CAMPAIGN, campaign_name: "Tuesday", name: "Ann", language: "en", role: "host", organiser: true };
    stubFetch({ ...routes(), ...me(seat) });
    renderPage();
    await screen.findByLabelText("Status");
    expect(tabNames()).toEqual(["Overview", "Party", "Maps", "World", "DM log"]);
  });

  it("a tab shows its sections alone: Party has the sheets and the portrait style", async () => {
    stubFetch(routes());
    renderPage();
    fireEvent.click(await screen.findByRole("tab", { name: "Party" }));
    expect(await screen.findByText("Grik sold the party out.")).toBeTruthy();
    expect(screen.getByRole("heading", { name: "Portraits" })).toBeTruthy();
    expect(screen.queryByRole("heading", { name: "House rules" })).toBeNull();
    // The page's head (title, module, world and status) stays above every tab.
    expect(screen.getByLabelText("Status")).toBeTruthy();
  });

  it("the Party tab lists the seats", async () => {
    const profile = { account_id: "acc_00000000000a", display_name: "Ana", pronouns: "", avatar: { emblem: "crown" }, colour: "gold" };
    stubFetch({
      ...routes(),
      [`GET ${base}/seats`]: () =>
        json(200, [
          seat(HOST_SEAT, "Raf", { role: "host", organiser: true }),
          seat("seat_00000000000a", "Ana", { profile }),
          seat("seat_00000000000c", "Cy", { role: "observer", present: false }),
        ]),
    });
    renderPage();
    fireEvent.click(await screen.findByRole("tab", { name: "Party" }));
    const seats = await screen.findByTestId("campaign-seats");
    expect(screen.getByRole("heading", { name: "Seats" })).toBeTruthy();
    const rows = within(seats).getAllByRole("listitem");
    expect(rows.map((r) => r.querySelector(".seat-name")?.textContent)).toEqual(["Raf", "Ana", "Cy"]);
    expect(rows.map((r) => r.querySelector(".seat-role")?.textContent)).toEqual(["Host", "Player", "Observer"]);
    expect(rows[1].querySelector(".avatar[data-emblem='crown']")).not.toBeNull();
    expect(rows[0].querySelector(".avatar-initial")).not.toBeNull();
  });

  it("World has the factions, the quests and the possessions", async () => {
    stubFetch({
      ...routes(),
      [`GET ${base}/factions`]: () => json(200, []),
      [`GET ${base}/quests`]: () => json(200, []),
      [`GET ${base}/possessions`]: () => json(200, []),
    });
    renderPage(`/campaigns/${CAMPAIGN}?tab=world`);
    for (const name of ["Factions and clocks", "Quests", "Possessions"]) {
      expect((await screen.findAllByRole("heading", { name })).length).toBeGreaterThan(0);
    }
  });

  it("?map= opens the Maps tab, as the Maps page's DM view links do", async () => {
    stubFetch({ ...routes(), [`GET ${base}`]: () => json(200, { ...campaign, maps: ["ground-floor", "cellar"] }) });
    renderPage(`/campaigns/${CAMPAIGN}?map=cellar`);
    expect(((await screen.findByLabelText("Map")) as HTMLSelectElement).value).toBe("cellar");
    expect(screen.getByRole("tab", { name: "Maps" }).getAttribute("aria-selected")).toBe("true");
  });

  it("an unknown ?tab= opens Overview", async () => {
    stubFetch(routes());
    renderPage(`/campaigns/${CAMPAIGN}?tab=nonsense`);
    expect(await screen.findByLabelText("Status")).toBeTruthy();
  });
});

describe("CampaignDetail: carrying the party on", () => {
  it("Carry the party on opens the form, with the campaign's PCs, and Cancel closes it", async () => {
    stubFetch({ ...routes(), "GET /api/modules": () => json(200, []) });
    renderPage();
    fireEvent.click(await screen.findByRole("button", { name: "Carry the party on" }));
    const form = await screen.findByRole("region", { name: "Carry the party on" });
    expect(within(form).getByRole("checkbox", { name: "Ash" })).toBeTruthy();
    expect(within(form).queryByRole("checkbox", { name: "Grik" })).toBeNull();
    fireEvent.click(within(form).getByRole("button", { name: "Cancel" }));
    await waitFor(() => expect(screen.queryByRole("region", { name: "Carry the party on" })).toBeNull());
  });

  it("opens the form at ?carry, as the campaigns list's row menu links", async () => {
    stubFetch({ ...routes(), "GET /api/modules": () => json(200, []) });
    renderPage(`/campaigns/${CAMPAIGN}?carry`);
    expect(await screen.findByRole("region", { name: "Carry the party on" })).toBeTruthy();
  });

  it("shows the History right after the banner when the party was carried on from another campaign", async () => {
    stubFetch({
      ...routes(),
      [`GET ${base}`]: () => json(200, { ...campaign, carried_from: { id: "cmp_00000000000o", name: "The Old Crypt" }, carried_to: [] }),
      [`GET ${base}/history`]: () =>
        json(200, { campaign_id: CAMPAIGN, dm_md: "The DM's.", table_md: "The table's.", status: "done", error: null, edited: false, conversion_id: null, cost_usd: null, created_at: "", updated_at: "" }),
    });
    renderPage();
    const history = await screen.findByTestId("history-section");
    expect(within(history).getByRole("link", { name: "The Old Crypt" })).toBeTruthy();
    expect(await within(history).findByText("The DM's.")).toBeTruthy();
    const headings = [...document.querySelectorAll("h2")].map((h) => h.textContent);
    expect(headings.indexOf("History")).toBe(headings.indexOf("Banner") + 1);
  });

  it("shows no History for a campaign that was never carried on", async () => {
    const fetchMock = stubFetch(routes());
    renderPage();
    await screen.findByLabelText("Status");
    await waitFor(() => expect(fetchMock.mock.calls.map(([p]) => p)).toContain(`${base}/history`));
    expect(screen.queryByTestId("history-section")).toBeNull();
  });

  it("shows the table settings on the Overview", async () => {
    stubFetch({ ...routes(), [`GET ${base}`]: () => json(200, { ...campaign, voice: "off", initiative: "side" }) });
    renderPage();
    const voice = await screen.findByRole("radiogroup", { name: "Voice" });
    expect((within(voice).getByRole("radio", { name: "Off" }) as HTMLInputElement).checked).toBe(true);
    const initiative = screen.getByRole("radiogroup", { name: "Initiative" });
    expect((within(initiative).getByRole("radio", { name: "Per side" }) as HTMLInputElement).checked).toBe(true);
  });

  const departurePath = (characterId: string) => `${base}/characters/${characterId}/departure`;

  it("leave with a reason: a PC leaves the party, Delete stays beside it", async () => {
    let ash = character("chr_00000000000a", "Ash");
    const fetchMock = stubFetch({
      ...routes(),
      [`GET ${base}/dm/characters`]: () => json(200, [ash, grik]),
      [`PUT ${departurePath(ash.id)}`]: (init) => {
        ash = { ...ash, departure: JSON.parse(String(init?.body)).departure, departed_at: "2026-10-25T20:00:00Z" };
        return json(200, ash);
      },
    });
    renderPage(`/campaigns/${CAMPAIGN}?tab=party`);
    const row = (await screen.findByLabelText("Name of Ash")).closest("li") as HTMLElement;
    expect(within(row).getByRole("button", { name: "Remove" })).toBeTruthy();
    const grikRow = screen.getByLabelText("Name of Grik").closest("li") as HTMLElement;
    expect(within(grikRow).queryByRole("button", { name: "Leave the party" })).toBeNull();

    fireEvent.click(within(row).getByRole("button", { name: "Leave the party" }));
    const reason = within(row).getByLabelText("Why Ash leaves") as HTMLSelectElement;
    expect([...reason.options].map((o) => o.text)).toEqual(["Died", "Retired", "Left"]);
    fireEvent.change(reason, { target: { value: "retired" } });
    fireEvent.click(within(row).getByRole("button", { name: "Leave" }));
    await waitFor(() => expect(sent(fetchMock, "PUT", departurePath(ash.id))).toEqual([{ departure: "retired" }]));
    await within(row).findByText("Retired");
    expect(within(row).getByRole("button", { name: "Return" })).toBeTruthy();
    expect(within(row).queryByRole("button", { name: "Leave the party" })).toBeNull();
  });

  it("leaving can be cancelled before it is sent", async () => {
    const fetchMock = stubFetch(routes());
    renderPage(`/campaigns/${CAMPAIGN}?tab=party`);
    const row = (await screen.findByLabelText("Name of Ash")).closest("li") as HTMLElement;
    fireEvent.click(within(row).getByRole("button", { name: "Leave the party" }));
    fireEvent.click(within(row).getByRole("button", { name: "Cancel" }));
    expect(within(row).queryByLabelText("Why Ash leaves")).toBeNull();
    expect(fetchMock.mock.calls.some(([, init]) => init?.method === "PUT")).toBe(false);
  });

  it("return: a departed PC shows its reason and comes back", async () => {
    let ash = { ...character("chr_00000000000a", "Ash"), departure: "died" as const, departed_at: "2026-10-25T20:00:00Z" };
    const fetchMock = stubFetch({
      ...routes(),
      [`GET ${base}/dm/characters`]: () => json(200, [ash, grik]),
      [`PUT ${departurePath(ash.id)}`]: () => {
        ash = { ...ash, departure: null as never, departed_at: null as never };
        return json(200, ash);
      },
    });
    renderPage(`/campaigns/${CAMPAIGN}?tab=party`);
    const row = (await screen.findByLabelText("Name of Ash")).closest("li") as HTMLElement;
    expect(within(row).getByText("Died")).toBeTruthy();
    fireEvent.click(within(row).getByRole("button", { name: "Return" }));
    await waitFor(() => expect(sent(fetchMock, "PUT", departurePath(ash.id))).toEqual([{ departure: null }]));
    await within(row).findByRole("button", { name: "Leave the party" });
    expect(within(row).queryByText("Died")).toBeNull();
  });
});

