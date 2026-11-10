import { fireEvent, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { page } from "../setting/testing";
import type { SeatView } from "../worldmap/api";
import { seatView } from "../worldmap/testing";
import SettingPanel from "./SettingPanel";
import { CAMPAIGN, base, json, renderWith, stubFetch, type Handler } from "./testing";

// Leaflet stays out of it: the stand-in shows what the panel gave the map.
vi.mock("../worldmap/WorldMapView", () => ({
  default: ({ view, tileUrl }: { view: SeatView; tileUrl: string | null }) => (
    <div data-testid="world-map-view" data-name={view.name} data-tiles={tileUrl ?? ""} />
  ),
}));

afterEach(() => {
  vi.unstubAllGlobals();
});

const setting = `${base}/setting`;

/** The table's setting routes (Task 8 and Task 9), as a seat of the campaign gets them. */
function settingRoutes(extra: Record<string, Handler> = {}): Record<string, Handler> {
  return {
    [`GET ${setting}`]: () => json(200, { id: "greyhawk", title: "Greyhawk", kinds: ["settlements"], calendar: null }),
    [`GET ${setting}/search?q=Hardby`]: () =>
      json(200, {
        query: "Hardby",
        results: [{ kind: "settlements", key: "Hardby", title: "Hardby", text: "<<Hardby>> is a port.", origin: "shipped" }],
      }),
    [`GET ${setting}/pages/Hardby`]: () =>
      json(200, page("Hardby", { text: "A port south of [[Greyhawk City|the city]].", fields: { ruler: "Despotrix" } })),
    [`GET ${setting}/pages/Greyhawk%20City`]: () => json(200, page("Greyhawk City", { text: "The Gem of the Flanaess." })),
    [`GET ${setting}/kinds/settlements`]: () =>
      json(200, { kind: "settlements", results: [{ kind: "settlements", key: "Dyvers", title: "Dyvers", text: "", origin: "shipped" }] }),
    [`GET ${setting}/facts`]: () =>
      json(200, {
        facts: [
          { text: "Hardby has a Despotrix.", category: "greyhawk", origin: "shipped" },
          { text: "The harbour master is a half-orc.", category: "", origin: "campaign" },
        ],
      }),
    [`GET ${setting}/maps`]: () =>
      json(200, [
        { name: "flanaess", title: "The Flanaess" },
        { name: "isles", title: "The Isles" },
      ]),
    [`GET ${setting}/maps/flanaess/view`]: () =>
      json(
        200,
        seatView({
          name: "flanaess",
          title: "The Flanaess",
          picture: { width_px: 400, height_px: 300, km_per_px: 0.1 },
          tiles_version: "p1",
        }),
      ),
    [`GET ${setting}/maps/isles/view`]: () => json(200, seatView({ name: "isles", title: "The Isles", tiles_version: "" })),
    ...extra,
  };
}

const panel = () => screen.getByTestId("setting-panel");

describe("SettingPanel", () => {
  it("opens a search hit's page in the panel, follows a link in it, and goes back", async () => {
    const fetchMock = stubFetch(settingRoutes());
    renderWith(<SettingPanel campaignId={CAMPAIGN} />);
    fireEvent.change(await screen.findByLabelText("Search the lore"), { target: { value: "Hardby" } });
    const hit = await screen.findByRole("button", { name: "Hardby" });
    expect(hit.closest("li")!.querySelector("mark")!.textContent).toBe("Hardby");
    fireEvent.click(hit);

    expect(await screen.findByRole("heading", { name: "Hardby" })).toBeTruthy();
    expect(within(panel()).getByText("Despotrix")).toBeTruthy();
    fireEvent.click(within(panel()).getByRole("link", { name: "the city" }));
    expect(await screen.findByRole("heading", { name: "Greyhawk City" })).toBeTruthy();
    expect(screen.getByText("The Gem of the Flanaess.")).toBeTruthy();
    // Still on the play screen: the link opened its page in the panel, not a route.
    expect(fetchMock.mock.calls.map(([p]) => String(p))).toContain(`${setting}/pages/Greyhawk%20City`);

    fireEvent.click(screen.getByRole("button", { name: "Back" }));
    expect(await screen.findByRole("heading", { name: "Hardby" })).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Back" }));
    expect(await screen.findByRole("button", { name: "Hardby" })).toBeTruthy();
    expect(screen.queryByRole("heading", { name: "Hardby" })).toBeNull();
  });

  it("browses a kind", async () => {
    stubFetch(settingRoutes());
    renderWith(<SettingPanel campaignId={CAMPAIGN} />);
    fireEvent.click(await screen.findByRole("button", { name: "settlements" }));
    expect(await screen.findByRole("button", { name: "Dyvers" })).toBeTruthy();
  });

  it("has no edit control at all, even for the owner's seat", async () => {
    const fetchMock = stubFetch(settingRoutes());
    renderWith(<SettingPanel campaignId={CAMPAIGN} />);
    fireEvent.change(await screen.findByLabelText("Search the lore"), { target: { value: "Hardby" } });
    fireEvent.click(await screen.findByRole("button", { name: "Hardby" }));
    await screen.findByRole("heading", { name: "Hardby" });
    for (const name of [/edit/i, /write/i, /delete/i, /revert/i, /save/i])
      expect(within(panel()).queryByRole("button", { name })).toBeNull();
    expect(within(panel()).queryByRole("link", { name: /write/i })).toBeNull();
    expect(within(panel()).queryByRole("textbox")).toBeNull();
    // Nothing but the seat's own read-only routes.
    for (const [path, init] of fetchMock.mock.calls) {
      expect(init?.method ?? "GET").toBe("GET");
      expect(String(path).startsWith(setting)).toBe(true);
    }
  });

  it("lists the table's facts, the campaign's marked", async () => {
    stubFetch(settingRoutes());
    renderWith(<SettingPanel campaignId={CAMPAIGN} />);
    fireEvent.click(await screen.findByRole("tab", { name: "Facts" }));
    const own = (await screen.findByText("The harbour master is a half-orc.")).closest("li")!;
    expect(within(own).getByText("This campaign")).toBeTruthy();
    const shipped = screen.getByText("Hardby has a Despotrix.").closest("li")!;
    expect(within(shipped).queryByText("This campaign")).toBeNull();
  });

  it("shows a setting map with WorldMapView and the table's tile URL", async () => {
    stubFetch(settingRoutes());
    renderWith(<SettingPanel campaignId={CAMPAIGN} />);
    fireEvent.click(await screen.findByRole("tab", { name: "Maps" }));
    const map = await screen.findByTestId("world-map-view");
    expect(map.getAttribute("data-name")).toBe("flanaess");
    expect(map.getAttribute("data-tiles")).toBe(`${setting}/maps/flanaess/tiles/{z}/{x}/{y}?v=p1`);
    fireEvent.change(screen.getByLabelText("World map"), { target: { value: "isles" } });
    expect((await screen.findByTestId("world-map-view")).getAttribute("data-name")).toBe("isles");
  });

  it("says so when the campaign has no setting", async () => {
    stubFetch({ [`GET ${setting}`]: () => json(404, { error: "This campaign has no setting." }) });
    renderWith(<SettingPanel campaignId={CAMPAIGN} />);
    expect(await screen.findByText("This campaign has no setting.")).toBeTruthy();
    expect(screen.queryByLabelText("Search the lore")).toBeNull();
  });
});
