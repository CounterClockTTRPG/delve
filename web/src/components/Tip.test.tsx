import { act, render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import Tip from "./Tip";

describe("Tip", () => {
  it("names an icon button when the keyboard reaches it, and keeps the button's own name", async () => {
    render(
      <Tip label="Move Ash up">
        <button type="button" aria-label="Move Ash up">
          ↑
        </button>
      </Tip>,
    );
    const button = screen.getByRole("button", { name: "Move Ash up" });
    act(() => button.focus());
    expect((await screen.findByRole("tooltip")).textContent).toBe("Move Ash up");
    act(() => button.blur());
    expect(screen.getByRole("button", { name: "Move Ash up" })).toBe(button);
  });
});
