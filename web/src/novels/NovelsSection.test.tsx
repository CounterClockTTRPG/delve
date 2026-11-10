import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";
import { EventsContext, type Conversion, type Subscribe } from "../api";
import { DialogsProvider } from "../components/dialogs";
import { I18nProvider } from "../i18n";
import { CAMPAIGN, base, json, sent, stubFetch, type Handler } from "../play/testing";
import type { ListedNovel as Listed } from "./api";
import NovelsSection from "./NovelsSection";

afterEach(() => {
  vi.unstubAllGlobals();
});

const OWNER = { principal: { id: "owner", roles: ["owner"] }, seat: null };
const ORGANISER = {
  principal: { id: "seat", roles: [] },
  seat: { id: "seat_1", campaign_id: CAMPAIGN, campaign_name: "Tuesday", name: "Ann", language: "en", role: "host", organiser: true },
};

function novel(id: string, overrides: Partial<Listed> = {}): Listed {
  return {
    id,
    title: "The Bones of Saint Vellis",
    campaign_id: CAMPAIGN,
    module_id: null,
    revision: null,
    sessions: null,
    length: "short-story",
    tone: "grimdark",
    custom_tone: "",
    language: "en",
    instructions: "Tell it from Ned's point of view, and leave out every fight on the second level of the crypt.",
    chapters: [
      { title: "Down the Stairs", summary: "They go down.", written: true },
      { title: "The Last Monk", summary: "Ansel waits.", written: true },
      { title: "Fire", summary: "The crypt burns.", written: false },
    ],
    status: "done",
    error: null,
    conversion_id: "cnv_000000000001",
    cost_usd: 0.42,
    created_at: "2026-10-20T10:00:00Z",
    updated_at: "2026-10-20T10:30:00Z",
    ...overrides,
  };
}

const job: Conversion = {
  id: "cnv_000000000009",
  kind: "novel",
  title: "Novel: Tuesday",
  mode: "ready",
  status: "running",
  step: "writing",
  done: 2,
  total: 5,
  steps: { index: 3, count: 3 },
  module_id: null,
  warnings: [],
  error: null,
  created_at: "2026-10-20T10:00:00Z",
  updated_at: "2026-10-20T10:01:00Z",
  target: { novel_id: "nov_000000000009" },
};

function routes(over: Record<string, Handler> = {}, novels: Listed[] = [novel("nov_000000000001")], conversions: Conversion[] = []) {
  return {
    "GET /api/me": () => json(200, OWNER),
    [`GET /api/novels?campaign_id=${CAMPAIGN}`]: () => json(200, novels),
    "GET /api/conversions": () => json(200, conversions),
    [`GET ${base}/play/options`]: () => json(200, { tone: "horror", detail: 1 }),
    ...over,
  };
}

const subscribe: Subscribe = () => () => {};

function renderSection(kind: "campaign" | "module" = "campaign", id = CAMPAIGN) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <I18nProvider language="en">
        <DialogsProvider>
          <EventsContext.Provider value={subscribe}>
            <MemoryRouter>
              <NovelsSection source={{ kind, id }} />
            </MemoryRouter>
          </EventsContext.Provider>
        </DialogsProvider>
      </I18nProvider>
    </QueryClientProvider>,
  );
}

