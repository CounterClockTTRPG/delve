import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen } from "@testing-library/react";
import type { ReactNode } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { I18nProvider } from "../i18n";
import ProvenanceNotice, { provenanceOf } from "./ProvenanceNotice";

const MODULE = "mod_1";
const SKETCH = "# Sketched from the room key: an invented layout. The book's map is asset:map-page-3.\nmap \"x\" {}\n";
const BOOK = "# Drawn from the book's map asset:map-page-35.\nmap \"x\" {}\n";
const DESCRIBED = "# Drawn from a description.\nmap \"x\" {}\n";

function renderWith(node: ReactNode) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <I18nProvider language="en">{node}</I18nProvider>
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  vi.stubGlobal("fetch", vi.fn(async () => new Response("[]", { status: 200, headers: { "Content-Type": "application/json" } })));
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("provenanceOf", () => {
  it("reads a sketch, a book draft and a description draft from the first line", () => {
    expect(provenanceOf(SKETCH)).toEqual({ kind: "sketched", page: "map-page-3" });
    expect(provenanceOf("# Sketched from the room key: an invented layout. No map page was found in the book.\n")).toEqual({
      kind: "sketched",
      page: null,
    });
    expect(provenanceOf(BOOK)).toEqual({ kind: "book", page: "map-page-35" });
    expect(provenanceOf(DESCRIBED)).toEqual({ kind: "described", page: null });
  });

  it("is null for an ordinary map", () => {
    expect(provenanceOf('map "Crypt" {\n  grid 10 x 10\n}\n')).toBeNull();
    expect(provenanceOf("")).toBeNull();
    expect(provenanceOf("# A comment\n# Drawn from the book's map asset:map-page-1.\n")).toBeNull();
  });
});

describe("ProvenanceNotice", () => {
  it("is one line, with its full text in its title", () => {
    renderWith(<ProvenanceNotice moduleId={MODULE} source={BOOK} mapName="ship" />);
    const note = screen.getByRole("note");
    const lines = note.querySelectorAll("p");
    expect(lines).toHaveLength(1);
    expect(lines[0].getAttribute("title")).toBe("Drawn by Claude from the book's page");
    expect(screen.getByText("Drawn by Claude from the book's page")).toBeTruthy();
  });

  it("links to the book's page without a toggle", () => {
    renderWith(<ProvenanceNotice moduleId={MODULE} source={BOOK} mapName="ship" />);
    expect(screen.getByRole("link", { name: "Show the book's page" }).getAttribute("href")).toBe(
      `/api/modules/${MODULE}/assets/map-page-35`,
    );
    // A drawn map isn't a sketch: it isn't offered to be drawn again.
    expect(screen.queryByRole("button", { name: "Draw it from the book's map" })).toBeNull();
  });

  it("toggles the book's page through onShowPage", () => {
    const onShowPage = vi.fn();
    const { rerender } = renderWith(
      <ProvenanceNotice moduleId={MODULE} source={SKETCH} mapName="caves" onShowPage={onShowPage} pageShown={false} />,
    );
    expect(screen.getByText("Sketched from the room key: the layout is invented.")).toBeTruthy();
    expect(screen.getByRole("button", { name: "Draw it from the book's map" })).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Show the book's page" }));
    expect(onShowPage).toHaveBeenCalledWith(true);
    rerender(
      <QueryClientProvider client={new QueryClient()}>
        <I18nProvider language="en">
          <ProvenanceNotice moduleId={MODULE} source={SKETCH} mapName="caves" onShowPage={onShowPage} pageShown />
        </I18nProvider>
      </QueryClientProvider>,
    );
    fireEvent.click(screen.getByRole("button", { name: "Hide the book's page" }));
    expect(onShowPage).toHaveBeenLastCalledWith(false);
  });

  it("names a description draft, with no page", () => {
    renderWith(<ProvenanceNotice moduleId={MODULE} source={DESCRIBED} onShowPage={() => {}} />);
    expect(screen.getByText("Drawn from a description")).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Show the book's page" })).toBeNull();
  });

  it("shows nothing for an ordinary map", () => {
    const { container } = renderWith(<ProvenanceNotice moduleId={MODULE} source={'map "x" {}\n'} />);
    expect(container.textContent).toBe("");
  });
});
