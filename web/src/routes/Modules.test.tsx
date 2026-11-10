import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { RouterProvider, createMemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { EventsContext, type Conversion, type Subscribe } from "../api";
import { DialogsProvider } from "../components/dialogs";
import { chooseFromRowMenu, rowMenuItem } from "../components/rowMenuTesting";
import { I18nProvider } from "../i18n";
import Modules from "./Modules";

const converting: Conversion = {
  id: "cnv_000000000001",
  kind: "pdf",
  title: "Dark Clouds Gather",
  mode: "draft",
  status: "running",
  step: "converting",
  done: 12,
  total: 300,
  steps: { index: 2, count: 4 },
  module_id: null,
  warnings: [],
  error: null,
  created_at: "2026-10-18T10:00:00Z",
  updated_at: "2026-10-18T10:04:00Z",
};

let heard: Record<string, ((data: unknown) => void)[]>;
const subscribe: Subscribe = (handlers) => {
  for (const [type, handle] of Object.entries(handlers)) (heard[type] ??= []).push(handle);
  return () => {
    for (const [type, handle] of Object.entries(handlers)) heard[type] = heard[type].filter((h) => h !== handle);
  };
};

const crypt = {
  id: "mod_0123456789ab",
  title: "Crypt of Saint Vellis",
  maps: [
    { name: "crypt", role: "map", is_default: true },
    { name: "core", role: "library", is_default: false },
  ],
  head_revision: 1,
  updated_at: "2026-10-17T10:00:00Z",
};
const empty = { id: "mod_ba9876543210", title: "Empty", maps: [], head_revision: null, updated_at: "2026-10-17T11:00:00Z" };

type Handler = (init: RequestInit | undefined) => Response;
let routes: Record<string, Handler>;
let fetchMock: ReturnType<typeof vi.fn>;

function json(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
}

beforeEach(() => {
  heard = {};
  localStorage.clear();
  routes = { "GET /api/modules": () => json(200, [crypt, empty]) };
  fetchMock = vi.fn(async (path: string, init?: RequestInit) => {
    const handler = routes[`${init?.method ?? "GET"} ${path}`];
    return handler ? handler(init) : json(404, { error: "not found" });
  });
  vi.stubGlobal("fetch", fetchMock);
});

afterEach(() => {
  vi.unstubAllGlobals();
});

function renderModules() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const router = createMemoryRouter(
    [
      { path: "/modules", element: <Modules /> },
      { path: "/modules/new", element: <h1>New module screen</h1> },
      { path: "/modules/:moduleId", element: <h1>Module screen</h1> },
    ],
    { initialEntries: ["/modules"] },
  );
  return render(
    <QueryClientProvider client={client}>
      <I18nProvider language="en">
        <DialogsProvider>
          <EventsContext.Provider value={subscribe}>
            <RouterProvider router={router} />
          </EventsContext.Provider>
        </DialogsProvider>
      </I18nProvider>
    </QueryClientProvider>,
  );
}

const saltmarsh = { ...empty, id: "mod_salt", title: "Sinister Secret of Saltmarsh", setting: "Greyhawk", levels: { min: 1, max: 3 }, tags: ["U1", "coast"] };
const tomb = { ...empty, id: "mod_tomb", title: "Tomb of Horrors", setting: "Greyhawk", levels: { min: 10, max: 14 }, tags: ["traps"] };
const phlan = { ...empty, id: "mod_phlan", title: "Ruins Of Adventure", setting: "Forgotten Realms", levels: null, tags: [] };
const listed = () => screen.queryAllByRole("link").map((l) => l.textContent).filter((t) => t && !["New module"].includes(t));

