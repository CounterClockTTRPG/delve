import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { RouterProvider, createMemoryRouter, useLocation } from "react-router-dom";
import { afterEach, beforeAll, describe, expect, it, vi } from "vitest";
import { I18nProvider } from "../i18n";
import { json, stubFetch } from "../play/testing";
import Desktop from "./Desktop";

beforeAll(() => {
  // cmdk scrolls the chosen item into view; jsdom has no layout.
  Element.prototype.scrollIntoView ??= () => {};
});

afterEach(() => {
  vi.unstubAllGlobals();
});

function Where() {
  const { pathname, hash } = useLocation();
  return <p data-testid="where">{pathname + hash}</p>;
}

function renderDesktop(owner: boolean, extra?: React.ReactNode) {
  stubFetch({
    "GET /api/campaigns": () => json(200, [{ id: "cmp_000000000001", name: "Barrowmaze", players: [], sessions: 0 }]),
    "GET /api/modules": () => json(200, [{ id: "mod_000000000001", title: "The Keep on the Borderlands", maps: [] }]),
    "GET /api/settings": () => json(200, [{ id: "set_greyhawk", title: "Greyhawk" }]),
    "GET /api/rulesets": () => json(200, [{ id: "adnd2e", title: "AD&D 2nd edition" }]),
    "GET /api/rulesets/adnd2e/search?q=web": () =>
      json(200, {
        results: [
          { section: "spells", id: "412", name: "Web" },
          { section: "items", id: "77", name: "Wand of Web" },
        ],
      }),
  });
  const router = createMemoryRouter(
    [
      {
        path: "*",
        element: (
          <>
            <Desktop owner={owner} />
            <Where />
            {extra}
          </>
        ),
      },
    ],
    { initialEntries: ["/campaigns"] },
  );
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <I18nProvider language="en">
        <RouterProvider router={router} />
      </I18nProvider>
    </QueryClientProvider>,
  );
}

const key = (k: string, init: KeyboardEventInit = {}) =>
  act(() => {
    fireEvent.keyDown(document, { key: k, ...init });
    fireEvent.keyUp(document, { key: k, ...init });
  });

describe("Desktop", () => {
  it("Ctrl K opens the palette, and choosing a campaign plays it", async () => {
    renderDesktop(true);
    key("k", { code: "KeyK", ctrlKey: true });
    const input = await screen.findByPlaceholderText("Type a campaign, a module, a setting or an action…");
    expect(await screen.findByText("Play Barrowmaze")).toBeTruthy();
    expect(screen.getByText("The Keep on the Borderlands")).toBeTruthy();
    expect(screen.getByText("Greyhawk")).toBeTruthy();

    fireEvent.change(input, { target: { value: "play barrow" } });
    fireEvent.click(screen.getByText("Play Barrowmaze"));
    await waitFor(() => expect(screen.getByTestId("where").textContent).toBe("/play/cmp_000000000001"));
    expect(screen.queryByPlaceholderText("Type a campaign, a module, a setting or an action…")).toBeNull();
  });

  it("New campaign opens the campaigns page at its form", async () => {
    renderDesktop(true);
    key("k", { code: "KeyK", ctrlKey: true });
    fireEvent.click(await screen.findByText("New campaign"));
    await waitFor(() => expect(screen.getByTestId("where").textContent).toBe("/campaigns#new-campaign"));
  });

  it("g then m goes to the modules", async () => {
    renderDesktop(true);
    key("g", { code: "KeyG" });
    key("m", { code: "KeyM" });
    await waitFor(() => expect(screen.getByTestId("where").textContent).toBe("/modules"));
  });

  it("g then b goes to the Rulesets area", async () => {
    renderDesktop(true);
    key("g", { code: "KeyG" });
    key("b", { code: "KeyB" });
    await waitFor(() => expect(screen.getByTestId("where").textContent).toBe("/rulesets"));
  });

  it("typing in the palette lists the rulesets' entries, and choosing one opens it", async () => {
    renderDesktop(true);
    key("k", { code: "KeyK", ctrlKey: true });
    const input = await screen.findByPlaceholderText("Type a campaign, a module, a setting or an action…");
    fireEvent.change(input, { target: { value: "w" } });
    // One character asks nothing.
    expect(screen.queryByRole("group", { name: "Rulesets" })).toBeNull();
    fireEvent.change(input, { target: { value: "web" } });
    const group = await screen.findByRole("group", { name: "Rulesets" });
    expect(await within(group).findByText("Wand of Web")).toBeTruthy();
    fireEvent.click(within(group).getByText("Web"));
    await waitFor(() => expect(screen.getByTestId("where").textContent).toBe("/rulesets/adnd2e/spells/412"));
  });

  it("? lists the shortcuts; a seat's list has nowhere to go", async () => {
    renderDesktop(false);
    key("?", { code: "Slash", shiftKey: true });
    expect(await screen.findByRole("dialog", { name: "Keyboard shortcuts" })).toBeTruthy();
    expect(screen.getByText("Type in the story's input box")).toBeTruthy();
    expect(screen.queryByText("Go anywhere: campaigns, modules, settings, actions")).toBeNull();
    expect(screen.queryByText("g c")).toBeNull();
  });

  it("a seat has no palette and no g sequences", async () => {
    renderDesktop(false);
    key("k", { code: "KeyK", ctrlKey: true });
    key("g", { code: "KeyG" });
    key("m", { code: "KeyM" });
    expect(screen.queryByPlaceholderText("Type a campaign, a module, a setting or an action…")).toBeNull();
    expect(screen.getByTestId("where").textContent).toBe("/campaigns");
  });

  it("/ puts the cursor in the composer, and typing / there stays text", async () => {
    renderDesktop(
      false,
      <form data-testid="composer">
        <textarea aria-label="act" />
      </form>,
    );
    const box = screen.getByLabelText("act");
    key("/", { code: "Slash" });
    expect(document.activeElement).toBe(box);
    // In the box, ? and g are text: no help opens.
    act(() => {
      fireEvent.keyDown(box, { key: "?", code: "Slash", shiftKey: true });
    });
    expect(screen.queryByRole("dialog")).toBeNull();
  });
});
