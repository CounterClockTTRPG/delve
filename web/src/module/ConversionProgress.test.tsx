import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes, useLocation } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { EventsContext, type Conversion, type Subscribe } from "../api";
import { DialogsProvider } from "../components/dialogs";
import { I18nProvider } from "../i18n";
import ConversionProgress from "./ConversionProgress";

const running: Conversion = {
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
};

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
  routes = {};
  fetchMock = vi.fn(async (path: string, init?: RequestInit) => {
    const handler = routes[`${init?.method ?? "GET"} ${path}`];
    return handler ? handler(init) : json(404, { error: "not found" });
  });
  vi.stubGlobal("fetch", fetchMock);
});

afterEach(() => {
  vi.unstubAllGlobals();
});

function ModulePage() {
  const state = useLocation().state as { warnings?: { message: string }[] } | null;
  return (
    <>
      <h1>Module page</h1>
      <ul>{state?.warnings?.map((w) => <li key={w.message}>{w.message}</li>)}</ul>
    </>
  );
}

function renderProgress(conversion: Conversion) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <I18nProvider language="en">
        <EventsContext.Provider value={subscribe}>
          <DialogsProvider>
            <MemoryRouter initialEntries={["/modules/new"]}>
              <Routes>
                <Route path="/modules/new" element={<ConversionProgress conversion={conversion} />} />
                <Route path="/modules/:moduleId" element={<ModulePage />} />
              </Routes>
            </MemoryRouter>
          </DialogsProvider>
        </EventsContext.Provider>
      </I18nProvider>
    </QueryClientProvider>,
  );
}

const thorough: Conversion = {
  ...running,
  title: "Saltmarsh",
  thorough: true,
  step: "cleaning",
  done: 12,
  total: 34,
  steps: { index: 5, count: 10 },
  cost_usd: 18.4,
  paused: null,
};

