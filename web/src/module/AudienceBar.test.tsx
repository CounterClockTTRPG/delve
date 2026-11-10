import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { RouterProvider, createMemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { ModuleSource } from "../api";
import { DialogsProvider } from "../components/dialogs";
import { I18nProvider } from "../i18n";
import ModuleDetail from "../routes/ModuleDetail";

const MODULE = "mod_cccccccccccc";
const module = {
  id: MODULE,
  title: "The Crypt of Saint Vellis",
  metadata: {},
  maps: [{ name: "crypt", role: "map", is_default: true, source: "" }],
  head_revision: 1,
  updated_at: "2026-10-17T10:00:00Z",
};

let audience: "gm" | "player" = "gm";

function source(): ModuleSource {
  return {
    texts: [
      { id: "intro", title: "Introduction", audience, map: null, markdown: "Intro text.\n" },
      { id: "crypt-key", title: "Keyed encounters", audience, map: "crypt", markdown: "Bones.\n" },
      { id: "notes", title: "Notes", audience: "gm", map: null, markdown: "Notes.\n" },
    ],
    entities: { npcs: [{ id: "prior-anselm", name: "Prior Anselm", audience: "gm" }] },
    attachments: [{ id: "map-page", type: "image/png", sha256: "78b9", size: 79, description: "", audience: "gm" }],
    keys: [],
    links: [],
    warnings: [],
  };
}

let posted: unknown[];

function json(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
}

beforeEach(() => {
  audience = "gm";
  posted = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (path: string, init?: RequestInit) => {
      const route = `${init?.method ?? "GET"} ${path}`;
      if (route === `GET /api/modules/${MODULE}`) return json(200, module);
      if (route === `GET /api/modules/${MODULE}/source`) return json(200, source());
      if (route === `POST /api/modules/${MODULE}/audience`) {
        const body = JSON.parse(String(init?.body));
        posted.push(body);
        audience = body.audience;
        return json(200, { changed: body.refs.length });
      }
      return json(404, { error: "not found" });
    }),
  );
});

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

function renderPage(entry = `/modules/${MODULE}?tab=text`) {
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
}

const box = (name: string) => screen.getByRole("checkbox", { name }) as HTMLInputElement;

describe("AudienceBar", () => {
  it("sets the chosen items for the players", async () => {
    renderPage();
    await screen.findByRole("button", { name: /Introduction/ });
    expect(screen.queryByRole("region", { name: "The chosen items' audience" })).toBeNull();
    fireEvent.click(box("Choose Introduction"));
    fireEvent.click(box("Choose Keyed encounters"));
    const bar = screen.getByRole("region", { name: "The chosen items' audience" });
    expect(within(bar).getByText("2 chosen")).toBeTruthy();
    fireEvent.click(within(bar).getByRole("button", { name: "For the players" }));
    await waitFor(() => expect(posted).toEqual([{ refs: ["text:intro", "text:crypt-key"], audience: "player" }]));
    await waitFor(() => expect(box("Choose Introduction").checked).toBe(false));
    expect(box("Choose Keyed encounters").checked).toBe(false);
    expect(screen.queryByRole("region", { name: "The chosen items' audience" })).toBeNull();
    // The source is read again: the two texts are the players' now.
    await waitFor(() => expect(screen.getByRole("button", { name: /Introduction/ }).textContent).toBe("Introduction"));
    expect(screen.getByRole("button", { name: /Keyed encounters/ }).textContent).toBe("Keyed encounters");
    expect(screen.getByRole("button", { name: /Notes/ }).textContent).toBe("NotesDM only");
  });

  it("selects all of a list, and sets them DM only", async () => {
    renderPage(`/modules/${MODULE}?tab=npcs`);
    const panel = await screen.findByRole("tabpanel", { name: "NPCs" });
    await within(panel).findByRole("button", { name: /Prior Anselm/ });
    fireEvent.click(within(panel).getByRole("checkbox", { name: "Select all" }));
    expect((within(panel).getByRole("checkbox", { name: "Choose Prior Anselm" }) as HTMLInputElement).checked).toBe(true);
    fireEvent.click(within(panel).getByRole("button", { name: "DM only" }));
    await waitFor(() => expect(posted).toEqual([{ refs: ["npc:prior-anselm"], audience: "gm" }]));
  });

  it("chooses attachments in their grid", async () => {
    renderPage(`/modules/${MODULE}?tab=attachments`);
    const panel = await screen.findByRole("tabpanel", { name: "Attachments" });
    fireEvent.click(await within(panel).findByRole("checkbox", { name: "Choose map-page" }));
    fireEvent.click(within(panel).getByRole("button", { name: "For the players" }));
    await waitFor(() => expect(posted).toEqual([{ refs: ["asset:map-page"], audience: "player" }]));
  });

  it("names what the server refused, and keeps the ticks", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async (path: string) => {
        if (path === `/api/modules/${MODULE}/audience`)
          return json(422, { error: "The module has no text:intro.", unknown: ["text:intro"] });
        if (path === `/api/modules/${MODULE}/source`) return json(200, source());
        return path === `/api/modules/${MODULE}` ? json(200, module) : json(404, { error: "not found" });
      }),
    );
    renderPage();
    await screen.findByRole("button", { name: /Introduction/ });
    fireEvent.click(box("Choose Introduction"));
    fireEvent.click(screen.getByRole("button", { name: "For the players" }));
    const bar = screen.getByRole("region", { name: "The chosen items' audience" });
    expect((await within(bar).findByRole("alert")).textContent).toBe("Not changed: The module has no text:intro.");
    expect(box("Choose Introduction").checked).toBe(true);
  });
});
