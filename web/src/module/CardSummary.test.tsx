import { fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import CardSummary from "./CardSummary";

/** jsdom lays nothing out: a summary is "cut off" when its scrollHeight (all of it) is more than its clientHeight. */
function laidOut(scrollHeight: number, clientHeight: number) {
  vi.spyOn(HTMLElement.prototype, "scrollHeight", "get").mockReturnValue(scrollHeight);
  vi.spyOn(HTMLElement.prototype, "clientHeight", "get").mockReturnValue(clientHeight);
}

afterEach(() => vi.restoreAllMocks());

describe("CardSummary", () => {
  it("offers no More when the summary fits its two lines", () => {
    laidOut(36, 36);
    render(<CardSummary text="Smugglers in a haunted house." />);
    expect(screen.getByText("Smugglers in a haunted house.")).toBeTruthy();
    expect(screen.queryByRole("button")).toBeNull();
  });

  it("opens a cut-off summary with More, and closes it with Less", () => {
    laidOut(90, 36);
    render(<CardSummary text="A long summary that runs on well past its two lines." />);
    const more = screen.getByRole("button", { name: "More" });
    expect(more.getAttribute("aria-expanded")).toBe("false");
    const text = screen.getByText(/A long summary/);
    expect(text.className).not.toContain("is-open");
    fireEvent.click(more);
    expect(text.className).toContain("is-open");
    const less = screen.getByRole("button", { name: "Less" });
    expect(less.getAttribute("aria-expanded")).toBe("true");
    fireEvent.click(less);
    expect(text.className).not.toContain("is-open");
    expect(screen.getByRole("button", { name: "More" })).toBeTruthy();
  });

  it("opens and closes with a click on the text too", () => {
    laidOut(90, 36);
    render(<CardSummary text="A long summary that runs on well past its two lines." />);
    const text = screen.getByText(/A long summary/);
    fireEvent.click(text);
    expect(text.className).toContain("is-open");
    fireEvent.click(text);
    expect(text.className).not.toContain("is-open");
  });
});
