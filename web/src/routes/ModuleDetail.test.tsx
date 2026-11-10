import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { Editor } from "@tiptap/core";
import { act, cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { RouterProvider, createMemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { ModuleSource } from "../api";
import { DialogsProvider } from "../components/dialogs";
import { I18nProvider } from "../i18n";
import ModuleDetail from "./ModuleDetail";

const MODULE = "mod_cccccccccccc";
const module = {
  id: MODULE,
  title: "The Crypt of Saint Vellis",
  metadata: { system: "adnd2e", party: { levels: { min: 1, max: 3 } } },
  maps: [
    { name: "crypt", role: "map", is_default: true, source: "" },
    { name: "core.dmap", role: "library", is_default: false, source: "" },
  ],
  head_revision: 1,
  updated_at: "2026-10-17T10:00:00Z",
};

function source(): ModuleSource {
  return {
    texts: [
      { id: "intro", title: "Introduction", audience: "player", map: null, markdown: "# The Crypt\n\nIntro text.\n" },
      { id: "crypt-key", title: "Keyed encounters", audience: "gm", map: "crypt", markdown: "## C1. Entry Hall {#c1}\n\nBones.\n" },
    ],
    entities: { npcs: [] },
    attachments: [
      { id: "ritualist-token", type: "image/png", sha256: "78b9", size: 79, description: "Cult ritualist token", audience: "player" },
    ],
    keys: [],
    links: [],
    warnings: [{ code: "room-without-text", message: "The room Crypt Exit on crypt has no text.", ref: "map:crypt#room.exit" }],
  };
}

type Handler = (init: RequestInit | undefined) => Response;
let routes: Record<string, Handler>;
let fetchMock: ReturnType<typeof vi.fn>;

function json(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
}

beforeEach(() => {
  routes = {
    [`GET /api/modules/${MODULE}`]: () => json(200, module),
    [`GET /api/modules/${MODULE}/source`]: () => json(200, source()),
  };
  fetchMock = vi.fn(async (path: string, init?: RequestInit) => {
    const handler = routes[`${init?.method ?? "GET"} ${path}`];
    return handler ? handler(init) : json(404, { error: "not found" });
  });
  vi.stubGlobal("fetch", fetchMock);
});

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

function renderPage(entry = `/modules/${MODULE}`) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const router = createMemoryRouter([{ path: "/modules/:moduleId", element: <ModuleDetail /> }], { initialEntries: [entry] });
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

describe("ModuleDetail", () => {
  it("opens on the Details tab", async () => {
    renderPage();
    expect((await screen.findByRole("tab", { name: "Details" })).getAttribute("aria-selected")).toBe("true");
    expect(((await screen.findByLabelText("Module title")) as HTMLInputElement).value).toBe("The Crypt of Saint Vellis");
  });

  it("shows the module's texts beside the first one on the Text tab", async () => {
    renderPage(`/modules/${MODULE}?tab=text`);
    expect((await screen.findByRole("tab", { name: "Text" })).getAttribute("aria-selected")).toBe("true");
    expect(await screen.findByRole("button", { name: "Introduction" })).toBeTruthy();
    expect(screen.getByRole("button", { name: /Keyed encounters/ })).toBeTruthy();
    expect(((await screen.findByLabelText("Text title")) as HTMLInputElement).value).toBe("Introduction");
    expect(screen.getAllByText("The room Crypt Exit on crypt has no text.").length).toBeGreaterThan(0);
    // Only maps, not libraries, can be a text's map.
    const maps = screen.getByLabelText("Map") as HTMLSelectElement;
    expect([...maps.options].map((o) => o.value)).toEqual(["", "crypt"]);
  });

  it("the module shows its campaigns' banners as links", async () => {
    routes[`GET /api/modules/${MODULE}/banners`] = () =>
      json(200, [
        { campaign_id: "cmp_00000000000a", name: "Tuesday", image_id: "img_00000000000a" },
        { campaign_id: "cmp_00000000000b", name: "Friday", image_id: "img_00000000000b" },
      ]);
    // On the Details tab, with the module's own banner (DEL-183).
    renderPage(`/modules/${MODULE}?tab=details`);
    const heading = await screen.findByRole("heading", { name: "Campaigns" });
    const row = heading.nextElementSibling as HTMLElement;
    const links = within(row).getAllByRole("link");
    expect(links.map((a) => [a.getAttribute("href"), a.textContent])).toEqual([
      ["/campaigns/cmp_00000000000a", "Tuesday"],
      ["/campaigns/cmp_00000000000b", "Friday"],
    ]);
    const img = within(links[0]).getByRole("img", { name: "Tuesday's banner" });
    expect(img.getAttribute("src")).toBe(`/api/modules/${MODULE}/banners/cmp_00000000000a?v=img_00000000000a&size=card`);
    expect(img.parentElement!.className).toBe("banner banner-thumb");
  });

  it("shows no Campaigns section when no campaign has a banner", async () => {
    routes[`GET /api/modules/${MODULE}/banners`] = () => json(200, []);
    renderPage();
    await screen.findByLabelText("Module title");
    await waitFor(() => expect(calls("GET", `/api/modules/${MODULE}/banners`)).toHaveLength(1));
    expect(screen.queryByRole("heading", { name: "Campaigns" })).toBeNull();
  });

  it("opens another text from the list", async () => {
    renderPage(`/modules/${MODULE}?tab=text`);
    fireEvent.click(await screen.findByRole("button", { name: /Keyed encounters/ }));
    await waitFor(() => expect((screen.getByLabelText("Text title") as HTMLInputElement).value).toBe("Keyed encounters"));
  });

  it("makes a new text with its title's slug as the id", async () => {
    routes[`POST /api/modules/${MODULE}/texts`] = (init) => {
      const body = JSON.parse(String(init?.body));
      return json(201, { ...body, audience: "gm", map: null, markdown: "" });
    };
    renderPage(`/modules/${MODULE}?tab=text`);
    fireEvent.click(await screen.findByRole("button", { name: "New text" }));
    await screen.findByRole("dialog", { name: "New text" });
    fireEvent.change(screen.getByLabelText("The new text's title:"), { target: { value: "  The Vestry " } });
    fireEvent.click(screen.getByRole("button", { name: "Make" }));
    await waitFor(() => expect(calls("POST", `/api/modules/${MODULE}/texts`)).toHaveLength(1));
    expect(JSON.parse(String(calls("POST", `/api/modules/${MODULE}/texts`)[0][1].body))).toEqual({
      id: "the-vestry",
      title: "The Vestry",
    });
    await waitFor(() => expect((screen.getByLabelText("Text title") as HTMLInputElement).value).toBe("The Vestry"));
  });

  it("deletes the open text after asking", async () => {
    routes[`DELETE /api/modules/${MODULE}/texts/intro`] = () => new Response(null, { status: 204 });
    renderPage(`/modules/${MODULE}?tab=text`);
    await screen.findByRole("button", { name: "Introduction" });
    fireEvent.click(screen.getByRole("button", { name: "Delete text" }));
    const dialog = await screen.findByRole("alertdialog", { name: "Delete the text Introduction?" });
    const confirm = [...dialog.querySelectorAll("button")].find((b) => b.textContent === "Delete")!;
    expect(confirm.className).toContain("danger");
    fireEvent.click(confirm);
    await waitFor(() => expect(calls("DELETE", `/api/modules/${MODULE}/texts/intro`)).toHaveLength(1));
  });

  it("Insert in text puts an attachment at the open text's cursor", async () => {
    routes[`PUT /api/modules/${MODULE}/texts/intro`] = (init) => {
      const body = JSON.parse(String(init?.body));
      return json(200, { text: { ...source().texts[0], ...body }, links: [], warnings: [] });
    };
    renderPage(`/modules/${MODULE}?tab=text`);
    await screen.findByRole("button", { name: "Introduction" });
    const editor = await waitFor(() => {
      const el = document.querySelector(".ProseMirror") as (HTMLElement & { editor?: Editor }) | null;
      expect(el?.editor).toBeTruthy();
      return el!.editor!;
    });
    act(() => {
      editor.commands.focus("end");
    });
    fireEvent.click(screen.getByRole("tab", { name: "Attachments" }));
    fireEvent.click(await screen.findByRole("button", { name: "Insert ritualist-token in text" }));
    expect(screen.getByRole("tab", { name: "Text" }).getAttribute("aria-selected")).toBe("true");
    fireEvent.click(screen.getByRole("button", { name: "Save" }));
    await waitFor(() => expect(calls("PUT", `/api/modules/${MODULE}/texts/intro`)).toHaveLength(1));
    expect(JSON.parse(String(calls("PUT", `/api/modules/${MODULE}/texts/intro`)[0][1].body)).markdown).toBe(
      "# The Crypt\n\nIntro text.\n\n![Cult ritualist token](asset:ritualist-token)\n",
    );
  });

  it("has a tab for each kind of entity, and the details", async () => {
    renderPage(`/modules/${MODULE}?tab=npcs`);
    expect(await screen.findByText("No NPCs yet.")).toBeTruthy();
    expect(screen.getByRole("button", { name: "New NPC" })).toBeTruthy();
    fireEvent.click(screen.getByRole("tab", { name: "Details" }));
    expect(((await screen.findByLabelText("Module title")) as HTMLInputElement).value).toBe("The Crypt of Saint Vellis");
    expect((screen.getByLabelText("Lowest level") as HTMLInputElement).value).toBe("1");
    expect(screen.getAllByRole("tab").map((tab) => tab.textContent)).toEqual([
      "Details",
      "Text",
      "NPCs",
      "Encounters",
      "Factions",
      "Quests",
      "Pregens",
      "Attachments",
      "Maps",
      "Checks",
    ]);
  });

  it("gives the owner a Novels tab, and a seat none", async () => {
    routes["GET /api/novels?module_id=" + MODULE] = () => json(200, []);
    routes["GET /api/conversions"] = () => json(200, []);
    routes["GET /api/me"] = () => json(200, { principal: { id: "owner", roles: [] }, seat: null });
    renderPage();
    fireEvent.click(await screen.findByRole("tab", { name: "Novels" }));
    expect(await screen.findByRole("button", { name: "Novelize" })).toBeTruthy();
    cleanup();
    const seat = { id: "seat_1", campaign_id: "cmp_00000000000a", campaign_name: "Tuesday", name: "Ann", language: "en", role: "host", organiser: true };
    routes["GET /api/me"] = () => json(200, { principal: { id: "p", roles: [] }, seat });
    fetchMock.mockClear();
    renderPage();
    expect(await screen.findByRole("tab", { name: "Text" })).toBeTruthy();
    await waitFor(() => expect(fetchMock).toHaveBeenCalledWith("/api/me", expect.anything()));
    expect(screen.queryByRole("tab", { name: "Novels" })).toBeNull();
    expect(fetchMock.mock.calls.some(([path]) => String(path).startsWith("/api/novels"))).toBe(false);
  });

  it("lists, adds, edits and deletes a pregen on its own tab", async () => {
    let pregens = [{ id: "ned", name: "Ned Shakeshaft", audience: "player", race: "human", class: "thief", level: 3 }];
    const saved: Handler = (init) => json(200, { record: JSON.parse(String(init?.body)), warnings: [] });
    routes[`GET /api/modules/${MODULE}/source`] = () => json(200, { ...source(), entities: { npcs: [], pregens } });
    routes[`PUT /api/modules/${MODULE}/entities/pregens/ned`] = saved;
    routes[`PUT /api/modules/${MODULE}/entities/pregens/ilsa`] = saved;
    routes[`DELETE /api/modules/${MODULE}/entities/pregens/ned`] = () => {
      pregens = [];
      return new Response(null, { status: 204 });
    };
    renderPage(`/modules/${MODULE}?tab=pregens`);
    expect(await screen.findByRole("button", { name: "Ned Shakeshaft" })).toBeTruthy();
    // The other kinds' forms are in their hidden panels: look in this one.
    const panel = within(document.getElementById("module-panel-pregens")!);

    // Edit the one that is open.
    fireEvent.change(panel.getByLabelText("Level"), { target: { value: "4" } });
    fireEvent.click(panel.getByRole("button", { name: "Save" }));
    await waitFor(() => expect(calls("PUT", `/api/modules/${MODULE}/entities/pregens/ned`)).toHaveLength(1));
    expect(JSON.parse(String(calls("PUT", `/api/modules/${MODULE}/entities/pregens/ned`)[0][1].body)).level).toBe(4);

    // Add one: for the players unless told otherwise.
    fireEvent.click(panel.getByRole("button", { name: "New pregen" }));
    expect((panel.getByLabelText("Who sees it") as HTMLSelectElement).value).toBe("player");
    fireEvent.change(panel.getByLabelText("Name"), { target: { value: "Ilsa" } });
    fireEvent.click(panel.getByRole("button", { name: "Save" }));
    expect(await panel.findByRole("button", { name: "Ilsa" })).toBeTruthy();
    expect(JSON.parse(String(calls("PUT", `/api/modules/${MODULE}/entities/pregens/ilsa`)[0][1].body))).toEqual({
      id: "ilsa",
      name: "Ilsa",
      audience: "player",
    });

    // Delete Ned, after asking.
    fireEvent.click(panel.getByRole("button", { name: "Ned Shakeshaft" }));
    fireEvent.click(await panel.findByRole("button", { name: "Delete" }));
    const dialog = await screen.findByRole("alertdialog", { name: "Delete Ned Shakeshaft?" });
    fireEvent.click([...dialog.querySelectorAll("button")].find((b) => b.textContent === "Delete")!);
    await waitFor(() => expect(calls("DELETE", `/api/modules/${MODULE}/entities/pregens/ned`)).toHaveLength(1));
  });

  it("keeps the maps in their own tab", async () => {
    renderPage(`/modules/${MODULE}?tab=maps`);
    expect((await screen.findByRole("tab", { name: "Maps" })).getAttribute("aria-selected")).toBe("true");
    expect(screen.getByRole("link", { name: "crypt" }).getAttribute("href")).toBe(`/maps/${MODULE}/crypt`);
  });

  it("shows the head revision of a module a campaign plays", async () => {
    renderPage();
    expect(await screen.findByText("Revision 1")).toBeTruthy();
    expect(screen.queryByText("Not played yet: a campaign takes its own copy when it starts")).toBeNull();
  });

  it("says a module with no head revision isn't played yet", async () => {
    routes[`GET /api/modules/${MODULE}`] = () => json(200, { ...module, head_revision: null });
    renderPage();
    expect(await screen.findByText("Not played yet: a campaign takes its own copy when it starts")).toBeTruthy();
  });

  it("makes no link to a map the module doesn't have", async () => {
    routes[`GET /api/modules/${MODULE}/source`] = () =>
      json(200, {
        ...source(),
        texts: [
          ...source().texts,
          { id: "ship-key", title: "The ship", audience: "gm", map: "starboard", markdown: "## 1. Deck\n" },
        ],
        warnings: [
          ...source().warnings,
          { code: "key-without-room", message: "The key 1 in The ship has no room on starboard.", ref: "map:starboard#r1" },
        ],
      });
    renderPage(`/modules/${MODULE}?tab=text`);
    const ship = await screen.findByRole("button", { name: /The ship/ });
    expect(ship.textContent).toContain("No such map");
    // The warnings are on the Checks tab (DEL-183).
    fireEvent.click(screen.getByRole("tab", { name: "Checks" }));
    const missing = await screen.findByText("The key 1 in The ship has no room on starboard.");
    expect(missing.closest("a")).toBeNull();
    expect(screen.queryByRole("link", { name: /starboard/ })).toBeNull();
    // A map that exists is still linked.
    expect(screen.getByRole("link", { name: "The room Crypt Exit on crypt has no text." }).getAttribute("href")).toBe(
      `/maps/${MODULE}/crypt`,
    );
  });

  it("marks a sketched map as invented, with a link to the book's map, and a drawn map not", async () => {
    const sketched = "# Sketched from the room key: an invented layout. The book's map is asset:map-page-46.\nmap \"x\" {}\n";
    const unpaged = "# Sketched from the room key: an invented layout. No map page was found in the book.\nmap \"y\" {}\n";
    routes[`GET /api/modules/${MODULE}`] = () =>
      json(200, {
        ...module,
        maps: [
          { name: "crypt", role: "map", is_default: true, source: 'map "crypt" {}\n' },
          { name: "map-c-the-cloud-castle", role: "map", is_default: false, source: sketched },
          { name: "sketch", role: "map", is_default: false, source: unpaged },
        ],
      });
    renderPage(`/modules/${MODULE}?tab=maps`);
    await screen.findByRole("link", { name: "map-c-the-cloud-castle" });
    const rows = screen.getAllByRole("listitem");
    const row = (name: string) => rows.find((li) => li.textContent?.includes(name))!;
    const notice = "Sketched from the room key: the layout is invented.";
    expect(row("crypt").textContent).not.toContain(notice);
    expect(row("map-c-the-cloud-castle").textContent).toContain(notice);
    const link = screen.getByRole("link", { name: "Show the book's page" });
    expect(link.getAttribute("href")).toBe(`/api/modules/${MODULE}/assets/map-page-46`);
    expect(row("map-c-the-cloud-castle").contains(link)).toBe(true);
    expect(row("sketch").textContent).toContain(notice);
    expect(screen.getAllByRole("link", { name: "Show the book's page" })).toHaveLength(1);
  });

  it("a module from the library shows Update available, and Publish to library needs a library", async () => {
    routes[`GET /api/modules/${MODULE}`] = () =>
      json(200, { ...module, library: { key: "lib_0123456789ab", version: 1, origin: "downloaded", newer: 2, edited: false } });
    routes["GET /api/library"] = () => json(200, { right: "publish", entries: [], warnings: [] });
    renderPage();
    expect(await screen.findByText("Update available")).toBeTruthy();
    expect(screen.getByRole("button", { name: "Update" })).toBeTruthy();
    expect(screen.getByRole("button", { name: "Publish to library" })).toBeTruthy();
    cleanup();

    routes["GET /api/library"] = () => json(409, { error: "No library store is set up." });
    renderPage();
    await screen.findByRole("heading", { name: module.title });
    await waitFor(() => expect(screen.queryByRole("button", { name: "Publish to library" })).toBeNull());
    expect(screen.queryByText("Update available")).toBeNull();
  });

  it("a draft shows its badge, and Mark as ready sends the PATCH", async () => {
    let sent: unknown;
    routes[`GET /api/modules/${MODULE}`] = () => json(200, { ...module, draft: true });
    routes[`PATCH /api/modules/${MODULE}`] = (init) => {
      sent = JSON.parse(String(init?.body));
      expect(new Headers(init?.headers).get("Content-Type")).toBe("application/json");
      return json(200, { ...module, draft: false });
    };
    renderPage();
    expect(await screen.findByText("Draft")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Mark as ready" }));
    await waitFor(() => expect(sent).toEqual({ draft: false }));
    await waitFor(() => expect(screen.queryByText("Draft")).toBeNull());
    expect(screen.queryByRole("button", { name: "Mark as ready" })).toBeNull();
  });

  it("a ready module has no badge and nothing to mark", async () => {
    routes[`GET /api/modules/${MODULE}`] = () => json(200, { ...module, draft: false });
    renderPage();
    await screen.findByRole("heading", { name: module.title });
    expect(screen.queryByText("Draft")).toBeNull();
    expect(screen.queryByRole("button", { name: "Mark as ready" })).toBeNull();
  });

  it("after a reload, shows the warnings of the conversion that made the module", async () => {
    const conversion = (id: string, module_id: string | null, status: string, message: string) => ({
      id,
      kind: "pdf",
      title: "The Crypt",
      mode: "draft",
      status,
      step: "maps",
      done: 1,
      total: 1,
      module_id,
      warnings: [{ code: "map-sketched", message, ref: "map:crypt" }],
      error: null,
      created_at: "2026-10-18T10:00:00Z",
      updated_at: "2026-10-18T10:05:00Z",
    });
    // Newest first, as the API lists them.
    routes["GET /api/conversions"] = () =>
      json(200, [
        conversion("cnv_other", "mod_other", "done", "Another module's warning."),
        conversion("cnv_new", MODULE, "done", "The map crypt is sketched from page 4."),
        conversion("cnv_old", MODULE, "done", "An older conversion's warning."),
      ]);
    renderPage();
    expect(await screen.findByText("The map crypt is sketched from page 4.")).toBeTruthy();
    expect(screen.getByText("Converted, with these warnings:")).toBeTruthy();
    expect(screen.queryByText("An older conversion's warning.")).toBeNull();
    expect(screen.queryByText("Another module's warning.")).toBeNull();
  });

  it("a module no conversion made shows no conversion warnings", async () => {
    routes["GET /api/conversions"] = () => json(200, []);
    renderPage();
    await screen.findByRole("heading", { name: module.title });
    await waitFor(() => expect(calls("GET", "/api/conversions")).toHaveLength(1));
    expect(screen.queryByText("Converted, with these warnings:")).toBeNull();
  });

  it("groups the warnings by code, collapsed, with the source's own, each linked to what it is about", async () => {
    const pages = Array.from({ length: 13 }, (_, n) => ({
      code: "page-too-large",
      message: `Page ${n + 3} is too large to render in full; it was rendered at a lower resolution.`,
      ref: `page:${n + 3}`,
    }));
    routes["GET /api/conversions"] = () =>
      json(200, [
        {
          id: "cnv_new",
          kind: "pdf",
          title: "The Crypt",
          mode: "draft",
          status: "done",
          step: "maps",
          done: 1,
          total: 1,
          steps: { index: 4, count: 4 },
          module_id: MODULE,
          warnings: [
            ...pages,
            { code: "map-sketched", message: "Drawn from the room key; compare it with page 4.", ref: "map:crypt" },
            { code: "image-to-describe", message: "The image from page 2 is described only by its page.", ref: "asset:ritualist-token" },
          ],
          error: null,
          created_at: "2026-10-18T10:00:00Z",
          updated_at: "2026-10-18T10:05:00Z",
        },
      ]);
    routes[`GET /api/modules/${MODULE}/source`] = () =>
      json(200, {
        ...source(),
        warnings: [
          ...source().warnings,
          { code: "key-without-room", message: "The key C1 in Keyed encounters has no room on crypt.", ref: "text:crypt-key#c1" },
        ],
      });
    renderPage(`/modules/${MODULE}?tab=checks`);

    const heading = await screen.findByText("Converted, with these warnings:");
    const details = heading.closest("details")!;
    expect(details.open).toBe(false);
    // 17 warnings of 5 distinct codes.
    expect(details.querySelector("summary")!.textContent).toContain("17 warnings, 5 kinds");
    await screen.findByText("The key C1 in Keyed encounters has no room on crypt.");

    // 13 identical codes are one line.
    const group = screen.getByText("13 ×").closest("summary")!;
    expect(group.textContent).toContain("Pages too large to render whole");

    const link = (name: string) => screen.getByRole("link", { name }).getAttribute("href");
    expect(link("Drawn from the room key; compare it with page 4.")).toBe(`/maps/${MODULE}/crypt`);
    expect(link("The room Crypt Exit on crypt has no text.")).toBe(`/maps/${MODULE}/crypt`);
    expect(link("The image from page 2 is described only by its page.")).toBe(`/modules/${MODULE}?tab=attachments`);
    expect(screen.queryByRole("link", { name: /Page 3 is too large/ })).toBeNull();

    fireEvent.click(screen.getByRole("link", { name: "The key C1 in Keyed encounters has no room on crypt." }));
    await waitFor(() => expect((screen.getByLabelText("Text title") as HTMLInputElement).value).toBe("Keyed encounters"));
  });

  it("opens on its tabs: the head has only the title, the category and the actions (DEL-183)", async () => {
    renderPage();
    const tabs = await screen.findByRole("tablist", { name: "Module parts" });
    const exported = screen.getByRole("link", { name: "Export .dscn" });
    expect(exported.compareDocumentPosition(tabs) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(screen.queryByRole("heading", { name: "Fix-it comments" })).toBeNull();
    fireEvent.click(screen.getByRole("tab", { name: "Checks" }));
    expect(await screen.findByRole("heading", { name: "Fix-it comments" })).toBeTruthy();
  });
});
