import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { EventsContext, type Conversion, type ConversionQueue, type Subscribe } from "../api";
import { DialogsProvider } from "../components/dialogs";
import { I18nProvider } from "../i18n";
import ConversionsPanel from "./ConversionsPanel";

const base: Conversion = {
  id: "cnv_000000000001",
  kind: "pdf",
  title: "Saltmarsh",
  mode: "ready",
  status: "running",
  step: "cleaning",
  done: 12,
  total: 34,
  steps: { index: 5, count: 10 },
  module_id: null,
  warnings: [],
  error: null,
  created_at: "2026-10-23T20:00:00Z",
  updated_at: "2026-10-23T20:00:00Z",
  cost_usd: 18.4,
  thorough: true,
  paused: null,
};
const running = base;
const queuedQuick: Conversion = {
  ...base,
  id: "cnv_000000000002",
  title: "Danger at Dunwater",
  status: "queued",
  step: "reading",
  done: 0,
  total: 0,
  steps: { index: 0, count: 5 },
  cost_usd: null,
  thorough: false,
};
const queuedThorough: Conversion = { ...queuedQuick, id: "cnv_000000000003", title: "The Final Enemy", thorough: true };
const paused: Conversion = {
  ...base,
  id: "cnv_000000000004",
  title: "The Isle of Dread",
  status: "paused",
  cost_usd: 3,
  paused: { reason: "paused by the organiser", resets_at: null },
};

type Handler = (init: RequestInit | undefined) => Response;
let routes: Record<string, Handler>;
let queue: ConversionQueue;
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
  queue = { paused: false, jobs: [running, queuedQuick, queuedThorough, paused] };
  routes = { "GET /api/conversions/queue": () => json(200, queue) };
  vi.stubGlobal(
    "fetch",
    vi.fn(async (path: string, init?: RequestInit) => {
      const handler = routes[`${init?.method ?? "GET"} ${path}`];
      return handler ? handler(init) : json(404, { error: "not found" });
    }),
  );
});

afterEach(() => {
  vi.unstubAllGlobals();
});

function renderPanel(language: "en" | "nl" = "en") {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <I18nProvider language={language}>
        <EventsContext.Provider value={subscribe}>
          <MemoryRouter>
            <DialogsProvider>
              <ConversionsPanel />
            </DialogsProvider>
          </MemoryRouter>
        </EventsContext.Provider>
      </I18nProvider>
    </QueryClientProvider>,
  );
}

const row = (id: string) => screen.getByTestId(`queued-${id}`);

