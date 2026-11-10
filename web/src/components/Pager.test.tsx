import { fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter, useLocation } from "react-router-dom";
import { describe, expect, it } from "vitest";
import { I18nProvider } from "../i18n";
import { usePages } from "./Pager";

function List({ items, size }: { items: number[]; size?: number }) {
  const { shown, pager } = usePages(items, size);
  return (
    <>
      <ul>
        {shown.map((n) => (
          <li key={n}>{n}</li>
        ))}
      </ul>
      {pager}
    </>
  );
}

const numbers = (n: number) => Array.from({ length: n }, (_, i) => i + 1);
const listed = () => screen.queryAllByRole("listitem").map((li) => Number(li.textContent));

function renderList(items: number[], size?: number) {
  return render(
    <I18nProvider language="en">
      <List items={items} size={size} />
    </I18nProvider>,
  );
}

describe("usePages", () => {
  it("shows no pager when everything fits on one page", () => {
    renderList(numbers(20));
    expect(listed()).toEqual(numbers(20));
    expect(screen.queryByRole("navigation")).toBeNull();
  });

  it("pages through 45 rows by 20, and says which ones show", () => {
    renderList(numbers(45));
    const pager = screen.getByRole("navigation");
    expect(listed()).toEqual(numbers(20));
    expect(pager.textContent).toContain("1–20 of 45");
    expect((screen.getByRole("button", { name: "Previous" }) as HTMLButtonElement).disabled).toBe(true);
    fireEvent.click(screen.getByRole("button", { name: "Next" }));
    expect(listed()).toEqual(numbers(40).slice(20));
    fireEvent.click(screen.getByRole("button", { name: "Next" }));
    expect(listed()).toEqual([41, 42, 43, 44, 45]);
    expect(pager.textContent).toContain("41–45 of 45");
    expect((screen.getByRole("button", { name: "Next" }) as HTMLButtonElement).disabled).toBe(true);
    fireEvent.click(screen.getByRole("button", { name: "Previous" }));
    expect(listed()[0]).toBe(21);
  });

  it("takes a page size", () => {
    renderList(numbers(12), 5);
    expect(listed()).toEqual([1, 2, 3, 4, 5]);
    expect(screen.getByRole("navigation").textContent).toContain("1–5 of 12");
  });

  it("stays on a page that still exists when rows go away", () => {
    const { rerender } = renderList(numbers(45));
    fireEvent.click(screen.getByRole("button", { name: "Next" }));
    fireEvent.click(screen.getByRole("button", { name: "Next" }));
    rerender(
      <I18nProvider language="en">
        <List items={numbers(30)} />
      </I18nProvider>,
    );
    expect(listed()).toEqual(numbers(30).slice(20));
  });

  it("keeps the page in the address when given a parameter, and reads it back", () => {
    function Where() {
      return <p data-testid="where">{useLocation().search}</p>;
    }
    function Addressed() {
      const { shown, pager } = usePages(numbers(45), 20, undefined, { param: "page" });
      return (
        <>
          <ul>
            {shown.map((n) => (
              <li key={n}>{n}</li>
            ))}
          </ul>
          {pager}
          <Where />
        </>
      );
    }
    render(
      <MemoryRouter initialEntries={["/x?page=3&tab=a"]}>
        <I18nProvider language="en">
          <Addressed />
        </I18nProvider>
      </MemoryRouter>,
    );
    expect(listed()).toEqual([41, 42, 43, 44, 45]);
    fireEvent.click(screen.getByRole("button", { name: "Previous" }));
    expect(listed()[0]).toBe(21);
    expect(screen.getByTestId("where").textContent).toBe("?page=2&tab=a");
    fireEvent.click(screen.getByRole("button", { name: "Previous" }));
    expect(screen.getByTestId("where").textContent).toBe("?tab=a");
  });

  it("reads a page number that is out of range or not a number as the nearest page", () => {
    function Addressed() {
      const { shown } = usePages(numbers(45), 20, undefined, { param: "page" });
      return <ul>{shown.map((n) => <li key={n}>{n}</li>)}</ul>;
    }
    for (const [search, first] of [["?page=99", 41], ["?page=0", 1], ["?page=abc", 1]] as const) {
      const { unmount } = render(
        <MemoryRouter initialEntries={[`/x${search}`]}>
          <I18nProvider language="en">
            <Addressed />
          </I18nProvider>
        </MemoryRouter>,
      );
      expect(listed()[0]).toBe(first);
      unmount();
    }
  });
});
