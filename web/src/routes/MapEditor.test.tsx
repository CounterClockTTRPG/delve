import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { RouterProvider, createMemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { DialogsProvider } from "../components/dialogs";
import type { Diagnostic } from "../editor/types";
import { I18nProvider } from "../i18n";
import MapEditor from "./MapEditor";

// Monaco needs a real browser; a textarea stands in for it, showing the markers it was given.
vi.mock("../editor/MonacoEditor", () => ({
  MonacoEditor: ({
    value,
    onChange,
    diagnostics = [],
  }: {
    value: string;
    onChange: (v: string) => void;
    diagnostics?: Diagnostic[];
  }) => (
    <div>
      <textarea aria-label="Map source" value={value} onChange={(e) => onChange(e.target.value)} />
      <ul aria-label="Markers">
        {diagnostics.map((d, i) => (
          <li key={i}>{`line ${d.line}: ${d.message}`}</li>
        ))}
      </ul>
    </div>
  ),
}));

const MODULE = "mod_0123456789ab";
const SOURCE = 'map "Crypt" {\n  grid 10 x 10\n}\n';
const detail = {
  module_id: MODULE,
  name: "crypt",
  role: "map",
  is_default: true,
  updated_at: "2026-10-17T10:00:00Z",
  source: SOURCE,
};
const module = {
  id: MODULE,
  title: "Crypt of Saint Vellis",
  metadata: {},
  maps: [
    { name: "crypt", role: "map", is_default: true, source: SOURCE },
    { name: "catacombs", role: "map", is_default: false, source: "" },
    { name: "core", role: "library", is_default: false, source: "" },
  ],
  head_revision: null,
  updated_at: "2026-10-17T10:00:00Z",
};

type Handler = (init: RequestInit | undefined) => Response | Promise<Response>;
let routes: Record<string, Handler>;
let fetchMock: ReturnType<typeof vi.fn>;

function json(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
}

const base = `/api/modules/${MODULE}/maps/crypt`;

beforeEach(() => {
  routes = {
    [`GET ${base}`]: () => json(200, detail),
    [`GET /api/modules/${MODULE}`]: () => json(200, module),
    [`POST ${base}/render`]: () => json(200, { svg: "<svg></svg>", diagnostics: [] }),
    [`POST ${base}/feature-names`]: () => json(200, { names: ["altar"], groups: [{ source: "core.dmap", names: ["altar"] }] }),
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

function renderEditor(at = `/maps/${MODULE}/crypt`) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const router = createMemoryRouter(
    [
      { path: "/maps/:moduleId/:mapName", element: <MapEditor /> },
      { path: "/campaigns/:campaignId/own-maps/:mapName", element: <MapEditor /> },
      { path: "/modules/:moduleId", element: <h1>Module page</h1> },
      { path: "/campaigns/:id", element: <h1>Campaign page</h1> },
    ],
    { initialEntries: [at] },
  );
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

function calls(method: string, path: string) {
  return fetchMock.mock.calls.filter(([p, init]) => p === path && (init?.method ?? "GET") === method);
}

describe("MapEditor", () => {
  it("opens an empty map with a starter map to draw on, unsaved, as dungml does", async () => {
    // With no source there is nothing rendered, and the drawing tools have nothing to draw on.
    routes[`GET ${base}`] = () => json(200, { ...detail, source: "" });
    renderEditor();
    const textarea = (await screen.findByLabelText("Map source")) as HTMLTextAreaElement;
    await waitFor(() => expect(textarea.value).toContain('map "crypt" {'));
    expect(textarea.value).toContain('include "core.dmap"');
    expect(textarea.value).toContain('room "main"');
    await waitFor(() => expect(calls("POST", `${base}/render`).length).toBeGreaterThan(0));
    expect(calls("PUT", base)).toEqual([]); // the starter is offered, not saved
  });

  it("loads the map's source from the module-scoped route", async () => {
    renderEditor();
    const editor = (await screen.findByLabelText("Map source")) as HTMLTextAreaElement;
    expect(editor.value).toBe(SOURCE);
    expect(screen.getByText("crypt")).toBeTruthy();
    await waitFor(() => expect(calls("POST", `${base}/render`)).toHaveLength(1));
    expect(JSON.parse(String(calls("POST", `${base}/render`)[0][1].body))).toEqual({ source: SOURCE });
  });

  it("marks a sketched map as invented, and shows the book's page beside the canvas", async () => {
    const sketched = "# Sketched from the room key: an invented layout. The book's map is asset:map-page-46.\n" + SOURCE;
    routes[`GET ${base}`] = () => json(200, { ...detail, source: sketched });
    renderEditor();
    expect(await screen.findByText("Sketched from the room key: the layout is invented.")).toBeTruthy();
    expect(screen.queryByRole("img", { name: "The book's page" })).toBeNull();

    fireEvent.click(screen.getByRole("button", { name: "Show the book's page" }));
    expect(screen.getByRole("img", { name: "The book's page" }).getAttribute("src")).toBe(
      `/api/modules/${MODULE}/assets/map-page-46`,
    );

    fireEvent.click(screen.getByRole("button", { name: "Hide the book's page" }));
    expect(screen.queryByRole("img", { name: "The book's page" })).toBeNull();
  });

  it("gives a map drawn from the book's page its notice and its page too", async () => {
    const drawn = "# Drawn from the book's map asset:map-page-35.\n" + SOURCE;
    routes[`GET ${base}`] = () => json(200, { ...detail, source: drawn });
    renderEditor();
    const note = await screen.findByRole("note");
    expect(note.querySelectorAll("p")).toHaveLength(1);
    expect(screen.getByText("Drawn by Claude from the book's page")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Show the book's page" }));
    expect(screen.getByRole("img", { name: "The book's page" }).getAttribute("src")).toBe(
      `/api/modules/${MODULE}/assets/map-page-35`,
    );
  });

  it("a drawn map has no sketch notice", async () => {
    renderEditor();
    await screen.findByLabelText("Map source");
    expect(screen.queryByText("Sketched from the room key: the layout is invented.")).toBeNull();
    expect(screen.queryByRole("note")).toBeNull();
  });

  it("shows a parse error from a 400 at its line", async () => {
    routes[`POST ${base}/render`] = () => json(400, { error: "Unexpected token '}'", line: 3, column: 5 });
    renderEditor();
    expect(await screen.findByText("line 3: Unexpected token '}'")).toBeTruthy();
    expect(screen.getByText("3:5")).toBeTruthy();
    expect(screen.getByText("1 error")).toBeTruthy();
  });

  it("saves the source with PUT", async () => {
    let sent: unknown;
    routes[`PUT ${base}`] = (init) => {
      sent = JSON.parse(String(init?.body));
      return json(200, { ...detail, source: (sent as { source: string }).source });
    };
    renderEditor();
    const editor = await screen.findByLabelText("Map source");
    fireEvent.change(editor, { target: { value: SOURCE + "# more\n" } });
    fireEvent.click(screen.getByRole("button", { name: "Save" }));
    await waitFor(() => expect(sent).toEqual({ source: SOURCE + "# more\n" }));
    await waitFor(() => expect(screen.queryByTitle("Unsaved changes")).toBeNull());
  });

  it("keeps what was typed while a save ran (DEL-174)", async () => {
    let saved = detail.source;
    let answer: () => void = () => {};
    routes[`GET ${base}`] = () => json(200, { ...detail, source: saved });
    routes[`PUT ${base}`] = (init) =>
      new Promise<Response>((resolve) => {
        answer = () => {
          saved = JSON.parse(String(init?.body)).source;
          resolve(json(200, { ...detail, source: saved }));
        };
      });
    renderEditor();
    const editor = (await screen.findByLabelText("Map source")) as HTMLTextAreaElement;
    fireEvent.change(editor, { target: { value: SOURCE + "# saved\n" } });
    fireEvent.click(screen.getByRole("button", { name: "Save" }));
    await waitFor(() => expect(calls("PUT", base)).toHaveLength(1));
    fireEvent.change(editor, { target: { value: SOURCE + "# saved\n# typed meanwhile\n" } });
    answer();
    // The map is read again after the save; the editor keeps the newer words, still unsaved.
    await waitFor(() => expect(calls("GET", base).length).toBeGreaterThan(1));
    expect(editor.value).toBe(SOURCE + "# saved\n# typed meanwhile\n");
    expect(screen.getByTitle("Unsaved changes")).toBeTruthy();
  });

  it("blocks navigation while there are unsaved changes", async () => {
    const router = renderEditor();
    const editor = await screen.findByLabelText("Map source");
    fireEvent.change(editor, { target: { value: SOURCE + "room x {}\n" } });
    expect(screen.getByTitle("Unsaved changes")).toBeTruthy();

    fireEvent.click(screen.getByRole("link", { name: "Crypt of Saint Vellis" }));
    await screen.findByRole("alertdialog", { name: "You have unsaved changes to this map. Leave without saving?" });
    fireEvent.click(screen.getByRole("button", { name: "Cancel" }));
    await waitFor(() => expect(screen.queryByRole("alertdialog")).toBeNull());
    expect(router.state.location.pathname).toBe(`/maps/${MODULE}/crypt`);
    expect(screen.getByLabelText("Map source")).toBeTruthy();

    fireEvent.click(screen.getByRole("link", { name: "Crypt of Saint Vellis" }));
    fireEvent.click(await screen.findByRole("button", { name: "Leave" }));
    expect(await screen.findByRole("heading", { name: "Module page" })).toBeTruthy();
  });

  it("offers the module's other maps, not libraries, to the exit tool", async () => {
    renderEditor();
    await screen.findByLabelText("Map source");
    // The tools are enabled once the debounced source is known to be a map.
    await waitFor(() => expect(calls("POST", `${base}/render`)).toHaveLength(1));
    const exit = screen.getByRole("button", { name: /^Exit/ }) as HTMLButtonElement;
    await waitFor(() => expect(exit.disabled).toBe(false));
    fireEvent.click(exit);
    const select = await screen.findByTitle("Map this exit leads to (other maps in this module)");
    const options = () => Array.from(select.querySelectorAll("option")).map((o) => o.textContent);
    await waitFor(() => expect(options()).toContain("catacombs"));
    expect(options()).not.toContain("core");
    expect(options()).not.toContain("crypt");
  });

  describe("a campaign's own map", () => {
    const CAMPAIGN = "cmp_0123456789ab";
    const own = `/api/campaigns/${CAMPAIGN}/own-maps/slums`;
    beforeEach(() => {
      routes[`GET ${own}`] = () =>
        json(200, { ...detail, name: "slums", is_default: false, own: true, campaign_id: CAMPAIGN, updated_at: null });
      routes[`GET /api/campaigns/${CAMPAIGN}`] = () =>
        json(200, { id: CAMPAIGN, name: "Phlan and beyond", module_id: MODULE, maps: ["crypt", "slums"], own_maps: ["slums"] });
      routes[`POST ${own}/render`] = () => json(200, { svg: "<svg></svg>", diagnostics: [] });
      routes[`POST ${own}/feature-names`] = () => json(200, { names: ["altar"], groups: [] });
    });

    it("loads, renders and saves through the campaign's routes, and goes back to the campaign", async () => {
      let sent: unknown;
      routes[`PUT ${own}`] = (init) => {
        sent = JSON.parse(String(init?.body));
        return json(200, { ...detail, name: "slums", source: (sent as { source: string }).source });
      };
      renderEditor(`/campaigns/${CAMPAIGN}/own-maps/slums`);
      const editor = await screen.findByLabelText("Map source");
      await waitFor(() => expect(calls("POST", `${own}/render`)).toHaveLength(1));
      expect(calls("GET", base)).toHaveLength(0);
      expect(screen.getByText("This campaign's own")).toBeTruthy();
      const crumb = await screen.findByRole("link", { name: "Phlan and beyond" });
      expect(crumb.getAttribute("href")).toBe(`/campaigns/${CAMPAIGN}?tab=maps`);
      expect(screen.queryByRole("button", { name: "Print" })).toBeNull();
      fireEvent.change(editor, { target: { value: SOURCE + "# more\n" } });
      fireEvent.click(screen.getByRole("button", { name: "Save" }));
      await waitFor(() => expect(sent).toEqual({ source: SOURCE + "# more\n" }));
    });

    it("offers the campaign's other maps to the exit tool", async () => {
      renderEditor(`/campaigns/${CAMPAIGN}/own-maps/slums`);
      await screen.findByLabelText("Map source");
      await waitFor(() => expect(calls("POST", `${own}/render`)).toHaveLength(1));
      const exit = screen.getByRole("button", { name: /^Exit/ }) as HTMLButtonElement;
      await waitFor(() => expect(exit.disabled).toBe(false));
      fireEvent.click(exit);
      const select = await screen.findByTitle("Map this exit leads to (other maps in this module)");
      const options = () => Array.from(select.querySelectorAll("option")).map((o) => o.textContent);
      await waitFor(() => expect(options()).toContain("crypt"));
      expect(options()).not.toContain("slums");
    });
  });
});
