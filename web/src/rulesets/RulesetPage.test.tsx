import { fireEvent, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { json, stubFetch } from "../play/testing";
import { asked, owner, player, playerAccount, renderArea } from "./testing";

afterEach(() => {
  vi.unstubAllGlobals();
});

const info = (campaign: string | null = null) => ({
  id: "adnd2e",
  title: "AD&D 2nd Edition",
  campaign_id: campaign,
  sections: [
    { key: "spells", kind: "list", count: 887 },
    { key: "monsters", kind: "list", count: 3826 },
    { key: "abilities", kind: "table", count: 6 },
    { key: "homebrew", kind: "list", count: 2 },
  ],
});

const campaigns = [
  { id: "cmp_00000000000a", name: "The Crypt" },
  { id: "cmp_00000000000b", name: "Saltmarsh" },
];

describe("A ruleset's page", () => {
  it("shows a card per section with its count", async () => {
    stubFetch({ "GET /api/me": player, "GET /api/rulesets/adnd2e": () => json(200, info()) });
    renderArea("/rulesets/adnd2e");
    expect(await screen.findByRole("heading", { level: 1, name: "AD&D 2nd Edition" })).toBeTruthy();
    const spells = screen.getByRole("link", { name: /Spells/ });
    expect(spells.getAttribute("href")).toBe("/rulesets/adnd2e/spells");
    expect(spells.textContent).toContain("887");
    expect(screen.getByRole("link", { name: /Ability scores/ }).getAttribute("href")).toBe("/rulesets/adnd2e/abilities");
    // A section Delve has no words for shows its key.
    expect(screen.getByRole("link", { name: /homebrew/ }).getAttribute("href")).toBe("/rulesets/adnd2e/homebrew");
  });

  it("shows the ruleset's licence notice under its sections, and none without one", async () => {
    const notice = "Delve is an independent product published under the OSRIC 3.0 Third-Party License.";
    stubFetch({ "GET /api/me": player, "GET /api/rulesets/osric": () => json(200, { ...info(), id: "osric", notice }) });
    renderArea("/rulesets/osric");
    expect(await screen.findByText(notice)).toBeTruthy();
  });

  it("lists the search's hits, each linking to its entry", async () => {
    const fetchMock = stubFetch({
      "GET /api/me": player,
      "GET /api/rulesets/adnd2e": () => json(200, info()),
      "GET /api/rulesets/adnd2e/search?q=web": () =>
        json(200, {
          results: [
            { section: "spells", id: "412", name: "Web" },
            { section: "items", id: "77", name: "Webbed boots" },
          ],
        }),
    });
    renderArea("/rulesets/adnd2e");
    fireEvent.change(await screen.findByRole("searchbox", { name: "Search this ruleset" }), { target: { value: "web" } });
    const web = await screen.findByRole("link", { name: "Web" });
    expect(web.getAttribute("href")).toBe("/rulesets/adnd2e/spells/412");
    expect(screen.getByRole("link", { name: "Webbed boots" }).getAttribute("href")).toBe("/rulesets/adnd2e/items/77");
    expect(asked(fetchMock)).toContain("/api/rulesets/adnd2e/search?q=web");
  });

  it("says when the search finds nothing", async () => {
    stubFetch({
      "GET /api/me": player,
      "GET /api/rulesets/adnd2e": () => json(200, info()),
      "GET /api/rulesets/adnd2e/search?q=zzz": () => json(200, { results: [] }),
    });
    renderArea("/rulesets/adnd2e");
    fireEvent.change(await screen.findByRole("searchbox", { name: "Search this ruleset" }), { target: { value: "zzz" } });
    expect(await screen.findByText("Nothing found.")).toBeTruthy();
  });

  it("lets an organiser without a seat choose whose house rules to see, and keeps it on every link", async () => {
    const fetchMock = stubFetch({
      "GET /api/me": owner,
      "GET /api/campaigns": () => json(200, campaigns),
      "GET /api/rulesets/adnd2e": () => json(200, info()),
      "GET /api/rulesets/adnd2e?campaign=cmp_00000000000b": () => json(200, info("cmp_00000000000b")),
      "GET /api/rulesets/adnd2e/search?q=web&campaign=cmp_00000000000b": () =>
        json(200, { results: [{ section: "spells", id: "412", name: "Web" }] }),
    });
    const router = renderArea("/rulesets/adnd2e");
    const select = (await screen.findByRole("combobox", { name: "House rules of" })) as HTMLSelectElement;
    await waitFor(() => expect(select.options.length).toBe(3));
    expect([...select.options].map((o) => o.textContent)).toEqual(["No campaign", "The Crypt", "Saltmarsh"]);

    fireEvent.change(select, { target: { value: "cmp_00000000000b" } });
    await waitFor(() => expect(router.state.location.search).toBe("?campaign=cmp_00000000000b"));
    await waitFor(() => expect(asked(fetchMock)).toContain("/api/rulesets/adnd2e?campaign=cmp_00000000000b"));
    await waitFor(() =>
      expect(screen.getByRole("link", { name: /Spells/ }).getAttribute("href")).toBe(
        "/rulesets/adnd2e/spells?campaign=cmp_00000000000b",
      ),
    );
    expect(screen.getByRole("link", { name: "Rulesets" }).getAttribute("href")).toBe("/rulesets?campaign=cmp_00000000000b");

    fireEvent.change(screen.getByRole("searchbox", { name: "Search this ruleset" }), { target: { value: "web" } });
    expect((await screen.findByRole("link", { name: "Web" })).getAttribute("href")).toBe(
      "/rulesets/adnd2e/spells/412?campaign=cmp_00000000000b",
    );

    fireEvent.change(select, { target: { value: "" } });
    await waitFor(() => expect(router.state.location.search).toBe(""));
  });

  it("shows a seat no choice of campaign", async () => {
    stubFetch({ "GET /api/me": player, "GET /api/rulesets/adnd2e": () => json(200, info()) });
    renderArea("/rulesets/adnd2e");
    await screen.findByRole("heading", { level: 1, name: "AD&D 2nd Edition" });
    expect(screen.queryByRole("combobox", { name: "House rules of" })).toBeNull();
  });

  it("shows a player account no choice of campaign, and the way back to the table it came from", async () => {
    const fetchMock = stubFetch({
      "GET /api/me": playerAccount,
      "GET /api/rulesets/adnd2e?campaign=cmp_00000000000a": () => json(200, info("cmp_00000000000a")),
    });
    renderArea("/rulesets/adnd2e?campaign=cmp_00000000000a");
    await screen.findByRole("heading", { level: 1, name: "AD&D 2nd Edition" });
    expect(screen.queryByRole("combobox", { name: "House rules of" })).toBeNull();
    expect(fetchMock.mock.calls.some(([path]) => path === "/api/campaigns")).toBe(false);
    expect((await screen.findByRole("link", { name: "Back to the table" })).getAttribute("href")).toBe("/play/cmp_00000000000a");
  });

  it("says not found for a ruleset that isn't there", async () => {
    stubFetch({ "GET /api/me": player });
    renderArea("/rulesets/nope");
    expect(await screen.findByText("This page isn't in the ruleset.")).toBeTruthy();
  });
});
