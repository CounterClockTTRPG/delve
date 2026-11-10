import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { CAMPAIGN, base, json, renderWith, sent, stubFetch } from "../play/testing";
import type { GeoDocFeature, WorldMapDoc } from "./editorApi";
import StartKnowledge from "./StartKnowledge";

afterEach(() => {
  vi.unstubAllGlobals();
});

function region(id: string, name: string, hidden = false): GeoDocFeature {
  return {
    type: "Feature",
    id,
    geometry: {
      type: "Polygon",
      coordinates: [
        [
          [0, 0],
          [10, 0],
          [10, 10],
          [0, 0],
        ],
      ],
    },
    properties: { layer: "regions", kind: "region", name, description: "", dm_notes: "", tags: [], hidden },
  };
}

const doc: WorldMapDoc = {
  name: "vale",
  title: "The Vale",
  source: "module",
  status: "ready",
  picture: null,
  knowledge: { everything: false },
  reading: null,
  geo: {
    type: "FeatureCollection",
    delve: {
      version: 1,
      frame: { width_km: 40, height_km: 20, units: "km" },
      grid: { kind: "square", size_km: 10, cols: 4, rows: 2, origin: [0, 0], orientation: "pointy" },
      terrain: "pppppppp",
      picture: null,
    },
    features: [region("domain", "Domain of Greyhawk"), region("cairn-hills", "Cairn Hills"), region("wild", "The Wild")],
  },
};

const path = `${base}/world-maps/vale/knowledge`;

async function open() {
  renderWith(<StartKnowledge campaignId={CAMPAIGN} name="vale" title="The Vale" />);
  fireEvent.click(screen.getByRole("button", { name: "What the party knows at the start" }));
  return screen.findByRole("dialog");
}

describe("StartKnowledge", () => {
  it("sends the picked regions", async () => {
    const fetchMock = stubFetch({
      [`GET ${base}/world-maps/vale`]: () => json(200, doc),
      [`PUT ${path}`]: () => json(200, { everything: false }),
    });
    const dialog = await open();
    fireEvent.click(within(dialog).getByLabelText("Some regions"));
    fireEvent.click(await within(dialog).findByLabelText("Domain of Greyhawk"));
    fireEvent.click(within(dialog).getByLabelText("Cairn Hills"));
    fireEvent.click(within(dialog).getByRole("button", { name: "Set what they know" }));
    await waitFor(() =>
      expect(sent(fetchMock, "PUT", path)).toEqual([{ how: "regions", regions: ["domain", "cairn-hills"] }]),
    );
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
  });

  it("sends everything or nothing without regions, and refuses regions with none picked", async () => {
    const fetchMock = stubFetch({
      [`GET ${base}/world-maps/vale`]: () => json(200, doc),
      [`PUT ${path}`]: () => json(200, { everything: true }),
    });
    const dialog = await open();
    fireEvent.click(within(dialog).getByLabelText("Some regions"));
    await within(dialog).findByLabelText("Cairn Hills");
    const set = within(dialog).getByRole("button", { name: "Set what they know" }) as HTMLButtonElement;
    expect(set.disabled).toBe(true);
    fireEvent.click(within(dialog).getByLabelText("Everything"));
    fireEvent.click(set);
    await waitFor(() => expect(sent(fetchMock, "PUT", path)).toEqual([{ how: "everything" }]));
  });

  it("offers an area drawn on the map", async () => {
    stubFetch({ [`GET ${base}/world-maps/vale`]: () => json(200, doc) });
    const dialog = await open();
    fireEvent.click(within(dialog).getByLabelText("An area drawn on the map"));
    expect(await within(dialog).findByRole("region", { name: "The world map: The Vale" })).toBeTruthy();
    expect(within(dialog).getByText("Draw the area they know: click its corners, then its first point to close it.")).toBeTruthy();
    expect((within(dialog).getByRole("button", { name: "Set what they know" }) as HTMLButtonElement).disabled).toBe(true);
  });
});