describe("Modules, filtered (backlog 37)", () => {
  beforeEach(() => {
    routes["GET /api/modules"] = () => json(200, [saltmarsh, tomb, phlan, crypt]);
  });

  it("shows each module's setting, levels and tags", async () => {
    renderModules();
    const row = (await screen.findByRole("link", { name: saltmarsh.title })).closest("li")!;
    expect(row.textContent).toContain("Greyhawk");
    expect(row.textContent).toContain("Levels 1–3");
    expect(within(row).getByRole("button", { name: "Only the modules tagged U1" })).toBeTruthy();
  });

  it("filters on part of the title, the setting, the starting level and a tag, and clears", async () => {
    renderModules();
    await screen.findByRole("link", { name: tomb.title });
    fireEvent.change(screen.getByLabelText("Title"), { target: { value: "of" } });
    expect(listed()).toEqual([crypt.title, phlan.title, saltmarsh.title, tomb.title]);
    fireEvent.change(screen.getByLabelText("Title"), { target: { value: "OF H" } });
    expect(listed()).toEqual([tomb.title]);
    fireEvent.click(screen.getByRole("button", { name: "Clear the filter" }));
    expect(listed()).toHaveLength(4);

    const setting = screen.getByLabelText("Setting") as HTMLSelectElement;
    expect([...setting.options].map((o) => o.text)).toEqual(["Any", "Forgotten Realms", "Greyhawk", "No setting"]);
    fireEvent.change(setting, { target: { value: "Greyhawk" } });
    expect(listed()).toEqual([saltmarsh.title, tomb.title]);
    fireEvent.change(screen.getByLabelText("Starting level"), { target: { value: "2" } });
    expect(listed()).toEqual([saltmarsh.title]);
    fireEvent.change(screen.getByLabelText("Starting level"), { target: { value: "5" } });
    expect(screen.getByText("No module fits the filter.")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Clear the filter" }));

    fireEvent.change(screen.getByLabelText("Tag"), { target: { value: "traps" } });
    expect(listed()).toEqual([tomb.title]);
  });

  it("filters on a row's tag when it is clicked", async () => {
    renderModules();
    fireEvent.click(await screen.findByRole("button", { name: "Only the modules tagged coast" }));
    expect(listed()).toEqual([saltmarsh.title]);
    expect((screen.getByLabelText("Tag") as HTMLSelectElement).value).toBe("coast");
  });

  it("goes back to the first page when the filter changes", async () => {
    routes["GET /api/modules"] = () =>
      json(200, Array.from({ length: 23 }, (_, i) => ({ ...empty, id: `mod_${i}`, title: `Module ${i + 1}` })));
    renderModules();
    fireEvent.click(await screen.findByRole("button", { name: "Next" }));
    expect(await screen.findByRole("link", { name: "Module 23" })).toBeTruthy();
    fireEvent.change(screen.getByLabelText("Title"), { target: { value: "Module 1" } });
    expect(await screen.findByRole("link", { name: "Module 1" })).toBeTruthy();
    expect(screen.getByRole("link", { name: "Module 10" })).toBeTruthy();
  });
});

describe("Modules", () => {
  it("pages through many modules, 20 at a time", async () => {
    routes["GET /api/modules"] = () =>
      json(200, Array.from({ length: 23 }, (_, i) => ({ ...empty, id: `mod_${i}`, title: `Module ${i + 1}` })));
    renderModules();
    expect(await screen.findByRole("link", { name: "Module 20" })).toBeTruthy();
    expect(screen.queryByRole("link", { name: "Module 21" })).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Next" }));
    expect(await screen.findByRole("link", { name: "Module 23" })).toBeTruthy();
    expect(screen.getByRole("navigation", { name: "Modules pages" }).textContent).toContain("21–23 of 23");
  });

  it("lists the modules with a link to each, and marks the drafts", async () => {
    routes["GET /api/modules"] = () => json(200, [crypt, { ...empty, draft: true }]);
    renderModules();
    const link = await screen.findByRole("link", { name: "Crypt of Saint Vellis" });
    expect(link.getAttribute("href")).toBe("/modules/mod_0123456789ab");
    expect(screen.getByRole("link", { name: "Empty" })).toBeTruthy();
    expect(screen.getByText("2 maps")).toBeTruthy();
    const rows = screen.getAllByRole("listitem");
    expect(within(rows[1]).getByText("Draft")).toBeTruthy();
    expect(within(rows[0]).queryByText("Draft")).toBeNull();
  });

  it("marks the homebrew modules, beside Draft and not among their tags (DEL-226)", async () => {
    routes["GET /api/modules"] = () => json(200, [saltmarsh, { ...tomb, tags: ["traps", "homebrew"] }]);
    renderModules();
    const tombLink = await screen.findByRole("link", { name: "Tomb of Horrors" });
    const tombRow = tombLink.closest("li") as HTMLElement;
    const saltRow = screen.getByRole("link", { name: "Sinister Secret of Saltmarsh" }).closest("li") as HTMLElement;
    expect(within(tombRow).getByText("Homebrew")).toBeTruthy();
    expect(within(tombRow).queryByText("homebrew")).toBeNull();
    expect(within(tombRow).getByText("traps")).toBeTruthy();
    expect(within(saltRow).queryByText("Homebrew")).toBeNull();
  });

  it("says which modules no campaign has played yet", async () => {
    renderModules();
    await screen.findByRole("link", { name: "Crypt of Saint Vellis" });
    const rows = screen.getAllByRole("listitem");
    expect(within(rows[0]).getByText("Revision 1")).toBeTruthy();
    expect(within(rows[1]).getByText("Not played yet: a campaign takes its own copy when it starts")).toBeTruthy();
  });

  it("New module opens the New module screen", async () => {
    renderModules();
    fireEvent.click(await screen.findByRole("link", { name: "New module" }));
    expect(await screen.findByRole("heading", { name: "New module screen" })).toBeTruthy();
  });

  it("a running conversion is a row at the top, with its step and count, that follows its events", async () => {
    routes["GET /api/conversions"] = () => json(200, [converting]);
    renderModules();
    const row = (await screen.findByText("Dark Clouds Gather")).closest("li")!;
    expect(within(row).getByText("Converting…")).toBeTruthy();
    expect(within(row).getByText("Step 2 of 4 · Converting the text")).toBeTruthy();
    expect(within(row).getByText("12 of 300 pages")).toBeTruthy();
    expect(within(row).getByRole("link", { name: "See the progress" }).getAttribute("href")).toBe("/modules/new");
    expect(screen.getAllByRole("listitem")[0]).toBe(row);

    act(() =>
      heard.conversion?.forEach((h) =>
        h({ id: converting.id, status: "running", step: "entities", done: 3, total: 9, steps: { index: 3, count: 4 } }),
      ),
    );
    expect(await within(row).findByText("Step 3 of 4 · Finding the NPCs and encounters")).toBeTruthy();
    expect(within(row).getByText("3 of 9 texts")).toBeTruthy();
  });

  it("the latest finished conversion stays as a row until its module is opened", async () => {
    const done = { ...converting, status: "done", module_id: "mod_0123456789ab", step: "maps", steps: { index: 4, count: 4 } };
    routes["GET /api/conversions"] = () => json(200, [done]);
    renderModules();
    const open = await screen.findByRole("link", { name: "Done: open the module" });
    expect(open.getAttribute("href")).toBe("/modules/mod_0123456789ab");
    fireEvent.click(open);
    expect(await screen.findByRole("heading", { name: "Module screen" })).toBeTruthy();

    renderModules();
    await screen.findByRole("link", { name: "Crypt of Saint Vellis" });
    expect(screen.queryByRole("link", { name: "Done: open the module" })).toBeNull();
  });

  it("a failed conversion shows its reason until it is dismissed", async () => {
    const failed = { ...converting, status: "failed", error: "The PDF has no pages." };
    routes["GET /api/conversions"] = () => json(200, [failed]);
    renderModules();
    expect(await screen.findByText("Failed: The PDF has no pages.")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Dismiss" }));
    expect(screen.queryByText("Failed: The PDF has no pages.")).toBeNull();
  });

  it("a running world-map reading links to its review, not to New module", async () => {
    const reading = {
      ...converting,
      kind: "worldmap",
      title: "The Flanaess",
      step: "grid",
      target: { module_id: crypt.id, name: "flanaess" },
    };
    routes["GET /api/conversions"] = () => json(200, [reading]);
    renderModules();
    const row = (await screen.findByText("The Flanaess")).closest("li")!;
    expect(within(row).getByRole("link", { name: "See the progress" }).getAttribute("href")).toBe(
      `/world-maps/module/${crypt.id}/flanaess/review`,
    );
  });

  it("a running map draft links to its module's maps", async () => {
    const draft = { ...converting, kind: "dungeon-map", title: "A map", step: "drawing", target: { module_id: crypt.id } };
    routes["GET /api/conversions"] = () => json(200, [draft]);
    renderModules();
    const row = (await screen.findByText("A map")).closest("li")!;
    expect(within(row).getByRole("link", { name: "See the progress" }).getAttribute("href")).toBe(
      `/modules/${crypt.id}?tab=maps`,
    );
  });

  it("an update available badge shows on the module list", async () => {
    const library = { key: "lib_0123456789ab", version: 1, origin: "downloaded", edited: false };
    routes["GET /api/modules"] = () => json(200, [{ ...crypt, library: { ...library, newer: 2 } }, { ...empty, library: null }]);
    renderModules();
    const row = (await screen.findByRole("link", { name: "Crypt of Saint Vellis" })).closest("li")!;
    expect(within(row).getByText("Update available")).toBeTruthy();
    expect(within(screen.getByRole("link", { name: "Empty" }).closest("li")!).queryByText("Update available")).toBeNull();
  });

  it("a Library tab shows only with a library store, and opens the library", async () => {
    renderModules();
    await screen.findByRole("link", { name: "Crypt of Saint Vellis" });
    expect(screen.queryByRole("tab", { name: "Library" })).toBeNull();

    routes["GET /api/library"] = () =>
      json(200, { right: "read", entries: [], warnings: [] });
    renderModules();
    fireEvent.click(await screen.findByRole("tab", { name: "Library" }));
    expect(await screen.findByText("The library has no modules yet.")).toBeTruthy();
    expect(screen.getByText("This library is read-only here.")).toBeTruthy();
  });

  it("each module has Export .dscn", async () => {
    renderModules();
    const exported = await rowMenuItem("Crypt of Saint Vellis", "Export .dscn");
    expect(exported.getAttribute("href")).toBe(`/api/modules/${crypt.id}/export.dscn`);
    expect(exported.hasAttribute("download")).toBe(true);
  });

  it("Delete asks first, then deletes the module", async () => {
    let deleted = false;
    routes[`DELETE /api/modules/${empty.id}`] = () => {
      deleted = true;
      return new Response(null, { status: 204 });
    };
    renderModules();
    await chooseFromRowMenu("Empty", "Delete");
    const dialog = await screen.findByRole("alertdialog", { name: "Delete the module Empty? This can't be undone." });
    const cancel = [...dialog.querySelectorAll("button")].find((b) => b.textContent === "Cancel")!;
    fireEvent.click(cancel);
    await waitFor(() => expect(screen.queryByRole("alertdialog")).toBeNull());
    expect(deleted).toBe(false);

    await chooseFromRowMenu("Empty", "Delete");
    const again = await screen.findByRole("alertdialog");
    fireEvent.click([...again.querySelectorAll("button")].find((b) => b.textContent === "Delete")!);
    await waitFor(() => expect(deleted).toBe(true));
  });

  it("a module campaigns play from isn't deleted, and says why", async () => {
    routes[`DELETE /api/modules/${crypt.id}`] = () =>
      json(409, { error: "Campaigns are played from this module.", campaigns: ["cmp_00000000000a"] });
    renderModules();
    await chooseFromRowMenu("Crypt of Saint Vellis", "Delete");
    const dialog = await screen.findByRole("alertdialog");
    fireEvent.click([...dialog.querySelectorAll("button")].find((b) => b.textContent === "Delete")!);
    expect(await screen.findByText("Not deleted: Campaigns are played from this module.")).toBeTruthy();
  });

  it("Import a .dscn posts the file and opens the module with its warnings", async () => {
    let contentType: string | null = null;
    let body: unknown;
    routes["POST /api/modules/import"] = (init) => {
      contentType = new Headers(init?.headers).get("Content-Type");
      body = init?.body;
      return json(201, { ...crypt, metadata: {}, warnings: ["One key has no room."] });
    };
    renderModules();
    const file = new File([new Uint8Array([0x50, 0x4b, 0x03, 0x04])], "crypt.dscn", { type: "" });
    fireEvent.change(await screen.findByLabelText("Import .dscn"), { target: { files: [file] } });
    await waitFor(() => expect(contentType).toBe("application/zip"));
    expect(body).toBe(file);
    expect(await screen.findByRole("heading", { name: "Module screen" })).toBeTruthy();
  });

  it("says why an import was refused", async () => {
    routes["POST /api/modules/import"] = () => json(400, { error: "scenario.json is missing" });
    renderModules();
    const file = new File([new Uint8Array([1, 2, 3])], "bad.dscn");
    fireEvent.change(await screen.findByLabelText("Import .dscn"), { target: { files: [file] } });
    expect(await screen.findByText("Not imported: bad.dscn: scenario.json is missing")).toBeTruthy();
  });
});

describe("Modules, in categories (DEL-114)", () => {
  const mega = { id: "cat_mega", name: "Megadungeons", position: 0 };
  beforeEach(() => {
    routes["GET /api/module-categories"] = () => json(200, [mega]);
    routes["GET /api/modules"] = () => json(200, [{ ...tomb, category: { id: mega.id, name: mega.name } }, saltmarsh, phlan]);
  });

  it("groups the modules under their category, No category last, each heading counted", async () => {
    renderModules();
    const headings = (await screen.findAllByRole("heading", { level: 2 })).map((h) => h.textContent);
    expect(headings).toEqual(["Megadungeons 1", "No category 2"]);
    const megaGroup = screen.getByRole("region", { name: "Megadungeons" });
    expect(within(megaGroup).getByRole("link", { name: tomb.title })).toBeTruthy();
  });

  it("deleting a category says how many modules lose it", async () => {
    let deleted = false;
    routes[`DELETE /api/module-categories/${mega.id}`] = () => ((deleted = true), new Response(null, { status: 204 }));
    renderModules();
    fireEvent.click(await screen.findByRole("button", { name: "Categories" }));
    const dialog = await screen.findByRole("dialog", { name: "Module categories" });
    fireEvent.click(await within(dialog).findByRole("button", { name: "Delete" }));
    const asked = await screen.findByRole("alertdialog");
    expect(asked.textContent).toContain("Its module gets no category.");
    fireEvent.click(within(asked).getByRole("button", { name: "Delete" }));
    await waitFor(() => expect(deleted).toBe(true));
  });

  it("puts a refused name back, beside the server's reason (DEL-174)", async () => {
    routes[`PUT /api/module-categories/${mega.id}`] = () => json(409, { error: "A category has that name." });
    renderModules();
    fireEvent.click(await screen.findByRole("button", { name: "Categories" }));
    const dialog = await screen.findByRole("dialog", { name: "Module categories" });
    const field = (await within(dialog).findByLabelText("Name of Megadungeons")) as HTMLInputElement;
    fireEvent.change(field, { target: { value: "Dungeons" } });
    fireEvent.keyDown(field, { key: "Enter" });
    expect((await within(dialog).findByRole("alert")).textContent).toContain("A category has that name.");
    expect(field.value).toBe("Megadungeons");
  });
});

describe("Modules, without categories", () => {
  it("shows no headings at all", async () => {
    routes["GET /api/module-categories"] = () => json(200, []);
    renderModules();
    await screen.findByRole("link", { name: crypt.title });
    expect(screen.queryAllByRole("heading", { level: 2 })).toEqual([]);
  });
});

describe("Modules as cards (DEL-123)", () => {
  beforeEach(() => {
    routes["GET /api/module-categories"] = () => json(200, []);
    routes["GET /api/modules"] = () =>
      json(200, [{ ...tomb, banner: { version: "abc123def456", source: "painted", status: null, error: null } }, saltmarsh]);
  });

  it("shows each module's banner, or its first letter, and remembers the choice", async () => {
    renderModules();
    fireEvent.click(await screen.findByRole("button", { name: "Cards" }));
    const cards = document.querySelectorAll(".module-card");
    expect(cards).toHaveLength(2);
    expect(cards[0].querySelector(".module-card-blank")?.textContent).toBe("S");
    expect(cards[1].querySelector("img")?.getAttribute("src")).toBe(`/api/modules/${tomb.id}/banner?v=abc123def456&size=card`);
    expect(localStorage.getItem("delve.modulesLayout")).toBe("cards");
    expect(screen.getByRole("button", { name: "Cards" }).getAttribute("aria-pressed")).toBe("true");
  });

  it("shows a module's one-line summary under its title, and nothing for one without", async () => {
    routes["GET /api/modules"] = () => json(200, [{ ...saltmarsh, summary: "Smugglers in a haunted house." }, tomb]);
    renderModules();
    fireEvent.click(await screen.findByRole("button", { name: "Cards" }));
    const cards = [...document.querySelectorAll(".module-card")];
    const summaries = cards.map((card) => card.querySelector(".module-card-summary")?.textContent ?? null);
    expect(summaries).toEqual(["Smugglers in a haunted house.", null]);
    expect(screen.getByRole("link", { name: saltmarsh.title })).toBeTruthy();
  });
});

describe("Modules, sorted (DEL-243)", () => {
  const keep = { ...empty, id: "mod_keep", title: "the Keep on the Borderlands", updated_at: "2026-10-20T10:00:00Z" };
  beforeEach(() => {
    routes["GET /api/module-categories"] = () => json(200, []);
    // As the server lists them: in the order they were added.
    routes["GET /api/modules"] = () =>
      json(200, [
        { ...tomb, updated_at: "2026-10-18T10:00:00Z" },
        keep,
        { ...saltmarsh, updated_at: "2026-10-27T10:00:00Z" },
        { ...phlan, updated_at: "2026-10-19T10:00:00Z" },
      ]);
  });

  it("lists them by title, in any case, by default", async () => {
    renderModules();
    await screen.findByRole("link", { name: tomb.title });
    expect(listed()).toEqual(["Ruins Of Adventure", "Sinister Secret of Saltmarsh", "the Keep on the Borderlands", "Tomb of Horrors"]);
    expect((screen.getByRole("combobox", { name: "Sort by" }) as HTMLSelectElement).value).toBe("title");
  });

  it("sorts by the last update, the newest or the oldest added, and remembers the choice", async () => {
    renderModules();
    const sort = await screen.findByRole("combobox", { name: "Sort by" });
    fireEvent.change(sort, { target: { value: "updated" } });
    expect(listed()).toEqual(["Sinister Secret of Saltmarsh", "the Keep on the Borderlands", "Ruins Of Adventure", "Tomb of Horrors"]);
    fireEvent.change(sort, { target: { value: "newest" } });
    expect(listed()).toEqual(["Ruins Of Adventure", "Sinister Secret of Saltmarsh", "the Keep on the Borderlands", "Tomb of Horrors"]);
    fireEvent.change(sort, { target: { value: "oldest" } });
    expect(listed()).toEqual(["Tomb of Horrors", "the Keep on the Borderlands", "Sinister Secret of Saltmarsh", "Ruins Of Adventure"]);
    expect(localStorage.getItem("delve.modulesSort")).toBe("oldest");
  });

  it("keeps the order within each category", async () => {
    const mega = { id: "cat_mega", name: "Megadungeons", position: 0 };
    routes["GET /api/module-categories"] = () => json(200, [mega]);
    routes["GET /api/modules"] = () =>
      json(200, [
        { ...tomb, category: { id: mega.id, name: mega.name } },
        saltmarsh,
        { ...keep, category: { id: mega.id, name: mega.name } },
        phlan,
      ]);
    renderModules();
    const megaGroup = await screen.findByRole("region", { name: "Megadungeons" });
    expect(within(megaGroup).getAllByRole("link").map((l) => l.textContent)).toEqual([keep.title, tomb.title]);
    const none = screen.getByRole("region", { name: "No category" });
    expect(within(none).getAllByRole("link").map((l) => l.textContent)).toEqual([phlan.title, saltmarsh.title]);
  });
});
