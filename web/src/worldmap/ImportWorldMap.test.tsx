import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { json, renderWith, sent, stubFetch } from "../play/testing";
import ImportWorldMap from "./ImportWorldMap";

afterEach(() => {
  vi.unstubAllGlobals();
});

const MODULE = "mod_0123456789ab";
const owner = { kind: "module", moduleId: MODULE } as const;
const geojsonPath = `/api/modules/${MODULE}/world-maps/geojson`;

const DOCUMENT = {
  type: "FeatureCollection",
  features: [
    { type: "Feature", geometry: { type: "Point", coordinates: [4.5, 51] }, properties: { Naam: "Oakton", Soort: "stad" } },
    { type: "Feature", geometry: { type: "Point", coordinates: [5, 51.2] }, properties: { Naam: "Elmbury", Soort: "dorp" } },
  ],
};

function file(content: string, name: string, type: string) {
  const made = new File([content], name, { type });
  // jsdom's File has no text(); the import reads the file through it.
  Object.defineProperty(made, "text", { value: async () => content });
  return made;
}

async function open() {
  fireEvent.click(screen.getByRole("button", { name: "Import a world map" }));
  return screen.findByRole("dialog");
}

function name(dialog: HTMLElement, value = "vale") {
  fireEvent.change(within(dialog).getByLabelText("Name"), { target: { value } });
  fireEvent.change(within(dialog).getByLabelText("Title"), { target: { value: "The Vale" } });
}

