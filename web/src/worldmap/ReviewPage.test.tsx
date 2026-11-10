import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { RouterProvider, createMemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";
import { DialogsProvider } from "../components/dialogs";
import { I18nProvider } from "../i18n";
import { json, sent, stubFetch } from "../play/testing";
import type { WorldMapDoc } from "./editorApi";
import type { Reading } from "./importApi";
import { doubtPoint } from "./ReviewPage";
import WorldMapRoutes from "./WorldMapRoutes";

afterEach(() => {
  vi.unstubAllGlobals();
});

const MODULE = "mod_0123456789ab";
const base = `/api/modules/${MODULE}/world-maps/vale`;

function reading(frame: string | null): Reading {
  return {
    clusters: [
      { id: 0, colour: [40, 120, 40], cells: [0, 1, 2, 4, 5, 6], suggestion: "forest", terrain: "forest" },
      { id: 1, colour: [240, 230, 200], cells: [3, 7], suggestion: null, terrain: frame },
    ],
    doubts: [
      {
        id: "d1",
        kind: "label-unpaired",
        ref: "label-1",
        message: "HARDBY has no symbol near it.",
        reading: "place",
        alternatives: ["place", "drop"],
        resolved: false,
        choice: null,
        data: { at: [15, 5] },
      },
      {
        id: "d2",
        kind: "cell-mixed",
        ref: "cell:6",
        message: "Cell 6 holds two colours.",
        reading: "forest",
        alternatives: [],
        resolved: false,
        choice: null,
      },
    ],
  };
}

function doc(frame: string | null = null, status: WorldMapDoc["status"] = "review"): WorldMapDoc {
  return {
    name: "vale",
    title: "The Vale",
    source: "module",
    status,
    picture: null,
    knowledge: null,
    reading: reading(frame),
    geo: {
      type: "FeatureCollection",
      delve: {
        version: 1,
        frame: { width_km: 40, height_km: 20, units: "km" },
        grid: { kind: "square", size_km: 10, cols: 4, rows: 2, origin: [0, 0], orientation: "pointy" },
        terrain: "fff.fff.",
        picture: null,
      },
      features: [
        {
          type: "Feature",
          id: "label-1",
          geometry: { type: "Point", coordinates: [15, 5] },
          properties: {
            layer: "places",
            kind: "town",
            name: "Hardby",
            description: "",
            dm_notes: "",
            tags: [],
            hidden: false,
            doubt: "d1",
          },
        },
      ],
    },
  };
}

function renderReview() {
  const router = createMemoryRouter(
    [
      { path: "/world-maps/:owner/:ownerId/:name/*", element: <WorldMapRoutes /> },
      { path: "/modules/:moduleId", element: <p>Module page</p> },
    ],
    { initialEntries: [`/world-maps/module/${MODULE}/vale/review`] },
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

describe("ReviewPage", () => {
  it("shows the reading on the map beside the review, and holds the server's answer to a decision", async () => {
    const fetchMock = stubFetch({
      [`GET ${base}`]: () => json(200, doc()),
      [`POST ${base}/review`]: () => json(200, doc("outside")),
      [`POST ${base}/accept`]: () => json(200, { ...doc("outside", "ready"), reading: null }),
    });
    const router = renderReview();
    expect(await screen.findByRole("heading", { name: "Review: The Vale" })).toBeTruthy();
    expect(screen.getByRole("region", { name: "The world map: The Vale" })).toBeTruthy();
    const accept = screen.getByRole("button", { name: "Accept the map" }) as HTMLButtonElement;
    expect(accept.disabled).toBe(true);

    const picker = within(screen.getByRole("listitem", { name: "Colour 2" })).getByRole("combobox");
    fireEvent.change(picker, { target: { value: "outside" } });
    await waitFor(() => expect(sent(fetchMock, "POST", `${base}/review`)).toEqual([{ clusters: { "1": "outside" } }]));
    await waitFor(() => expect(accept.disabled).toBe(false));

    fireEvent.click(accept);
    await waitFor(() => expect(router.state.location.pathname).toBe(`/modules/${MODULE}`));
    expect(sent(fetchMock, "POST", `${base}/accept`)).toHaveLength(1);
  });

  it("says so for a map that isn't in review", async () => {
    stubFetch({ [`GET ${base}`]: () => json(200, { ...doc("forest", "ready"), reading: null }) });
    renderReview();
    expect(await screen.findByText("This map isn't waiting for a review.")).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Accept the map" })).toBeNull();
  });

  it("finds a doubt by its place, its cell, or the feature it is about", () => {
    const shown = doc();
    const [label, mixed] = shown.reading ? (shown.reading as Reading).doubts : [];
    expect(doubtPoint(shown, label)).toEqual([15, 5]);
    expect(doubtPoint(shown, mixed)).toEqual([25, 15]);
    expect(doubtPoint(shown, { ...label, data: undefined, ref: "nothing" })).toEqual([15, 5]);
  });
});
