import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { Link, RouterProvider, createMemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { DialogsProvider } from "../components/dialogs";
import { I18nProvider } from "../i18n";
import type { GeoDocument, WorldMapDoc } from "./editorApi";
import WorldMapRoutes from "./WorldMapRoutes";

const MODULE = "mod_0123456789ab";
const base = `/api/modules/${MODULE}/world-maps/region`;

function geo(overrides: Partial<GeoDocument["delve"]> = {}): GeoDocument {
  return {
    type: "FeatureCollection",
    delve: {
      version: 1,
      frame: { width_km: 40, height_km: 30, units: "miles" },
      grid: { kind: "square", size_km: 10, cols: 4, rows: 3, origin: [0, 0], orientation: "pointy" },
      terrain: "pppppppppppp",
      picture: null,
      ...overrides,
    },
    features: [
      {
        type: "Feature",
        id: "greyhawk",
        geometry: { type: "Point", coordinates: [5, 15] },
        properties: {
          layer: "places",
          kind: "city",
          name: "Greyhawk",
          description: "The Gem of the Flanaess.",
          dm_notes: "",
          tags: [],
          hidden: false,
        },
      },
      {
        type: "Feature",
        id: "selintan",
        geometry: {
          type: "LineString",
          coordinates: [
            [2, 0],
            [3, 30],
          ],
        },
        properties: {
          layer: "water",
          kind: "river",
          name: "Selintan",
          description: "",
          dm_notes: "",
          tags: [],
          hidden: false,
        },
      },
    ],
  };
}

function doc(overrides: Partial<WorldMapDoc> = {}): WorldMapDoc {
  return {
    name: "region",
    title: "The region",
    source: "module",
    status: "ready",
    geo: geo(),
    picture: null,
    knowledge: null,
    reading: null,
    ...overrides,
  };
}

type Handler = (init: RequestInit | undefined) => Response;
let routes: Record<string, Handler>;
let fetchMock: ReturnType<typeof vi.fn>;

function json(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
}

beforeEach(() => {
  routes = { [`GET ${base}`]: () => json(200, doc()) };
  fetchMock = vi.fn(async (path: string, init?: RequestInit) => {
    const handler = routes[`${init?.method ?? "GET"} ${path}`];
    return handler ? handler(init) : json(404, { error: "not found" });
  });
  vi.stubGlobal("fetch", fetchMock);
});

afterEach(() => {
  vi.unstubAllGlobals();
});

function renderEditor() {
  const router = createMemoryRouter(
    [
      { path: "/world-maps/:owner/:ownerId/:name/*", element: <WorldMapRoutes /> },
      {
        path: "/modules/:moduleId",
        element: (
          <p>
            Module page <Link to={`/world-maps/module/${MODULE}/region`}>back</Link>
          </p>
        ),
      },
    ],
    { initialEntries: [`/world-maps/module/${MODULE}/region`] },
  );
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <I18nProvider language="en">
        <DialogsProvider>
          <RouterProvider router={router} />
        </DialogsProvider>
      </I18nProvider>
    </QueryClientProvider>,
  );
  return router;
}

/** A feature's button in the side panel's list (the map's own markers are buttons too). */
async function featureButton(name: string) {
  return within(await screen.findByRole("region", { name: "Features on the map" })).getByRole("button", { name });
}

async function hideGreyhawk() {
  fireEvent.click(await featureButton("Greyhawk"));
  fireEvent.click(screen.getByLabelText("Hidden from the players"));
}

