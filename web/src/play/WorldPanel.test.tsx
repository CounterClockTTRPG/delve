import { fireEvent, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { seatView } from "../worldmap/testing";
import { CAMPAIGN, base, json, renderWith, stubFetch, world, worldRoutes } from "./testing";
import WorldPanel from "./WorldPanel";

afterEach(() => {
  vi.unstubAllGlobals();
});

/** Makes `usePhone` answer `phone`, as a browser under 600 px would. */
function stubPhone(phone: boolean) {
  vi.stubGlobal("matchMedia", (query: string) => ({
    matches: phone,
    media: query,
    addEventListener: () => {},
    removeEventListener: () => {},
  }));
}

describe("WorldPanel", () => {
  it("shows the map, the known places, the known quests, the factions' standing and the possessions", async () => {
    const fetchMock = stubFetch(worldRoutes());
    renderWith(<WorldPanel campaignId={CAMPAIGN} />);

    expect(await screen.findByText("Find the relic")).toBeTruthy();
    expect(screen.getByText(/the abbot/)).toBeTruthy();
    expect(screen.getByText("The ward fails.")).toBeTruthy();
    expect(screen.getByText("The abbot sent us.")).toBeTruthy();
    expect(screen.getByText("The Watch")).toBeTruthy();
    expect(screen.getByText("Friendly")).toBeTruthy();
    expect(screen.getByText("Bess")).toBeTruthy();
    expect(screen.getByText(/Ash/)).toBeTruthy();
    expect(await screen.findByRole("region", { name: "The world map: Greyhawk region" })).toBeTruthy();
    const places = await screen.findByRole("list", { name: "Known places" });
    expect(places.textContent).toContain("Hardby");
    expect(places.textContent).toContain("You are here");
    const asked = fetchMock.mock.calls.map(([path]) => String(path));
    expect(asked).toContain(`${base}/world-maps/greyhawk-region/view`);
    expect(asked.some((path) => path.includes("dm-view"))).toBe(false);
    expect(screen.queryByLabelText("World map")).toBeNull(); // one map, no picker
  });

  it("picks among several maps, and says Map offline when one can't be read", async () => {
    stubFetch({
      ...worldRoutes([
        { name: "greyhawk-region", title: "Greyhawk region" },
        { name: "isles", title: "The Isles" },
      ]),
      [`GET ${base}/world-maps/isles/view`]: () => json(409, { error: "map offline" }),
    });
    renderWith(<WorldPanel campaignId={CAMPAIGN} />);
    const picker = (await screen.findByLabelText("World map")) as HTMLSelectElement;
    expect(picker.value).toBe("greyhawk-region");
    expect(await screen.findByRole("region", { name: /Greyhawk region/ })).toBeTruthy();
    fireEvent.change(picker, { target: { value: "isles" } });
    expect(await screen.findByText("Map offline")).toBeTruthy();
    expect(screen.queryByRole("region", { name: /Greyhawk region/ })).toBeNull();
  });

  it("reads the open map's view again on a world event", async () => {
    let calls = 0;
    stubFetch({
      ...worldRoutes(),
      [`GET ${base}/world-maps/greyhawk-region/view`]: () => {
        calls += 1;
        // The second read knows Greyhawk alone.
        return json(200, calls > 1 ? seatView({ features: seatView().features.slice(0, 1) }) : seatView());
      },
    });
    const { client } = renderWith(<WorldPanel campaignId={CAMPAIGN} />);
    expect((await screen.findByRole("list", { name: "Known places" })).textContent).toContain("Hardby");
    // The play screen invalidates the world's queries on a `world` event; the view's key is under them.
    await client.invalidateQueries({ queryKey: ["campaign", CAMPAIGN, "world"] });
    await waitFor(() => expect(screen.getByRole("list", { name: "Known places" }).textContent).not.toContain("Hardby"));
  });

  it("says so when the world has nothing yet", async () => {
    stubFetch({
      [`GET ${base}/world`]: () => json(200, { ...world, position: null, quests: [], factions: [], possessions: [] }),
      [`GET ${base}/world-maps`]: () => json(200, []),
    });
    renderWith(<WorldPanel campaignId={CAMPAIGN} />);
    expect(await screen.findByText("No quests yet.")).toBeTruthy();
    // No world map at all is said as such, not as a map that won't load (DEL-265).
    expect(screen.getByTestId("world-none").textContent).toContain("This campaign has no world map");
  });

  it("fills the phone's screen with the map, with the known places in a sheet", async () => {
    stubPhone(true);
    stubFetch(worldRoutes());
    const { container } = renderWith(<WorldPanel campaignId={CAMPAIGN} />);
    expect(await screen.findByRole("region", { name: /Greyhawk region/ })).toBeTruthy();
    expect(container.querySelector(".world-panel.world-phone")).toBeTruthy();
    expect(container.querySelector(".world-phone .world-map-full")).toBeTruthy();
    const toggle = screen.getByRole("button", { name: "Known places" });
    expect(toggle.getAttribute("aria-expanded")).toBe("false");
    expect(screen.queryByRole("list", { name: "Known places" })).toBeNull();
    fireEvent.click(toggle);
    expect(toggle.getAttribute("aria-expanded")).toBe("true");
    expect((await screen.findByRole("list", { name: "Known places" })).textContent).toContain("Hardby");
    expect(screen.getByText("Find the relic")).toBeTruthy();
  });
});
