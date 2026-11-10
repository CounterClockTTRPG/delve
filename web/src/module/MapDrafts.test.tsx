import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import type { ReactNode } from "react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { EventsContext, type Conversion, type Subscribe } from "../api";
import { DialogsProvider } from "../components/dialogs";
import { I18nProvider } from "../i18n";
import GenerateMap from "./GenerateMap";
import MapDrafts from "./MapDrafts";
import type { MapDraft } from "./mapDrafts";
import SketchNotice from "./SketchNotice";

const MODULE = "mod_1";
const DRAFTS = `/api/modules/${MODULE}/map-drafts`;

const warren: MapDraft = {
  id: "cnv_1",
  kind: "dungeon-map",
  name: "warren",
  source: '# Drawn from a description.\nroom "r1" { rect 1,1 4 x 4 }\n',
  warnings: [{ code: "map-described", message: "Drawn from a description: an invented layout.", ref: "map:warren" }],
  created_at: "2026-10-18T10:00:00Z",
  replaces: null,
  part: null,
  page: null,
  maps: [{ name: "warren", title: "warren", source: '# Drawn from a description.\nroom "r1" { rect 1,1 4 x 4 }\n', part: null }],
};
const caves: MapDraft = {
  id: "cnv_2",
  kind: "book-map",
  name: "caves",
  source: "# Drawn from the book's map asset:map-page-3.\nroom \"r2\" { rect 1,1 4 x 4 }\n",
  warnings: [],
  created_at: "2026-10-18T10:05:00Z",
  replaces: "caves",
  part: "caves",
  page: "map-page-3",
  maps: [{ name: "caves", title: "caves", source: "# Drawn from the book's map asset:map-page-3.\nroom \"r2\" { rect 1,1 4 x 4 }\n", part: "caves" }],
};
const ship: MapDraft = {
  ...caves,
  id: "cnv_4",
  name: "page-35",
  source: "# Drawn from the book's map asset:page-35.\nroom \"r1\" { rect 1,1 4 x 4 }\n",
  replaces: null,
  part: "the-sea-ghost",
  page: "page-35",
  maps: [{ name: "page-35", title: "page-35", source: "# Drawn from the book's map asset:page-35.\nroom \"r1\" { rect 1,1 4 x 4 }\n", part: "the-sea-ghost" }],
};
const house: MapDraft = {
  ...caves,
  id: "cnv_5",
  name: "house-ground-floor",
  replaces: null,
  part: "the-haunted-house",
  page: "map-page-2",
  maps: [
    { name: "house-ground-floor", title: "Ground floor", source: 'room "r1" { rect 1,1 4 x 4 }\n', part: "the-haunted-house" },
    { name: "house-cellar", title: "Cellar", source: 'room "r22" { rect 1,1 4 x 4 }\n', part: "the-haunted-house" },
  ],
};

const started: Conversion = {
  id: "cnv_3",
  kind: "dungeon-map",
  title: "A kobold warren",
  mode: "ready",
  status: "running",
  step: "drawing",
  done: 0,
  total: 1,
  steps: { index: 1, count: 1 },
  module_id: null,
  warnings: [],
  error: null,
  created_at: "2026-10-18T10:10:00Z",
  updated_at: "2026-10-18T10:10:00Z",
  target: { module_id: MODULE, name: "warren" },
};

type Handler = (init: RequestInit | undefined) => Response;
let routes: Record<string, Handler>;
let fetchMock: ReturnType<typeof vi.fn>;
let heard: Record<string, ((data: unknown) => void)[]>;

const subscribe: Subscribe = (handlers) => {
  for (const [type, handle] of Object.entries(handlers)) (heard[type] ??= []).push(handle);
  return () => {
    for (const [type, handle] of Object.entries(handlers)) heard[type] = heard[type].filter((h) => h !== handle);
  };
};

function json(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
}

function calls(key: string): (RequestInit | undefined)[] {
  return fetchMock.mock.calls.filter(([path, init]) => `${init?.method ?? "GET"} ${path}` === key).map(([, init]) => init);
}

