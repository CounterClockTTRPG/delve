import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import type { ReactNode } from "react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { EventsContext, type ModuleMapEntry, type ModuleSource, type Subscribe } from "../api";
import { DialogsProvider } from "../components/dialogs";
import { I18nProvider } from "../i18n";
import FixIts from "./FixIts";
import type { FixitComment, FixitReview } from "./fixits";
import { lineDiff } from "./fixits";

const MODULE = "mod_1";
const LIST = `/api/modules/${MODULE}/fixits`;

const maps: ModuleMapEntry[] = [{ name: "shrine", role: "map", source: 'room "r2" { }', is_default: true }];
const source: ModuleSource = {
  texts: [{ id: "shrine", title: "The Sunken Shrine", audience: "gm", map: null, markdown: "# The Sunken Shrine\n" }],
  entities: { npcs: [{ id: "muckfoot", name: "Chief Muckfoot", audience: "gm" }] },
  attachments: [],
  keys: [],
  links: [
    { text_id: "shrine", anchor: "2-hall", key: "2", map: "shrine", node: "r2", label: "2. Hall of Echoes", explicit: false },
  ],
  warnings: [],
};

const comment = (over: Partial<FixitComment>): FixitComment => ({
  id: "mcm_1",
  module_id: MODULE,
  text: "The exit from room 2 to room 3 is not yet in place, fix it.",
  anchor: null,
  status: "open",
  conversion_id: null,
  revision: null,
  error: null,
  author: "raf",
  created_at: "2026-10-25T10:00:00Z",
  updated_at: "2026-10-25T10:00:00Z",
  job: null,
  ...over,
});

const review: FixitReview = {
  conversion_id: "cnv_1",
  module_id: MODULE,
  revision: 2,
  summary: "Added the passage from the hall to the altar.",
  stale: false,
  comments: ["mcm_2"],
  texts: [{ id: "shrine", title: "The Sunken Shrine", before: "# The Sunken Shrine\nA hall.\n", after: "# The Sunken Shrine\nA hall.\nA passage south.\n" }],
  maps: [{ name: "shrine", before: "map a", after: "map b", before_svg: '<svg data-map="before"></svg>', after_svg: '<svg data-map="after"></svg>' }],
  entities: { added: [{ kind: "npcs", id: "grik", name: "Grik", record: {} }], changed: [], removed: [] },
};

type Handler = (init: RequestInit | undefined) => Response;
let routes: Record<string, Handler>;
let fetchMock: ReturnType<typeof vi.fn>;
let heard: Record<string, ((data: unknown) => void)[]>;
let wide: boolean;

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
  wide = true;
  routes = {
    [`GET ${LIST}`]: () =>
      json(200, [
        comment({ id: "mcm_1", status: "open" }),
        comment({ id: "mcm_2", status: "review", conversion_id: "cnv_1", revision: 2, anchor: { kind: "room", map: "shrine", node: "r2" } }),
        comment({ id: "mcm_3", status: "failed", conversion_id: "cnv_0", error: "The map shrine doesn't parse." }),
        comment({ id: "mcm_4", status: "kept", conversion_id: "cnv_9", revision: 3, anchor: { kind: "entity", entity_kind: "npcs", entity_id: "muckfoot" } }),
        comment({
          id: "mcm_5",
          status: "working",
          conversion_id: "cnv_5",
          job: { id: "cnv_5", status: "running", step: "fixing", done: 0, total: 1, steps: { index: 1, count: 1 } },
        }),
      ]),
    "GET /api/fixits/cnv_1/review": () => json(200, review),
  };
  fetchMock = vi.fn(async (path: string, init?: RequestInit) => {
    const handler = routes[`${init?.method ?? "GET"} ${path}`];
    return handler ? handler(init) : json(404, { error: "not found" });
  });
  vi.stubGlobal("fetch", fetchMock);
  vi.stubGlobal("matchMedia", (query: string) => ({
    matches: query.includes("min-width") ? wide : !wide,
    media: query,
    addEventListener: () => {},
    removeEventListener: () => {},
  }));
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

const fixIts = () => <FixIts moduleId={MODULE} maps={maps} source={source} />;

async function openReview() {
  renderWith(fixIts());
  const rows = await screen.findAllByTestId("fixit-comment");
  fireEvent.click(within(rows[1]).getByRole("button", { name: "Review" }));
  return screen.findByTestId("fixit-review");
}

