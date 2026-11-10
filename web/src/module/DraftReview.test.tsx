import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { DialogsProvider } from "../components/dialogs";
import { I18nProvider } from "../i18n";
import DraftReview from "./DraftReview";
import MapDrafts from "./MapDrafts";
import type { MapDraft } from "./mapDrafts";

const MODULE = "mod_1";
const DRAFTS = `/api/modules/${MODULE}/map-drafts`;

const house: MapDraft = {
  id: "cnv_5",
  kind: "book-map",
  name: "house-ground-floor",
  source: 'room "r1" { rect 1,1 4 x 4 }\n',
  warnings: [
    { code: "map-from-book", message: "Drawn by Claude from the book's map: compare it with the page.", ref: "map:house" },
    { code: "map-warning", message: "Cellar: map is not connected: 2 separate parts", ref: "map:house-cellar" },
  ],
  created_at: "2026-10-19T10:00:00Z",
  replaces: null,
  part: "the-haunted-house",
  page: "map-page-2",
  maps: [
    { name: "house-ground-floor", title: "Ground floor", source: 'room "r1" { rect 1,1 4 x 4 }\n', part: "the-haunted-house" },
    { name: "house-cellar", title: "Cellar", source: 'room "r18" { rect 1,1 4 x 4 }\n', part: null },
  ],
};

type Handler = (init: RequestInit | undefined) => Response;
let routes: Record<string, Handler>;
let fetchMock: ReturnType<typeof vi.fn>;

function json(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
}

function calls(key: string): (RequestInit | undefined)[] {
  return fetchMock.mock.calls.filter(([path, init]) => `${init?.method ?? "GET"} ${path}` === key).map(([, init]) => init);
}

beforeEach(() => {
  routes = {
    [`GET ${DRAFTS}`]: () => json(200, [house]),
    [`GET /api/modules/${MODULE}/source`]: () =>
      json(200, {
        texts: [{ id: "the-haunted-house", title: "The Haunted House", audience: "gm", map: null, markdown: "" }],
        entities: {},
        attachments: [],
        keys: [],
        links: [],
        warnings: [],
      }),
    "POST /api/dsl/render": (init) => {
      const { source } = JSON.parse(String(init?.body));
      const room = /room "(\w+)"/.exec(source)?.[1] ?? "none";
      return json(200, { svg: `<svg data-room="${room}"></svg>`, diagnostics: [] });
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

function renderWith(children: React.ReactNode) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <I18nProvider language="en">
        <MemoryRouter>
          <DialogsProvider>{children}</DialogsProvider>
        </MemoryRouter>
      </I18nProvider>
    </QueryClientProvider>,
  );
}

const shownRoom = (dialog: HTMLElement) => dialog.querySelector("svg[data-room]")?.getAttribute("data-room");

describe("DraftReview", () => {
  it("shows the book's page beside the level, drawn", async () => {
    renderWith(<DraftReview moduleId={MODULE} draft={house} onClose={() => {}} />);

    const dialog = await screen.findByRole("dialog", { name: "Review the draft house-ground-floor" });
    const page = within(dialog).getByRole("img", { name: "The book's page map-page-2" }) as HTMLImageElement;
    expect(page.getAttribute("src")).toBe(`/api/modules/${MODULE}/assets/map-page-2`);
    await waitFor(() => expect(shownRoom(dialog)).toBe("r1"));
  });

  it("has a tab per level with its part's title, and a tab switches the drawing", async () => {
    renderWith(<DraftReview moduleId={MODULE} draft={house} onClose={() => {}} />);
    const dialog = await screen.findByRole("dialog");

    const tabs = within(dialog).getAllByRole("tab");
    await waitFor(() => expect(tabs[0].textContent).toBe("Ground floor · The Haunted House"));
    expect(tabs[1].textContent).toBe("Cellar");
    fireEvent.click(tabs[1]);

    expect(within(dialog).getAllByRole("tab")[1].getAttribute("aria-selected")).toBe("true");
    await waitFor(() => expect(shownRoom(dialog)).toBe("r18"));
  });

  it("lists the map warnings first", async () => {
    renderWith(<DraftReview moduleId={MODULE} draft={house} onClose={() => {}} />);
    const dialog = await screen.findByRole("dialog");

    const list = within(dialog).getByRole("list", { name: "Warnings" });
    const items = within(list).getAllByRole("listitem").map((li) => li.textContent);
    expect(items).toEqual([
      "Cellar: map is not connected: 2 separate parts",
      "Drawn by Claude from the book's map: compare it with the page.",
    ]);
  });

  it("keeps the draft, then links to its first level in the map editor", async () => {
    routes[`POST ${DRAFTS}/cnv_5/keep`] = () => json(201, { name: "house-ground-floor" });
    renderWith(<DraftReview moduleId={MODULE} draft={house} onClose={() => {}} />);
    const dialog = await screen.findByRole("dialog");
    expect(within(dialog).queryByRole("link", { name: "Open in the map editor" })).toBeNull();

    fireEvent.click(within(dialog).getByRole("button", { name: "Keep" }));

    await waitFor(() => expect(calls(`POST ${DRAFTS}/cnv_5/keep`)).toHaveLength(1));
    const open = await within(dialog).findByRole("link", { name: "Open in the map editor" });
    expect(open.getAttribute("href")).toBe(`/maps/${MODULE}/house-ground-floor`);
    expect(within(dialog).queryByRole("button", { name: "Keep" })).toBeNull();
  });

  it("is opened from a draft's card, and stays open once kept", async () => {
    routes[`POST ${DRAFTS}/cnv_5/keep`] = () => {
      routes[`GET ${DRAFTS}`] = () => json(200, []);
      return json(201, { name: "house-ground-floor" });
    };
    renderWith(<MapDrafts moduleId={MODULE} />);

    const [card] = await screen.findAllByTestId("map-draft");
    fireEvent.click(within(card).getByRole("button", { name: "Review" }));
    const dialog = await screen.findByRole("dialog", { name: "Review the draft house-ground-floor" });
    fireEvent.click(within(dialog).getByRole("button", { name: "Keep" }));

    expect(await within(dialog).findByRole("link", { name: "Open in the map editor" })).toBeTruthy();
    await waitFor(() => expect(screen.queryByTestId("map-draft")).toBeNull());
    expect(screen.getByRole("dialog")).toBeTruthy();
  });
});
