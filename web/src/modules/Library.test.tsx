import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import type { ReactNode } from "react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { ModuleDetail } from "../api";
import type { Library as LibraryShape, LibraryEntry } from "../cloud/api";
import { DialogsProvider } from "../components/dialogs";
import { I18nProvider } from "../i18n";
import Library, { ModuleLibraryBar } from "./Library";

const shrine: LibraryEntry = {
  key: "lib_0123456789ab",
  version: 3,
  title: "The Sunken Shrine",
  summary: "A drowned temple.",
  author: "Mira",
  created_at: "2026-09-01T10:00:00Z",
  updated_at: "2026-10-20T10:00:00Z",
  size: 12_400,
  hash: "abc",
  publisher: "install-b",
  format: 1,
  local: null,
};
const crypt: LibraryEntry = {
  ...shrine,
  key: "lib_ba9876543210",
  version: 1,
  title: "Crypt of Saint Vellis",
  summary: "",
  author: "Raf",
  local: { module_id: "mod_crypt", origin: "published", version: 1 },
};

const module: ModuleDetail = {
  id: "mod_shrine",
  title: "The Sunken Shrine",
  maps: [],
  head_revision: 2,
  updated_at: "2026-10-20T10:00:00Z",
  draft: false,
  metadata: { summary: "A drowned temple." },
  library: null,
};

type Handler = (init: RequestInit | undefined) => Response;
let routes: Record<string, Handler>;
let calls: { path: string; body: unknown }[];

function json(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
}

const library = (right: LibraryShape["right"], entries: LibraryEntry[] = [shrine, crypt], warnings: string[] = []) =>
  json(200, { right, entries, warnings });

beforeEach(() => {
  calls = [];
  routes = {
    "GET /api/library": () => library("publish"),
    "GET /api/me": () =>
      json(200, { principal: { id: "acc_1", roles: ["organiser"] }, seat: null, account: { display_name: "Raf Janssens" } }),
    "GET /api/modules": () => json(200, [module]),
  };
  vi.stubGlobal(
    "fetch",
    vi.fn(async (path: string, init?: RequestInit) => {
      const method = init?.method ?? "GET";
      calls.push({ path: `${method} ${path}`, body: init?.body ? JSON.parse(init.body as string) : undefined });
      const handler = routes[`${method} ${path}`];
      return handler ? handler(init) : json(404, { error: "not found" });
    }),
  );
});

afterEach(() => vi.unstubAllGlobals());

function renderIt(children: ReactNode) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <I18nProvider language="en">
        <DialogsProvider>
          <MemoryRouter>{children}</MemoryRouter>
        </DialogsProvider>
      </I18nProvider>
    </QueryClientProvider>,
  );
}

const rowOf = async (title: string) => (await screen.findByText(title)).closest("tr")!;