describe("FixIts", () => {
  it("lists comments with their status", async () => {
    renderWith(fixIts());
    const rows = await screen.findAllByTestId("fixit-comment");
    expect(rows.map((r) => r.dataset.status)).toEqual(["open", "review", "failed", "kept", "working"]);
    expect(within(rows[0]).getByText("Open")).toBeTruthy();
    expect(within(rows[0]).getByRole("button", { name: "Close" })).toBeTruthy();
    expect(within(rows[1]).getByText("Ready to review")).toBeTruthy();
    expect(within(rows[1]).getByText(/2\. Hall of Echoes on shrine/)).toBeTruthy();
    expect(within(rows[2]).getByText("Why: The map shrine doesn't parse.")).toBeTruthy();
    expect(within(rows[2]).getByRole("button", { name: "Run again" })).toBeTruthy();
    expect(within(rows[3]).getByText(/Kept as revision 3/)).toBeTruthy();
    expect(within(rows[3]).getByText(/Chief Muckfoot/)).toBeTruthy();
    expect(within(rows[4]).getByText(/Step 1 of 1: Fixing up the module|Fixing up the module/)).toBeTruthy();
  });

  it("sends a comment tied to a room, and refetches on the job's events", async () => {
    routes[`POST ${LIST}`] = () => json(201, comment({ id: "mcm_6", status: "working" }));
    renderWith(fixIts());
    await screen.findAllByTestId("fixit-comment");

    fireEvent.change(screen.getByLabelText("What should be fixed"), { target: { value: "  Add the exit.  " } });
    fireEvent.change(screen.getByLabelText("About (optional)"), { target: { value: "room:shrine/r2" } });
    fireEvent.click(screen.getByRole("button", { name: "Send" }));

    await waitFor(() => expect(calls(`POST ${LIST}`)).toHaveLength(1));
    expect(JSON.parse(String(calls(`POST ${LIST}`)[0]?.body))).toEqual({
      text: "Add the exit.",
      anchor: { kind: "room", map: "shrine", node: "r2" },
    });
    const before = calls(`GET ${LIST}`).length;
    act(() => heard.conversion?.forEach((h) => h({ id: "cnv_5", status: "done" })));
    await waitFor(() => expect(calls(`GET ${LIST}`).length).toBeGreaterThan(before));
  });

  it("closes an open comment and runs a failed one again", async () => {
    routes["POST /api/fixit-comments/mcm_1/close"] = () => json(200, comment({ status: "closed" }));
    routes["POST /api/fixit-comments/mcm_3/rerun"] = () => json(200, comment({ id: "mcm_3", status: "working" }));
    renderWith(fixIts());
    const rows = await screen.findAllByTestId("fixit-comment");
    fireEvent.click(within(rows[0]).getByRole("button", { name: "Close" }));
    await waitFor(() => expect(calls("POST /api/fixit-comments/mcm_1/close")).toHaveLength(1));
    fireEvent.click(within(rows[2]).getByRole("button", { name: "Run again" }));
    await waitFor(() => expect(calls("POST /api/fixit-comments/mcm_3/rerun")).toHaveLength(1));
  });
});

describe("FixItReview", () => {
  it("review shows the diff", async () => {
    const dialog = await openReview();
    expect(await within(dialog).findByText("Added the passage from the hall to the altar.")).toBeTruthy();
    const text = within(dialog).getByTestId("fixit-text");
    const added = [...text.querySelectorAll('[data-diff="added"]')].map((n) => n.textContent);
    expect(added).toEqual(["+ A passage south.\n"]);
    expect(text.querySelectorAll('[data-diff="removed"]')).toHaveLength(0);
    expect(within(dialog).getByTestId("fixit-map-before").querySelector('svg[data-map="before"]')).toBeTruthy();
    expect(within(dialog).getByTestId("fixit-map-after").querySelector('svg[data-map="after"]')).toBeTruthy();
    expect(within(dialog).getByText("Grik")).toBeTruthy();
  });

  it("keep calls keep", async () => {
    routes["POST /api/fixits/cnv_1/keep"] = () => json(200, { revision: 3 });
    const dialog = await openReview();
    fireEvent.click(await within(dialog).findByRole("button", { name: "Keep" }));
    await waitFor(() => expect(calls("POST /api/fixits/cnv_1/keep")).toHaveLength(1));
    expect(await within(dialog).findByText("Kept as revision 3")).toBeTruthy();
    expect(within(dialog).queryByRole("button", { name: "Keep" })).toBeNull();
  });

  it("stale keep offers run again", async () => {
    routes["POST /api/fixits/cnv_1/keep"] = () => json(409, { error: "The module was changed", code: "stale" });
    routes["POST /api/fixit-comments/mcm_2/rerun"] = () => json(200, comment({ id: "mcm_2", status: "working" }));
    const dialog = await openReview();
    fireEvent.click(await within(dialog).findByRole("button", { name: "Keep" }));
    const stale = await within(dialog).findByTestId("fixit-stale");
    expect(stale.textContent).toContain("The module was changed since this fix was made");
    expect((within(dialog).getByRole("button", { name: "Keep" }) as HTMLButtonElement).disabled).toBe(true);
    fireEvent.click(within(stale).getByRole("button", { name: "Run again" }));
    await waitFor(() => expect(calls("POST /api/fixit-comments/mcm_2/rerun")).toHaveLength(1));
  });

  it("rejects after asking", async () => {
    routes["POST /api/fixits/cnv_1/reject"] = () => json(200, { rejected: "cnv_1" });
    const dialog = await openReview();
    fireEvent.click(await within(dialog).findByRole("button", { name: "Reject" }));
    const sure = await screen.findByRole("alertdialog");
    fireEvent.click(within(sure).getByRole("button", { name: "Reject" }));
    await waitFor(() => expect(calls("POST /api/fixits/cnv_1/reject")).toHaveLength(1));
  });

  it("phone layout stacks before and after", async () => {
    wide = false;
    const dialog = await openReview();
    const before = await within(dialog).findByTestId("fixit-map-before");
    const panes = before.parentElement!;
    expect(panes.dataset.layout).toBe("stacked");
    expect([...panes.children].map((c) => (c as HTMLElement).dataset.testid)).toEqual(["fixit-map-before", "fixit-map-after"]);
  });
});

describe("lineDiff", () => {
  it("keeps, adds and removes lines", () => {
    expect(lineDiff("a\nb\nc", "a\nc\nd")).toEqual([
      { kind: "same", text: "a" },
      { kind: "removed", text: "b" },
      { kind: "same", text: "c" },
      { kind: "added", text: "d" },
    ]);
    expect(lineDiff(null, "x")).toEqual([{ kind: "added", text: "x" }]);
  });
});
