import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { RouterProvider, createMemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { EventsContext, type Subscribe } from "../api";
import { I18nProvider } from "../i18n";
import type { Chapter, Novel } from "./api";
import NovelReader from "./NovelReader";

const ID = "nov_aaaaaaaaaaaa";

function novel(overrides: Partial<Novel> = {}): Novel {
  return {
    id: ID,
    title: "The Bones of Saint Vellis",
    campaign_id: "cmp_bbbbbbbbbbbb",
    module_id: null,
    revision: null,
    sessions: null,
    length: "short-story",
    tone: "grimdark",
    custom_tone: "",
    language: "en",
    instructions: "Tell it from Ned's point of view.",
    chapters: [
      { title: "Down the Stairs", summary: "They go down.", text: "Dust lay **thick** on the stairs.\n\nNed went first." },
      { title: "The Last Monk", summary: "Ansel waits.", text: "> We have waited for you.\n\nBrother Ansel smiled." },
      { title: "Fire", summary: "The crypt burns.", text: "It burned for a day." },
    ],
    status: "done",
    error: null,
    conversion_id: "cnv_cccccccccccc",
    cost_usd: 0.42,
    created_at: "2026-10-20T10:00:00Z",
    updated_at: "2026-10-20T10:30:00Z",
    ...overrides,
  };
}

type Handler = (init: RequestInit | undefined) => Response;
let routes: Record<string, Handler>;
let fetchMock: ReturnType<typeof vi.fn>;
let handlers: Record<string, (data: unknown) => void>;

function json(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
}

beforeEach(() => {
  handlers = {};
  routes = { [`GET /api/novels/${ID}`]: () => json(200, novel()) };
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

const subscribe: Subscribe = (next) => {
  handlers = { ...handlers, ...next };
  return () => {};
};

function renderReader() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const router = createMemoryRouter(
    [
      { path: "/novels/:id", element: <NovelReader /> },
      { path: "/novels/:id/print", element: <p>the print view</p> },
    ],
    { initialEntries: [`/novels/${ID}`] },
  );
  const { container } = render(
    <QueryClientProvider client={client}>
      <I18nProvider language="en">
        <EventsContext.Provider value={subscribe}>
          <RouterProvider router={router} />
        </EventsContext.Provider>
      </I18nProvider>
    </QueryClientProvider>,
  );
  return { container, router };
}

const written = (n: number, of: number): Chapter[] =>
  Array.from({ length: of }, (_, i) => ({ title: `Chapter ${i + 1}`, summary: `Summary ${i + 1}`, text: i < n ? `Text ${i + 1}.` : null }));

describe("NovelReader", () => {
  it("shows the title, a table of contents linking to each chapter, and each chapter's Markdown", async () => {
    const { container } = renderReader();
    expect(await screen.findByRole("heading", { level: 1, name: "The Bones of Saint Vellis" })).toBeTruthy();

    const contents = screen.getByRole("navigation", { name: "Contents" });
    const links = within(contents).getAllByRole("link");
    expect(links.map((a) => a.textContent)).toEqual(["Down the Stairs", "The Last Monk", "Fire"]);
    for (const link of links) {
      const target = container.querySelector(link.getAttribute("href")!);
      expect(target?.tagName).toBe("SECTION");
      expect(within(target as HTMLElement).getByRole("heading", { level: 2 }).textContent).toBe(link.textContent);
    }

    const first = container.querySelector("#chapter-1")!;
    expect(first.querySelector("strong")?.textContent).toBe("thick");
    expect(first.querySelectorAll("p")).toHaveLength(2);
    expect(container.querySelector("#chapter-2 blockquote")?.textContent).toContain("We have waited for you.");
    expect(screen.queryByText(/Unfinished/)).toBeNull();
    expect(screen.queryByRole("button", { name: "Continue" })).toBeNull();
    expect((screen.getByRole("link", { name: "Print the novel" })).getAttribute("href")).toBe(`/novels/${ID}/print`);
    expect((screen.getByRole("link", { name: "← Back to the campaign" })).getAttribute("href")).toBe("/campaigns/cmp_bbbbbbbbbbbb");
  });

  it("escapes what the writer wrote: Markdown, never markup of its own", async () => {
    routes[`GET /api/novels/${ID}`] = () =>
      json(200, novel({ chapters: [{ title: "One", summary: "", text: 'A <img src=x onerror="alert(1)"> trap.' }] }));
    const { container } = renderReader();
    await screen.findByRole("heading", { level: 2, name: "One" });
    expect(container.querySelector("#chapter-1 img")).toBeNull();
    expect(container.querySelector("#chapter-1")?.textContent).toContain("<img");
  });

  it("shows a partial novel as unfinished, its planned chapters unlinked, and Continue starts it again", async () => {
    routes[`GET /api/novels/${ID}`] = () =>
      json(200, novel({ length: "novella", status: "failed", error: "The writer didn't answer", chapters: written(2, 9) }));
    let continued = false;
    routes[`POST /api/novels/${ID}/continue`] = () => {
      continued = true;
      return json(202, novel({ length: "novella", status: "writing", conversion_id: "cnv_dddddddddddd", chapters: written(2, 9) }));
    };
    renderReader();

    expect(await screen.findByText("Unfinished: 2 of 9 chapters")).toBeTruthy();
    expect(screen.getByText("The writer didn't answer")).toBeTruthy();
    const contents = screen.getByRole("navigation", { name: "Contents" });
    expect(within(contents).getAllByRole("link")).toHaveLength(2);
    expect(within(contents).getByText("Chapter 9")).toBeTruthy();
    expect(Array.from(document.querySelectorAll("section h2")).map((h) => h.textContent)).toEqual(["Chapter 1", "Chapter 2"]);

    fireEvent.click(screen.getByRole("button", { name: "Continue" }));
    await waitFor(() => expect(continued).toBe(true));
    expect(await screen.findByText("Being written: 2 of 9 chapters")).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Continue" })).toBeNull();
  });

  it("says why Continue was refused, as while another job runs", async () => {
    routes[`GET /api/novels/${ID}`] = () => json(200, novel({ status: "cancelled", chapters: written(1, 3) }));
    routes[`POST /api/novels/${ID}/continue`] = () => json(409, { error: "A conversion is running." });
    renderReader();
    fireEvent.click(await screen.findByRole("button", { name: "Continue" }));
    expect((await screen.findByRole("alert")).textContent).toContain("A conversion is running.");
  });

  it("is fetched again when its job's progress arrives", async () => {
    let calls = 0;
    routes[`GET /api/novels/${ID}`] = () => {
      calls++;
      return json(200, novel({ status: "writing", chapters: written(calls, 3) }));
    };
    renderReader();
    expect(await screen.findByText("Being written: 1 of 3 chapters")).toBeTruthy();
    handlers.conversion({ id: "cnv_other", status: "running" });
    handlers.conversion({ id: "cnv_cccccccccccc", status: "running" });
    expect(await screen.findByText("Being written: 2 of 3 chapters")).toBeTruthy();
    expect(calls).toBe(2);
  });

  it("renames the novel in place", async () => {
    let sent: unknown = null;
    let title = "The Bones of Saint Vellis";
    routes[`GET /api/novels/${ID}`] = () => json(200, novel({ title }));
    routes[`PATCH /api/novels/${ID}`] = (init) => {
      sent = JSON.parse(String(init?.body));
      title = "Ash and Bone";
      return json(200, novel({ title }));
    };
    renderReader();
    fireEvent.click(await screen.findByRole("button", { name: "Rename" }));
    const input = screen.getByRole("textbox", { name: "Title" });
    expect((input as HTMLInputElement).value).toBe("The Bones of Saint Vellis");
    fireEvent.change(input, { target: { value: "  Ash and Bone " } });
    fireEvent.click(screen.getByRole("button", { name: "Save" }));

    expect(await screen.findByRole("heading", { level: 1, name: "Ash and Bone" })).toBeTruthy();
    expect(sent).toEqual({ title: "Ash and Bone" });
    expect(screen.queryByRole("textbox", { name: "Title" })).toBeNull();
  });

  it("leaves the title as it was when the rename is cancelled with Escape", async () => {
    renderReader();
    fireEvent.click(await screen.findByRole("button", { name: "Rename" }));
    const input = screen.getByRole("textbox", { name: "Title" });
    fireEvent.change(input, { target: { value: "Something else" } });
    fireEvent.keyDown(input, { key: "Escape" });
    expect(screen.getByRole("heading", { level: 1, name: "The Bones of Saint Vellis" })).toBeTruthy();
    expect(fetchMock.mock.calls.some(([, init]) => init?.method === "PATCH")).toBe(false);
  });

  it("links a module's novel back to its module", async () => {
    routes[`GET /api/novels/${ID}`] = () => json(200, novel({ campaign_id: null, module_id: "mod_eeeeeeeeeeee", revision: 2 }));
    renderReader();
    expect((await screen.findByRole("link", { name: "← Back to the module" })).getAttribute("href")).toBe("/modules/mod_eeeeeeeeeeee");
  });

  it("says when the novel can't be read, as for a seat (403)", async () => {
    routes[`GET /api/novels/${ID}`] = () => json(403, { error: "owner only" });
    renderReader();
    expect((await screen.findByRole("alert")).textContent).toContain("owner only");
  });
});
