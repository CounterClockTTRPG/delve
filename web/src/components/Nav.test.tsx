import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { useState } from "react";
import { Link, RouterProvider, createMemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { Account } from "../account/api";
import { EventsContext, type Conversion, type Subscribe } from "../api";
import { I18nProvider } from "../i18n";
import Nav from "./Nav";
import { NavMenuContext } from "./navMenu";
import Toasts from "./Toasts";

const running: Conversion = {
  id: "cnv_000000000001",
  kind: "pdf",
  title: "Dark Clouds Gather",
  mode: "draft",
  status: "running",
  step: "reading",
  done: 3,
  total: 38,
  steps: { index: 1, count: 4 },
  module_id: null,
  warnings: [],
  error: null,
  created_at: "2026-10-18T10:00:00Z",
  updated_at: "2026-10-18T10:01:00Z",
};

let listed: Conversion[];
let heard: Record<string, ((data: unknown) => void)[]>;
const subscribe: Subscribe = (handlers) => {
  for (const [type, handle] of Object.entries(handlers)) (heard[type] ??= []).push(handle);
  return () => {
    for (const [type, handle] of Object.entries(handlers)) heard[type] = heard[type].filter((h) => h !== handle);
  };
};

function json(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
}

const preferences = {
  choices: { dm: { provider: "fake", model: "fake-large", effort: "auto" } },
  language: "en",
  warnings: [] as string[],
};
let saved: unknown[];
let calls: string[];
let accounts: { id: string; pending: boolean }[];

beforeEach(() => {
  heard = {};
  listed = [running];
  saved = [];
  calls = [];
  accounts = [];
  localStorage.clear();
  vi.stubGlobal(
    "fetch",
    vi.fn(async (path: string, init?: RequestInit) => {
      calls.push(`${init?.method ?? "GET"} ${path}`);
      if (path === "/api/logout") return new Response(null, { status: 204 });
      if (path === "/api/conversions") return json(200, listed);
      if (path === "/api/accounts") return json(200, accounts);
      if (path === "/api/preferences" && init?.method === "PUT") {
        const body = JSON.parse(String(init.body));
        saved.push(body);
        return json(200, { ...body, warnings: [] });
      }
      if (path === "/api/preferences") return json(200, preferences);
      if (path === "/api/account/profile" && init?.method === "PUT") {
        const body = JSON.parse(String(init.body));
        saved.push({ profile: body });
        return json(200, { ...body });
      }
      return json(404, { error: "not found" });
    }),
  );
});

afterEach(() => {
  vi.unstubAllGlobals();
});

/** The notification that holds `text`, in the corner. */
async function notice(text: string): Promise<HTMLElement> {
  return (await screen.findByText(text, { exact: false })).closest("[data-sonner-toast]") as HTMLElement;
}

function renderNav(at = "/campaigns", account: Account | null = null) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const router = createMemoryRouter([{ path: "*", element: <><Nav account={account} /><Toasts /></> }], { initialEntries: [at] });
  render(
    <QueryClientProvider client={client}>
      <I18nProvider language="en">
        <EventsContext.Provider value={subscribe}>
          <RouterProvider router={router} />
        </EventsContext.Provider>
      </I18nProvider>
    </QueryClientProvider>,
  );
}

const ana: Account = { id: "acc_00000000000a", username: "ana", display_name: "Ana", language: "en", organiser: false, owner: false };

