import { screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import MapPanel from "./MapPanel";
import { base, json, party, renderWith, stubFetch } from "./testing";

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("MapPanel", () => {
  it("shows Map offline on 409, and a group switcher when split", async () => {
    const fetchMock = stubFetch({
      [`GET ${base}/maps/crypt/view?characters=chr_00000000000a,chr_00000000000b`]: () =>
        json(409, { error: "map offline" }),
    });
    renderWith(
      <MapPanel
        campaignId="cmp_00000000000a"
        party={party}
        positions={[
          { map: "crypt", location: "room.entry", label: "Entry", characters: ["Ash", "Birch"] },
          { map: "crypt", location: "room.chute", label: "Chute", characters: ["chr_00000000000c"] },
        ]}
      />,
    );

    expect(await screen.findByText("Map offline")).toBeTruthy();
    // Split: one view per group, picked with a switcher; never the DM view.
    expect(screen.getByRole("button", { name: /Entry.*Ash, Birch/ }).getAttribute("aria-pressed")).toBe("true");
    expect(screen.getByRole("button", { name: /Chute.*Cedar/ })).toBeTruthy();
    expect(fetchMock.mock.calls.map(([p]) => String(p)).some((p) => p.includes("dm-view"))).toBe(false);
  });

  it("says the part has no map when nobody is on one, never Map offline", async () => {
    const fetchMock = stubFetch({});
    renderWith(<MapPanel campaignId="cmp_00000000000a" party={party} positions={[]} />);

    const status = await screen.findByRole("status");
    expect(status.textContent).toBe("This part of the adventure has no map.");
    expect(screen.queryByText("Map offline")).toBeNull();
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("says nobody is on a map yet while the party is empty", async () => {
    const fetchMock = stubFetch({});
    renderWith(<MapPanel campaignId="cmp_00000000000a" party={[]} positions={[]} />);

    const status = await screen.findByRole("status");
    expect(status.textContent).toBe("No character is on a map yet.");
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("frames the party's room and follows it, rather than the whole map", async () => {
    stubFetch({
      [`GET ${base}/maps/crypt/view?characters=chr_00000000000a`]: () =>
        json(200, { svg: '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 40 20" width="400" height="200"></svg>' }),
    });
    renderWith(
      <MapPanel
        campaignId="cmp_00000000000a"
        party={party}
        positions={[{ map: "crypt", location: "room.entry_hall", label: "Entry Hall", characters: ["Ash"] }]}
      />,
    );
    const follow = await screen.findByRole("button", { name: "Focus on the party" });
    expect(follow.getAttribute("aria-pressed")).toBe("true");
  });

  it("on a phone, opens on the whole known map, with the party's room one tap away", async () => {
    stubFetch({
      [`GET ${base}/maps/crypt/view?characters=chr_00000000000a`]: () =>
        json(200, { svg: '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 40 20" width="400" height="200"></svg>' }),
    });
    renderWith(
      <MapPanel
        campaignId="cmp_00000000000a"
        party={party}
        positions={[{ map: "crypt", location: "room.entry_hall", label: "Entry Hall", characters: ["Ash"] }]}
        fitWhole
      />,
    );
    const follow = await screen.findByRole("button", { name: "Focus on the party" });
    expect(follow.getAttribute("aria-pressed")).toBe("false");
  });

  it("draws the party's faces on the fight's tokens (DEL-10)", async () => {
    const token =
      '<g class="marker" data-name="chr_00000000000a" data-tag="party">' +
      '<circle cx="2" cy="-3" r="0.4" fill="#2c7be5"/><text x="2" y="-3">A</text></g>';
    stubFetch({
      [`GET ${base}/maps/crypt/view?characters=chr_00000000000a`]: () =>
        json(200, { svg: `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 -10 10 10"><g class="markers">${token}</g></svg>` }),
    });
    const { container } = renderWith(
      <MapPanel
        campaignId="cmp_00000000000a"
        party={party}
        positions={[{ map: "crypt", location: "room.entry", label: "Entry", characters: ["chr_00000000000a"] }]}
        faces={{ chr_00000000000a: { portrait: { kind: "image", image_id: "img_000000000001" }, hp: 4, hpMax: 8 } }}
      />,
    );
    await vi.waitFor(() => expect(container.querySelector("g.marker[data-face=portrait] image")).not.toBeNull());
    expect(container.querySelector(".token-hp")!.getAttribute("stroke-dasharray")).toBe("50 100");
  });
});
