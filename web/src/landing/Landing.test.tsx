import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { I18nProvider } from "../i18n";
import { json, stubFetch } from "../play/testing";
import Landing from "./Landing";

// The public front page (DEL-144): the way in for a visitor, the way on for whoever is logged in.

afterEach(() => vi.unstubAllGlobals());

function renderLanding(language = "en") {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <I18nProvider language={language}>
        <Landing />
      </I18nProvider>
    </QueryClientProvider>,
  );
}

const ana = { id: "acc_00000000000a", username: "ana", display_name: "Ana", language: "en", organiser: false, owner: false };

describe("Landing", () => {
  it("offers a visitor Log in, and Ask for an account while sign-up is open", async () => {
    stubFetch({ "GET /api/me": () => json(401, { error: "Log in." }), "GET /api/sign-up": () => json(200, { open: true }) });
    renderLanding();
    // The hero's (once it knows nobody is logged in) and the foot's.
    await waitFor(() => expect(screen.getAllByRole("link", { name: "Log in" })).toHaveLength(2));
    expect(screen.getAllByRole("link", { name: "Log in" }).map((link) => link.getAttribute("href"))).toEqual(["/login", "/login"]);
    expect((await screen.findByRole("link", { name: "Ask for an account" })).getAttribute("href")).toBe("/sign-up");
    expect(screen.queryByRole("link", { name: "Open Delve" })).toBeNull();
  });

  it("says invites are the way in while sign-up is closed", async () => {
    stubFetch({ "GET /api/me": () => json(401, { error: "Log in." }), "GET /api/sign-up": () => json(200, { open: false }) });
    renderLanding();
    expect(await screen.findByText("New here? Ask whoever runs this Delve for an invite.")).toBeTruthy();
    expect(screen.queryByRole("link", { name: "Ask for an account" })).toBeNull();
  });

  it("takes whoever is logged in on into the app", async () => {
    stubFetch({
      "GET /api/me": () => json(200, { account: ana, seat: null, principal: { id: "acc_00000000000a", roles: ["player"] } }),
      "GET /api/sign-up": () => json(200, { open: true }),
    });
    renderLanding();
    expect((await screen.findByRole("link", { name: "Open Delve" })).getAttribute("href")).toBe("/home");
    expect(screen.getByText("Logged in as Ana")).toBeTruthy();
    expect(screen.queryAllByRole("link", { name: "Log in" })).toHaveLength(0);
  });

  it("says what Delve is, how to get to a table, and links the privacy policy and terms", async () => {
    stubFetch({ "GET /api/me": () => json(401, { error: "Log in." }), "GET /api/sign-up": () => json(200, { open: false }) });
    renderLanding("nl");
    expect(await screen.findByRole("heading", { level: 2, name: "Zo kom je aan tafel" })).toBeTruthy();
    expect(screen.getAllByRole("listitem")).toHaveLength(3);
    expect(screen.getByRole("link", { name: "Privacy" }).getAttribute("href")).toBe("/privacy");
    expect(screen.getByRole("link", { name: "Voorwaarden" }).getAttribute("href")).toBe("/terms");
  });
});