describe("Nav", () => {
  it("a player's nav", async () => {
    const assign = vi.fn();
    vi.stubGlobal("location", { ...window.location, assign });
    renderNav("/tables", ana);
    const nav = await screen.findByRole("navigation", { name: "Areas" });
    expect(Array.from(nav.querySelectorAll("a")).map((a) => a.textContent)).toEqual(["My tables", "Find a table", "Board", "Preferences"]);
    expect(within(nav).getByRole("link", { name: "My tables" }).getAttribute("href")).toBe("/tables");
    // The language switch is the account's own; nothing of the organiser's is asked for.
    expect((within(nav).getByRole("combobox", { name: "Language" }) as HTMLSelectElement).value).toBe("en");
    fireEvent.click(within(nav).getByTestId("nav-logout"));
    await waitFor(() => expect(assign).toHaveBeenCalledWith("/"));
    expect(calls).toEqual(["POST /api/logout"]);
  });

  it("logged in, the language menu saves the account's language, not the install's", async () => {
    renderNav("/tables", ana);
    const menu = (await screen.findByRole("combobox", { name: "Language" })) as HTMLSelectElement;
    fireEvent.change(menu, { target: { value: "nl" } });
    await waitFor(() => expect(saved).toEqual([{ profile: { language: "nl" } }]));
    expect(calls).not.toContain("GET /api/preferences");
  });

  it("the owner's account's language menu saves its own language and the install's", async () => {
    renderNav("/campaigns", { ...ana, owner: true });
    const menu = (await screen.findByRole("combobox", { name: "Language" })) as HTMLSelectElement;
    fireEvent.change(menu, { target: { value: "nl" } });
    await waitFor(() => expect(saved).toEqual([{ profile: { language: "nl" } }, { language: "nl" }]));
  });

  it("an organiser account's nav adds My tables and Log out", async () => {
    renderNav("/campaigns", { ...ana, organiser: true });
    const nav = await screen.findByRole("navigation", { name: "Areas" });
    const labels = Array.from(nav.querySelectorAll("a")).map((a) => a.textContent);
    expect(labels[0]).toBe("My tables");
    expect(labels).toContain("Modules");
    expect(within(nav).getByTestId("nav-logout")).toBeTruthy();
  });

  it("an owner account's nav is an organiser's, though its organiser flag is off (DEL-158)", async () => {
    renderNav("/campaigns", { ...ana, owner: true });
    const nav = await screen.findByRole("navigation", { name: "Areas" });
    expect(Array.from(nav.querySelectorAll("a")).map((a) => a.textContent)).toContain("Modules");
  });

  it("the owner without an account has no Log out", async () => {
    renderNav();
    const nav = await screen.findByRole("navigation", { name: "Areas" });
    expect(within(nav).queryByTestId("nav-logout")).toBeNull();
    expect(within(nav).queryByRole("link", { name: "My tables" })).toBeNull();
  });

  it("its footer's menu offers every language by its own name, and saves only the language (DEL-122)", async () => {
    renderNav();
    const menu = (await screen.findByRole("combobox", { name: "Language" })) as HTMLSelectElement;
    await waitFor(() => expect(menu.value).toBe("en"));
    expect([...menu.options].map((o) => o.textContent)).toEqual(["English", "Nederlands", "Français", "Deutsch", "Latviešu"]);
    fireEvent.change(menu, { target: { value: "lv" } });
    await waitFor(() => expect(saved).toEqual([{ language: "lv" }]));
    await waitFor(() => expect(menu.value).toBe("lv"));
  });

  it("has a dot on Modules while a conversion runs", async () => {
    renderNav();
    const dot = await screen.findByRole("img", { name: "A conversion is running" });
    expect(screen.getByRole("link", { name: /Modules/ }).contains(dot)).toBe(true);
  });

  it("counts the sign-ups waiting for approval on Preferences (DEL-156)", async () => {
    accounts = [
      { id: "acc_00000000000a", pending: false },
      { id: "acc_00000000000b", pending: true },
      { id: "acc_00000000000c", pending: true },
    ];
    renderNav();
    const count = await screen.findByTestId("nav-waiting");
    expect(count.textContent).toBe("2");
    expect(count.getAttribute("aria-label")).toBe("Waiting for approval: 2");
    expect(screen.getByRole("link", { name: /Preferences/ }).contains(count)).toBe(true);
  });

  it("no count while nobody waits", async () => {
    accounts = [{ id: "acc_00000000000a", pending: false }];
    renderNav();
    await screen.findByRole("link", { name: /Preferences/ });
    await waitFor(() => expect(calls).toContain("GET /api/accounts"));
    expect(screen.queryByTestId("nav-waiting")).toBeNull();
  });

  it("no dot when nothing runs", async () => {
    listed = [{ ...running, status: "cancelled" }];
    renderNav();
    await screen.findByRole("link", { name: /Modules/ });
    await waitFor(() => expect(heard.conversion?.length).toBeTruthy());
    expect(screen.queryByRole("img", { name: "A conversion is running" })).toBeNull();
  });

  it("on any screen, a conversion that ends shows a notice with a link to its module", async () => {
    renderNav();
    await screen.findByRole("img", { name: "A conversion is running" });
    listed = [{ ...running, status: "done", module_id: "mod_aaaaaaaaaaaa", step: "maps", steps: { index: 4, count: 4 } }];
    act(() =>
      heard.conversion?.forEach((h) =>
        h({ id: running.id, status: "done", step: "maps", done: 1, total: 1, steps: { index: 4, count: 4 } }),
      ),
    );
    expect(await notice("Dark Clouds Gather is converted.")).toBeTruthy();
    const link = await screen.findByRole("link", { name: "Open the module" });
    expect(link.getAttribute("href")).toBe("/modules/mod_aaaaaaaaaaaa");
    expect(screen.queryByRole("img", { name: "A conversion is running" })).toBeNull();
  });

  it("a failed conversion's notice says why", async () => {
    renderNav();
    await screen.findByRole("img", { name: "A conversion is running" });
    listed = [{ ...running, status: "failed", error: "claude stopped" }];
    act(() => heard.conversion?.forEach((h) => h({ id: running.id, status: "failed", step: "reading", done: 3, total: 38 })));
    expect(await notice("Dark Clouds Gather wasn't converted: claude stopped")).toBeTruthy();
  });

  it("a read world map's notice links to its review", async () => {
    const reading: Conversion = {
      ...running,
      kind: "worldmap",
      title: "The Flanaess",
      step: "tiles",
      steps: { index: 1, count: 6 },
      target: { module_id: "mod_aaaaaaaaaaaa", name: "flanaess", title: "The Flanaess" },
    };
    listed = [reading];
    renderNav();
    await screen.findByRole("img", { name: "A conversion is running" });
    listed = [{ ...reading, status: "done", step: "routes", steps: { index: 6, count: 6 } }];
    act(() => heard.conversion?.forEach((h) => h({ id: running.id, status: "done", step: "routes", done: 1, total: 1 })));
    expect(await notice("The Flanaess is ready to look at.")).toBeTruthy();
    const link = await screen.findByRole("link", { name: "Review the map" });
    expect(link.getAttribute("href")).toBe("/world-maps/module/mod_aaaaaaaaaaaa/flanaess/review");
  });

  it("a drawn dungeon map's notice links to the module's maps", async () => {
    const drawing: Conversion = {
      ...running,
      kind: "dungeon-map",
      title: "The kobold warren",
      step: "drawing",
      steps: { index: 1, count: 1 },
      target: { module_id: "mod_aaaaaaaaaaaa" },
    };
    listed = [drawing];
    renderNav();
    await screen.findByRole("img", { name: "A conversion is running" });
    listed = [{ ...drawing, status: "done" }];
    act(() => heard.conversion?.forEach((h) => h({ id: running.id, status: "done", step: "drawing", done: 1, total: 1 })));
    const link = await screen.findByRole("link", { name: "See the drafts" });
    expect(link.getAttribute("href")).toBe("/modules/mod_aaaaaaaaaaaa?tab=maps");
  });

  it("on a phone, More opens the whole nav as a sheet, which a link, Escape or a tap beside it closes (DEL-188)", async () => {
    function WithMenu() {
      const [open, setOpen] = useState(false);
      return (
        <NavMenuContext.Provider value={{ open, setOpen }}>
          <Nav account={null} />
          <Link to="/modules">elsewhere</Link>
        </NavMenuContext.Provider>
      );
    }
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    const router = createMemoryRouter([{ path: "*", element: <WithMenu /> }], { initialEntries: ["/campaigns"] });
    render(
      <QueryClientProvider client={client}>
        <I18nProvider language="en">
          <EventsContext.Provider value={subscribe}>
            <RouterProvider router={router} />
          </EventsContext.Provider>
        </I18nProvider>
      </QueryClientProvider>,
    );
    const nav = await screen.findByRole("navigation", { name: "Areas" });
    // The bar's four, then the rest under More.
    const items = Array.from(nav.querySelectorAll("li"));
    expect(items.map((li) => li.className)).toEqual(["", "", "", "", "nav-extra", "nav-extra", "nav-extra", "nav-extra", "nav-extra", "nav-more-item"]);
    const more = within(nav).getByTestId("nav-more");
    expect([more.textContent, more.getAttribute("aria-expanded")]).toEqual(["More", "false"]);
    fireEvent.click(more);
    expect(nav.className).toBe("nav menu-open");
    expect([more.textContent, more.getAttribute("aria-expanded")]).toEqual(["Close", "true"]);
    fireEvent.keyDown(window, { key: "Escape" });
    expect(nav.className).toBe("nav");
    fireEvent.click(more);
    fireEvent.click(screen.getByTestId("nav-backdrop"));
    expect(nav.className).toBe("nav");
    fireEvent.click(more);
    fireEvent.click(screen.getByRole("link", { name: "elsewhere" }));
    await waitFor(() => expect(nav.className).toBe("nav"));
  });
});
