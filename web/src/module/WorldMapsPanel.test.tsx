import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { json, renderWith, sent, stubFetch } from "../play/testing";
import WorldMapsPanel from "./WorldMapsPanel";

afterEach(() => {
  vi.unstubAllGlobals();
});

const MODULE = "mod_0123456789ab";
const base = `/api/modules/${MODULE}/world-maps`;
const worlds = {
  rulesets: [{ id: "adnd2e", title: "AD&D 2nd edition" }],
  settings: [
    { id: "forgotten-realms", title: "Forgotten Realms" },
    { id: "greyhawk", title: "Greyhawk" },
  ],
};
const ROWS = [
  { name: "flanaess", title: "The Flanaess", status: "ready", source: "picture", picture: true },
  { name: "isles", title: "The Isles", status: "review", source: "picture", picture: true },
];

function routes(greyhawkMaps: unknown[] = []) {
  return {
    [`GET ${base}`]: () => json(200, ROWS),
    "GET /api/worlds": () => json(200, worlds),
    "GET /api/settings/greyhawk/world-maps": () => json(200, greyhawkMaps),
    "GET /api/settings/forgotten-realms/world-maps": () => json(200, []),
    "POST /api/settings/greyhawk/world-maps/copy": () =>
      json(201, { name: "flanaess", title: "The Flanaess", source: "setting", status: "ready" }),
  };
}

const row = async (title: string) => (await screen.findByText(title)).closest("li")!;

describe("WorldMapsPanel", () => {
  it("lists the module's world maps with Export, Edit, Review and the picture", async () => {
    stubFetch(routes());
    renderWith(<WorldMapsPanel moduleId={MODULE} />);
    const flanaess = await row("The Flanaess");
    expect(within(flanaess).getByRole("link", { name: "Export" }).getAttribute("href")).toBe(
      `${base}/flanaess/export.geojson`,
    );
    expect(within(flanaess).getByRole("link", { name: "Edit" }).getAttribute("href")).toBe(
      `/world-maps/module/${MODULE}/flanaess`,
    );
    const isles = await row("The Isles");
    expect(within(isles).getByText("In review")).toBeTruthy();
    expect(within(isles).getByRole("link", { name: "Review" })).toBeTruthy();
  });

  it("copies a ready map into its setting's maps, the module's setting first", async () => {
    const fetchMock = stubFetch(routes());
    renderWith(<WorldMapsPanel moduleId={MODULE} setting="Greyhawk" />);
    const flanaess = await row("The Flanaess");
    fireEvent.click(await within(flanaess).findByRole("button", { name: "Copy to Greyhawk's maps" }));
    await waitFor(() =>
      expect(sent(fetchMock, "POST", "/api/settings/greyhawk/world-maps/copy")).toEqual([
        { module_id: MODULE, name: "flanaess" },
      ]),
    );
    // A map in review can't be copied.
    expect(within(await row("The Isles")).queryByRole("button", { name: /Copy to/ })).toBeNull();
  });

  it("shows the server's message when the setting has the name already", async () => {
    stubFetch({
      ...routes(),
      "POST /api/settings/greyhawk/world-maps/copy": () =>
        json(409, { error: "Greyhawk has a world map named flanaess." }),
    });
    renderWith(<WorldMapsPanel moduleId={MODULE} setting="greyhawk" />);
    fireEvent.click(await within(await row("The Flanaess")).findByRole("button", { name: "Copy to Greyhawk's maps" }));
    expect(await screen.findByText(/Greyhawk has a world map named flanaess\./)).toBeTruthy();
  });

  it("links a copied map to the setting's Maps tab", async () => {
    stubFetch(routes([{ name: "flanaess", title: "The Flanaess", status: "ready", source: "setting", picture: true }]));
    renderWith(<WorldMapsPanel moduleId={MODULE} setting="greyhawk" />);
    const flanaess = await row("The Flanaess");
    const link = await within(flanaess).findByRole("link", { name: "In Greyhawk's maps" });
    expect(link.getAttribute("href")).toBe("/settings/greyhawk?tab=maps");
    expect(within(flanaess).queryByRole("button", { name: /Copy to/ })).toBeNull();
  });
});
