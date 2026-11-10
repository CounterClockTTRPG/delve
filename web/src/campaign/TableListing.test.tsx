import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { Campaign } from "../api";
import { I18nProvider } from "../i18n";
import { CAMPAIGN, base, json, sent, stubFetch } from "../play/testing";
import TableListing from "./TableListing";

afterEach(() => vi.unstubAllGlobals());

const campaign: Campaign = {
  id: CAMPAIGN,
  name: "Tuesday",
  module_id: "mod_00000000000a",
  revision: 1,
  created_at: "2026-10-17T12:00:00Z",
  ruleset: "adnd2e",
  setting: null,
  status: "in_progress",
  visibility: "private",
  description: "",
  slots: null,
};

function renderListing(shown: Campaign = campaign) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <I18nProvider language="en">
        <TableListing campaign={shown} />
      </I18nProvider>
    </QueryClientProvider>,
  );
}

describe("TableListing (DEL-204)", () => {
  it("saves who can find the table, its places and its description for players", async () => {
    const fetchMock = stubFetch({ [`PUT ${base}/listing`]: () => json(200, { ...campaign, visibility: "public", slots: 4 }) });
    renderListing();
    const save = screen.getByTestId("listing-save") as HTMLButtonElement;
    expect(save.disabled, "nothing changed yet").toBe(true);
    fireEvent.click(screen.getByLabelText("Public"));
    fireEvent.change(screen.getByLabelText("Places for players"), { target: { value: "4" } });
    fireEvent.change(screen.getByLabelText("About this table, for players"), { target: { value: " Newcomers welcome. " } });
    fireEvent.click(save);
    await waitFor(() =>
      expect(sent(fetchMock, "PUT", `${base}/listing`)).toEqual([
        { visibility: "public", description: "Newcomers welcome.", slots: 4 },
      ]),
    );
  });

  it("says the DM never reads the description, and previews its Markdown", () => {
    stubFetch({});
    renderListing({ ...campaign, description: "**Be kind** to each other." });
    expect(screen.getByTestId("table-listing").textContent).toContain("the DM never does");
    fireEvent.click(screen.getByRole("button", { name: "Preview" }));
    expect(screen.getByTestId("listing-preview").querySelector("strong")?.textContent).toBe("Be kind");
  });

  it("takes empty places as no limit, and refuses places out of range", () => {
    stubFetch({});
    renderListing({ ...campaign, slots: 3 });
    const places = screen.getByLabelText("Places for players");
    fireEvent.change(places, { target: { value: "0" } });
    expect((screen.getByTestId("listing-save") as HTMLButtonElement).disabled).toBe(true);
    expect(screen.getByTestId("table-listing").textContent).toContain("A number from 1 to 20");
    fireEvent.change(places, { target: { value: "" } });
    expect((screen.getByTestId("listing-save") as HTMLButtonElement).disabled).toBe(false);
  });
});
