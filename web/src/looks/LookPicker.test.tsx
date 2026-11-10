import { fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import LookPicker from "./LookPicker";
import { LOOK_KEY } from "./looks";

afterEach(() => {
  localStorage.clear();
  delete document.documentElement.dataset.look;
});

describe("LookPicker", () => {
  it("offers the three looks by name, and switches to the one chosen", () => {
    render(<LookPicker />);
    const select = screen.getByLabelText("Look") as HTMLSelectElement;
    expect([...select.options].map((o) => o.textContent)).toEqual(["Delve today", "Gold and wood", "Dark dungeon"]);
    expect(select.value).toBe("delve");
    expect(screen.getByText("For this browser only.")).toBeTruthy();

    fireEvent.change(select, { target: { value: "dark-dungeon" } });

    expect(select.value).toBe("dark-dungeon");
    expect(document.documentElement.dataset.look).toBe("dark-dungeon");
    expect(localStorage.getItem(LOOK_KEY)).toBe("dark-dungeon");
  });

  it("shows a swatch of the chosen look", () => {
    const { container } = render(<LookPicker compact />);
    expect(container.querySelector(".look-swatch")?.getAttribute("data-swatch")).toBe("delve");
    fireEvent.change(screen.getByLabelText("Look"), { target: { value: "gold-wood" } });
    expect(container.querySelector(".look-swatch")?.getAttribute("data-swatch")).toBe("gold-wood");
  });

  it("is compact on the play screen: no hint", () => {
    render(<LookPicker compact />);
    expect(screen.getByLabelText("Look").getAttribute("title")).toBe("Delve today");
    expect(screen.queryByText("For this browser only.")).toBeNull();
  });
});
