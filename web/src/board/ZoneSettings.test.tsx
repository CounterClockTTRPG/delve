import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { I18nProvider } from "../i18n";
import { json, sent, stubFetch } from "../play/testing";
import { rights, zone } from "./testing";
import ZoneSettings, { ZonePeople } from "./ZoneSettings";

// A zone's settings and people (DEL-297): the levels offered follow the server's rules, a zone's removal says what goes
// with it, and a refusal is shown in the server's words.

afterEach(() => vi.unstubAllGlobals());

const ZONE = "/api/board/zones/zon_00000000000a";
const people = { moderators: [], members: [{ account_id: "acc_00000000000b", display_name: "Bob", username: "bob" }] };

function open(ui: React.ReactNode) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <I18nProvider language="en">{ui}</I18nProvider>
    </QueryClientProvider>,
  );
}

const optionsOf = (name: string) => within(screen.getByRole("combobox", { name })).getAllByRole("option").map((o) => o.textContent);

describe("ZoneSettings", () => {
  it("offers a host only the table and members levels", () => {
    stubFetch({});
    open(<ZoneSettings campaignId="cmp_00000000000a" wide={false} onDone={() => {}} />);
    expect(optionsOf("Who reads")).toEqual(["Its members", "The table"]);
    expect(screen.queryByRole("combobox", { name: "Campaign" })).toBeNull();
  });

  it("keeps write no wider than read", () => {
    stubFetch({ "GET /api/campaigns": () => json(200, []) });
    open(<ZoneSettings wide onDone={() => {}} />);
    const read = screen.getByRole("combobox", { name: "Who reads" });
    expect(optionsOf("Who reads")).toEqual(["Everybody", "Any account", "Its members"]);
    fireEvent.change(read, { target: { value: "everybody" } });
    expect(optionsOf("Who writes")).toEqual(["Any account", "Its members"]);
    fireEvent.change(screen.getByRole("combobox", { name: "Who writes" }), { target: { value: "members" } });
    fireEvent.change(read, { target: { value: "members" } });
    expect(optionsOf("Who writes")).toEqual(["Its members"]);
  });

  it("names how many topics go before a zone is removed", async () => {
    const fetchMock = stubFetch({
      [`GET ${ZONE}/people`]: () => json(200, { moderators: [], members: [] }),
      [`DELETE ${ZONE}`]: () => new Response(null, { status: 204 }),
    });
    const onDone = vi.fn();
    open(<ZoneSettings zone={zone({ rights: rights({ manage: true, manage_wide: true }) })} wide topics={3} onDone={onDone} />);
    fireEvent.click(screen.getByRole("button", { name: "Remove zone" }));
    expect(screen.getByRole("alert").textContent).toContain("Its 3 topics and all their posts go with it");
    expect(fetchMock.mock.calls.some(([, init]) => init?.method === "DELETE")).toBe(false);
    fireEvent.click(screen.getByRole("button", { name: "Yes, remove the zone" }));
    await waitFor(() => expect(onDone).toHaveBeenCalled());
  });

  it("makes a zone with its campaign and sends what was chosen", async () => {
    const fetchMock = stubFetch({
      "GET /api/campaigns": () => json(200, [{ id: "cmp_00000000000a", name: "Citadel" }]),
      "POST /api/board/zones": () => json(201, { zone: zone() }),
    });
    const onDone = vi.fn();
    open(<ZoneSettings wide onDone={onDone} />);
    fireEvent.change(screen.getByRole("textbox", { name: "Name" }), { target: { value: " Lore " } });
    await screen.findByRole("option", { name: "Citadel" });
    fireEvent.change(screen.getByRole("combobox", { name: "Campaign" }), { target: { value: "cmp_00000000000a" } });
    fireEvent.click(screen.getByRole("button", { name: "Save" }));
    await waitFor(() => expect(onDone).toHaveBeenCalled());
    expect(sent(fetchMock, "POST", "/api/board/zones")).toEqual([
      { name: "Lore", description: "", read: "accounts", write: "accounts", pictures: false, campaign_id: "cmp_00000000000a" },
    ]);
  });

  it("keeps write within read when the campaign is untied", () => {
    stubFetch({ "GET /api/campaigns": () => json(200, []) });
    const tied = zone({ read: "members", write: "table", campaign_id: "cmp_00000000000a", rights: rights({ manage: true, manage_wide: true }) });
    open(<ZoneSettings zone={tied} wide onDone={() => {}} />);
    fireEvent.change(screen.getByRole("combobox", { name: "Campaign" }), { target: { value: "" } });
    expect((screen.getByRole("combobox", { name: "Who reads" }) as HTMLSelectElement).value).toBe("members");
    expect((screen.getByRole("combobox", { name: "Who writes" }) as HTMLSelectElement).value).toBe("members");
  });

  it("changes the zone it made, not makes another, when Save is pressed again after the moderators failed", async () => {
    let tries = 0;
    const fetchMock = stubFetch({
      "POST /api/board/zones": () => json(201, { zone: zone() }),
      [`PATCH ${ZONE}`]: () => json(200, { zone: zone() }),
      [`PUT ${ZONE}/moderators`]: () => (++tries === 1 ? json(422, { error: "No account is called zed." }) : json(200, people)),
    });
    const onDone = vi.fn();
    open(<ZoneSettings campaignId="cmp_00000000000a" wide={false} onDone={onDone} />);
    fireEvent.change(screen.getByRole("textbox", { name: "Name" }), { target: { value: "Lore" } });
    fireEvent.change(screen.getByRole("textbox", { name: "Moderators" }), { target: { value: "zed" } });
    fireEvent.click(screen.getByRole("button", { name: "Save" }));
    expect((await screen.findByRole("alert")).textContent).toBe("No account is called zed.");
    fireEvent.click(screen.getByRole("button", { name: "Save" }));
    await waitFor(() => expect(onDone).toHaveBeenCalled());
    expect(sent(fetchMock, "POST", "/api/board/zones")).toHaveLength(1);
    expect(sent(fetchMock, "PATCH", ZONE)).toHaveLength(1);
  });

  it("lets a host keep the wider levels an organiser set, offered but not chosen again", async () => {
    const opened = zone({ read: "accounts", write: "accounts", campaign_id: "cmp_00000000000a", rights: rights({ manage: true }) });
    const fetchMock = stubFetch({
      [`GET ${ZONE}/people`]: () => json(200, { moderators: [], members: [] }),
      [`PATCH ${ZONE}`]: () => json(200, { zone: opened }),
    });
    const onDone = vi.fn();
    open(<ZoneSettings zone={opened} wide={false} onDone={onDone} />);
    const read = screen.getByRole("combobox", { name: "Who reads" }) as HTMLSelectElement;
    expect(read.value).toBe("accounts");
    expect(optionsOf("Who reads")).toEqual(["Its members", "The table", "Any account"]);
    expect((within(read).getByRole("option", { name: "Any account" }) as HTMLOptionElement).disabled).toBe(true);
    expect((screen.getByRole("combobox", { name: "Who writes" }) as HTMLSelectElement).value).toBe("accounts");
    fireEvent.click(screen.getByRole("checkbox", { name: "Pictures in posts" }));
    fireEvent.click(screen.getByRole("button", { name: "Save" }));
    await waitFor(() => expect(onDone).toHaveBeenCalled());
    expect(sent(fetchMock, "PATCH", ZONE)).toEqual([
      { name: "The engine", description: "How Delve plays.", read: "accounts", write: "accounts", pictures: true },
    ]);
  });

  it("shows the server's refusal", async () => {
    stubFetch({ "POST /api/board/zones": () => json(422, { error: "That name is taken." }) });
    open(<ZoneSettings campaignId="cmp_00000000000a" wide={false} onDone={() => {}} />);
    fireEvent.change(screen.getByRole("textbox", { name: "Name" }), { target: { value: "Lore" } });
    fireEvent.click(screen.getByRole("button", { name: "Save" }));
    expect((await screen.findByRole("alert")).textContent).toBe("That name is taken.");
  });
});