describe("ConversionsPanel", () => {
  it("shows a fix-it job as one, with its module", async () => {
    const fixit: Conversion = {
      ...queuedQuick,
      id: "cnv_000000000005",
      kind: "fixit",
      title: "The Sunken Shrine",
      step: "fixing",
      thorough: false,
      target: { module_id: "mod_1" },
    };
    queue = { paused: false, jobs: [running, fixit] };
    renderPanel();
    await screen.findByTestId(`queued-${fixit.id}`);
    expect(within(row(fixit.id)).getByText("Fix-it comments")).toBeTruthy();
    expect(within(row(fixit.id)).getByRole("link", { name: "Open the module" }).getAttribute("href")).toBe("/modules/mod_1");
  });

  it("lists the running, queued and paused conversions in order, with their status, step and cost", async () => {
    renderPanel();
    const list = await screen.findByRole("list", { name: "The conversion queue" });
    const items = within(list).getAllByRole("listitem");
    expect(items.map((item) => item.dataset.status)).toEqual(["running", "queued", "queued", "paused"]);
    expect(items[0].textContent).toContain("Saltmarsh");
    expect(items[0].textContent).toContain("Step 5 of 10 · Cleaning the texts against the pages");
    expect(items[0].textContent).toContain("12 of 34 batches of texts");
    expect(items[0].textContent).toContain("Cost so far: $18.40");
    expect(items[1].textContent).toContain("Number 1 in the queue");
    expect(items[1].textContent).toContain("Quick");
    expect(items[2].textContent).toContain("Number 2 in the queue");
    expect(items[3].textContent).toContain("You paused it.");
    expect(screen.getByText("The queue runs: the next conversion starts when the running one ends.")).toBeTruthy();
  });

  it("offers Pause on a running thorough conversion only, and Resume on a paused one", async () => {
    let pausedIt = false;
    let resumedIt = false;
    routes[`POST /api/conversions/${running.id}/pause`] = () => {
      pausedIt = true;
      return json(200, { ...running, status: "paused" });
    };
    routes[`POST /api/conversions/${paused.id}/resume`] = () => {
      resumedIt = true;
      return json(202, { ...paused, status: "queued" });
    };
    renderPanel();
    await screen.findByRole("list", { name: "The conversion queue" });
    expect(within(row(queuedQuick.id)).queryByRole("button", { name: "Pause" })).toBeNull();
    expect(within(row(queuedThorough.id)).queryByRole("button", { name: "Pause" })).toBeNull();
    expect(within(row(paused.id)).queryByRole("button", { name: "Pause" })).toBeNull();

    fireEvent.click(within(row(running.id)).getByRole("button", { name: "Pause" }));
    await waitFor(() => expect(pausedIt).toBe(true));
    fireEvent.click(within(row(paused.id)).getByRole("button", { name: "Resume" }));
    await waitFor(() => expect(resumedIt).toBe(true));
  });

  it("asks before it cancels", async () => {
    let cancelled = 0;
    routes[`POST /api/conversions/${queuedQuick.id}/cancel`] = () => {
      cancelled += 1;
      return json(200, { ...queuedQuick, status: "cancelled" });
    };
    renderPanel();
    await screen.findByRole("list", { name: "The conversion queue" });
    fireEvent.click(within(row(queuedQuick.id)).getByRole("button", { name: "Cancel" }));
    const dialog = await screen.findByRole("alertdialog");
    expect(dialog.textContent).toContain("It stops, and no module is made from it.");
    fireEvent.click(within(dialog).getByRole("button", { name: "Cancel it" }));
    await waitFor(() => expect(cancelled).toBe(1));
  });

  it("pauses and unpauses the queue", async () => {
    const sent: unknown[] = [];
    routes["PUT /api/conversions/queue"] = (init) => {
      const body = JSON.parse(String(init?.body));
      sent.push(body);
      queue = { ...queue, paused: body.paused };
      return json(200, queue);
    };
    renderPanel();
    await screen.findByRole("list", { name: "The conversion queue" });
    fireEvent.click(screen.getByRole("button", { name: "Pause the queue" }));
    expect(await screen.findByText(/The queue is paused: no waiting conversion starts/)).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Unpause the queue" }));
    await screen.findByRole("button", { name: "Pause the queue" });
    expect(sent).toEqual([{ paused: true }, { paused: false }]);
  });

  it("moves a running job's step from its events, and fetches the queue again when one changes", async () => {
    let fetched = 0;
    routes["GET /api/conversions/queue"] = () => {
      fetched += 1;
      return json(200, queue);
    };
    renderPanel();
    await screen.findByRole("list", { name: "The conversion queue" });
    emit("conversion", { id: running.id, status: "running", step: "tracing", done: 9, total: 26, steps: { index: 6, count: 10 }, cost_usd: 31.05 });
    await waitFor(() => expect(row(running.id).textContent).toContain("Step 6 of 10 · Tracing the maps from the book"));
    expect(row(running.id).textContent).toContain("Cost so far: $31.05");
    expect(fetched).toBe(1);

    queue = { ...queue, jobs: [{ ...queuedQuick, status: "running" }, queuedThorough, paused] };
    emit("conversion", { id: running.id, status: "done", step: "making", done: 0, total: 0, steps: { index: 10, count: 10 }, cost_usd: 40 });
    await waitFor(() => expect(row(queuedQuick.id).dataset.status).toBe("running"));
    emit("conversion-queue", { paused: true });
    await waitFor(() => expect(fetched).toBe(3));
  });

  it("says when nothing runs or waits, in Dutch too", async () => {
    queue = { paused: true, jobs: [] };
    renderPanel("nl");
    expect(await screen.findByText("Er loopt of wacht geen omzetting.")).toBeTruthy();
    expect(screen.getByRole("button", { name: "De wachtrij hervatten" })).toBeTruthy();
  });
});
