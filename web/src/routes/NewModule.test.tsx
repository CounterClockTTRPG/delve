import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { RouterProvider, createMemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { EventsContext, type Conversion, type Subscribe } from "../api";
import { I18nProvider } from "../i18n";
import ModuleDetail from "./ModuleDetail";
import NewModule from "./NewModule";

const crypt = {
  id: "mod_cccccccccccc",
  title: "Crypt of Saint Vellis",
  metadata: {},
  maps: [{ name: "crypt", role: "map", is_default: true, source: "" }],
  head_revision: 1,
  updated_at: "2026-10-17T10:00:00Z",
  draft: false,
};

const conversion = (patch: Partial<Conversion> = {}): Conversion => ({
  id: "cnv_000000000001",
  kind: "pdf",
  title: "Barrow of the Lost",
  mode: "draft",
  status: "running",
  step: "reading",
  done: 0,
  total: 0,
  steps: { index: 1, count: 4 },
  module_id: null,
  warnings: [],
  error: null,
  created_at: "2026-10-18T10:00:00Z",
  updated_at: "2026-10-18T10:00:00Z",
  ...patch,
});

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

function emit(type: string, data: unknown) {
  act(() => heard[type]?.forEach((h) => h(data)));
}

function json(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
}

beforeEach(() => {
  heard = {};
  routes = {
    "GET /api/conversions": () => json(200, []),
    "GET /api/conversions/options": () => json(200, { thorough: { available: true, reason: null } }),
    [`GET /api/modules/${crypt.id}`]: () => json(200, crypt),
    [`GET /api/modules/${crypt.id}/source`]: () =>
      json(200, { texts: [], entities: {}, attachments: [], keys: [], links: [], warnings: [] }),
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

function renderNew() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const router = createMemoryRouter(
    [
      { path: "/modules/new", element: <NewModule /> },
      { path: "/modules/:moduleId", element: <ModuleDetail /> },
    ],
    { initialEntries: ["/modules/new"] },
  );
  render(
    <QueryClientProvider client={client}>
      <I18nProvider language="en">
        <EventsContext.Provider value={subscribe}>
          <RouterProvider router={router} />
        </EventsContext.Provider>
      </I18nProvider>
    </QueryClientProvider>,
  );
  return router;
}

/** Picks a way on the first screen, and returns its form's region. */
function choose(name: string) {
  fireEvent.click(screen.getByRole("button", { name: new RegExp(`^${name.replace(/[.]/g, "\\.")}`) }));
  return within(screen.getByRole("region", { name }));
}

/** The regions of the ways' forms: all but the Conversions panel. */
const forms = () => screen.queryAllByRole("region").filter((region) => region.dataset.testid !== "conversions-panel");

describe("NewModule", () => {
  it("offers the four ways to get a module, and no form until one is picked", async () => {
    renderNew();
    expect(await screen.findByRole("heading", { level: 1, name: "New module" })).toBeTruthy();
    for (const name of ["An empty module", "Import a .dscn", "From a PDF", "Describe the module you want"])
      expect(screen.getByRole("button", { name: new RegExp(`^${name.replace(/[.]/g, "\\.")}`) })).toBeTruthy();
    expect(screen.queryAllByRole("textbox")).toEqual([]);
    expect(forms()).toEqual([]);
    expect(screen.getByRole("region", { name: "Conversions" })).toBeTruthy();
    expect(document.body.textContent).not.toMatch(/ingest/i);
  });

  it("a picked way shows only its own form, and Back returns to the four", async () => {
    const router = renderNew();
    await screen.findByRole("heading", { level: 1, name: "New module" });
    const pdf = choose("From a PDF");
    expect(router.state.location.search).toBe("?way=pdf");
    // One title field and one button: the other ways' forms aren't on the screen.
    expect(screen.getAllByLabelText("Title")).toHaveLength(1);
    expect(screen.queryByRole("button", { name: "Make the module" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Generate" })).toBeNull();
    expect(pdf.getByRole("button", { name: "Convert" })).toBeTruthy();

    fireEvent.click(screen.getByRole("link", { name: "Other ways" }));
    await waitFor(() => expect(forms()).toEqual([]));
    expect(screen.getByRole("button", { name: /^An empty module/ })).toBeTruthy();
  });

  it("an empty module posts its title as JSON and opens it", async () => {
    let sent: unknown;
    routes["POST /api/modules"] = (init) => {
      sent = JSON.parse(String(init?.body));
      expect(new Headers(init?.headers).get("Content-Type")).toBe("application/json");
      return json(200, crypt);
    };
    renderNew();
    const empty = choose("An empty module");
    fireEvent.change(empty.getByLabelText("Title"), { target: { value: "Stonehell" } });
    fireEvent.click(empty.getByRole("button", { name: "Make the module" }));
    await waitFor(() => expect(sent).toEqual({ title: "Stonehell" }));
    expect(await screen.findByRole("heading", { name: "Crypt of Saint Vellis" })).toBeTruthy();
  });

  it("Import .dscn posts the file's bytes as application/zip and opens the module with its warnings", async () => {
    let contentType: string | null = null;
    let body: unknown;
    routes["POST /api/modules/import"] = (init) => {
      contentType = new Headers(init?.headers).get("Content-Type");
      body = init?.body;
      return json(201, { ...crypt, warnings: ["Text, entities and assets are not imported yet."] });
    };
    renderNew();
    choose("Import a .dscn");
    const file = new File([new Uint8Array([0x50, 0x4b, 0x03, 0x04])], "crypt.dscn", { type: "" });
    fireEvent.change(screen.getByLabelText("Import .dscn"), { target: { files: [file] } });

    await waitFor(() => expect(contentType).toBe("application/zip"));
    expect(body).toBe(file);
    expect(await screen.findByRole("heading", { name: "Crypt of Saint Vellis" })).toBeTruthy();
    expect(screen.getByText("Text, entities and assets are not imported yet.")).toBeTruthy();
  });

  it("a PDF dropped on the page opens the PDF form with it, titled by its name", async () => {
    renderNew();
    const pdf = new File(["%PDF-1.4"], "Tomb of Horrors.pdf", { type: "application/pdf" });
    const dataTransfer = { types: ["Files"], files: [pdf] };
    fireEvent.dragEnter(window, { dataTransfer });
    expect(screen.getByText("Drop a PDF to convert it, or a .dscn file to import it")).toBeTruthy();
    fireEvent.drop(window, { dataTransfer });
    const form = within(await screen.findByRole("region", { name: "From a PDF" }));
    expect((form.getByLabelText("Title") as HTMLInputElement).value).toBe("Tomb of Horrors");
    expect(form.getByText("Dropped: Tomb of Horrors.pdf")).toBeTruthy();
    expect(screen.queryByText("Drop a PDF to convert it, or a .dscn file to import it")).toBeNull();
  });

  it("a .dscn dropped on the page is imported; anything else is refused", async () => {
    let imported: unknown;
    routes["POST /api/modules/import"] = (init) => {
      imported = init?.body;
      return json(201, { ...crypt, warnings: [] });
    };
    renderNew();
    fireEvent.drop(window, { dataTransfer: { types: ["Files"], files: [new File(["x"], "notes.txt")] } });
    expect(await screen.findByText("notes.txt is neither a PDF nor a .dscn file.")).toBeTruthy();
    const dscn = new File([new Uint8Array([0x50, 0x4b])], "crypt.dscn");
    fireEvent.drop(window, { dataTransfer: { types: ["Files"], files: [dscn] } });
    await waitFor(() => expect(imported).toBe(dscn));
  });

  it("says what an import brings, and why one was refused", async () => {
    routes["POST /api/modules/import"] = () => json(400, { error: "scenario.json is missing" });
    renderNew();
    expect(screen.getByText(/^A \.dscn scenario comes in with its maps/)).toBeTruthy();
    choose("Import a .dscn");
    const file = new File([new Uint8Array([1, 2, 3])], "bad.dscn");
    fireEvent.change(screen.getByLabelText("Import .dscn"), { target: { files: [file] } });
    expect(await screen.findByText("Not imported: bad.dscn: scenario.json is missing")).toBeTruthy();
  });

  it("a file that isn't a .dscn is refused in plain words, naming the file picked or dropped", async () => {
    routes["POST /api/modules/import"] = () => json(400, { error: "this is not a .dscn file (it isn't a zip archive)" });
    renderNew();
    fireEvent.drop(window, { dataTransfer: { types: ["Files"], files: [new File(["x"], "dropped.dscn")] } });
    expect(await screen.findByText("Not imported: dropped.dscn: this is not a .dscn file (it isn't a zip archive)")).toBeTruthy();
    choose("Import a .dscn");
    fireEvent.change(screen.getByLabelText("Import .dscn"), { target: { files: [new File(["x"], "picked.dscn")] } });
    expect(await screen.findByText("Not imported: picked.dscn: this is not a .dscn file (it isn't a zip archive)")).toBeTruthy();
    expect(document.body.textContent).not.toMatch(/bad zip/);
  });

  describe("pictures of a generated module (DEL-347)", () => {
    const start = async (pictures?: { paid: boolean; allowed: boolean }) => {
      routes["GET /api/conversions/options"] = () => json(200, { thorough: { available: true, reason: null }, pictures });
      routes["POST /api/conversions/generate/scope"] = () => json(200, { scale: "module", questions: [] });
      let sent: Record<string, unknown> | undefined;
      routes["POST /api/conversions/generate"] = (init) => {
        sent = JSON.parse(String(init?.body));
        return json(202, conversion({ kind: "generate" }));
      };
      renderNew();
      const form = choose("Describe the module you want");
      fireEvent.change(form.getByLabelText("Your request"), { target: { value: "A haunted mansion" } });
      const box = form.getByLabelText("Paint pictures of its key people and places") as HTMLInputElement;
      return { form, box, sent: () => sent };
    };

    it("is off by default, and a request then asks for none", async () => {
      const { form, box, sent } = await start({ paid: false, allowed: true });
      expect(box.checked).toBe(false);
      expect(form.queryByLabelText("At most")).toBeNull();
      fireEvent.click(form.getByRole("button", { name: "Generate" }));
      await waitFor(() => expect(sent()).toBeTruthy());
      expect(sent()).not.toHaveProperty("pictures");
    });

    it("sends the limit, 6 unless changed, and warns of a paid model", async () => {
      const { form, box, sent } = await start({ paid: true, allowed: true });
      fireEvent.click(box);
      expect(await form.findByText(/costs money/)).toBeTruthy();
      expect((form.getByLabelText("At most") as HTMLSelectElement).value).toBe("6");
      fireEvent.change(form.getByLabelText("At most"), { target: { value: "3" } });
      fireEvent.click(form.getByRole("button", { name: "Generate" }));
      await waitFor(() => expect(sent()).toBeTruthy());
      expect(sent()?.pictures).toBe(3);
    });

    it("is disabled with the reason when only the owner may paint", async () => {
      const { form, box } = await start({ paid: true, allowed: false });
      expect(await form.findByText("Only the owner may paint with a paid image model.")).toBeTruthy();
      expect(box.disabled).toBe(true);
    });
  });

  it("a conversion's tag says what it makes: a playable module or a draft", async () => {
    const title = "A sprawling dungeon of kobold warrens beneath the old salt mine, with a flooded…";
    routes["GET /api/conversions"] = () =>
      json(200, [conversion({ kind: "generate", title, mode: "ready" }), conversion({ id: "cnv_000000000002", status: "done", mode: "draft" })]);
    renderNew();
    const progress = await screen.findByTestId("conversion-progress");
    expect(within(progress).getByText(title)).toBeTruthy();
    expect(within(progress).getByText("Makes a playable module")).toBeTruthy();
    expect(within(progress).queryByText("Ready to play")).toBeNull();
  });

  it("a PDF upload starts a conversion and shows its progress from the events", async () => {
    let url = "";
    let init: RequestInit | undefined;
    const started = conversion();
    let list: Conversion[] = [];
    routes["GET /api/conversions"] = () => json(200, list);
    fetchMock.mockImplementation(async (path: string, i?: RequestInit) => {
      if (path.startsWith("/api/conversions/pdf?")) {
        url = path;
        init = i;
        list = [started];
        return json(202, started);
      }
      const handler = routes[`${i?.method ?? "GET"} ${path}`];
      return handler ? handler(i) : json(404, { error: "not found" });
    });
    renderNew();
    const pdf = choose("From a PDF");
    // Thorough is the default once the options say it can run; Quick is today's conversion.
    await waitFor(() => expect((pdf.getByLabelText("Thorough (default)") as HTMLInputElement).checked).toBe(true));
    fireEvent.click(pdf.getByLabelText("Quick"));
    fireEvent.click(pdf.getByLabelText("A draft to work on"));
    const book = new File([new Uint8Array([0x25, 0x50, 0x44, 0x46, 0x2d])], "Barrow of the Lost.pdf", { type: "" });
    fireEvent.change(pdf.getByLabelText("The PDF"), { target: { files: [book] } });
    // The title comes from the file's name, and can be changed.
    expect((pdf.getByLabelText("Title") as HTMLInputElement).value).toBe("Barrow of the Lost");
    // Drawing the maps from the book's map pages is on unless unticked.
    const bookMaps = pdf.getByLabelText("Draw each map from the book's map page") as HTMLInputElement;
    expect(bookMaps.checked).toBe(true);
    fireEvent.click(bookMaps);
    fireEvent.click(pdf.getByRole("button", { name: "Convert" }));

    await waitFor(() => expect(init).toBeTruthy());
    expect(url).toBe("/api/conversions/pdf?title=Barrow%20of%20the%20Lost&mode=draft&thorough=false&book_maps=false");
    expect(new Headers(init?.headers).get("Content-Type")).toBe("application/pdf");
    expect(init?.body).toBe(book);

    const progress = await screen.findByTestId("conversion-progress");
    expect(within(progress).getByText("Barrow of the Lost")).toBeTruthy();
    emit("conversion", { id: started.id, status: "running", step: "converting", done: 3, total: 10 });
    expect(within(progress).getByText("3 of 10 pages")).toBeTruthy();
    // While it runs, another book may be uploaded and a request sent: they wait in the queue (DEL-141).
    expect((pdf.getByRole("button", { name: "Convert" }) as HTMLButtonElement).disabled).toBe(false);
    fireEvent.click(screen.getByRole("link", { name: "Other ways" }));
    const describe = choose("Describe the module you want");
    fireEvent.change(describe.getByLabelText("Your request"), { target: { value: "kobolds" } });
    expect((describe.getByRole("button", { name: "Generate" }) as HTMLButtonElement).disabled).toBe(false);
  });

  it("a PDF converts thoroughly by default, without the book-maps checkbox", async () => {
    let url = "";
    fetchMock.mockImplementation(async (path: string, i?: RequestInit) => {
      if (path.startsWith("/api/conversions/pdf?")) {
        url = path;
        return json(202, conversion({ thorough: true, steps: { index: 1, count: 10 } }));
      }
      const handler = routes[`${i?.method ?? "GET"} ${path}`];
      return handler ? handler(i) : json(404, { error: "not found" });
    });
    renderNew();
    const pdf = choose("From a PDF");
    const thorough = (await pdf.findByLabelText("Thorough (default)")) as HTMLInputElement;
    await waitFor(() => expect(thorough.checked).toBe(true));
    expect(thorough.disabled).toBe(false);
    expect(
      pdf.getByText(
        "Checks every page, traces every map from the book. Takes hours for a big book and costs much more. Needs the Claude CLI.",
      ),
    ).toBeTruthy();
    expect(pdf.queryByLabelText("Draw each map from the book's map page")).toBeNull();
    // Quick brings the checkbox back.
    fireEvent.click(pdf.getByLabelText("Quick"));
    expect(pdf.getByLabelText("Draw each map from the book's map page")).toBeTruthy();
    fireEvent.click(pdf.getByLabelText("Thorough (default)"));

    fireEvent.change(pdf.getByLabelText("The PDF"), { target: { files: [new File(["%PDF-"], "Saltmarsh.pdf")] } });
    fireEvent.click(pdf.getByRole("button", { name: "Convert" }));
    await waitFor(() => expect(url).toBe("/api/conversions/pdf?title=Saltmarsh&mode=ready&thorough=true"));
  });

  it("sends the comments", async () => {
    let url = "";
    fetchMock.mockImplementation(async (path: string, i?: RequestInit) => {
      if (path.startsWith("/api/conversions/pdf?")) {
        url = path;
        return json(202, conversion({ thorough: true, steps: { index: 1, count: 10 } }));
      }
      const handler = routes[`${i?.method ?? "GET"} ${path}`];
      return handler ? handler(i) : json(404, { error: "not found" });
    });
    renderNew();
    const pdf = choose("From a PDF");
    const comments = (await pdf.findByLabelText("Comments for Claude")) as HTMLTextAreaElement;
    expect(comments.maxLength).toBe(2000);
    expect(pdf.getByText(/the room key starts on page 40/)).toBeTruthy();
    fireEvent.change(comments, { target: { value: "Keep the book's spelling & the maps." } });
    fireEvent.change(pdf.getByLabelText("The PDF"), { target: { files: [new File(["%PDF-"], "Saltmarsh.pdf")] } });
    await waitFor(() => expect((pdf.getByLabelText("Thorough (default)") as HTMLInputElement).checked).toBe(true));
    fireEvent.click(pdf.getByRole("button", { name: "Convert" }));
    await waitFor(() =>
      expect(url).toBe(
        "/api/conversions/pdf?title=Saltmarsh&mode=ready&thorough=true&comments=" +
          encodeURIComponent("Keep the book's spelling & the maps."),
      ),
    );
  });

  it("points to the PDF form", async () => {
    const router = renderNew();
    const describe = choose("Describe the module you want");
    const request = describe.getByLabelText("Your request");
    fireEvent.change(request, { target: { value: "a dungeon with kobolds, no plot" } });
    expect(describe.queryByRole("link", { name: "Convert a PDF instead" })).toBeNull();
    for (const text of ["convert saltmarsh.pdf", "Import my old module", "dit boek omzetten", "importeer het"]) {
      fireEvent.change(request, { target: { value: text } });
      expect(describe.getByText(/sounds like a book to convert or a file to import/)).toBeTruthy();
    }
    fireEvent.click(describe.getByRole("link", { name: "Convert a PDF instead" }));
    await waitFor(() => expect(router.state.location.search).toBe("?way=pdf"));
    expect(await screen.findByRole("region", { name: "From a PDF" })).toBeTruthy();
  });

  it("Thorough is disabled with its reason when it can't run, and Quick is chosen", async () => {
    const reason = "The Claude CLI isn't installed, and a thorough conversion runs on it.";
    routes["GET /api/conversions/options"] = () => json(200, { thorough: { available: false, reason } });
    renderNew();
    const pdf = choose("From a PDF");
    expect(await pdf.findByText(`Not available: ${reason}`)).toBeTruthy();
    expect((pdf.getByLabelText("Thorough (default)") as HTMLInputElement).disabled).toBe(true);
    expect((pdf.getByLabelText("Quick") as HTMLInputElement).checked).toBe(true);
    expect(pdf.getByLabelText("Draw each map from the book's map page")).toBeTruthy();
  });

  it("a reload shows a paused thorough conversion, to resume, and a new one may start", async () => {
    const paused = conversion({
      status: "paused",
      thorough: true,
      step: "cleaning",
      done: 12,
      total: 34,
      steps: { index: 5, count: 10 },
      cost_usd: 18.4,
      paused: { reason: "Delve stopped", resets_at: null },
    });
    routes["GET /api/conversions"] = () => json(200, [paused]);
    renderNew();
    const progress = await screen.findByTestId("conversion-progress");
    expect(within(progress).getByRole("button", { name: "Resume" })).toBeTruthy();
    expect(screen.queryByText("One conversion runs at a time: wait for this one, or cancel it.")).toBeNull();
    const pdf = choose("From a PDF");
    fireEvent.change(pdf.getByLabelText("The PDF"), { target: { files: [new File(["%PDF-"], "Dunwater.pdf")] } });
    expect((pdf.getByRole("button", { name: "Convert" }) as HTMLButtonElement).disabled).toBe(false);
  });

  it("a reload shows the running conversion", async () => {
    routes["GET /api/conversions"] = () =>
      json(200, [conversion({ step: "entities", done: 1, total: 4, steps: { index: 3, count: 4 } }), conversion({ id: "cnv_000000000000", status: "done" })]);
    renderNew();
    const progress = await screen.findByTestId("conversion-progress");
    expect(within(progress).getByText("Step 3 of 4 · Finding the NPCs and encounters")).toBeTruthy();
    expect(within(progress).getByText("1 of 4 texts")).toBeTruthy();
    expect(screen.getAllByTestId("conversion-progress")).toHaveLength(1);
  });

  it("after a reload, the running conversion stays in view when it ends", async () => {
    let listed = [conversion({ step: "maps", done: 0, total: 1 })];
    routes["GET /api/conversions"] = () => json(200, listed);
    const done = conversion({ status: "done", step: "maps", done: 1, total: 1, module_id: "mod_barrow" });
    routes["GET /api/conversions/cnv_000000000001"] = () => json(200, done);
    renderNew();
    await screen.findByTestId("conversion-progress");
    listed = [done];
    act(() => emit("conversion", { id: done.id, status: "done", step: "maps", done: 1, total: 1 }));
    const progress = await screen.findByTestId("conversion-progress");
    await waitFor(() => expect(progress.getAttribute("data-status")).toBe("done"));
    expect(within(progress).getByRole("link", { name: "Open the module" })).toBeTruthy();
  });

  it("Generate and Convert queue behind a conversion found after a reload (DEL-141)", async () => {
    routes["GET /api/conversions"] = () => json(200, [conversion({ step: "maps", done: 0, total: 1 })]);
    renderNew();
    await screen.findByTestId("conversion-progress");
    const describe = choose("Describe the module you want");
    fireEvent.change(describe.getByLabelText("Your request"), { target: { value: "a dungeon with kobolds, no plot" } });
    const generate = describe.getByRole("button", { name: "Generate" }) as HTMLButtonElement;
    expect(generate.disabled).toBe(false); // a request waits in the queue
    fireEvent.click(screen.getByRole("link", { name: "Other ways" }));
    const pdf = choose("From a PDF");
    const book = new File([new Uint8Array([0x25, 0x50, 0x44, 0x46, 0x2d])], "Barrow of the Lost.pdf", { type: "" });
    fireEvent.change(pdf.getByLabelText("The PDF"), { target: { files: [book] } });
    expect((pdf.getByRole("button", { name: "Convert" }) as HTMLButtonElement).disabled).toBe(false); // a book waits in the queue
  });

  it("shows what the conversion cost once it has ended, and nothing while it runs or when unknown", async () => {
    let listed = [conversion({ step: "maps", done: 0, total: 1, cost_usd: 0.01 })];
    routes["GET /api/conversions"] = () => json(200, listed);
    renderNew();
    await screen.findByTestId("conversion-progress");
    expect(screen.queryByText(/^Cost:/)).toBeNull();
    listed = [conversion({ status: "done", step: "maps", done: 1, total: 1, module_id: "mod_barrow", cost_usd: 0.034 })];
    act(() => emit("conversion", { id: listed[0].id, status: "done", step: "maps", done: 1, total: 1 }));
    expect(await screen.findByText("Cost: $0.03")).toBeTruthy();
  });

  it("shows no cost for a job that reported none", async () => {
    let listed = [conversion({ step: "maps", done: 0, total: 1 })];
    routes["GET /api/conversions"] = () => json(200, listed);
    renderNew();
    const progress = await screen.findByTestId("conversion-progress");
    listed = [conversion({ status: "done", step: "maps", done: 1, total: 1, module_id: "mod_barrow", cost_usd: null })];
    act(() => emit("conversion", { id: listed[0].id, status: "done", step: "maps", done: 1, total: 1 }));
    await waitFor(() => expect(progress.getAttribute("data-status")).toBe("done"));
    expect(screen.queryByText(/^Cost:/)).toBeNull();
  });

  it("after the conversion, follows the drafts of the book's map pages, then links to them", async () => {
    const warning = { code: "map-warning", message: "Ground floor: map is not connected", ref: "map:house" };
    const done = conversion({ status: "done", step: "maps", done: 1, total: 1, module_id: "mod_barrow", warnings: [warning] });
    const page = (id: string, n: number, index: number, status: Conversion["status"]) =>
      conversion({
        id,
        kind: "book-map",
        title: `page ${n}`,
        status,
        step: "drawing",
        steps: { index: 1, count: 1 },
        target: { module_id: "mod_barrow", page: `map-page-${n}`, batch: { index, count: 3 } } as unknown as Record<string, string>,
      });
    let listed = [conversion({ step: "maps", done: 0, total: 1 })];
    routes["GET /api/conversions"] = () => json(200, listed);
    routes["GET /api/conversions/cnv_000000000001"] = () => json(200, done);
    renderNew();
    await screen.findByTestId("conversion-progress");

    listed = [page("cnv_b1", 2, 1, "done"), page("cnv_b2", 37, 2, "running"), done];
    emit("conversion", { id: done.id, status: "done", step: "maps", done: 1, total: 1 });
    expect(await screen.findByText("Drawing the map of page 37 (2 of 3)")).toBeTruthy();
    expect(screen.queryByRole("link", { name: "Review the drafts" })).toBeNull();

    listed = [page("cnv_b3", 35, 3, "running"), page("cnv_b2", 37, 2, "done"), page("cnv_b1", 2, 1, "done"), done];
    emit("conversion", { id: "cnv_b3", status: "running", step: "drawing", done: 0, total: 1 });
    expect(await screen.findByText("Drawing the map of page 35 (3 of 3)")).toBeTruthy();

    listed = [page("cnv_b3", 35, 3, "done"), page("cnv_b2", 37, 2, "done"), page("cnv_b1", 2, 1, "done"), done];
    emit("conversion", { id: "cnv_b3", status: "done", step: "drawing", done: 1, total: 1 });
    const review = await screen.findByRole("link", { name: "Review the drafts" });
    expect(review.getAttribute("href")).toBe("/modules/mod_barrow?tab=maps");
    expect(screen.queryByText(/Drawing the map of page/)).toBeNull();
    expect(screen.getByRole("link", { name: "See the warnings" }).getAttribute("href")).toBe("/modules/mod_barrow");
  });

  it("Generate posts the request as a ready module", async () => {
    let sent: unknown;
    routes["POST /api/conversions/generate"] = (init) => {
      sent = JSON.parse(String(init?.body));
      return json(202, conversion({ kind: "generate", title: "A dungeon", mode: "ready", step: "generating", total: 1, steps: { index: 1, count: 2 } }));
    };
    renderNew();
    const describe = choose("Describe the module you want");
    fireEvent.change(describe.getByLabelText("Your request"), { target: { value: "a dungeon with kobolds, no plot" } });
    fireEvent.click(describe.getByRole("button", { name: "Generate" }));
    await waitFor(() => expect(sent).toEqual({ request: "a dungeon with kobolds, no plot", mode: "ready" }));
    expect(await screen.findByText("Step 1 of 2 · Generating the module")).toBeTruthy();
  });

  it("asks the scope questions before a campaign is generated, and sends the answers with its scale", async () => {
    let sent: unknown;
    routes["POST /api/conversions/generate/scope"] = () =>
      json(200, {
        scale: "campaign",
        questions: [
          { id: "s1", text: "How many levels?", default: "Assumed five." },
          { id: "s2", text: "Which tone?", default: "Assumed grim." },
        ],
      });
    routes["POST /api/conversions/generate"] = (init) => {
      sent = JSON.parse(String(init?.body));
      return json(202, conversion({ kind: "generate", title: "A dungeon", mode: "ready", step: "planning", total: 1, steps: { index: 2, count: 5 } }));
    };
    renderNew();
    const describe = choose("Describe the module you want");
    fireEvent.change(describe.getByLabelText("Your request"), { target: { value: "a sprawling dungeon" } });
    fireEvent.click(describe.getByRole("button", { name: "Generate" }));
    const levels = (await screen.findByLabelText("How many levels?")) as HTMLInputElement;
    expect(levels.placeholder).toBe("Assumed five.");
    expect(screen.getByText(/Claude reads this as a campaign/)).toBeTruthy();
    expect(sent).toBeUndefined();
    fireEvent.change(levels, { target: { value: " Seven " } });
    fireEvent.click(describe.getByRole("button", { name: "Generate" }));
    await waitFor(() =>
      expect(sent).toEqual({
        request: "a sprawling dungeon",
        mode: "ready",
        scale: "campaign",
        answers: [
          { text: "How many levels?", default: "Assumed five.", answer: "Seven" },
          { text: "Which tone?", default: "Assumed grim.", answer: "" },
        ],
      }),
    );
    expect(await screen.findByText("Step 2 of 5 · Outlining the campaign")).toBeTruthy();
    expect(screen.queryByLabelText("How many levels?")).toBeNull();
  });

  it("starts at once when the scope has no questions, and drops the questions when the request changes", async () => {
    let sent: unknown;
    let questions = [{ id: "s1", text: "How many levels?", default: "Five." }];
    routes["POST /api/conversions/generate/scope"] = () => json(200, { scale: "module", questions });
    routes["POST /api/conversions/generate"] = (init) => {
      sent = JSON.parse(String(init?.body));
      return json(202, conversion({ kind: "generate", title: "Kobolds", mode: "ready", step: "generating" }));
    };
    renderNew();
    const describe = choose("Describe the module you want");
    fireEvent.change(describe.getByLabelText("Your request"), { target: { value: "kobolds" } });
    fireEvent.click(describe.getByRole("button", { name: "Generate" }));
    await screen.findByLabelText("How many levels?");
    questions = [];
    fireEvent.change(describe.getByLabelText("Your request"), { target: { value: "kobolds, no plot" } });
    expect(screen.queryByLabelText("How many levels?")).toBeNull();
    fireEvent.click(describe.getByRole("button", { name: "Generate" }));
    await waitFor(() => expect(sent).toEqual({ request: "kobolds, no plot", mode: "ready", scale: "module", answers: [] }));
  });

  it("a refused start shows the running conversion it was refused for", async () => {
    routes["POST /api/conversions/generate"] = () =>
      json(409, { error: "A conversion is running.", conversion: conversion({ title: "The other book" }) });
    renderNew();
    const describe = choose("Describe the module you want");
    fireEvent.change(describe.getByLabelText("Your request"), { target: { value: "kobolds" } });
    fireEvent.click(describe.getByRole("button", { name: "Generate" }));
    expect(await screen.findByText("Not started: A conversion is running.")).toBeTruthy();
    expect(within(await screen.findByTestId("conversion-progress")).getByText("The other book")).toBeTruthy();
  });

  it("leaves out the jobs that make no module, running or done", async () => {
    routes["GET /api/conversions"] = () =>
      json(200, [
        conversion({ kind: "worldmap", title: "The Flanaess", step: "grid", steps: { index: 2, count: 6 }, target: { module_id: crypt.id, name: "flanaess" } }),
        conversion({ id: "cnv_000000000000", kind: "dungeon-map", title: "A warren", status: "done", step: "drawing", target: { module_id: crypt.id } }),
      ]);
    renderNew();
    await screen.findByRole("heading", { level: 1, name: "New module" });
    await waitFor(() => expect(fetchMock).toHaveBeenCalledWith("/api/conversions", expect.anything()));
    await act(async () => {});
    expect(screen.queryByTestId("conversion-progress")).toBeNull();
    expect(screen.queryByText("The Flanaess")).toBeNull();
  });
});
