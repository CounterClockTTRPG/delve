import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { CampaignDetail, Conversion, History } from "../api";
import { DialogsProvider } from "../components/dialogs";
import { I18nProvider } from "../i18n";
import { CAMPAIGN, base, json, sent, stubFetch, type Handler } from "../play/testing";
import HistorySection from "./HistorySection";

afterEach(() => {
  vi.unstubAllGlobals();
});

const campaign: CampaignDetail = {
  id: CAMPAIGN,
  name: "Into Barrowmaze",
  module_id: "mod_00000000000b",
  revision: 1,
  created_at: "2026-10-22T12:00:00Z",
  ruleset: "adnd2e",
  setting: null,
  status: "in_progress",
  module_title: "Barrowmaze",
  maps: [],
  upgrade_available: false,
  carried_from: { id: "cmp_00000000000o", name: "The Crypt" },
  carried_to: [],
};

function history(overrides: Partial<History> = {}): History {
  return {
    campaign_id: CAMPAIGN,
    dm_md: "## The party\n\nAsh and Birch.\n\n## Loose ends\n\nThe Prior's key.",
    table_md: "## The party\n\nAsh and **Birch**.",
    status: "done",
    error: null,
    edited: false,
    conversion_id: "cnv_00000000000h",
    cost_usd: 0.12,
    created_at: "2026-10-22T12:00:00Z",
    updated_at: "2026-10-22T12:00:00Z",
    ...overrides,
  };
}

const job: Conversion = {
  id: "cnv_00000000000h",
  kind: "history",
  title: "History: The Crypt",
  mode: "ready",
  status: "running",
  step: "writing",
  done: 1,
  total: 2,
  steps: { index: 0, count: 0 },
  module_id: null,
  warnings: [],
  error: null,
  created_at: "2026-10-22T12:00:00Z",
  updated_at: "2026-10-22T12:00:00Z",
  target: { campaign_id: CAMPAIGN },
};

function routes(stored: History | null, extra: Record<string, Handler> = {}): Record<string, Handler> {
  return {
    [`GET ${base}/history`]: () => (stored ? json(200, stored) : json(200, null)),
    "GET /api/conversions": () => json(200, stored?.status === "writing" ? [job] : []),
    [`PUT ${base}/history`]: (init) => json(200, { ...stored, ...JSON.parse(String(init?.body)), edited: true, status: "done" }),
    [`POST ${base}/history/write`]: () => json(202, history({ status: "writing", dm_md: "", table_md: "" })),
    ...extra,
  };
}

function renderSection(shown: CampaignDetail = campaign) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <I18nProvider language="en">
        <DialogsProvider>
          <MemoryRouter>
            <HistorySection campaign={shown} />
          </MemoryRouter>
        </DialogsProvider>
      </I18nProvider>
    </QueryClientProvider>,
  );
}

const section = () => screen.getByTestId("history-section");

