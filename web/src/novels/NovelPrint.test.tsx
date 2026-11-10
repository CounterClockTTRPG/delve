import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen } from "@testing-library/react";
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { RouterProvider, createMemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { I18nProvider } from "../i18n";
import type { Novel } from "./api";
import NovelPrint from "./NovelPrint";

const ID = "nov_aaaaaaaaaaaa";
const here = dirname(fileURLToPath(import.meta.url));

function novel(overrides: Partial<Novel> = {}): Novel {
  return {
    id: ID,
    title: "The Bones of Saint Vellis",
    campaign_id: null,
    module_id: "mod_cccccccccccc",
    revision: 1,
    sessions: null,
    length: "short-story",
    tone: "heroic",
    custom_tone: "",
    language: "en",
    instructions: "",
    chapters: [
      { title: "Down the Stairs", summary: "", text: "Dust lay *thick* on the stairs." },
      { title: "The Last Monk", summary: "", text: "Brother Ansel smiled." },
      { title: "Fire", summary: "", text: null },
    ],
    status: "failed",
    error: "Delve stopped while writing",
    conversion_id: null,
    cost_usd: null,
    created_at: "2026-10-20T10:00:00Z",
    updated_at: "2026-10-20T10:30:00Z",
    ...overrides,
  };
}

let body: Novel;

function json(status: number, data: unknown): Response {
  return new Response(JSON.stringify(data), { status, headers: { "Content-Type": "application/json" } });
}

beforeEach(() => {
  body = novel();
  vi.stubGlobal(
    "fetch",
    vi.fn(async (path: string) => (path === `/api/novels/${ID}` ? json(200, body) : json(404, { error: "not found" }))),
  );
});

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

function renderPrint() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const router = createMemoryRouter(
    [
      { path: "/novels/:id", element: <p>the reader</p> },
      { path: "/novels/:id/print", element: <NovelPrint /> },
    ],
    { initialEntries: [`/novels/${ID}/print`] },
  );
  const { container } = render(
    <QueryClientProvider client={client}>
      <I18nProvider language="en">
        <RouterProvider router={router} />
      </I18nProvider>
    </QueryClientProvider>,
  );
  return { container, router };
}

describe("NovelPrint", () => {
  it("prints a title page, then one section per written chapter", async () => {
    const { container } = renderPrint();
    await screen.findByRole("heading", { level: 1, name: "The Bones of Saint Vellis" });

    const parts = Array.from(container.querySelectorAll<HTMLElement>("section[data-part]"));
    expect(parts.map((part) => part.dataset.part)).toEqual(["title", "chapter", "chapter"]);
    expect((parts[0]).textContent).toContain("Short story");
    expect(parts[1].querySelector("h2")?.textContent).toBe("Down the Stairs");
    expect(parts[1].querySelector("em")?.textContent).toBe("thick");
    expect((parts[2]).textContent).toContain("Brother Ansel smiled.");
    expect(screen.queryByText("Fire")).toBeNull();
    expect(document.title).toBe("The Bones of Saint Vellis — Delve");
  });

  it("starts each chapter on a new page in print, with the page's margins", () => {
    const css = readFileSync(join(here, "NovelPrint.module.css"), "utf8");
    expect(css).toMatch(/@page novel\s*\{[^}]*margin/);
    const print = css.slice(css.indexOf("@media print"));
    expect(print).toMatch(/\.page\s*\{[^}]*page:\s*novel/);
    expect(print).toMatch(/\.chapter\s*\{[^}]*break-before:\s*page/);
  });

  it("prints from the browser's dialog, and goes back to the reader", async () => {
    const print = vi.spyOn(window, "print").mockImplementation(() => {});
    const { router } = renderPrint();
    fireEvent.click(await screen.findByRole("button", { name: "Print or save as PDF" }));
    expect(print).toHaveBeenCalled();
    fireEvent.click(screen.getByRole("link", { name: "← Back to the novel" }));
    expect(router.state.location.pathname).toBe(`/novels/${ID}`);
  });

  it("never follows the look", async () => {
    document.documentElement.dataset.look = "gold-wood";
    renderPrint();
    await screen.findByRole("heading", { level: 1, name: "The Bones of Saint Vellis" });
    expect(document.documentElement.hasAttribute("data-look")).toBe(false);
    delete document.documentElement.dataset.look;
  });
});
