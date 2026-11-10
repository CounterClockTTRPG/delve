import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";
import { I18nProvider } from "../i18n";
import CampaignLog, { logMarkdown } from "./CampaignLog";
import { translate } from "../i18n";
import { CAMPAIGN, base, json, stubFetch } from "./testing";

afterEach(() => vi.unstubAllGlobals());

const pages = [
  { page: 1, session: null, title: "", part: 1, parts: 1, from: "2026-10-24T08:24:00Z", to: "2026-10-24T08:30:00Z", entries: 2 },
  { page: 2, session: 1, title: "The Road", part: 1, parts: 1, from: "2026-10-24T08:31:00Z", to: "2026-10-24T09:15:00Z", entries: 3 },
];
const entry = (id: string, kind: string, payload: Record<string, unknown>) => ({
  id,
  campaign_id: CAMPAIGN,
  beat_id: "beat_1",
  seq: 1,
  kind,
  payload,
  at: "2026-10-24T08:31:00Z",
  audience: null,
});
const page = (n: number) => ({
  campaign: { id: CAMPAIGN, name: "Puppets" },
  pages,
  page: n,
  names: { chr_1: "Garrek" },
  entries:
    n === 1
      ? [entry("e1", "player_act", { text: "Make us a party.", seat_id: "seat_1", name: "Ana", characters: [] }), entry("e2", "dm_text", { text: "Six take **shape**." })]
      : [
          entry("e3", "player_act", { text: "I swing.", seat_id: "seat_1", name: "Ana", characters: ["chr_1"] }),
          entry("e4", "tool", { dice: [{ who: "Garrek", side: null, what: "attack", detail: null, dice: "d20", faces: [17], total: 17 }] }),
          entry("e5", "say", { speaker: { id: "chr_2", name: "Prior Anselm", portrait: null }, mood: "sigh", text: "Thank the saint." }),
        ],
});

function show() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <I18nProvider language="en">
        <MemoryRouter initialEntries={[`/campaigns/${CAMPAIGN}/log`]}>
          <Routes>
            <Route path="/campaigns/:campaignId/log" element={<CampaignLog />} />
          </Routes>
        </MemoryRouter>
      </I18nProvider>
    </QueryClientProvider>,
  );
}

describe("CampaignLog", () => {
  it("browses the log a page at a time, by session, with the dice the players read (DEL-324)", async () => {
    stubFetch({
      [`GET ${base}/log?page=1&language=en`]: () => json(200, page(1)),
      [`GET ${base}/log?page=2&language=en`]: () => json(200, page(2)),
    });
    show();
    expect(await screen.findByRole("heading", { level: 1, name: "Puppets" })).toBeTruthy();
    expect(screen.getByRole("heading", { level: 2, name: "Before the first session" })).toBeTruthy();
    expect(screen.getByText("Make us a party.")).toBeTruthy();
    expect(screen.getByText("shape").tagName).toBe("STRONG");
    const contents = screen.getByRole("combobox", { name: "Page" }) as HTMLSelectElement;
    expect([...contents.options].map((o) => o.textContent?.split(" · ")[0])).toEqual(["1. Before the first session", "2. Session 1: The Road"]);

    fireEvent.click(screen.getAllByRole("button", { name: "Next page" })[0]);
    expect(await screen.findByRole("heading", { level: 2, name: "Session 1: The Road" })).toBeTruthy();
    expect(screen.getByText("Ana · Garrek")).toBeTruthy();
    expect(screen.getByText("Garrek, attack — d20: 17")).toBeTruthy();
    expect(screen.getByText("Prior Anselm")).toBeTruthy();
    fireEvent.click(screen.getByRole("checkbox", { name: "Dice" }));
    await waitFor(() => expect(screen.queryByText("Garrek, attack — d20: 17")).toBeNull());
  });

  it("says so when nothing has been played", async () => {
    stubFetch({ [`GET ${base}/log?page=1&language=en`]: () => json(200, { ...page(1), pages: [], page: 0, entries: [] }) });
    show();
    expect(await screen.findByText("Nothing has been played yet.")).toBeTruthy();
  });

  it("downloads the whole log as Markdown, as the page reads it (DEL-346)", async () => {
    stubFetch({
      [`GET ${base}/log?page=1&language=en`]: () => json(200, page(1)),
      [`GET ${base}/log?page=2&language=en`]: () => json(200, page(2)),
    });
    const saved: Blob[] = [];
    vi.stubGlobal("URL", { ...URL, createObjectURL: (b: Blob) => (saved.push(b), "blob:log"), revokeObjectURL: () => {} });
    show();
    fireEvent.click(await screen.findByRole("button", { name: "Download Markdown" }));
    await waitFor(() => expect(saved).toHaveLength(1));
    const text = await saved[0].text();
    expect(text.startsWith("# Puppets\n")).toBe(true);
    expect(text).toContain("## Before the first session");
    expect(text).toContain("> **Ana:** Make us a party.");
    expect(text).toContain("Six take **shape**.");
    expect(text).toContain("## Session 1: The Road");
    expect(text).toContain("> **Ana · Garrek:** I swing.");
    expect(text).toContain("- *Garrek, attack — d20: 17*");
    expect(text).toContain("**Prior Anselm:** Thank the saint.");
  });

  it("leaves the dice out when they are off", () => {
    const md = logMarkdown("Puppets", [page(2) as never], false, (key: string, vars?: Record<string, string>) => translate("en", key, vars), "en");
    expect(md).not.toContain("d20");
  });
});