describe("ZonePeople", () => {
  it("adds a member by username and shows the server's refusal", async () => {
    const fetchMock = stubFetch({
      [`GET ${ZONE}/people`]: () => json(200, people),
      [`POST ${ZONE}/members`]: (init) =>
        JSON.parse(String(init?.body)).username === "zed" ? json(404, { error: "No account is called zed." }) : json(200, people),
    });
    open(<ZonePeople zone={zone()} onDone={() => {}} />);
    expect(await screen.findByText("Bob")).toBeTruthy();
    fireEvent.change(screen.getByRole("textbox", { name: "Add by username" }), { target: { value: "zed" } });
    fireEvent.click(screen.getByRole("button", { name: "Add" }));
    expect((await screen.findByRole("alert")).textContent).toBe("No account is called zed.");
    expect(sent(fetchMock, "POST", `${ZONE}/members`)).toEqual([{ username: "zed" }]);
  });

  it("removes a member", async () => {
    const fetchMock = stubFetch({
      [`GET ${ZONE}/people`]: () => json(200, people),
      [`DELETE ${ZONE}/members/acc_00000000000b`]: () => json(200, { moderators: [], members: [] }),
    });
    open(<ZonePeople zone={zone()} onDone={() => {}} />);
    fireEvent.click(await screen.findByRole("button", { name: "Remove Bob from the zone" }));
    await waitFor(() => expect(fetchMock.mock.calls.some(([, init]) => init?.method === "DELETE")).toBe(true));
  });
});
