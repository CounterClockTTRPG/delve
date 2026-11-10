import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { CampaignDetail, Character } from "../api";
import { DialogsProvider } from "../components/dialogs";
import { I18nProvider } from "../i18n";
import { CAMPAIGN, base, character, json, sent, stubFetch, type Handler } from "../play/testing";
import CarryForm from "./CarryForm";

const { toast } = vi.hoisted(() => ({ toast: vi.fn() }));
vi.mock("sonner", () => ({ toast }));

afterEach(() => {
  vi.unstubAllGlobals();
});

const campaign: CampaignDetail = {
  id: CAMPAIGN,
  name: "Tuesday",
  module_id: "mod_00000000000a",
  revision: 1,
  created_at: "2026-10-17T12:00:00Z",
  ruleset: "osric",
  setting: "greyhawk",
  status: "in_progress",
  module_title: "The Crypt",
  maps: [],
  upgrade_available: false,
  carried_from: null,
  carried_to: [],
};

const module = (id: string, title: string, draft = false) => ({ id, title, maps: [], head_revision: 1, updated_at: "", draft });

const ash = character("chr_00000000000a", "Ash");
const birch: Character = { ...character("chr_00000000000b", "Birch"), state: { ...ash.state, hp: -10 } };
const grik: Character = { ...character("chr_00000000000g", "Grik"), kind: "npc" };

const NEW = "cmp_00000000000n";

function routes(extra: Record<string, Handler> = {}): Record<string, Handler> {
  return {
    "GET /api/modules": () =>
      json(200, [module("mod_00000000000a", "The Crypt"), module("mod_00000000000d", "Half-done", true), module("mod_00000000000b", "Barrowmaze")]),
    "GET /api/worlds": () =>
      json(200, {
        rulesets: [
          { id: "adnd2e", title: "AD&D 2e" },
          { id: "osric", title: "OSRIC" },
        ],
        settings: [
          { id: "greyhawk", title: "Greyhawk" },
          { id: "forgotten-realms", title: "The Forgotten Realms" },
        ],
      }),
    [`GET ${base}/house-rules`]: () => json(200, { bundle_ids: ["bnd_1"], rule_ids: ["hr_1"] }),
    "GET /api/house-rules": () => json(200, []),
    "GET /api/house-rule-bundles": () => json(200, []),
    [`POST ${base}/carry`]: () => json(201, { ...campaign, id: NEW, name: "Tuesday", history: { status: "writing" } }),
    ...extra,
  };
}

function renderForm(characters: Character[] = [ash, birch, grik]) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const onCancel = vi.fn();
  render(
    <QueryClientProvider client={client}>
      <I18nProvider language="en">
        <DialogsProvider>
          <MemoryRouter initialEntries={[`/campaigns/${CAMPAIGN}`]}>
            <Routes>
              <Route
                path="/campaigns/:id"
                element={<CarryForm campaign={campaign} characters={characters} onCancel={onCancel} />}
              />
              <Route path="/campaigns/cmp_00000000000n" element={<p>the new campaign</p>} />
            </Routes>
          </MemoryRouter>
        </DialogsProvider>
      </I18nProvider>
    </QueryClientProvider>,
  );
  return { onCancel };
}

describe("CarryForm", () => {
  it("lists the PCs, the living ticked and the dead unticked and marked dead; no NPC", async () => {
    stubFetch(routes());
    renderForm();
    const living = await screen.findByRole("checkbox", { name: "Ash" });
    expect((living as HTMLInputElement).checked).toBe(true);
    const dead = screen.getByRole("checkbox", { name: /Birch/ });
    expect((dead as HTMLInputElement).checked).toBe(false);
    expect(dead.closest("label")!.textContent).toContain("dead");
    expect(screen.queryByRole("checkbox", { name: /Grik/ })).toBeNull();
  });

  it("offers only the modules that aren't drafts, by title (DEL-246)", async () => {
    stubFetch(routes());
    renderForm();
    const select = (await screen.findByLabelText("Module")) as HTMLSelectElement;
    await waitFor(() => expect(select.options.length).toBe(2));
    expect([...select.options].map((o) => o.textContent)).toEqual(["Barrowmaze", "The Crypt"]);
  });

  it("pre-fills the name, the ruleset, the setting and the house rules from the old campaign, and goes to the new one", async () => {
    const fetchMock = stubFetch(routes());
    renderForm();
    expect(((await screen.findByLabelText("New campaign's name")) as HTMLInputElement).value).toBe("Tuesday");
    await waitFor(() => expect((screen.getByLabelText("Ruleset") as HTMLSelectElement).value).toBe("osric"));
    expect((screen.getByLabelText("Setting") as HTMLSelectElement).value).toBe("greyhawk");
    fireEvent.change(screen.getByLabelText("Module"), { target: { value: "mod_00000000000b" } });
    fireEvent.change(screen.getByLabelText("New campaign's name"), { target: { value: "Into Barrowmaze" } });
    fireEvent.click(screen.getByRole("button", { name: "Carry the party on" }));

    expect(await screen.findByText("the new campaign")).toBeTruthy();
    expect(toast).toHaveBeenCalledWith("The party was carried on into Tuesday.");
    expect(sent(fetchMock, "POST", `${base}/carry`)).toEqual([
      {
        name: "Into Barrowmaze",
        module_id: "mod_00000000000b",
        character_ids: ["chr_00000000000a"],
        ruleset: "osric",
        setting: "greyhawk",
        bundle_ids: ["bnd_1"],
        rule_ids: ["hr_1"],
      },
    ]);
  });

  it("carries a dead PC when it is ticked, and none without a PC", async () => {
    const fetchMock = stubFetch(routes());
    renderForm();
    fireEvent.click(await screen.findByRole("checkbox", { name: "Ash" }));
    await waitFor(() => expect((screen.getByLabelText("Ruleset") as HTMLSelectElement).value).toBe("osric"));
    expect((screen.getByRole("button", { name: "Carry the party on" }) as HTMLButtonElement).disabled).toBe(true);
    fireEvent.click(screen.getByRole("checkbox", { name: /Birch/ }));
    fireEvent.click(screen.getByRole("button", { name: "Carry the party on" }));
    await screen.findByText("the new campaign");
    expect((sent(fetchMock, "POST", `${base}/carry`)[0] as { character_ids: string[] }).character_ids).toEqual(["chr_00000000000b"]);
  });

  it("shows a refusal, such as a live fight's, as an error", async () => {
    stubFetch(routes({ [`POST ${base}/carry`]: () => json(409, { error: "End the fight first." }) }));
    renderForm();
    await screen.findByRole("checkbox", { name: "Ash" });
    await waitFor(() => expect((screen.getByLabelText("Ruleset") as HTMLSelectElement).value).toBe("osric"));
    fireEvent.click(screen.getByRole("button", { name: "Carry the party on" }));
    expect((await screen.findByRole("alert")).textContent).toContain("End the fight first.");
  });

  it("Cancel closes the form", async () => {
    stubFetch(routes());
    const { onCancel } = renderForm();
    fireEvent.click(await screen.findByRole("button", { name: "Cancel" }));
    expect(onCancel).toHaveBeenCalled();
  });
});
