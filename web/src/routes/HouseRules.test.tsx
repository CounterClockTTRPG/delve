import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";
import { I18nProvider } from "../i18n";
import HouseRules from "./HouseRules";

const maxHp = {
  id: "hr_000000000001",
  title: "Max HP at first level",
  body_md: "",
  kind: "general",
  phases: ["character-creation"],
  ruleset: null,
  setting: null,
  subject: null,
  enabled: true,
};
const example = { id: "hb_00000000000a", title: "My table (from ttrpg2)", description_md: "", rule_ids: [maxHp.id] };

function json(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
}

/** A fake API whose library is `rules` and `bundles`; the example import fills it. */
function stubApi(rules: unknown[], bundles: unknown[]) {
  const fetch = vi.fn(async (path: string, init?: RequestInit) => {
    if (path === "/api/house-rules/import-example" && init?.method === "POST") {
      rules = [maxHp];
      bundles = [example];
      return json(200, example);
    }
    if (path === "/api/house-rules") return json(200, rules);
    if (path === "/api/house-rule-bundles") return json(200, bundles);
    return json(404, { error: "not found" });
  });
  vi.stubGlobal("fetch", fetch);
  return fetch;
}

afterEach(() => {
  vi.unstubAllGlobals();
});

function renderPage() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <I18nProvider language="en">
        <MemoryRouter>
          <HouseRules />
        </MemoryRouter>
      </I18nProvider>
    </QueryClientProvider>,
  );
}

describe("HouseRules", () => {
  it("offers the example rules on an empty library, and imports them on request", async () => {
    const fetch = stubApi([], []);
    renderPage();
    const button = await screen.findByRole("button", { name: "Import the example rules" });
    expect(screen.getByText(/A fresh install starts without house rules/)).toBeTruthy();
    expect(fetch).not.toHaveBeenCalledWith("/api/house-rules/import-example", expect.anything());

    fireEvent.click(button);
    expect(await screen.findByText("My table (from ttrpg2)")).toBeTruthy();
    const call = fetch.mock.calls.find(([path]) => path === "/api/house-rules/import-example");
    expect(call?.[1]?.method).toBe("POST");
    expect(new Headers(call?.[1]?.headers).get("Content-Type")).toBe("application/json");
    expect(screen.queryByRole("button", { name: "Import the example rules" })).toBeNull();
  });

  it("offers no import when the library has rules", async () => {
    stubApi([maxHp], []);
    renderPage();
    expect(await screen.findByText("Max HP at first level")).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Import the example rules" })).toBeNull();
  });
});
