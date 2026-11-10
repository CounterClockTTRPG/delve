import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { DialogsProvider } from "../components/dialogs";
import { chooseFromRowMenu, rowMenuItem } from "../components/rowMenuTesting";
import { I18nProvider } from "../i18n";
import { boardZone } from "../board/testing";
import Campaigns from "./Campaigns";

const crypt = {
  id: "mod_0123456789ab",
  title: "Crypt of Saint Vellis",
  maps: [{ name: "crypt", role: "map", is_default: true }],
  head_revision: 1,
  updated_at: "2026-10-17T10:00:00Z",
};
const stonehell = { ...crypt, id: "mod_ba9876543210", title: "Stonehell", head_revision: null };
const campaign = {
  id: "cmp_00000000000a",
  name: "Tuesday group",
  module_id: crypt.id,
  revision: 1,
  created_at: "2026-10-17T12:00:00Z",
  ruleset: "adnd2e",
  setting: "greyhawk",
  status: "in_progress",
  module_title: "Crypt of Saint Vellis",
  players: ["Host", "Bo"],
  last_played: null,
  sessions: 0,
  playtime_s: 0,
};
const worlds = {
  rulesets: [
    { id: "adnd2e", title: "AD&D 2nd edition", preferred: true },
    { id: "osric", title: "OSRIC" },
  ],
  settings: [
    { id: "greyhawk", title: "Greyhawk", preferred: true },
    { id: "realms", title: "Forgotten Realms" },
  ],
};
const detail = (module: object, metadata: Record<string, unknown>) => ({ ...module, maps: [], metadata });

const rule = { body_md: "", kind: "general", ruleset: null, subject: null, enabled: true };
const maxHp = { ...rule, id: "hr_00000000000a", title: "Max HP", phases: ["character-creation"], setting: null };
const tressym = { ...rule, id: "hr_00000000000b", title: "Tressym familiar", phases: ["always"], setting: "forgotten-realms" };
const seeded = { id: "hb_00000000000a", title: "My table (from ttrpg2)", description_md: "", rule_ids: [maxHp.id] };

type Handler = (init: RequestInit | undefined) => Response;
let routes: Record<string, Handler>;
let fetchMock: ReturnType<typeof vi.fn>;

function json(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
}