describe("WorldMapEditor", () => {
  it("draws the map's terrain, its places and its rivers", async () => {
    renderEditor();
    const map = await screen.findByRole("region", { name: "The world map: The region" });
    await waitFor(() => expect(map.querySelector(".world-terrain-plains")).toBeTruthy());
    expect([...map.querySelectorAll(".world-place-label")].map((label) => label.textContent)).toEqual(["Greyhawk"]);
    expect(map.querySelector(".world-river")).toBeTruthy();
    expect(screen.getByRole("link", { name: "Export (GeoJSON)" }).getAttribute("href")).toBe(`${base}/export.geojson`);
    // A map without a picture has no picture to download.
    expect(screen.queryByRole("link", { name: "Download the picture" })).toBeNull();
  });

  it("offers the picture's download, and lays the picture's own tiles", async () => {
    const picture = { id: "abc123", width_px: 1000, height_px: 750, km_per_px: 0.04, asset: null };
    routes[`GET ${base}`] = () => json(200, doc({ geo: geo({ picture }), picture: "abc123" }));
    renderEditor();
    const link = await screen.findByRole("link", { name: "Download the picture" });
    expect(link.getAttribute("href")).toBe(`${base}/picture`);
    const map = screen.getByRole("region", { name: "The world map: The region" });
    await waitFor(() => expect(map.querySelector("img.leaflet-tile")).toBeTruthy());
    for (const img of map.querySelectorAll<HTMLImageElement>("img.leaflet-tile"))
      expect(img.src).toMatch(/\/api\/world-pictures\/abc123\/tiles\/\d+\/\d+\/\d+$/);
  });

  it("fades the picture with the Picture slider, and remembers it", async () => {
    const picture = { id: "abc123", width_px: 1000, height_px: 750, km_per_px: 0.04, asset: null };
    routes[`GET ${base}`] = () => json(200, doc({ geo: geo({ picture }), picture: "abc123" }));
    localStorage.removeItem("delve.worldmap.pictureOpacity");
    renderEditor();
    const slider = (await screen.findByRole("slider", { name: "Picture" })) as HTMLInputElement;
    expect(slider.value).toBe("100");
    const map = screen.getByRole("region", { name: "The world map: The region" });
    await waitFor(() => expect(map.querySelector("img.leaflet-tile")).toBeTruthy());
    const layer = () => map.querySelector("img.leaflet-tile")!.closest<HTMLElement>(".leaflet-layer")!;
    fireEvent.change(slider, { target: { value: "40" } });
    await waitFor(() => expect(layer().style.opacity).toBe("0.4"));
    expect(screen.getByText("40%")).toBeTruthy();
    expect(localStorage.getItem("delve.worldmap.pictureOpacity")).toBe("40");
  });

  it("has no Picture slider without a picture", async () => {
    renderEditor();
    await screen.findByRole("region", { name: "The world map: The region" });
    expect(screen.queryByRole("slider", { name: "Picture" })).toBeNull();
  });

  it("undoes and redoes an edit, also with Ctrl+Z and Ctrl+Shift+Z", async () => {
    renderEditor();
    await hideGreyhawk();
    const hidden = () => (screen.getByLabelText("Hidden from the players") as HTMLInputElement).checked;
    expect(hidden()).toBe(true);
    expect(screen.getByTitle("Unsaved changes")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Undo" }));
    expect(hidden()).toBe(false);
    expect(screen.queryByTitle("Unsaved changes")).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Redo" }));
    expect(hidden()).toBe(true);
    fireEvent.keyDown(window, { key: "z", ctrlKey: true });
    expect(hidden()).toBe(false);
    fireEvent.keyDown(window, { key: "Z", ctrlKey: true, shiftKey: true });
    expect(hidden()).toBe(true);
  });

  it("saves the document it holds, then holds the server's answer", async () => {
    let sent: { title: string; geo: GeoDocument } | null = null;
    // The server derived lake cells from an area: its answer has other terrain.
    routes[`PUT ${base}`] = (init) => {
      sent = JSON.parse(String(init?.body));
      return json(200, doc({ geo: { ...sent!.geo, delve: { ...sent!.geo.delve, terrain: "llllpppppppp" } } }));
    };
    renderEditor();
    await hideGreyhawk();
    const map = screen.getByRole("region", { name: "The world map: The region" });
    expect(map.querySelector(".world-terrain-lake")).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Save" }));
    await waitFor(() => expect(sent).not.toBeNull());
    expect(sent!.title).toBe("The region");
    expect(sent!.geo.features.find((f) => f.id === "greyhawk")?.properties.hidden).toBe(true);
    await waitFor(() => expect(map.querySelector(".world-terrain-lake")).toBeTruthy());
    expect(screen.queryByTitle("Unsaved changes")).toBeNull();
    expect((screen.getByRole("button", { name: "Save" }) as HTMLButtonElement).disabled).toBe(true);
  });

  it("shows the problems of a document the server refuses", async () => {
    routes[`PUT ${base}`] = () =>
      json(422, { error: "The map doesn't hold together.", problems: ["greyhawk: places need a Point geometry"] });
    renderEditor();
    await hideGreyhawk();
    fireEvent.click(screen.getByRole("button", { name: "Save" }));
    expect(await screen.findByText("greyhawk: places need a Point geometry")).toBeTruthy();
    expect(screen.getByTitle("Unsaved changes")).toBeTruthy();
  });

  it("blocks leaving with unsaved changes, with Delve's own dialog", async () => {
    const confirm = vi.spyOn(window, "confirm");
    const router = renderEditor();
    await hideGreyhawk();
    fireEvent.click(screen.getByRole("link", { name: "Back to the module" }));
    const dialog = await screen.findByRole("alertdialog");
    expect(within(dialog).getByText("You have unsaved changes to this world map. Leave without saving?")).toBeTruthy();
    fireEvent.click(within(dialog).getByRole("button", { name: "Cancel" }));
    await waitFor(() => expect(screen.queryByRole("alertdialog")).toBeNull());
    expect(router.state.location.pathname).toBe(`/world-maps/module/${MODULE}/region`);

    fireEvent.click(screen.getByRole("link", { name: "Back to the module" }));
    fireEvent.click(within(await screen.findByRole("alertdialog")).getByRole("button", { name: "Leave" }));
    expect(await screen.findByText(/Module page/)).toBeTruthy();
    expect(confirm).not.toHaveBeenCalled();
  });

  it("goes back to the setting's Maps tab from a setting's map", async () => {
    routes["GET /api/settings/greyhawk/world-maps/region"] = () => json(200, doc({ source: "setting" }));
    const router = createMemoryRouter(
      [
        { path: "/world-maps/:owner/:ownerId/:name/*", element: <WorldMapRoutes /> },
        { path: "/settings/:settingId", element: <p>Setting page</p> },
      ],
      { initialEntries: ["/world-maps/setting/greyhawk/region"] },
    );
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(
      <QueryClientProvider client={client}>
        <I18nProvider language="en">
          <DialogsProvider>
            <RouterProvider router={router} />
          </DialogsProvider>
        </I18nProvider>
      </QueryClientProvider>,
    );
    fireEvent.click(await screen.findByRole("link", { name: "Back to the setting" }));
    expect(await screen.findByText("Setting page")).toBeTruthy();
    expect(router.state.location.pathname + router.state.location.search).toBe("/settings/greyhawk?tab=maps");
  });

  it("removes the selected feature", async () => {
    renderEditor();
    fireEvent.click(await featureButton("Selintan"));
    fireEvent.click(screen.getByRole("button", { name: "Remove from the map" }));
    const map = screen.getByRole("region", { name: "The world map: The region" });
    await waitFor(() => expect(map.querySelector(".world-river")).toBeNull());
    expect(within(await screen.findByRole("region", { name: "Features on the map" })).queryByText("Selintan")).toBeNull();
  });
});
