import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, within } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";
import { I18nProvider } from "../i18n";
import { json, stubFetch } from "../play/testing";
import MyTables from "./MyTables";

afterEach(() => {
  vi.unstubAllGlobals();
});

const crypt = {
  campaign_id: "cmp_00000000000a",
  name: "The Crypt",
  module_title: "The Crypt of Saint Vellis",
  role: "player",
  seat_id: "seat_00000000000a",
  last_played_at: new Date(Date.now() - 2 * 86400_000).toISOString(),
  session_number: 3,
  banner: true,
};
const inn = { ...crypt, campaign_id: "cmp_00000000000b", name: "The Wayside Inn", role: "observer", last_played_at: null, session_number: 1, banner: false };

function renderTables() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <I18nProvider language="en">
        <MemoryRouter initialEntries={["/tables"]}>
          <Routes>
            <Route path="/tables" element={<MyTables />} />
            <Route path="/play/:campaignId" element={<p>the play screen</p>} />
          </Routes>
        </MemoryRouter>
      </I18nProvider>
    </QueryClientProvider>,
  );
}

describe("MyTables", () => {
  it("grays a complete campaign, to open rather than play", async () => {
    const done = { ...crypt, campaign_id: "cmp_00000000000c", name: "Done", status: "complete" };
    stubFetch({ "GET /api/account/tables": () => json(200, [{ ...crypt, status: "in_progress" }, done]) });
    renderTables();
    const card = await screen.findByTestId("my-table-cmp_00000000000c");
    expect(card.className).toContain("complete");
    expect(card.textContent).toContain("Complete");
    const open = within(card).getByTestId("my-table-play-cmp_00000000000c");
    expect(open.textContent).toBe("Open");
    expect(open.className).not.toContain("primary");
    const live = screen.getByTestId("my-table-cmp_00000000000a");
    expect(live.className).not.toContain("complete");
    expect(within(live).getByTestId("my-table-play-cmp_00000000000a").textContent).toBe("Play");
  });

  it("lists the tables with Play", async () => {
    stubFetch({ "GET /api/account/tables": () => json(200, [crypt, inn]) });
    renderTables();
    expect(await screen.findByRole("heading", { level: 1, name: "My tables" })).toBeTruthy();
    const card = await screen.findByTestId("my-table-cmp_00000000000a");
    expect(within(card).getByRole("heading", { name: "The Crypt" })).toBeTruthy();
    expect(card.textContent).toContain("The Crypt of Saint Vellis");
    expect(card.textContent).toContain("Player");
    expect(card.textContent).toContain("Session 3, played 2 days ago");
    expect(card.querySelector("img")?.getAttribute("src")).toBe("/api/campaigns/cmp_00000000000a/banner?size=card");

    const other = screen.getByTestId("my-table-cmp_00000000000b");
    expect(other.querySelector("img")).toBeNull();
    expect(other.textContent).toContain("Observer");
    expect(other.textContent).toContain("Not played yet");

    fireEvent.click(within(card).getByTestId("my-table-play-cmp_00000000000a"));
    expect(await screen.findByText("the play screen")).toBeTruthy();
  });

  it("says when there are none", async () => {
    stubFetch({ "GET /api/account/tables": () => json(200, []) });
    renderTables();
    expect(await screen.findByText("You have no table yet: open an invite link.")).toBeTruthy();
  });
});
