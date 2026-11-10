import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, within } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { I18nProvider } from "../i18n";
import Maps, { ModuleMaps } from "./Maps";

const house = {
  id: "mod_0123456789ab",
  title: "The Haunted House",
  maps: [
    { name: "ground-floor", role: "map", is_default: true },
    { name: "cellar", role: "map", is_default: false },
    { name: "core", role: "library", is_default: false },
  ],
  head_revision: 1,
  updated_at: "2026-10-19T10:00:00Z",
};
const campaign = {
  id: "cmp_0123456789ab",
  name: "Saltmarsh",
  module_id: house.id,
  module_title: house.title,
  revision: 1,
  created_at: "2026-10-19T10:00:00Z",
  ruleset: "adnd2e",
  setting: null,
  status: "in_progress",
  players: [],
};

function json(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
}

const bare = { ...house, id: "mod_bare", title: "No Maps Here", maps: [] };
let modules: unknown[] = [house, bare];

beforeEach(() => {
  modules = [house, bare];
  const routes: Record<string, () => Response> = {
    "/api/modules": () => json(200, modules),
    "/api/campaigns": () => json(200, [campaign, { ...campaign, id: "cmp_other", module_id: "mod_other", name: "Other" }]),
  };
  vi.stubGlobal("fetch", vi.fn(async (path: string) => (routes[path] ?? (() => json(404, { error: "not found" })))()));
});

afterEach(() => {
  vi.unstubAllGlobals();
});

function renderAt(path: string) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <I18nProvider language="en">
        <MemoryRouter initialEntries={[path]}>
          <Routes>
            <Route path="/maps" element={<Maps />} />
            <Route path="/maps/:moduleId" element={<ModuleMaps />} />
          </Routes>
        </MemoryRouter>
      </I18nProvider>
    </QueryClientProvider>,
  );
}

const many = (n: number, prefix: string) => Array.from({ length: n }, (_, i) => `${prefix}-${String(i + 1).padStart(2, "0")}`);

describe("Maps", () => {
  it("lists the modules that have maps, with their counts, each opening its maps", async () => {
    renderAt("/maps");
    const row = (await screen.findByRole("link", { name: house.title })).closest("li")!;
    expect(within(row).getByRole("link", { name: house.title }).getAttribute("href")).toBe(`/maps/${house.id}`);
    expect(row.textContent).toContain("3 maps");
    expect(screen.queryByText(bare.title)).toBeNull();
    // The maps themselves are one level down.
    expect(screen.queryByRole("link", { name: "cellar" })).toBeNull();
  });

  it("filters the modules, with the filter in the address (backlog 37)", async () => {
    const tomb = { ...house, id: "mod_tomb", title: "Tomb of Horrors", setting: "Greyhawk", levels: { min: 10, max: 14 }, tags: ["traps"] };
    modules = [{ ...house, setting: "Forgotten Realms", levels: { min: 1, max: 3 }, tags: [] }, tomb, bare];
    renderAt("/maps?level=12");
    expect(await screen.findByRole("link", { name: tomb.title })).toBeTruthy();
    expect(screen.queryByRole("link", { name: house.title })).toBeNull();
    expect((screen.getByLabelText("Starting level") as HTMLInputElement).value).toBe("12");
    // The settings offered are the ones of the modules that have maps.
    const setting = screen.getByLabelText("Setting") as HTMLSelectElement;
    expect([...setting.options].map((o) => o.text)).toEqual(["Any", "Forgotten Realms", "Greyhawk"]);
  });

  it("pages through many modules, 20 at a time, with the page in the address", async () => {
    modules = many(25, "Module").map((title, i) => ({ ...house, id: `mod_${i}`, title }));
    renderAt("/maps?page=2");
    expect(await screen.findByRole("link", { name: "Module-21" })).toBeTruthy();
    expect(screen.queryByRole("link", { name: "Module-01" })).toBeNull();
    expect(screen.getByRole("navigation", { name: "Modules pages" }).textContent).toContain("21–25 of 25");
  });
});

describe("A module's maps", () => {
  it("lists every map with its editor, and a played map with its DM view in each campaign that plays it", async () => {
    renderAt(`/maps/${house.id}`);
    expect(await screen.findByRole("heading", { name: house.title })).toBeTruthy();
    const cellar = (await screen.findByRole("link", { name: "cellar" })).closest("li")!;
    expect(within(cellar).getByRole("link", { name: "cellar" }).getAttribute("href")).toBe(`/maps/${house.id}/cellar`);
    const dmView = await within(cellar).findByRole("link", { name: "DM view in Saltmarsh" });
    expect(dmView.getAttribute("href")).toBe(`/campaigns/${campaign.id}?map=cellar`);
    expect(screen.queryByRole("link", { name: "DM view in Other" })).toBeNull();
    // A library isn't played: it has no DM view.
    const core = screen.getByRole("link", { name: "core" }).closest("li")!;
    expect(within(core).queryByRole("link", { name: /DM view/ })).toBeNull();
    expect(screen.getByRole("link", { name: "All maps" }).getAttribute("href")).toBe("/maps");
    expect(screen.getByRole("link", { name: "The module's page" }).getAttribute("href")).toBe(`/modules/${house.id}`);
  });

  it("pages through many maps, 20 at a time", async () => {
    const names = many(23, "level");
    modules = [{ ...house, maps: names.map((name, i) => ({ name, role: "map", is_default: i === 0 })) }];
    renderAt(`/maps/${house.id}`);
    expect(await screen.findByRole("link", { name: "level-20" })).toBeTruthy();
    expect(screen.queryByRole("link", { name: "level-21" })).toBeNull();
    expect(screen.getByRole("navigation", { name: "Maps pages" }).textContent).toContain("1–20 of 23");
  });

  it("says so for a module without maps", async () => {
    renderAt("/maps/mod_bare");
    expect(await screen.findByText("This module has no maps yet.")).toBeTruthy();
  });

  it("says so for a module that isn't there", async () => {
    renderAt("/maps/mod_gone");
    expect(await screen.findByText("There is no such module.")).toBeTruthy();
    expect(screen.getByRole("link", { name: "All maps" })).toBeTruthy();
  });
});
