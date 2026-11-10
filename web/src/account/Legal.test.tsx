import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import type { ReactNode } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { I18nProvider } from "../i18n";
import { json, stubFetch } from "../play/testing";
import { Privacy, Terms } from "./Legal";
import Login from "./Login";

// The public privacy policy and terms (DEL-208): the operator's contact, and only the outside services set up.

afterEach(() => vi.unstubAllGlobals());

function renderWith(node: ReactNode) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <I18nProvider language="en">{node}</I18nProvider>
    </QueryClientProvider>,
  );
}

const legal = (services: Partial<Record<"google" | "replicate" | "backups", boolean>> = {}, email = "raf@example.org") => ({
  operator: { name: "Raf", email },
  services: { google: false, replicate: false, backups: false, ...services },
});

describe("Privacy policy", () => {
  it("names the operator and Anthropic, and only the services set up", async () => {
    stubFetch({ "GET /api/legal": () => json(200, legal()) });
    renderWith(<Privacy />);
    expect(await screen.findAllByRole("link", { name: "raf@example.org" })).not.toHaveLength(0);
    expect(screen.getByText(/Anthropic \(Claude\):/)).toBeTruthy();
    expect(screen.queryByText(/Signing in with Google:/)).toBeNull();
    expect(screen.queryByText(/Replicate:/)).toBeNull();
    expect(screen.queryByText(/Backups:/)).toBeNull();
  });

  it("names Google, Replicate and backups once they are set up", async () => {
    stubFetch({ "GET /api/legal": () => json(200, legal({ google: true, replicate: true, backups: true })) });
    renderWith(<Privacy />);
    expect(await screen.findByText(/Signing in with Google:/)).toBeTruthy();
    expect(screen.getByText(/Replicate:/)).toBeTruthy();
    expect(screen.getByText(/Backups:/)).toBeTruthy();
  });

  it("without a contact says the owner of this Delve", async () => {
    stubFetch({ "GET /api/legal": () => json(200, { ...legal({}, ""), operator: { name: "", email: "" } }) });
    renderWith(<Terms />);
    expect((await screen.findAllByText(/the owner of this Delve/)).length).toBeGreaterThan(0);
    expect(screen.getByRole("link", { name: "privacy policy" }).getAttribute("href")).toBe("/privacy");
  });
});

it("the login page links to both", async () => {
  stubFetch({ "GET /api/me": () => json(401, { error: "Log in." }) });
  renderWith(<Login onDone={vi.fn()} />);
  expect((await screen.findByRole("link", { name: "Privacy" })).getAttribute("href")).toBe("/privacy");
  expect(screen.getByRole("link", { name: "Terms" }).getAttribute("href")).toBe("/terms");
});