describe("the Library tab", () => {
  it("lists entries with author, created and last updated", async () => {
    renderIt(<Library />);
    const row = await rowOf("The Sunken Shrine");
    expect(row.textContent).toContain("A drowned temple.");
    expect(row.textContent).toContain("Mira");
    expect(row.textContent).toContain("Sep 1, 2026");
    expect(row.textContent).toContain("Oct 20, 2026");
    expect(row.textContent).toContain("12.4 kB");
    expect(within(row).getByRole("button", { name: "Download The Sunken Shrine" })).toBeTruthy();
    const mine = await rowOf("Crypt of Saint Vellis");
    expect(within(mine).getByRole("link", { name: "Published from here" }).getAttribute("href")).toBe("/modules/mod_crypt");
    expect(within(mine).getByRole("button", { name: "Publish a new version of Crypt of Saint Vellis" })).toBeTruthy();
    // Publish, not manage: no deleting, and no version on another install's entry.
    expect(screen.queryByRole("button", { name: /Delete/ })).toBeNull();
    expect(within(row).queryByRole("button", { name: /new version/ })).toBeNull();
  });

  it("a read right shows no publish or delete", async () => {
    routes["GET /api/library"] = () => library("read");
    renderIt(<Library />);
    await rowOf("The Sunken Shrine");
    expect(screen.getByText("This library is read-only here.")).toBeTruthy();
    expect(screen.queryByRole("button", { name: /Publish|new version|Delete/ })).toBeNull();
    expect(screen.getByRole("button", { name: "Download The Sunken Shrine" })).toBeTruthy();
  });

  it("manage deletes any entry or its newest version, after asking", async () => {
    routes["GET /api/library"] = () => library("manage", [shrine, { ...crypt, version: 2 }]);
    routes[`DELETE /api/library/${shrine.key}?version=3`] = () => new Response(null, { status: 204 });
    renderIt(<Library />);
    const row = await rowOf("The Sunken Shrine");
    // Manage adds a version to an entry published from here even when another install's version is newer.
    const mine = await rowOf("Crypt of Saint Vellis");
    expect(within(mine).getByRole("button", { name: "Publish a new version of Crypt of Saint Vellis" })).toBeTruthy();
    fireEvent.click(within(row).getByRole("button", { name: "Delete version 3" }));
    const dialog = await screen.findByRole("alertdialog", { name: "Delete version 3 of The Sunken Shrine from the library?" });
    fireEvent.click(within(dialog).getByRole("button", { name: "Delete" }));
    await waitFor(() => expect(calls.some((c) => c.path === `DELETE /api/library/${shrine.key}?version=3`)).toBe(true));
  });

  it("Download makes a local module of the entry", async () => {
    routes["POST /api/library/download"] = () => json(200, { ...module, library: { key: shrine.key, version: 3, origin: "downloaded", newer: null, edited: false } });
    renderIt(<Library />);
    fireEvent.click(await screen.findByRole("button", { name: "Download The Sunken Shrine" }));
    await waitFor(() => expect(calls.find((c) => c.path === "POST /api/library/download")?.body).toEqual({ key: shrine.key }));
  });

  it("publish shows the entry before it is made, author editable", async () => {
    routes["POST /api/modules/mod_shrine/publish"] = () => json(200, { ...shrine, version: 1, local: undefined });
    renderIt(<Library />);
    fireEvent.click(await screen.findByRole("button", { name: "Publish a module…" }));
    const dialog = await screen.findByRole("dialog", { name: "Publish to the library" });
    await within(dialog).findByRole("option", { name: "The Sunken Shrine" });
    fireEvent.change(within(dialog).getByLabelText("Module"), { target: { value: "mod_shrine" } });
    const entry = dialog.querySelector("dl")!;
    expect(entry.textContent).toContain("The Sunken Shrine");
    expect(entry.textContent).toContain("Version1");
    const author = within(dialog).getByLabelText("Author") as HTMLInputElement;
    await waitFor(() => expect(author.value).toBe("Raf Janssens"));
    expect(calls.some((c) => c.path.includes("/publish"))).toBe(false);
    fireEvent.change(author, { target: { value: "Raf of Ghent" } });
    fireEvent.click(within(dialog).getByRole("button", { name: "Publish" }));
    await waitFor(() =>
      expect(calls.find((c) => c.path === "POST /api/modules/mod_shrine/publish")?.body).toEqual({ author: "Raf of Ghent" }),
    );
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
  });

  it("a malformed entry's warning is shown above the list", async () => {
    routes["GET /api/library"] = () =>
      library("read", [shrine], ["The library's entry lib_ffffffffffff can't be read by this Delve, so it isn't listed."]);
    renderIt(<Library />);
    const note = await screen.findByText(/lib_ffffffffffff can't be read/);
    const table = await screen.findByRole("table");
    expect(note.compareDocumentPosition(table) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  });
});

describe("a module's library bar", () => {
  const downloaded = (edited: boolean): ModuleDetail => ({
    ...module,
    library: { key: shrine.key, version: 2, origin: "downloaded", newer: 3, edited },
  });

  it("update on an edited module warns and offers to keep a copy", async () => {
    routes["POST /api/modules/mod_shrine/library-update"] = () =>
      json(200, { ...module, library: { key: shrine.key, version: 3, origin: "downloaded", newer: null, edited: false } });
    renderIt(<ModuleLibraryBar module={downloaded(true)} />);
    expect(await screen.findByText("Update available")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Update" }));
    const dialog = await screen.findByRole("dialog", { name: "Update The Sunken Shrine to version 3?" });
    expect(within(dialog).getByText("Your edits to this module will be replaced.")).toBeTruthy();
    const keep = within(dialog).getByLabelText("Keep my version as a separate module") as HTMLInputElement;
    expect(keep.checked).toBe(true);
    expect(calls.some((c) => c.path.includes("library-update"))).toBe(false);
    fireEvent.click(within(dialog).getByRole("button", { name: "Update" }));
    await waitFor(() =>
      expect(calls.find((c) => c.path === "POST /api/modules/mod_shrine/library-update")?.body).toEqual({ keep_copy: true }),
    );
    expect(await screen.findByText(/Updated to version 3/)).toBeTruthy();
  });

  it("update on an unedited module takes the new version at once", async () => {
    routes["POST /api/modules/mod_shrine/library-update"] = () => json(200, { ...module, library: { ...downloaded(false).library!, version: 3, newer: null } });
    renderIt(<ModuleLibraryBar module={downloaded(false)} />);
    fireEvent.click(await screen.findByRole("button", { name: "Update" }));
    await waitFor(() =>
      expect(calls.find((c) => c.path === "POST /api/modules/mod_shrine/library-update")?.body).toEqual({ keep_copy: false }),
    );
    expect(screen.queryByRole("dialog")).toBeNull();
  });

  it("a published module says it is up to date until it is edited, and manage may delete it", async () => {
    routes["GET /api/library"] = () => library("manage", [crypt]);
    const published = { ...module, id: "mod_crypt", title: crypt.title, library: { key: crypt.key, version: 1, origin: "published" as const, newer: null, edited: false } };
    renderIt(<ModuleLibraryBar module={published} />);
    const upToDate = (await screen.findByRole("button", { name: "Up to date with the library" })) as HTMLButtonElement;
    expect(upToDate.disabled).toBe(true);
    expect(screen.getByRole("button", { name: "Delete from library" })).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Publish to library" })).toBeNull();
  });

  it("a read right offers Update but no publishing, and nothing for a module not from the library", async () => {
    routes["GET /api/library"] = () => library("read");
    const { unmount } = renderIt(<ModuleLibraryBar module={downloaded(false)} />);
    expect(await screen.findByRole("button", { name: "Update" })).toBeTruthy();
    expect(screen.queryByRole("button", { name: /Publish|Delete|New version/ })).toBeNull();
    unmount();
    const { container } = renderIt(<ModuleLibraryBar module={module} />);
    await waitFor(() => expect(calls.filter((c) => c.path === "GET /api/library")).toHaveLength(2));
    expect(container.querySelector(".library-bar")).toBeNull();
  });
});