describe("NovelsSection", () => {
  it("shows a seat nothing, an organiser seat included, and asks for no novel", async () => {
    const fetchMock = stubFetch(routes({ "GET /api/me": () => json(200, ORGANISER) }));
    renderSection();
    await waitFor(() => expect(fetchMock).toHaveBeenCalledWith("/api/me", expect.anything()));
    await new Promise((r) => setTimeout(r, 20));
    expect(screen.queryByRole("heading", { name: "Novels" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Novelize" })).toBeNull();
    expect(fetchMock.mock.calls.some(([path]) => String(path).startsWith("/api/novels"))).toBe(false);
  });

  it("shows an organiser account nothing: only the owner has novels", async () => {
    const account = { id: "acc_1", username: "bo", display_name: "Bo", language: "en", organiser: true, owner: false };
    const fetchMock = stubFetch(
      routes({ "GET /api/me": () => json(200, { principal: { id: "account:acc_1", roles: ["organiser"] }, account, seat: null }) }),
    );
    renderSection();
    await waitFor(() => expect(fetchMock).toHaveBeenCalledWith("/api/me", expect.anything()));
    await new Promise((r) => setTimeout(r, 20));
    expect(screen.queryByRole("heading", { name: "Novels" })).toBeNull();
    expect(fetchMock.mock.calls.some(([path]) => String(path).startsWith("/api/novels"))).toBe(false);
  });

  it("shows an owner account its novels", async () => {
    const account = { id: "acc_1", username: "olga", display_name: "Olga", language: "en", organiser: true, owner: true };
    stubFetch(routes({ "GET /api/me": () => json(200, { principal: { id: "account:acc_1", roles: ["organiser"] }, account, seat: null }) }));
    renderSection();
    expect(await screen.findByRole("link", { name: "The Bones of Saint Vellis" })).toBeTruthy();
  });

  it("lists each novel's length, tone, the start of its instructions, its date and its status", async () => {
    stubFetch(routes());
    renderSection();
    const row = (await screen.findByRole("link", { name: "The Bones of Saint Vellis" })).closest("li")!;
    expect(row.querySelector("a")!.getAttribute("href")).toBe("/novels/nov_000000000001");
    const text = row.textContent!;
    expect(text).toContain("Short story");
    expect(text).toContain("Grimdark");
    expect(text).toContain("Tell it from Ned's point of view, and leave out every fight…");
    expect(text).not.toContain("second level");
    expect(text).toContain(new Date("2026-10-20T10:00:00Z").toLocaleDateString());
    expect(text).toContain("Done");
  });

  it("defaults the form's tone to the campaign's", async () => {
    stubFetch(routes());
    renderSection();
    await waitFor(() => expect((screen.getByLabelText("Tone") as HTMLSelectElement).value).toBe("horror"));
  });

  it("shows a novel being written with its job's progress, and cancels it", async () => {
    const writing = novel("nov_000000000009", { status: "writing", conversion_id: job.id });
    const fetchMock = stubFetch(
      routes(
        { "POST /api/novels/nov_000000000009/cancel": () => json(200, { ...writing, status: "cancelled" }) },
        [writing],
        [job],
      ),
    );
    renderSection();
    const row = (await screen.findByRole("link", { name: "The Bones of Saint Vellis" })).closest("li")!;
    const bar = (await within(row).findByRole("progressbar")) as HTMLProgressElement;
    expect(bar.value).toBe(2);
    expect(bar.max).toBe(5);
    expect(row.textContent).toContain("Being written");
    expect(row.textContent).toContain("2 of 5 chapters");
    // The form says a job is running, and waits.
    expect((screen.getByRole("button", { name: "Novelize" }) as HTMLButtonElement).disabled).toBe(true);
    fireEvent.click(within(row).getByRole("button", { name: "Cancel" }));
    await waitFor(() => expect(sent(fetchMock, "POST", "/api/novels/nov_000000000009/cancel")).toHaveLength(1));
  });

  it("offers Continue on a failed novel, with its reason", async () => {
    const failed = novel("nov_000000000002", { status: "failed", error: "Delve stopped while writing." });
    const fetchMock = stubFetch(
      routes(
        { "POST /api/novels/nov_000000000002/continue": () => json(202, { ...failed, status: "writing", error: null }) },
        [failed],
      ),
    );
    renderSection();
    const row = (await screen.findByRole("link", { name: "The Bones of Saint Vellis" })).closest("li")!;
    expect(row.textContent).toContain("Failed");
    expect(row.textContent).toContain("Delve stopped while writing.");
    expect(row.textContent).toContain("2 of 3 chapters");
    fireEvent.click(within(row).getByRole("button", { name: "Continue" }));
    await waitFor(() => expect(sent(fetchMock, "POST", "/api/novels/nov_000000000002/continue")).toHaveLength(1));
  });

  it("offers no Continue on a finished novel", async () => {
    stubFetch(routes());
    renderSection();
    const row = (await screen.findByRole("link", { name: "The Bones of Saint Vellis" })).closest("li")!;
    expect(within(row).queryByRole("button", { name: "Continue" })).toBeNull();
  });

  it("Write again fills the form with the novel's choices", async () => {
    const again = novel("nov_000000000003", { length: "novella", tone: "custom", custom_tone: "Like a ballad", language: "nl", instructions: "Ned tells it.", sessions: [2, 3] });
    stubFetch(routes({}, [again]));
    renderSection();
    const row = (await screen.findByRole("link", { name: "The Bones of Saint Vellis" })).closest("li")!;
    await waitFor(() => expect((screen.getByLabelText("Tone") as HTMLSelectElement).value).toBe("horror"));
    fireEvent.click(within(row).getByRole("button", { name: "Write again" }));
    await waitFor(() => expect((screen.getByLabelText("Novella") as HTMLInputElement).checked).toBe(true));
    expect((screen.getByLabelText("Tone") as HTMLSelectElement).value).toBe("custom");
    expect((screen.getByLabelText("Your tone") as HTMLInputElement).value).toBe("Like a ballad");
    expect((screen.getByLabelText("Language") as HTMLSelectElement).value).toBe("nl");
    expect((screen.getByLabelText("Instructions") as HTMLTextAreaElement).value).toBe("Ned tells it.");
    expect((screen.getByLabelText("Sessions from") as HTMLInputElement).checked).toBe(true);
    expect((screen.getByLabelText("First session") as HTMLInputElement).value).toBe("2");
    expect((screen.getByLabelText("Last session") as HTMLInputElement).value).toBe("3");
  });

  it("deletes a novel after asking with Delve's own dialog", async () => {
    let removed = false;
    const fetchMock = stubFetch(
      routes({
        "DELETE /api/novels/nov_000000000001": () => {
          removed = true;
          return new Response(null, { status: 204 });
        },
      }),
    );
    const confirm = vi.spyOn(window, "confirm");
    renderSection();
    const row = (await screen.findByRole("link", { name: "The Bones of Saint Vellis" })).closest("li")!;
    fireEvent.click(within(row).getByRole("button", { name: "Delete" }));
    const dialog = await screen.findByRole("alertdialog", { name: "Delete the novel The Bones of Saint Vellis?" });
    expect(removed).toBe(false);
    fireEvent.click([...dialog.querySelectorAll("button")].find((b) => b.textContent === "Delete")!);
    await waitFor(() => expect(removed).toBe(true));
    expect(confirm).not.toHaveBeenCalled();
    expect(fetchMock.mock.calls.filter(([path]) => path === `/api/novels?campaign_id=${CAMPAIGN}`).length).toBeGreaterThan(1);
  });

  it("lists a module's novels from its own route", async () => {
    const MODULE = "mod_00000000000a";
    stubFetch({
      ...routes(),
      [`GET /api/novels?module_id=${MODULE}`]: () => json(200, [novel("nov_000000000004", { campaign_id: null, module_id: MODULE, title: "A Run Through the Crypt" })]),
    });
    renderSection("module", MODULE);
    expect(await screen.findByRole("link", { name: "A Run Through the Crypt" })).toBeTruthy();
    expect((screen.getByLabelText("Tone") as HTMLSelectElement).value).toBe("classic");
  });
});