describe("ImportWorldMap", () => {
  it("asks for the mapping and the size when the GeoJSON isn't in km, and sends the width", async () => {
    const answers = [
      () =>
        json(422, {
          error: "The map needs its size.",
          needs: "scale",
          properties: ["Naam", "Soort"],
          kinds: ["stad", "dorp"],
        }),
      () => json(201, { name: "vale", title: "The Vale", status: "ready" }),
    ];
    const fetchMock = stubFetch({ [`POST ${geojsonPath}`]: () => answers.shift()!() });
    renderWith(<ImportWorldMap owner={owner} />);
    const dialog = await open();
    name(dialog);
    fireEvent.change(within(dialog).getByLabelText("GeoJSON file"), {
      target: { files: [file(JSON.stringify(DOCUMENT), "vale.geojson", "application/geo+json")] },
    });
    fireEvent.click(within(dialog).getByRole("button", { name: "Import" }));

    await within(dialog).findByText("The map needs its size.");
    fireEvent.change(within(dialog).getByLabelText("The names are in"), { target: { value: "Naam" } });
    fireEvent.change(within(dialog).getByLabelText("The kinds are in"), { target: { value: "Soort" } });
    fireEvent.change(within(dialog).getByLabelText("stad"), { target: { value: "city" } });
    fireEvent.change(within(dialog).getByLabelText("Width of the map (km)"), { target: { value: "320" } });
    fireEvent.click(within(dialog).getByRole("button", { name: "Import" }));

    await waitFor(() => expect(sent(fetchMock, "POST", geojsonPath)).toHaveLength(2));
    const [first, second] = sent(fetchMock, "POST", geojsonPath) as Record<string, unknown>[];
    expect(first).toEqual({ name: "vale", title: "The Vale", document: DOCUMENT });
    expect(second).toEqual({
      name: "vale",
      title: "The Vale",
      document: DOCUMENT,
      mapping: { name: "Naam", kind: "Soort", values: { stad: "city" } },
      width_km: 320,
    });
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
  });

  it("sends a known distance between two places instead of the width", async () => {
    const answers = [
      () => json(422, { error: "The map needs its size.", needs: "scale", properties: ["name"], kinds: [] }),
      () => json(201, { name: "vale" }),
    ];
    const fetchMock = stubFetch({ [`POST ${geojsonPath}`]: () => answers.shift()!() });
    renderWith(<ImportWorldMap owner={owner} />);
    const dialog = await open();
    name(dialog);
    fireEvent.change(within(dialog).getByLabelText("GeoJSON file"), {
      target: { files: [file(JSON.stringify(DOCUMENT), "vale.geojson", "application/geo+json")] },
    });
    fireEvent.click(within(dialog).getByRole("button", { name: "Import" }));
    await within(dialog).findByText("The map needs its size.");
    fireEvent.click(within(dialog).getByLabelText("A known distance between two places"));
    fireEvent.change(within(dialog).getByLabelText("From"), { target: { value: "Oakton" } });
    fireEvent.change(within(dialog).getByLabelText("To"), { target: { value: "Elmbury" } });
    fireEvent.change(within(dialog).getByLabelText("Distance"), { target: { value: "30" } });
    fireEvent.change(within(dialog).getByLabelText("Units"), { target: { value: "miles" } });
    fireEvent.click(within(dialog).getByRole("button", { name: "Import" }));
    await waitFor(() => expect(sent(fetchMock, "POST", geojsonPath)).toHaveLength(2));
    expect((sent(fetchMock, "POST", geojsonPath)[1] as Record<string, unknown>).known).toEqual({
      from: "Oakton",
      to: "Elmbury",
      distance: 30,
      units: "miles",
    });
  });

  it("refuses a picture with no grid until two points are marked, and sends the key with them", async () => {
    const conversion = {
      id: "cnv_000000000001",
      kind: "worldmap",
      title: "The Vale",
      mode: "ready",
      status: "running",
      step: "tiles",
      done: 0,
      total: 0,
      steps: { index: 1, count: 6 },
      module_id: null,
      warnings: [],
      error: null,
      created_at: "2026-10-18T20:00:00Z",
      updated_at: "2026-10-18T20:00:00Z",
      target: { module_id: MODULE, name: "vale", title: "The Vale" },
    };
    const fetchMock = stubFetch({});
    fetchMock.mockImplementation(async (path: string) =>
      path.startsWith("/api/conversions/worldmap?") ? json(202, conversion) : json(404, { error: "not found" }),
    );
    renderWith(<ImportWorldMap owner={owner} />);
    const dialog = await open();
    fireEvent.click(within(dialog).getByLabelText("A picture with its key"));
    name(dialog);
    const picture = file("png", "vale.png", "image/png");
    fireEvent.change(within(dialog).getByLabelText("The picture"), { target: { files: [picture] } });
    fireEvent.change(within(dialog).getByLabelText("Grid"), { target: { value: "none" } });
    fireEvent.change(within(dialog).getByLabelText("Distance"), { target: { value: "20" } });
    fireEvent.click(within(dialog).getByRole("button", { name: "Start reading" }));
    expect((await within(dialog).findByRole("alert")).textContent).toBe(
      "Mark two points on the picture and give their distance.",
    );
    expect(fetchMock.mock.calls.some(([p]) => String(p).startsWith("/api/conversions/worldmap"))).toBe(false);

    const shown = within(dialog).getByRole("img", { name: "The picture: click two points a known distance apart" });
    fireEvent.click(shown, { clientX: 10, clientY: 20 });
    fireEvent.click(shown, { clientX: 110, clientY: 20 });
    expect(within(dialog).getByText("2 of 2 points marked")).toBeTruthy();
    fireEvent.click(within(dialog).getByRole("button", { name: "Start reading" }));

    await within(dialog).findByTestId("conversion-progress");
    const [path, init] = fetchMock.mock.calls.find(([p]) => String(p).startsWith("/api/conversions/worldmap"))!;
    const query = new URL(String(path), "http://delve").searchParams;
    expect(Object.fromEntries(query)).toEqual({
      module_id: MODULE,
      name: "vale",
      title: "The Vale",
      cell: "none",
      distance: "20",
      units: "km",
      points: "10,20,110,20",
    });
    expect(new Headers(init?.headers).get("Content-Type")).toBe("image/png");
    expect(init?.body).toBe(picture);
  });

  it("sends the grid's key, 1 hex = 30 miles", async () => {
    const fetchMock = stubFetch({});
    fetchMock.mockImplementation(async () => json(415, { error: "unsupported" }));
    renderWith(<ImportWorldMap owner={{ kind: "campaign", campaignId: "cmp_00000000000a" }} />);
    const dialog = await open();
    fireEvent.click(within(dialog).getByLabelText("A picture with its key"));
    name(dialog, "flanaess");
    fireEvent.change(within(dialog).getByLabelText("The picture"), { target: { files: [file("x", "f.jpg", "image/jpeg")] } });
    fireEvent.change(within(dialog).getByLabelText("Grid"), { target: { value: "hex" } });
    fireEvent.change(within(dialog).getByLabelText("Distance"), { target: { value: "30" } });
    fireEvent.change(within(dialog).getByLabelText("Units"), { target: { value: "miles" } });
    fireEvent.click(within(dialog).getByRole("button", { name: "Start reading" }));
    await within(dialog).findByRole("alert");
    const query = new URL(String(fetchMock.mock.calls[0][0]), "http://delve").searchParams;
    expect(query.get("campaign_id")).toBe("cmp_00000000000a");
    expect(query.get("cell")).toBe("hex");
    expect(query.get("distance")).toBe("30");
    expect(query.get("units")).toBe("miles");
    expect(query.has("points")).toBe(false);
  });
});