beforeEach(() => {
  heard = {};
  routes = {
    [`GET ${DRAFTS}`]: () => json(200, [warren, caves]),
    "POST /api/dsl/render": (init) => {
      const { source } = JSON.parse(String(init?.body));
      return json(200, { svg: `<svg data-source="${source.includes("r1") ? "warren" : "caves"}"></svg>`, diagnostics: [] });
    },
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

function renderWith(children: ReactNode) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <I18nProvider language="en">
        <EventsContext.Provider value={subscribe}>
          <MemoryRouter>
            <DialogsProvider>{children}</DialogsProvider>
          </MemoryRouter>
        </EventsContext.Provider>
      </I18nProvider>
    </QueryClientProvider>,
  );
}

describe("GenerateMap", () => {
  it("starts a draft from the description, and shows the drafts side by side", async () => {
    routes[`POST ${DRAFTS}`] = () => json(202, started);
    renderWith(<GenerateMap moduleId={MODULE} />);

    fireEvent.click(screen.getByRole("button", { name: "Generate a map" }));
    const dialog = await screen.findByRole("dialog", { name: "Generate a map" });
    fireEvent.change(within(dialog).getByLabelText("Description"), { target: { value: "A kobold warren" } });
    fireEvent.change(within(dialog).getByLabelText("Name of the map (optional)"), { target: { value: "warren" } });
    fireEvent.click(within(dialog).getByRole("button", { name: "Draw it" }));

    await waitFor(() => expect(calls(`POST ${DRAFTS}`)).toHaveLength(1));
    expect(JSON.parse(String(calls(`POST ${DRAFTS}`)[0]?.body))).toEqual({ description: "A kobold warren", name: "warren" });
    expect(await within(dialog).findByTestId("conversion-progress")).toBeTruthy();

    const cards = await within(dialog).findAllByTestId("map-draft");
    expect(cards).toHaveLength(2);
    await waitFor(() => expect(dialog.querySelectorAll("svg[data-source]")).toHaveLength(2));
    expect(within(cards[0]).getByText("From a description")).toBeTruthy();
    expect(within(cards[1]).getByText("From the book's map")).toBeTruthy();
    expect(within(cards[1]).getByText("Keeping it replaces the map caves.")).toBeTruthy();
  });

  it("refetches the drafts when a drawing ends", async () => {
    renderWith(<MapDrafts moduleId={MODULE} />);
    await screen.findAllByTestId("map-draft");
    expect(calls(`GET ${DRAFTS}`)).toHaveLength(1);

    act(() => heard.conversion?.forEach((h) => h({ ...started, status: "done" })));

    await waitFor(() => expect(calls(`GET ${DRAFTS}`)).toHaveLength(2));
  });
});

describe("MapDrafts", () => {
  it("keeps a description draft under the name typed", async () => {
    routes[`POST ${DRAFTS}/cnv_1/keep`] = () => json(201, { name: "lower-warren" });
    renderWith(<MapDrafts moduleId={MODULE} />);

    const [card] = await screen.findAllByTestId("map-draft");
    fireEvent.change(within(card).getByLabelText("Keep as"), { target: { value: "lower-warren" } });
    fireEvent.click(within(card).getByRole("button", { name: "Keep" }));

    await waitFor(() => expect(calls(`POST ${DRAFTS}/cnv_1/keep`)).toHaveLength(1));
    expect(JSON.parse(String(calls(`POST ${DRAFTS}/cnv_1/keep`)[0]?.body))).toEqual({ name: "lower-warren" });
  });

  it("keeps a book draft over its sketch, and discards after asking", async () => {
    routes[`POST ${DRAFTS}/cnv_2/keep`] = () => json(201, { name: "caves" });
    routes[`DELETE ${DRAFTS}/cnv_1`] = () => new Response(null, { status: 204 });
    renderWith(<MapDrafts moduleId={MODULE} />);

    const [first, second] = await screen.findAllByTestId("map-draft");
    fireEvent.click(within(second).getByRole("button", { name: "Keep" }));
    await waitFor(() => expect(calls(`POST ${DRAFTS}/cnv_2/keep`)).toHaveLength(1));
    expect(JSON.parse(String(calls(`POST ${DRAFTS}/cnv_2/keep`)[0]?.body))).toEqual({});

    fireEvent.click(within(first).getByRole("button", { name: "Discard" }));
    const confirm = await screen.findByRole("alertdialog");
    fireEvent.click(within(confirm).getByRole("button", { name: "Discard" }));
    await waitFor(() => expect(calls(`DELETE ${DRAFTS}/cnv_1`)).toHaveLength(1));
  });

  it("keeps a book draft for a new map under the name typed", async () => {
    routes[`GET ${DRAFTS}`] = () => json(200, [ship]);
    routes[`POST ${DRAFTS}/cnv_4/keep`] = () => json(201, { name: "sea-ghost" });
    renderWith(<MapDrafts moduleId={MODULE} />);

    const [card] = await screen.findAllByTestId("map-draft");
    expect(within(card).queryByText(/replaces the map/)).toBeNull();
    fireEvent.change(within(card).getByLabelText("Keep as"), { target: { value: "sea-ghost" } });
    fireEvent.click(within(card).getByRole("button", { name: "Keep" }));

    await waitFor(() => expect(calls(`POST ${DRAFTS}/cnv_4/keep`)).toHaveLength(1));
    expect(JSON.parse(String(calls(`POST ${DRAFTS}/cnv_4/keep`)[0]?.body))).toEqual({ name: "sea-ghost" });
  });

  it("lists a mismatch's problems, and Keep anyway keeps with force", async () => {
    routes[`GET ${DRAFTS}`] = () => json(200, [ship]);
    routes[`POST ${DRAFTS}/cnv_4/keep`] = (init) =>
      JSON.parse(String(init?.body)).force
        ? json(201, { name: "page-35" })
        : json(409, {
            error: "The draft's rooms don't match The Sea Ghost.",
            problems: ["Room r1 is labelled “1. Kitchen”, but 1 of The Sea Ghost is “Main Deck”."],
          });
    renderWith(<MapDrafts moduleId={MODULE} />);

    const [card] = await screen.findAllByTestId("map-draft");
    fireEvent.click(within(card).getByRole("button", { name: "Keep" }));

    const dialog = await screen.findByRole("alertdialog");
    expect(within(dialog).getByText(/The draft's rooms don't match The Sea Ghost\./)).toBeTruthy();
    expect(within(dialog).getByText(/Room r1 is labelled “1\. Kitchen”/)).toBeTruthy();
    fireEvent.click(within(dialog).getByRole("button", { name: "Keep anyway" }));

    await waitFor(() => expect(calls(`POST ${DRAFTS}/cnv_4/keep`)).toHaveLength(2));
    expect(JSON.parse(String(calls(`POST ${DRAFTS}/cnv_4/keep`)[1]?.body))).toEqual({ name: "page-35", force: true });
    expect(screen.queryByRole("alert")).toBeNull();
  });

  it("shows a tab per level, each drawn when chosen", async () => {
    routes[`GET ${DRAFTS}`] = () => json(200, [house]);
    renderWith(<MapDrafts moduleId={MODULE} />);

    const [card] = await screen.findAllByTestId("map-draft");
    const tabs = within(card).getAllByRole("tab");
    expect(tabs.map((tab) => tab.textContent)).toEqual(["Ground floor", "Cellar"]);
    expect(within(card).getByRole("tablist", { name: "Levels" })).toBeTruthy();
    expect(tabs[0].getAttribute("aria-selected")).toBe("true");
    await waitFor(() => expect(card.querySelector("svg")?.getAttribute("data-source")).toBe("warren"));

    fireEvent.click(tabs[1]);

    expect(within(card).getAllByRole("tab")[1].getAttribute("aria-selected")).toBe("true");
    await waitFor(() => expect(card.querySelector("svg")?.getAttribute("data-source")).toBe("caves"));
    expect(within(card).getByText("Keeps 2 maps, one per level.")).toBeTruthy();
  });

  it("shows no tabs for a draft of one map", async () => {
    renderWith(<MapDrafts moduleId={MODULE} />);
    const cards = await screen.findAllByTestId("map-draft");
    expect(within(cards[0]).queryByRole("tablist")).toBeNull();
  });

  it("shows a draft that drew no map with its warning, and only Discard", async () => {
    const empty = { ...warren, source: null, maps: [], warnings: [{ code: "map-not-drawn", message: "The map couldn't be drawn.", ref: "map:warren" }] };
    routes[`GET ${DRAFTS}`] = () => json(200, [empty]);
    renderWith(<MapDrafts moduleId={MODULE} />);

    const [card] = await screen.findAllByTestId("map-draft");
    expect(within(card).getByText("No map was drawn.")).toBeTruthy();
    expect(within(card).getByText("The map couldn't be drawn.")).toBeTruthy();
    expect(within(card).queryByRole("button", { name: "Keep" })).toBeNull();
    expect(calls("POST /api/dsl/render")).toHaveLength(0);
  });

  it("shows nothing without drafts", async () => {
    routes[`GET ${DRAFTS}`] = () => json(200, []);
    const { container } = renderWith(<MapDrafts moduleId={MODULE} />);
    await waitFor(() => expect(calls(`GET ${DRAFTS}`)).toHaveLength(1));
    expect(container.textContent).toBe("");
  });
});

describe("SketchNotice", () => {
  const sketch = "# Sketched from the room key: an invented layout. The book's map is asset:map-page-3.\nmap \"x\" {}\n";

  it("offers to draw the map from the book's map page", async () => {
    routes[`POST ${DRAFTS}/from-book`] = () => json(202, { ...started, kind: "book-map", title: "caves" });
    renderWith(<SketchNotice moduleId={MODULE} source={sketch} mapName="caves" />);

    fireEvent.click(screen.getByRole("button", { name: "Draw it from the book's map" }));

    await waitFor(() => expect(calls(`POST ${DRAFTS}/from-book`)).toHaveLength(1));
    expect(JSON.parse(String(calls(`POST ${DRAFTS}/from-book`)[0]?.body))).toEqual({ map: "caves", page: "map-page-3" });
    expect(await screen.findByTestId("conversion-progress")).toBeTruthy();
  });

  it("shows the drawing that runs for this map, started by a conversion, and fetches it when it starts", async () => {
    const drawing = { ...started, id: "cnv_9", kind: "book-map" as const, title: "caves", target: { module_id: MODULE, name: "caves", page: "map-page-3" } };
    let list: Conversion[] = [];
    routes["GET /api/conversions"] = () => json(200, list);
    renderWith(<SketchNotice moduleId={MODULE} source={sketch} mapName="caves" />);
    await waitFor(() => expect(calls("GET /api/conversions")).toHaveLength(1));
    expect(screen.queryByTestId("conversion-progress")).toBeNull();

    list = [drawing, { ...drawing, id: "cnv_8", target: { module_id: MODULE, name: "annex", page: "map-page-4" } }];
    act(() => heard.conversion?.forEach((handle) => handle({ id: "cnv_9", status: "running", step: "drawing", done: 0, total: 1 })));

    expect(await screen.findByTestId("conversion-progress")).toBeTruthy();
    expect(screen.getAllByTestId("conversion-progress")).toHaveLength(1);
    expect((screen.getByRole("button", { name: "Draw it from the book's map" }) as HTMLButtonElement).disabled).toBe(true);
  });

  it("doesn't offer it without a map page, or without the map's name", () => {
    const none = "# Sketched from the room key: an invented layout. No map page was found in the book.\n";
    renderWith(
      <>
        <SketchNotice moduleId={MODULE} source={none} mapName="caves" />
        <SketchNotice moduleId={MODULE} source={sketch} />
      </>,
    );
    expect(screen.getAllByRole("note")).toHaveLength(2);
    expect(screen.queryByRole("button", { name: "Draw it from the book's map" })).toBeNull();
  });
});