describe("ConversionProgress, thorough", () => {
  it("shows the stage, its pieces done out of pieces and the cost so far", () => {
    renderProgress(thorough);
    expect(screen.getByText("Step 5 of 10 · Cleaning the texts against the pages")).toBeTruthy();
    expect(screen.getByText("12 of 34 batches of texts")).toBeTruthy();
    expect(screen.getByText("Cost so far: $18.40")).toBeTruthy();
    emit("conversion", { id: thorough.id, status: "running", step: "tracing", done: 9, total: 26, steps: { index: 6, count: 10 }, cost_usd: 31.05 });
    expect(screen.getByText("Step 6 of 10 · Tracing the maps from the book")).toBeTruthy();
    expect(screen.getByText("9 of 26 maps")).toBeTruthy();
    expect(screen.getByText("Cost so far: $31.05")).toBeTruthy();
  });

  it("a paused one says why, and Resume runs it again", async () => {
    const paused: Conversion = { ...thorough, status: "paused", paused: { reason: "Delve stopped", resets_at: null } };
    let resumed = false;
    routes[`POST /api/conversions/${thorough.id}/resume`] = () => {
      resumed = true;
      return json(202, { ...thorough, status: "running" });
    };
    renderProgress(paused);
    const progress = screen.getByTestId("conversion-progress");
    expect(progress.dataset.status).toBe("paused");
    expect(screen.getByText("Paused · Step 5 of 10 · Cleaning the texts against the pages")).toBeTruthy();
    expect(screen.getByText(/Delve stopped while it ran\. Resume it to go on where it was/)).toBeTruthy();
    expect(screen.getByText("Cost so far: $18.40")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Resume" }));
    await waitFor(() => expect(resumed).toBe(true));
    expect(await screen.findByText("Step 5 of 10 · Cleaning the texts against the pages")).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Resume" })).toBeNull();
    expect(screen.getByRole("button", { name: "Cancel" })).toBeTruthy();
  });

  it("a pause at the usage limit says when it resumes by itself; one on an error says the error", () => {
    const limited: Conversion = {
      ...thorough,
      status: "paused",
      paused: { reason: "The Claude usage limit was reached.", resets_at: "3am (Europe/Brussels)" },
    };
    const { unmount } = renderProgress(limited);
    expect(screen.getByText("The Claude usage limit was reached. It resumes by itself after 3am (Europe/Brussels), or resume it now.")).toBeTruthy();
    unmount();
    renderProgress({ ...thorough, status: "paused", error: "list index out of range", paused: { reason: "list index out of range", resets_at: null } });
    expect(screen.getByText("It paused on an error: list index out of range Its work is kept: resume it once that is fixed.")).toBeTruthy();
  });

  it("cancelling asks first, as the work done is deleted", async () => {
    let cancelled = false;
    routes[`POST /api/conversions/${thorough.id}/cancel`] = () => {
      cancelled = true;
      return json(200, { ...thorough, status: "cancelled" });
    };
    renderProgress(thorough);
    fireEvent.click(screen.getByRole("button", { name: "Cancel" }));
    const dialog = await screen.findByRole("alertdialog");
    expect(dialog.textContent).toContain("The work done so far is deleted, and no module is made.");
    fireEvent.click(screen.getByRole("button", { name: "Cancel and delete the work" }));
    await waitFor(() => expect(cancelled).toBe(true));
    expect(await screen.findByText("Cancelled. No module was made.")).toBeTruthy();
  });
});

describe("ConversionProgress, queued", () => {
  it("a queued one says it waits its turn, and runs once an event says it started", async () => {
    const queued: Conversion = { ...thorough, status: "queued", step: "reading", done: 0, total: 0, steps: { index: 0, count: 10 }, cost_usd: null };
    renderProgress(queued);
    expect(screen.getByTestId("conversion-progress").dataset.status).toBe("queued");
    expect(screen.getByText("Waiting in the queue: it starts by itself when its turn comes.")).toBeTruthy();
    expect(screen.getByRole("button", { name: "Cancel" })).toBeTruthy();
    emit("conversion", { id: queued.id, status: "running", step: "reading", done: 2, total: 9, steps: { index: 1, count: 10 }, cost_usd: null });
    expect(await screen.findByText("Step 1 of 10 · Reading the PDF")).toBeTruthy();
    expect(screen.getByText("2 of 9 pages")).toBeTruthy();
    expect(screen.queryByText(/Waiting in the queue/)).toBeNull();
  });

  it("a resume that is queued says so", async () => {
    const paused: Conversion = { ...thorough, status: "paused", paused: { reason: "paused by the organiser", resets_at: null } };
    routes[`POST /api/conversions/${thorough.id}/resume`] = () => json(202, { ...paused, status: "queued", paused: null });
    renderProgress(paused);
    expect(screen.getByText(/You paused it\. Resume it to go on where it was/)).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Resume" }));
    expect(await screen.findByText("Waiting in the queue: it starts by itself when its turn comes.")).toBeTruthy();
  });
});

describe("ConversionProgress", () => {
  it("shows the step and the pages done out of pages from the conversion events", () => {
    renderProgress(running);
    expect(screen.getByText("Step 1 of 4 · Reading the PDF")).toBeTruthy();

    emit("conversion", { id: running.id, status: "running", step: "reading", done: 12, total: 38, steps: { index: 1, count: 4 } });
    expect(screen.getByText("12 of 38 pages")).toBeTruthy();

    const converting = { id: running.id, status: "running", step: "converting", done: 12, total: 300, steps: { index: 2, count: 4 } };
    emit("conversion", converting);
    expect(screen.getByText("Step 2 of 4 · Converting the text")).toBeTruthy();
    expect(screen.getByText("12 of 300 pages")).toBeTruthy();
    const bar = screen.getByRole("progressbar", { name: "Converting the text" }) as HTMLProgressElement;
    expect(bar.value).toBe(12);
    expect(bar.max).toBe(300);

    // Another conversion's events are not this one's.
    emit("conversion", { id: "cnv_000000000002", status: "running", step: "maps", done: 1, total: 2, steps: { index: 4, count: 4 } });
    expect(screen.getByText("12 of 300 pages")).toBeTruthy();
  });

  it("with no count yet, the bar is indeterminate, and the time since the start counts up every second", () => {
    vi.useFakeTimers({ toFake: ["Date", "setInterval", "clearInterval"] });
    try {
      vi.setSystemTime(new Date("2026-10-18T10:03:25Z"));
      renderProgress(running);
      const bar = screen.getByRole("progressbar", { name: "Reading the PDF" });
      expect(bar.hasAttribute("value")).toBe(false);
      expect(screen.getByText("3:25 elapsed")).toBeTruthy();
      act(() => vi.advanceTimersByTime(2000));
      expect(screen.getByText("3:27 elapsed")).toBeTruthy();
    } finally {
      vi.useRealTimers();
    }
  });

  it("Cancel posts to the conversion's cancel route as JSON", async () => {
    let posted: RequestInit | undefined;
    routes[`POST /api/conversions/${running.id}/cancel`] = (init) => {
      posted = init;
      return json(200, { ...running, status: "cancelled" });
    };
    routes[`GET /api/conversions/${running.id}`] = () => json(200, { ...running, status: "cancelled" });
    renderProgress(running);
    fireEvent.click(screen.getByRole("button", { name: "Cancel" }));
    await waitFor(() => expect(posted).toBeTruthy());
    expect(new Headers(posted?.headers).get("Content-Type")).toBe("application/json");
    expect(posted?.body).toBe("{}");
    expect(await screen.findByText("Cancelled. No module was made.")).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Cancel" })).toBeNull();
  });

  it("a finished conversion links to its module, which opens with the conversion's warnings", async () => {
    const done: Conversion = {
      ...running,
      status: "done",
      step: "maps",
      done: 1,
      total: 1,
      module_id: "mod_aaaaaaaaaaaa",
      warnings: [{ code: "map-sketched", message: "Drawn from the room key; compare it with page 4.", ref: "map:barrow" }],
    };
    routes[`GET /api/conversions/${running.id}`] = () => json(200, done);
    renderProgress(running);

    emit("conversion", { id: running.id, status: "done", step: "maps", done: 1, total: 1, steps: { index: 4, count: 4 } });
    const link = await screen.findByRole("link", { name: "Open the module" });
    expect(link.getAttribute("href")).toBe("/modules/mod_aaaaaaaaaaaa");
    expect(screen.getByText("Done, with 1 warning.")).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Cancel" })).toBeNull();

    fireEvent.click(link);
    expect(await screen.findByRole("heading", { name: "Module page" })).toBeTruthy();
    expect(screen.getByText("Drawn from the room key; compare it with page 4.")).toBeTruthy();
  });

  it("a failed conversion shows its reason", async () => {
    const failed = { ...running, status: "failed", error: "The PDF is encrypted: it needs a password to open." };
    routes[`GET /api/conversions/${running.id}`] = () => json(200, failed);
    renderProgress(running);
    emit("conversion", { id: running.id, status: "failed", step: "reading", done: 0, total: 0, steps: { index: 1, count: 4 } });
    expect((await screen.findByRole("alert")).textContent).toBe(
      "The conversion failed: The PDF is encrypted: it needs a password to open.",
    );
  });

  it("its tag says what it makes, never a status", () => {
    renderProgress(running);
    expect(screen.getByText("Makes a draft").className).toBe("tag");
    expect(screen.queryByText("A draft to work on")).toBeNull();
  });

  it("names and counts a world map's grid step", () => {
    renderProgress({ ...running, kind: "worldmap", title: "The Flanaess", mode: "ready", step: "tiles", steps: { index: 1, count: 6 } });
    expect(screen.getByText("Step 1 of 6 · Cutting the picture into tiles")).toBeTruthy();
    emit("conversion", { id: running.id, status: "running", step: "grid", done: 2, total: 5, steps: { index: 2, count: 6 } });
    expect(screen.getByText("Step 2 of 6 · Finding the grid")).toBeTruthy();
    expect(screen.getByText("2 of 5")).toBeTruthy();
    expect(screen.queryByText("Ready")).toBeNull();
  });
});
