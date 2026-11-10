import { render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import PickList, { VIRTUAL_FROM } from "./PickList";

const rows = (n: number) => Array.from({ length: n }, (_, i) => ({ id: `e${i}`, name: `Encounter ${i}` }));

afterEach(() => vi.restoreAllMocks());

describe("PickList", () => {
  it("draws every row of a short list", () => {
    render(<PickList items={rows(VIRTUAL_FROM - 1)} keyOf={(r) => r.id} render={(r) => <button>{r.name}</button>} />);
    expect(screen.getAllByRole("button")).toHaveLength(VIRTUAL_FROM - 1);
    expect(screen.queryByTestId("pick-list-scroll")).toBeNull();
  });

  it("draws only the rows in view of a long one, in its own scroll box", () => {
    // jsdom lays nothing out: the scroll box is given a screen's height.
    vi.spyOn(HTMLElement.prototype, "clientHeight", "get").mockReturnValue(600);
    vi.spyOn(HTMLElement.prototype, "offsetHeight", "get").mockReturnValue(36);
    vi.spyOn(HTMLElement.prototype, "clientWidth", "get").mockReturnValue(300);
    render(<PickList items={rows(384)} keyOf={(r) => r.id} render={(r) => <button>{r.name}</button>} />);
    expect(screen.getByTestId("pick-list-scroll")).toBeTruthy();
    const drawn = screen.getAllByRole("button");
    expect(drawn.length).toBeGreaterThan(0);
    expect(drawn.length).toBeLessThan(60);
    expect(screen.getByText("Encounter 0")).toBeTruthy();
    expect(screen.queryByText("Encounter 383")).toBeNull();
  });
});