beforeEach(() => {
  localStorage.clear();
  routes = {
    "GET /api/campaigns": () => json(200, [campaign]),
    "GET /api/modules": () => json(200, [crypt, stonehell]),
    "GET /api/house-rules": () => json(200, [maxHp, tressym]),
    "GET /api/house-rule-bundles": () => json(200, [seeded]),
    "GET /api/worlds": () => json(200, worlds),
    [`GET /api/modules/${crypt.id}?map_sources=false`]: () => json(200, detail(crypt, {})),
    [`GET /api/modules/${stonehell.id}?map_sources=false`]: () =>
      json(200, detail(stonehell, { system: "osric", setting: "forgotten realms" })),
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

function renderCampaigns() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <I18nProvider language="en">
        <DialogsProvider>
          <MemoryRouter initialEntries={["/campaigns"]}>
            <Routes>
              <Route path="/campaigns" element={<Campaigns />} />
              <Route path="/campaigns/:id" element={<h1>Campaign page</h1>} />
            </Routes>
          </MemoryRouter>
        </DialogsProvider>
      </I18nProvider>
    </QueryClientProvider>,
  );
}

describe("Campaigns", () => {
  it("pages through many campaigns, 20 at a time", async () => {
    routes["GET /api/campaigns"] = () =>
      json(200, Array.from({ length: 22 }, (_, i) => ({ ...campaign, id: `cmp_${i}`, name: `Group ${i + 1}` })));
    renderCampaigns();
    expect(await screen.findByRole("link", { name: "Group 20" })).toBeTruthy();
    expect(screen.queryByRole("link", { name: "Group 21" })).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Next" }));
    expect(await screen.findByRole("link", { name: "Group 22" })).toBeTruthy();
    expect(screen.getByRole("navigation", { name: "In progress pages" }).textContent).toContain("21–22 of 22");
  });

  it("offers Carry the party on in a row's menu, to the campaign page's form", async () => {
    renderCampaigns();
    const item = await rowMenuItem("Tuesday group", "Carry the party on");
    expect(item).toBeTruthy();
  });

  it("opens the campaign log from a row's menu, as the play head no longer does", async () => {
    renderCampaigns();
    expect(await rowMenuItem("Tuesday group", "Campaign log")).toBeTruthy();
  });

  it("deletes a campaign from its row, once confirmed, and lists the rest", async () => {
    const other = { ...campaign, id: "cmp_00000000000b", name: "Friday group" };
    let listed = [campaign, other];
    routes["GET /api/campaigns"] = () => json(200, listed);
    routes[`DELETE /api/campaigns/${campaign.id}`] = () => {
      listed = [other];
      return new Response(null, { status: 204 });
    };
    renderCampaigns();
    await chooseFromRowMenu("Tuesday group", "Delete");
    const dialog = await screen.findByRole("alertdialog");
    expect(dialog.textContent).toContain("Delete the campaign Tuesday group, with its characters and map states?");
    fireEvent.click(within(dialog).getByRole("button", { name: "Delete" }));
    await waitFor(() => expect(screen.queryByRole("link", { name: "Tuesday group" })).toBeNull());
    expect(screen.getByRole("link", { name: "Friday group" })).toBeTruthy();
    expect(fetchMock.mock.calls.filter(([, init]) => init?.method === "DELETE").map(([path]) => path)).toEqual([
      `/api/campaigns/${campaign.id}`,
    ]);
  });

  it("says in the delete confirmation that the campaign's zone on the board stays", async () => {
    routes["GET /api/board"] = () => json(200, { zones: [boardZone({ campaign_id: campaign.id })], may_create: true, signed_in: true });
    renderCampaigns();
    await chooseFromRowMenu("Tuesday group", "Delete");
    expect((await screen.findByRole("alertdialog")).textContent).toContain(
      "Its zone on the board stays, open to its members only, for the organisers and its moderators to keep or remove.",
    );
  });

  it("keeps the campaign when the delete is cancelled", async () => {
    renderCampaigns();
    await chooseFromRowMenu("Tuesday group", "Delete");
    fireEvent.click(within(await screen.findByRole("alertdialog")).getByRole("button", { name: "Cancel" }));
    await waitFor(() => expect(screen.queryByRole("alertdialog")).toBeNull());
    expect(screen.getByRole("link", { name: "Tuesday group" })).toBeTruthy();
    expect(fetchMock.mock.calls.some(([, init]) => init?.method === "DELETE")).toBe(false);
  });

  it("lists the campaigns with their module", async () => {
    renderCampaigns();
    const link = await screen.findByRole("link", { name: "Tuesday group" });
    expect(link.getAttribute("href")).toBe("/campaigns/cmp_00000000000a");
    expect(await screen.findByText("Crypt of Saint Vellis · revision 1")).toBeTruthy();
  });

  it("each row has the module, the players, when it was last played, its sessions and its playtime", async () => {
    const threeDaysAgo = new Date(Date.now() - 3 * 24 * 3600 * 1000).toISOString();
    routes["GET /api/campaigns"] = () =>
      json(200, [{ ...campaign, module_title: "The Crypt", last_played: threeDaysAgo, sessions: 2, playtime_s: 7500 }]);
    renderCampaigns();
    const row = (await screen.findByRole("link", { name: "Tuesday group" })).closest("li")!;
    expect(within(row).getByText("The Crypt · revision 1")).toBeTruthy();
    expect(within(row).getByText("Players: Host, Bo")).toBeTruthy();
    expect(within(row).getByText("Last played 3 days ago")).toBeTruthy();
    expect(within(row).getByText("2 sessions")).toBeTruthy();
    expect(within(row).getByText("2 h 5 min played")).toBeTruthy();
  });

  it("a campaign never played says so, and shows no playtime", async () => {
    renderCampaigns();
    const row = (await screen.findByRole("link", { name: "Tuesday group" })).closest("li")!;
    expect(within(row).getByText("Not played yet")).toBeTruthy();
    expect(within(row).queryByText(/played$/)).toBeNull();
  });

  it("groups the campaigns In progress, Paused and Complete, with Complete folded", async () => {
    routes["GET /api/campaigns"] = () =>
      json(200, [
        { ...campaign, id: "cmp_00000000000c", name: "Done one", status: "complete" },
        { ...campaign, id: "cmp_00000000000d", name: "Resting", status: "paused" },
        campaign,
      ]);
    renderCampaigns();
    await screen.findByRole("link", { name: "Tuesday group" });
    const groups = [...document.querySelectorAll(".campaign-group")] as HTMLElement[];
    expect(groups.map((g) => g.dataset.status)).toEqual(["in_progress", "paused", "complete"]);
    expect(within(groups[0]).getByRole("heading", { name: "In progress" })).toBeTruthy();
    expect(within(groups[0]).getByRole("link", { name: "Tuesday group" })).toBeTruthy();
    expect(within(groups[1]).getByRole("heading", { name: "Paused" })).toBeTruthy();
    expect(within(groups[1]).getByRole("link", { name: "Resting" })).toBeTruthy();
    const complete = groups[2].querySelector("details")!;
    expect(complete.open).toBe(false);
    expect(within(complete).getByText("Complete (1)")).toBeTruthy();
    expect(within(complete).getByRole("link", { hidden: true, name: "Done one" })).toBeTruthy();
  });

  it("shows no empty group", async () => {
    renderCampaigns();
    await screen.findByRole("link", { name: "Tuesday group" });
    expect(screen.queryByRole("heading", { name: "Paused" })).toBeNull();
    expect(screen.queryByText(/^Complete/)).toBeNull();
  });

  it("New campaign posts {name, module_id} and opens it", async () => {
    let sent: unknown;
    routes["POST /api/campaigns"] = (init) => {
      sent = JSON.parse(String(init?.body));
      expect(new Headers(init?.headers).get("Content-Type")).toBe("application/json");
      return json(201, { ...campaign, id: "cmp_00000000000b", name: "Solo", module_id: stonehell.id });
    };
    renderCampaigns();
    await screen.findByRole("option", { name: "Stonehell" });
    fireEvent.change(screen.getByLabelText("Name"), { target: { value: "Solo" } });
    fireEvent.change(screen.getByLabelText("Module"), { target: { value: stonehell.id } });
    await waitFor(() => expect((screen.getByLabelText("Ruleset") as HTMLSelectElement).value).toBe("osric"));
    fireEvent.click(screen.getByRole("button", { name: "New campaign" }));

    await waitFor(() =>
      expect(sent).toEqual({
        name: "Solo",
        module_id: stonehell.id,
        ruleset: "osric",
        setting: "realms",
        bundle_ids: [],
        rule_ids: [],
      }),
    );
    expect(await screen.findByRole("heading", { name: "Campaign page" })).toBeTruthy();
  });

  it("New campaign posts the chosen bundle_ids and rule_ids", async () => {
    let sent: unknown;
    routes["POST /api/campaigns"] = (init) => {
      sent = JSON.parse(String(init?.body));
      return json(201, campaign);
    };
    renderCampaigns();
    fireEvent.click(await screen.findByRole("checkbox", { name: /My table \(from ttrpg2\)/ }));
    fireEvent.click(screen.getByRole("checkbox", { name: /Tressym familiar/ }));
    fireEvent.change(screen.getByLabelText("Name"), { target: { value: "Tuesday" } });
    fireEvent.click(screen.getByRole("button", { name: "New campaign" }));

    await waitFor(() =>
      expect(sent).toEqual({
        name: "Tuesday",
        module_id: crypt.id,
        ruleset: "adnd2e",
        setting: "greyhawk",
        bundle_ids: [seeded.id],
        rule_ids: [tressym.id],
      }),
    );
  });

  it("offers the rulesets and settings, and preselects the module's", async () => {
    renderCampaigns();
    const ruleset = (await screen.findByLabelText("Ruleset")) as HTMLSelectElement;
    const setting = screen.getByLabelText("Setting") as HTMLSelectElement;
    await screen.findByRole("option", { name: "OSRIC" });
    expect([...ruleset.options].map((o) => o.text)).toEqual(["AD&D 2nd edition", "OSRIC"]);
    expect([...setting.options].map((o) => o.text)).toEqual(["Greyhawk", "Forgotten Realms", "No setting"]);
    await waitFor(() => expect([ruleset.value, setting.value]).toEqual(["adnd2e", "greyhawk"]));

    fireEvent.change(screen.getByLabelText("Module"), { target: { value: stonehell.id } });
    await waitFor(() => expect([ruleset.value, setting.value]).toEqual(["osric", "realms"]));
  });

  it("offers only No setting, chosen, where no setting is installed, and posts it", async () => {
    routes["GET /api/worlds"] = () => json(200, { ...worlds, settings: [] });
    let sent: Record<string, unknown> | undefined;
    routes["POST /api/campaigns"] = (init) => {
      sent = JSON.parse(String(init?.body));
      return json(201, campaign);
    };
    renderCampaigns();
    const setting = (await screen.findByLabelText("Setting")) as HTMLSelectElement;
    await screen.findByRole("option", { name: "OSRIC" });
    expect([...setting.options].map((o) => o.text)).toEqual(["No setting"]);
    expect(setting.value).toBe("");
    fireEvent.change(screen.getByLabelText("Name"), { target: { value: "Tuesday" } });
    fireEvent.click(screen.getByRole("button", { name: "New campaign" }));
    await waitFor(() => expect(sent).toMatchObject({ ruleset: "adnd2e", setting: null }));
  });

  it("preselects the preferred ruleset, else the first offered, and a preferred setting only where it is installed", async () => {
    routes["GET /api/worlds"] = () =>
      json(200, {
        rulesets: [
          { id: "mine", title: "Mine" },
          { id: "osric", title: "OSRIC", preferred: true },
        ],
        settings: [{ id: "realms", title: "Forgotten Realms" }],
      });
    renderCampaigns();
    const ruleset = (await screen.findByLabelText("Ruleset")) as HTMLSelectElement;
    const setting = screen.getByLabelText("Setting") as HTMLSelectElement;
    await screen.findByRole("option", { name: "Mine" });
    await waitFor(() => expect([ruleset.value, setting.value]).toEqual(["osric", ""]));
  });

  it("lists the modules by title in the Module select, the first chosen (DEL-246)", async () => {
    routes["GET /api/modules"] = () => json(200, [stonehell, { ...crypt, id: "mod_barrowmaze", title: "barrowmaze" }, crypt]);
    renderCampaigns();
    const module = (await screen.findByLabelText("Module")) as HTMLSelectElement;
    await screen.findByRole("option", { name: "Stonehell" });
    expect([...module.options].map((o) => o.text)).toEqual(["barrowmaze", crypt.title, "Stonehell"]);
    expect(module.value).toBe("mod_barrowmaze");
  });

  it("narrows the Module select with the module filter, and posts the module it leaves chosen (backlog 37)", async () => {
    let sent: unknown;
    routes["POST /api/campaigns"] = (init) => {
      sent = JSON.parse(String(init?.body));
      return json(201, campaign);
    };
    routes["GET /api/modules"] = () =>
      json(200, [
        { ...crypt, setting: "Greyhawk", levels: { min: 1, max: 3 }, tags: ["crypt"] },
        { ...stonehell, setting: "Forgotten Realms", levels: { min: 4, max: 8 }, tags: [] },
      ]);
    renderCampaigns();
    const module = (await screen.findByLabelText("Module")) as HTMLSelectElement;
    await screen.findByRole("option", { name: "Stonehell" });
    expect(screen.getByLabelText("Module setting")).toBeTruthy(); // apart from the campaign's own Setting
    fireEvent.change(screen.getByLabelText("Module starting level"), { target: { value: "5" } });
    expect([...module.options].map((o) => o.text)).toEqual(["Stonehell"]);
    await waitFor(() => expect(module.value).toBe(stonehell.id));
    fireEvent.change(screen.getByLabelText("Module title"), { target: { value: "nothing like it" } });
    expect([...module.options].map((o) => o.text)).toEqual(["No module to play fits the filter"]);
    expect(module.disabled).toBe(true);
    fireEvent.click(screen.getByRole("button", { name: "Clear the filter" }));
    fireEvent.change(screen.getByLabelText("Module tag"), { target: { value: "crypt" } });
    fireEvent.change(screen.getByLabelText("Name"), { target: { value: "Crypt night" } });
    fireEvent.click(screen.getByRole("button", { name: "New campaign" }));
    await waitFor(() => expect(sent).toMatchObject({ name: "Crypt night", module_id: crypt.id }));
  });

  it("No setting posts setting null", async () => {
    let sent: unknown;
    routes["POST /api/campaigns"] = (init) => {
      sent = JSON.parse(String(init?.body));
      return json(201, campaign);
    };
    renderCampaigns();
    await screen.findByRole("option", { name: "Forgotten Realms" });
    fireEvent.change(screen.getByLabelText("Setting"), { target: { value: "" } });
    fireEvent.change(screen.getByLabelText("Name"), { target: { value: "Bare" } });
    fireEvent.click(screen.getByRole("button", { name: "New campaign" }));
    await waitFor(() => expect(sent).toMatchObject({ name: "Bare", ruleset: "adnd2e", setting: null }));
  });

  it("offers no drafts: a draft can't start a campaign until it is marked ready", async () => {
    const draft = { ...crypt, id: "mod_dddddddddddd", title: "Barrow of the Lost", draft: true };
    routes["GET /api/modules"] = () => json(200, [draft, { ...crypt, draft: false }, { ...stonehell, draft: false }]);
    renderCampaigns();
    await screen.findByRole("option", { name: "Stonehell" });
    const module = screen.getByLabelText("Module") as HTMLSelectElement;
    expect([...module.options].map((o) => o.text)).toEqual(["Crypt of Saint Vellis", "Stonehell"]);
    expect(module.value).toBe(crypt.id);
    // The campaign list still names a draft's title.
    expect(await screen.findByText("Crypt of Saint Vellis · revision 1")).toBeTruthy();
  });

  it("says so when every module is a draft", async () => {
    routes["GET /api/modules"] = () => json(200, [{ ...crypt, draft: true }]);
    renderCampaigns();
    expect(await screen.findByText(/A campaign plays a module\./)).toBeTruthy();
    expect((screen.getByRole("button", { name: "New campaign" }) as HTMLButtonElement).disabled).toBe(true);
  });

  it("says so when there are no modules to start from", async () => {
    routes["GET /api/modules"] = () => json(200, []);
    renderCampaigns();
    expect(await screen.findByText(/A campaign plays a module\./)).toBeTruthy();
    const link = screen.getByRole("link", { name: "Import or make a module first" });
    expect(link.getAttribute("href")).toBe("/modules");
    expect((screen.getByRole("button", { name: "New campaign" }) as HTMLButtonElement).disabled).toBe(true);
  });

  it("an empty name says a campaign needs one, marks the field and focuses it", async () => {
    renderCampaigns();
    const button = (await screen.findByRole("button", { name: "New campaign" })) as HTMLButtonElement;
    await waitFor(() => expect(button.disabled).toBe(false));
    fireEvent.click(button);
    const input = screen.getByLabelText("Name");
    expect(await screen.findByText("A campaign needs a name.")).toBeTruthy();
    expect(input.getAttribute("aria-invalid")).toBe("true");
    expect(document.activeElement).toBe(input);
    expect(fetchMock.mock.calls.some(([, init]) => init?.method === "POST")).toBe(false);
    fireEvent.change(input, { target: { value: "Solo" } });
    expect(screen.queryByText("A campaign needs a name.")).toBeNull();
    expect(input.getAttribute("aria-invalid")).toBeNull();
  });

  it("with no module to play, the select says so and the hint is in the Module field", async () => {
    routes["GET /api/modules"] = () => json(200, [{ ...crypt, draft: true }]);
    renderCampaigns();
    const module = (await screen.findByLabelText("Module")) as HTMLSelectElement;
    await waitFor(() => expect([...module.options].map((o) => o.text)).toEqual(["No module yet"]));
    const field = module.closest(".field")!;
    expect(within(field as HTMLElement).getByText(/A campaign plays a module\./)).toBeTruthy();
    expect(within(field as HTMLElement).getByRole("link", { name: "Import or make a module first" })).toBeTruthy();
  });

  it("offers no empty module", async () => {
    routes["GET /api/modules"] = () => json(200, [{ ...crypt, empty: true }, { ...stonehell, empty: false }]);
    renderCampaigns();
    await screen.findByRole("option", { name: "Stonehell" });
    const module = screen.getByLabelText("Module") as HTMLSelectElement;
    expect([...module.options].map((o) => o.text)).toEqual(["Stonehell"]);
    expect(module.value).toBe(stonehell.id);
  });

  it("shows a first-run guide in three steps when there is nothing yet (G3, S2)", async () => {
    routes["GET /api/campaigns"] = () => json(200, []);
    routes["GET /api/modules"] = () => json(200, []);
    renderCampaigns();
    const guide = await screen.findByRole("region", { name: "Getting started" });
    const steps = within(guide).getAllByRole("listitem");
    expect(steps.map((s) => s.textContent)).toEqual(["Make or import a module", "Start a campaign from it", "Play"]);
    expect(steps.map((s) => within(s).getByRole("link").getAttribute("href"))).toEqual(["/modules", "/campaigns", "/play"]);
    // Instead of the bare form.
    expect(screen.queryByRole("button", { name: "New campaign" })).toBeNull();
    expect(screen.queryByText("No campaigns yet. Start one from a module.")).toBeNull();
  });
});

describe("Campaigns as cards (DEL-207)", () => {
  it("shows each campaign's banner, or its first letter, and remembers the choice", async () => {
    const painted = { ...campaign, id: "cmp_00000000000b", name: "Thursday group", banner: "img_0000000000aa" };
    routes["GET /api/campaigns"] = () => json(200, [painted, campaign]);
    renderCampaigns();
    fireEvent.click(await screen.findByRole("button", { name: "Cards" }));
    const cards = document.querySelectorAll(".module-card");
    expect(cards).toHaveLength(2);
    expect(cards[0].querySelector("img")?.getAttribute("src")).toBe(`/api/campaigns/${painted.id}/banner?v=img_0000000000aa&size=card`);
    expect(cards[1].querySelector(".module-card-blank")?.textContent).toBe("T");
    expect(within(cards[1] as HTMLElement).getByRole("link").getAttribute("href")).toBe(`/campaigns/${campaign.id}`);
    expect(localStorage.getItem("delve.campaignsLayout")).toBe("cards");
    expect(screen.getByRole("button", { name: "Cards" }).getAttribute("aria-pressed")).toBe("true");
  });

  it("shows who sits at the table, its open places and the places taken, on a card and a row (DEL-230)", async () => {
    const people = [
      { seat_id: "seat_00000000000a", name: "Host", role: "host", profile: null },
      { seat_id: "seat_00000000000b", name: "Bo", role: "player", profile: null },
    ];
    routes["GET /api/campaigns"] = () => json(200, [{ ...campaign, people, slots: 4, taken: 1 }]);
    renderCampaigns();
    const row = (await screen.findByRole("link", { name: "Tuesday group" })).closest("li")!;
    expect(within(row).getByText("1/4 seats taken")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Cards" }));
    const card = document.querySelector(".module-card") as HTMLElement;
    const faces = within(card).getByTestId("table-faces");
    expect(faces.querySelectorAll(".face-open")).toHaveLength(3);
    expect(within(faces).getByText("1/4 seats taken")).toBeTruthy();
  });

  it("keeps a campaign's menu on its card", async () => {
    routes[`DELETE /api/campaigns/${campaign.id}`] = () => new Response(null, { status: 204 });
    renderCampaigns();
    fireEvent.click(await screen.findByRole("button", { name: "Cards" }));
    const card = document.querySelector(".module-card") as HTMLElement;
    expect(within(card).getByRole("button", { name: "Actions for Tuesday group" })).toBeTruthy();
    await chooseFromRowMenu("Tuesday group", "Delete");
    fireEvent.click(within(await screen.findByRole("alertdialog")).getByRole("button", { name: "Delete" }));
    await waitFor(() =>
      expect(fetchMock.mock.calls.some(([path, init]) => path === `/api/campaigns/${campaign.id}` && init?.method === "DELETE")).toBe(true),
    );
  });
});