describe("HistorySection", () => {
  it("lets the host toggle between the DM's text and the table's", async () => {
    stubFetch(routes(history()));
    renderSection();
    expect(await screen.findByText("The Prior's key.")).toBeTruthy();
    expect(section().querySelector("h1, h2")!.id).toBe("history");
    fireEvent.click(screen.getByRole("tab", { name: "The table's" }));
    expect(await screen.findByText("Birch")).toBeTruthy();
    expect(screen.getByText("Birch").tagName).toBe("STRONG");
    expect(screen.queryByText("The Prior's key.")).toBeNull();
    fireEvent.click(screen.getByRole("tab", { name: "The DM's" }));
    expect(await screen.findByText("The Prior's key.")).toBeTruthy();
  });

  it("shows the job's progress while the history is written", async () => {
    stubFetch(routes(history({ status: "writing", dm_md: "", table_md: "" })));
    renderSection();
    expect(await screen.findByText("Being written")).toBeTruthy();
    expect(await screen.findByText("1 of 2 texts")).toBeTruthy();
    expect(within(section()).getByRole("progressbar")).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Edit" })).toBeNull();
  });

  it("Edit saves both texts", async () => {
    const fetchMock = stubFetch(routes(history()));
    renderSection();
    fireEvent.click(await screen.findByRole("button", { name: "Edit" }));
    fireEvent.change(screen.getByLabelText("The DM's history"), { target: { value: "## The party\n\nAsh alone." } });
    fireEvent.change(screen.getByLabelText("The table's history"), { target: { value: "## The party\n\nAsh." } });
    fireEvent.click(screen.getByRole("button", { name: "Save" }));
    await waitFor(() =>
      expect(sent(fetchMock, "PUT", `${base}/history`)).toEqual([
        { dm_md: "## The party\n\nAsh alone.", table_md: "## The party\n\nAsh." },
      ]),
    );
    expect(await screen.findByText("Edited")).toBeTruthy();
  });

  it("asks before Write again replaces an edited history, and sends overwrite", async () => {
    const fetchMock = stubFetch(routes(history({ edited: true })));
    renderSection();
    fireEvent.click(await screen.findByRole("button", { name: "Write again" }));
    const dialog = await screen.findByRole("alertdialog");
    expect(dialog.textContent).toContain("Your edit of the history will be replaced.");
    fireEvent.click(within(dialog).getByRole("button", { name: "Cancel" }));
    await waitFor(() => expect(screen.queryByRole("alertdialog")).toBeNull());
    expect(sent(fetchMock, "POST", `${base}/history/write`)).toEqual([]);

    fireEvent.click(screen.getByRole("button", { name: "Write again" }));
    fireEvent.click(within(await screen.findByRole("alertdialog")).getByRole("button", { name: "Write again" }));
    await waitFor(() => expect(sent(fetchMock, "POST", `${base}/history/write`)).toEqual([{ overwrite: true }]));
  });

  it("writes an unedited history again without asking", async () => {
    const fetchMock = stubFetch(routes(history()));
    renderSection();
    fireEvent.click(await screen.findByRole("button", { name: "Write again" }));
    await waitFor(() => expect(sent(fetchMock, "POST", `${base}/history/write`)).toEqual([{ overwrite: false }]));
    expect(screen.queryByRole("alertdialog")).toBeNull();
  });

  it("shows a failed history's error, with Write again", async () => {
    stubFetch(routes(history({ status: "failed", dm_md: "", table_md: "", error: "A conversion is running: write the history again when it ends." })));
    renderSection();
    expect((await screen.findByRole("alert")).textContent).toContain("A conversion is running");
    expect(screen.getByRole("button", { name: "Write again" })).toBeTruthy();
  });

  it("links to the campaign it was carried on from and those it was carried on to", async () => {
    stubFetch(routes(history()));
    renderSection({
      ...campaign,
      carried_to: [
        { id: "cmp_00000000000x", name: "Barrowmaze I" },
        { id: "cmp_00000000000y", name: "Barrowmaze II" },
      ],
    });
    const from = await screen.findByRole("link", { name: "The Crypt" });
    expect(from.getAttribute("href")).toBe("/campaigns/cmp_00000000000o");
    expect(from.closest("p")!.textContent).toContain("Carried on from");
    const to = screen.getByRole("link", { name: "Barrowmaze II" });
    expect(to.getAttribute("href")).toBe("/campaigns/cmp_00000000000y");
    expect(to.closest("p")!.textContent).toContain("Carried on to");
    expect(screen.getByRole("link", { name: "Barrowmaze I" })).toBeTruthy();
  });

  it("shows only the links on a campaign with no history, and no Write again", async () => {
    stubFetch(routes(null));
    renderSection({ ...campaign, carried_from: null, carried_to: [{ id: "cmp_00000000000x", name: "Barrowmaze" }] });
    expect(await screen.findByRole("link", { name: "Barrowmaze" })).toBeTruthy();
    await waitFor(() => expect(screen.queryByText("Loading the history…")).toBeNull());
    expect(screen.queryByRole("button", { name: "Write again" })).toBeNull();
  });
});
