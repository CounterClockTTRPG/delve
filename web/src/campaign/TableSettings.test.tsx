import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { Campaign } from "../api";
import { I18nProvider } from "../i18n";
import { CAMPAIGN, base, json, sent, stubFetch } from "../play/testing";
import { PHONE_QUERY } from "../play/usePhone";
import TableSettings from "./TableSettings";

afterEach(() => {
  vi.unstubAllGlobals();
});

const campaign: Campaign = {
  id: CAMPAIGN,
  name: "Tuesday",
  module_id: "mod_00000000000a",
  revision: 1,
  created_at: "2026-10-17T12:00:00Z",
  ruleset: "adnd2e",
  setting: null,
  status: "in_progress",
  voice: "allowed",
  initiative: "combatant",
};

function renderSettings(shown: Campaign = campaign, language: "en" | "nl" = "en") {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <I18nProvider language={language}>
        <TableSettings campaign={shown} />
      </I18nProvider>
    </QueryClientProvider>,
  );
}

const answering = (changes: Partial<Campaign>[]) => (init?: RequestInit) => {
  const body = JSON.parse(String(init?.body)) as Partial<Campaign>;
  changes.push(body);
  return json(200, { ...campaign, ...changes.reduce((all, change) => ({ ...all, ...change }), {}) });
};

describe("TableSettings", () => {
  it("sets voice off, saying it disconnects everyone in voice", async () => {
    const changes: Partial<Campaign>[] = [];
    const fetchMock = stubFetch({ [`PUT ${base}/table-settings`]: answering(changes) });
    renderSettings();
    const voice = screen.getByRole("radiogroup", { name: "Voice" });
    expect((within(voice).getByRole("radio", { name: "Allowed" }) as HTMLInputElement).checked).toBe(true);
    expect(screen.getByText("Switching it off disconnects everyone in voice.")).toBeTruthy();

    fireEvent.click(within(voice).getByRole("radio", { name: "Off" }));
    await waitFor(() => expect(sent(fetchMock, "PUT", `${base}/table-settings`)).toEqual([{ voice: "off" }]));
    expect((within(voice).getByRole("radio", { name: "Off" }) as HTMLInputElement).checked).toBe(true);
  });

  it("sets who may watch (DEL-215)", async () => {
    const changes: Partial<Campaign>[] = [];
    const fetchMock = stubFetch({ [`PUT ${base}/table-settings`]: answering(changes) });
    renderSettings();
    const watching = screen.getByRole("radiogroup", { name: "Who may watch" });
    expect((within(watching).getByRole("radio", { name: "Anyone with the link" }) as HTMLInputElement).checked).toBe(true);
    fireEvent.click(within(watching).getByRole("radio", { name: "Only those you let in" }));
    await waitFor(() => expect(sent(fetchMock, "PUT", `${base}/table-settings`)).toEqual([{ observers: "approved" }]));
  });

  it("sets per side, from the next round", async () => {
    const changes: Partial<Campaign>[] = [];
    const fetchMock = stubFetch({ [`PUT ${base}/table-settings`]: answering(changes) });
    renderSettings();
    const initiative = screen.getByRole("radiogroup", { name: "Initiative" });
    expect((within(initiative).getByRole("radio", { name: "Per combatant" }) as HTMLInputElement).checked).toBe(true);
    expect(screen.getByText("From the next round of a fight.")).toBeTruthy();

    fireEvent.click(within(initiative).getByRole("radio", { name: "Per side" }));
    await waitFor(() => expect(sent(fetchMock, "PUT", `${base}/table-settings`)).toEqual([{ initiative: "side" }]));
    expect((within(initiative).getByRole("radio", { name: "Per side" }) as HTMLInputElement).checked).toBe(true);
  });

  it("shows what the server has, and an older server's campaign as the defaults", () => {
    stubFetch({});
    const { voice: _voice, initiative: _initiative, ...older } = campaign;
    renderSettings(older);
    expect((screen.getByRole("radio", { name: "Allowed" }) as HTMLInputElement).checked).toBe(true);
    expect((screen.getByRole("radio", { name: "Per combatant" }) as HTMLInputElement).checked).toBe(true);
  });

  it("shows a refusal", async () => {
    stubFetch({ [`PUT ${base}/table-settings`]: () => json(403, { error: "Only the host can do that." }) });
    renderSettings();
    fireEvent.click(screen.getByRole("radio", { name: "Off" }));
    expect((await screen.findByRole("alert")).textContent).toContain("Only the host can do that.");
    expect((screen.getByRole("radio", { name: "Allowed" }) as HTMLInputElement).checked).toBe(true);
  });

  it("390 px stacks the two settings", () => {
    stubFetch({});
    renderSettings();
    expect(screen.getByTestId("table-settings").dataset.layout).toBe("row");
    document.body.innerHTML = "";
    vi.stubGlobal("matchMedia", (query: string) => ({
      matches: query === PHONE_QUERY,
      addEventListener: () => {},
      removeEventListener: () => {},
    }));
    renderSettings(campaign, "nl");
    expect(screen.getByTestId("table-settings").dataset.layout).toBe("stacked");
    expect(screen.getByRole("radiogroup", { name: "Spraak" })).toBeTruthy();
  });
});
