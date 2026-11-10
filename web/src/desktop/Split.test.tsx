import { render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { I18nProvider } from "../i18n";
import ListAndEditor from "./ListAndEditor";
import Split from "./Split";
import { safeStorage } from "./storage";

function wide(matches: boolean) {
  vi.stubGlobal(
    "matchMedia",
    (query: string) => ({ matches, media: query, addEventListener: () => {}, removeEventListener: () => {} }) as unknown as MediaQueryList,
  );
}

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
  localStorage.clear();
});

describe("Split", () => {
  it("shows both panes with a labelled divider between them", () => {
    render(
      <I18nProvider language="en">
        <Split id="test" start={{ size: 30, min: 100, children: <p>left</p> }} end={{ size: 70, min: 100, children: <p>right</p> }} />
      </I18nProvider>,
    );
    expect(screen.getByText("left")).toBeTruthy();
    expect(screen.getByText("right")).toBeTruthy();
    const divider = screen.getByRole("separator", { name: "Resize the panes" });
    expect(divider.getAttribute("title")).toBe("Drag to resize · double-click to reset");
  });

  it("still opens when the browser's storage throws", () => {
    vi.spyOn(Storage.prototype, "getItem").mockImplementation(() => {
      throw new Error("blocked");
    });
    render(
      <I18nProvider language="nl">
        <Split id="test" start={{ size: 50, min: 100, children: <p>left</p> }} end={{ size: 50, min: 100, children: <p>right</p> }} />
      </I18nProvider>,
    );
    expect(screen.getByRole("separator", { name: "Breedte van de panelen" })).toBeTruthy();
  });
});

describe("safeStorage", () => {
  it("reads nothing and keeps nothing when storage throws", () => {
    vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => {
      throw new Error("full");
    });
    vi.spyOn(Storage.prototype, "getItem").mockImplementation(() => {
      throw new Error("blocked");
    });
    expect(() => safeStorage.setItem("k", "v")).not.toThrow();
    expect(safeStorage.getItem("k")).toBeNull();
  });
});

describe("ListAndEditor", () => {
  it("is a split from 900 px", () => {
    wide(true);
    render(
      <I18nProvider language="en">
        <ListAndEditor id="texts" className="module-texts">
          <aside>list</aside>
          <section>editor</section>
        </ListAndEditor>
      </I18nProvider>,
    );
    expect(screen.getByRole("separator")).toBeTruthy();
  });

  it("is the page's grid under 900 px", () => {
    wide(false);
    const { container } = render(
      <I18nProvider language="en">
        <ListAndEditor id="texts" className="module-texts">
          <aside>list</aside>
          <section>editor</section>
        </ListAndEditor>
      </I18nProvider>,
    );
    expect(screen.queryByRole("separator")).toBeNull();
    expect(container.querySelector(".module-texts")?.children).toHaveLength(2);
  });
});
