import { fireEvent, render, screen, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { I18nProvider } from "../i18n";
import type { Doubt, Reading } from "./importApi";
import ReviewPanel from "./ReviewPanel";

function doubt(id: string, kind: string, alternatives: string[], overrides: Partial<Doubt> = {}): Doubt {
  return {
    id,
    kind,
    ref: `label-${id}`,
    message: `Doubt ${id}`,
    reading: alternatives[0] ?? "",
    alternatives,
    resolved: false,
    choice: null,
    data: { at: [10, 10] },
    ...overrides,
  };
}

export function reading(overrides: Partial<Reading> = {}): Reading {
  return {
    clusters: [
      { id: 0, colour: [40, 120, 40], cells: [0, 1, 2], suggestion: "forest", terrain: "forest" },
      { id: 1, colour: [240, 230, 200], cells: [3], suggestion: null, terrain: null },
    ],
    doubts: [
      doubt("d1", "cluster-unmapped", [], { ref: "1", message: "Colour 1 has no terrain." }),
      doubt("d2", "label-unpaired", ["place", "river-name", "drop"], { message: "HARDBY has no symbol near it." }),
      doubt("d3", "label-unpaired", ["river-name", "place", "region-name", "drop"], { message: "SELINTAN is alone." }),
      doubt("d4", "water-kind-guessed", ["sea", "lake"], { message: "Is this water a sea?" }),
      doubt("d5", "label-unpaired", ["place", "drop"], { resolved: true, choice: "place", message: "OAKTON was decided." }),
    ],
    ...overrides,
  };
}

function renderPanel(shown: Reading, handlers: Partial<Parameters<typeof ReviewPanel>[0]> = {}) {
  const props = { reading: shown, onReview: vi.fn(), onAccept: vi.fn(), onSelect: vi.fn(), busy: false, ...handlers };
  render(
    <I18nProvider language="en">
      <ReviewPanel {...props} />
    </I18nProvider>,
  );
  return props;
}

describe("ReviewPanel", () => {
  it("says what a mixed cell and a guessed river were read as: the colour, and which way it flows (DEL-94)", () => {
    const { container } = render(
      <I18nProvider language="en">
        <ReviewPanel
          reading={reading({
            doubts: [
              doubt("m1", "cell-mixed", ["keep", "forest", "~"], { reading: "0", ref: "cell:4" }),
              doubt("r1", "river-flow-guessed", ["keep", "reverse"], { data: { at: [1, 1], flows: ["lake", "sea"] } }),
              doubt("r2", "river-flow-guessed", ["keep", "reverse"]),
            ],
          })}
          onReview={vi.fn()}
          onAccept={vi.fn()}
          onSelect={vi.fn()}
          busy={false}
        />
      </I18nProvider>,
    );
    const mixed = container.querySelector('[data-doubt="m1"]') as HTMLElement;
    expect(within(mixed).getByText("Read as: Colour 1")).toBeTruthy();
    expect((mixed.querySelector("p span") as HTMLElement).style.background).toBe("rgb(40, 120, 40)");
    expect(within(mixed).getByRole("button", { name: "Forest" })).toBeTruthy();
    expect(within(container.querySelector('[data-doubt="r1"]') as HTMLElement).getByText("Read as: from the lake to the sea")).toBeTruthy();
    // A map read before the reader named the ends keeps the plain line.
    expect(within(container.querySelector('[data-doubt="r2"]') as HTMLElement).getByText("Read as: Keep")).toBeTruthy();
  });

  it("lists the doubts first, in the server's order, then the colours", () => {
    renderPanel(reading());
    const headings = screen.getAllByRole("heading").map((h) => h.textContent);
    expect(headings.indexOf("Doubtful readings")).toBeLessThan(headings.indexOf("Colours"));
    const items = screen.getAllByRole("listitem").map((li) => li.getAttribute("data-doubt") ?? li.getAttribute("data-cluster"));
    expect(items.filter(Boolean)).toEqual(["d2", "d3", "d5", "d4", "0", "1"]);
    // A colour's doubt is decided by its terrain picker, not in the list.
    expect(screen.queryByText("Colour 1 has no terrain.")).toBeNull();
    expect(screen.getByText("Decided: A place")).toBeTruthy();
  });

  it("sends one decision for one doubt", () => {
    const { onReview } = renderPanel(reading());
    const item = screen.getByText("SELINTAN is alone.").closest("li")!;
    fireEvent.click(within(item).getByRole("button", { name: "A river's name" }));
    expect(onReview).toHaveBeenCalledWith({ decisions: { d3: "river-name" } });
    fireEvent.click(within(item).getByRole("button", { name: "Drop" }));
    expect(onReview).toHaveBeenLastCalledWith({ decisions: { d3: "drop" } });
  });

  it("decides all of a kind with a choice its doubts share", () => {
    const { onReview } = renderPanel(reading());
    const group = screen.getByRole("group", { name: "Labels without a place (3)" });
    const choice = within(group).getByLabelText("For every one of them") as HTMLSelectElement;
    // d2 and d3 are still open, and share place, river-name and drop; region-name is d3's alone.
    expect(Array.from(choice.options).map((o) => o.value)).toEqual(["place", "river-name", "drop", "keep"]);
    fireEvent.change(choice, { target: { value: "drop" } });
    fireEvent.click(within(group).getByRole("button", { name: "Decide all of this kind" }));
    expect(onReview).toHaveBeenCalledWith({ kinds: { "label-unpaired": "drop" } });
  });

  it("flies to a doubt when it is selected", () => {
    const { onSelect } = renderPanel(reading());
    fireEvent.click(screen.getByRole("button", { name: "HARDBY has no symbol near it." }));
    expect(onSelect).toHaveBeenCalledWith(expect.objectContaining({ id: "d2" }));
  });

  it("maps a colour to a terrain, with the suggestion shown, or to outside the map", () => {
    const { onReview } = renderPanel(reading());
    const first = screen.getByRole("listitem", { name: "Colour 1" });
    expect(within(first).getByText("Suggested: Forest")).toBeTruthy();
    const picker = within(screen.getByRole("listitem", { name: "Colour 2" })).getByRole("combobox") as HTMLSelectElement;
    const options = Array.from(picker.options);
    expect(options[options.length - 1].textContent).toBe("Outside the map");
    fireEvent.change(picker, { target: { value: "outside" } });
    expect(onReview).toHaveBeenCalledWith({ clusters: { "1": "outside" } });
  });

  it("keeps Accept disabled, with the reason, while a colour has no terrain", () => {
    renderPanel(reading());
    const button = screen.getByRole("button", { name: "Accept the map" }) as HTMLButtonElement;
    expect(button.disabled).toBe(true);
    expect(screen.getByText("Give every colour a terrain first.")).toBeTruthy();
  });

  it("enables Accept once the last colour is outside the map", () => {
    const shown = reading();
    shown.clusters[1].terrain = "outside";
    const { onAccept } = renderPanel(shown);
    const button = screen.getByRole("button", { name: "Accept the map" }) as HTMLButtonElement;
    expect(button.disabled).toBe(false);
    expect(screen.queryByText("Give every colour a terrain first.")).toBeNull();
    fireEvent.click(button);
    expect(onAccept).toHaveBeenCalled();
  });
});
