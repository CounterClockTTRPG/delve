import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import PartySidebar from "./PartySidebar";
import PregenPicker from "./PregenPicker";
import { base, json, renderWith, stubFetch } from "./testing";

afterEach(() => {
  vi.unstubAllGlobals();
});

const PREGENS = {
  pregens: [
    { id: "ned", name: "Ned", race: "Human", class: "Fighter/Thief", level: "3/3", gear: [] },
    { id: "ian", name: "Ian", race: "Elf", class: "Mage", level: 3 },
    { id: "tom", name: "Tom", race: "Dwarf", class: "Fighter", level: 2 },
  ],
};

describe("PregenPicker", () => {
  it("asks the DM to make the pregens ticked, none at first, and says a beat makes them (DEL-187)", async () => {
    stubFetch({ [`GET ${base}/pregens`]: () => json(200, PREGENS) });
    const onAct = vi.fn();
    renderWith(<PregenPicker campaignId="cmp_00000000000a" onAct={onAct} />);

    const ned = await screen.findByRole("checkbox", { name: /Ned/ });
    expect(screen.getByText("Human Fighter/Thief, level 3/3")).toBeTruthy();
    expect(screen.getAllByRole("checkbox").every((box) => !(box as HTMLInputElement).checked)).toBe(true);
    const make = screen.getByRole("button", { name: "Ask the DM to make them" }) as HTMLButtonElement;
    expect(make.disabled).toBe(true);
    expect(screen.getByText("Tick the characters you want.")).toBeTruthy();
    fireEvent.click(ned);
    fireEvent.click(screen.getByRole("checkbox", { name: /Tom/ }));
    expect(screen.getByText("The DM makes the ticked characters in a beat of the story.")).toBeTruthy();
    fireEvent.click(make);

    expect(onAct).toHaveBeenCalledWith("Create the party from the module's pregenerated characters: Ned, Tom.");
  });

  it("waits, and says why, while the table can't act", async () => {
    stubFetch({ [`GET ${base}/pregens`]: () => json(200, { pregens: [PREGENS.pregens[0]] }) });
    renderWith(<PregenPicker campaignId="cmp_00000000000a" onAct={vi.fn()} blocked="Start the session first." />);
    fireEvent.click(await screen.findByRole("checkbox", { name: /Ned/ }));
    expect((screen.getByRole("button", { name: "Ask the DM to make them" }) as HTMLButtonElement).disabled).toBe(true);
    expect(screen.getByText("Start the session first.")).toBeTruthy();
  });

  it("in the party's empty state, for the host only; without pregens the line stays", async () => {
    const fetchMock = stubFetch({ [`GET ${base}/pregens`]: () => json(200, PREGENS) });
    const onPregens = vi.fn();
    const { unmount } = renderWith(
      <PartySidebar campaignId="cmp_00000000000a" party={[]} onOpenSheet={vi.fn()} onPregens={onPregens} />,
    );
    expect(await screen.findByRole("checkbox", { name: /Tom/ })).toBeTruthy();
    expect(screen.getByText("No characters yet. Choose one, or ask the DM to make one.")).toBeTruthy();
    unmount();

    // A player's sidebar never asks for them.
    fetchMock.mockClear();
    const { unmount: gone } = renderWith(<PartySidebar campaignId="cmp_00000000000a" party={[]} onOpenSheet={vi.fn()} />);
    expect(screen.getByText("No characters yet. Choose one, or ask the DM to make one.")).toBeTruthy();
    expect(fetchMock).not.toHaveBeenCalled();
    gone();

    stubFetch({ [`GET ${base}/pregens`]: () => json(200, { pregens: [] }) });
    renderWith(<PartySidebar campaignId="cmp_00000000000a" party={[]} onOpenSheet={vi.fn()} onPregens={onPregens} />);
    await waitFor(() => expect(screen.getByText("No characters yet. Choose one, or ask the DM to make one.")).toBeTruthy());
    expect(screen.queryByRole("button", { name: "Ask the DM to make them" })).toBeNull();
  });

  it("tells the host when the party's level is outside the module's (DEL-187)", () => {
    renderWith(
      <PartySidebar campaignId="cmp_00000000000a" party={[]} onOpenSheet={vi.fn()} levelFit={{ min: 3, max: 8, party: 1 }} />,
    );
    expect(screen.getByTestId("level-fit").textContent).toBe("The module is written for levels 3 to 8; the party is level 1.");
  });

  it("puts the levels notice away with its X, until the numbers change (DEL-345)", () => {
    localStorage.clear();
    const view = renderWith(
      <PartySidebar campaignId="cmp_00000000000a" party={[]} onOpenSheet={vi.fn()} levelFit={{ min: 2, max: 4, party: 1 }} />,
    );
    fireEvent.click(within(screen.getByTestId("level-fit")).getByRole("button", { name: "Dismiss" }));
    expect(screen.queryByTestId("level-fit")).toBeNull();
    view.unmount();
    renderWith(
      <PartySidebar campaignId="cmp_00000000000a" party={[]} onOpenSheet={vi.fn()} levelFit={{ min: 2, max: 4, party: 1 }} />,
    );
    expect(screen.queryByTestId("level-fit")).toBeNull();
    renderWith(
      <PartySidebar campaignId="cmp_00000000000a" party={[]} onOpenSheet={vi.fn()} levelFit={{ min: 2, max: 4, party: 5 }} />,
    );
    expect(screen.getByTestId("level-fit").textContent).toContain("the party is level 5");
  });
});
