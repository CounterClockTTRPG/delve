import { fireEvent, render, screen, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { I18nProvider } from "../i18n";
import PendingActs from "./PendingActs";
import type { PendingAct } from "./api";

const ME = "seat_00000000000a";
const BO = "seat_00000000000b";

function pending(seat: string, name: string, text: string, overrides: Partial<PendingAct> = {}): PendingAct {
  return { seat_id: seat, name, kind: "act", text, characters: [], private: false, at: "2026-10-18T20:00:00Z", ...overrides };
}

function shown(acts: PendingAct[], onChange = vi.fn()) {
  render(
    <I18nProvider language="en">
      <PendingActs pending={acts} mySeatId={ME} names={{ chr_1: "Mira" }} onChange={onChange} />
    </I18nProvider>,
  );
  return onChange;
}

describe("PendingActs", () => {
  it("lists the seat's own act first, with Change, and the others' as drafts", () => {
    const onChange = shown([
      pending(BO, "Bo", "I keep watch.", { characters: ["chr_1"] }),
      pending(ME, "Ana", "I pocket the gem.", { private: true }),
    ]);
    const list = screen.getByTestId("pending-acts");
    expect(list.firstElementChild?.getAttribute("data-testid")).toBe("my-act");
    const mine = screen.getByTestId("my-act");
    expect(mine.textContent).toContain("Your act: I pocket the gem.");
    expect(within(mine).getByTestId("private-act").textContent).toBe("Only the DM");
    const theirs = screen.getByTestId("pending-act");
    expect(theirs.textContent).toContain("Bo · Mira");
    expect(theirs.textContent).toContain("draft");
    expect(theirs.textContent).toContain("I keep watch.");

    fireEvent.click(within(mine).getByRole("button", { name: "Change" }));
    expect(onChange).toHaveBeenCalledWith({ text: "I pocket the gem.", private: true, hotseat: null });
  });

  it("shows a pass without Change, and nothing without pending acts", () => {
    shown([pending(ME, "Ana", "", { kind: "pass" }), pending(BO, "Bo", "", { kind: "pass" })]);
    expect(screen.getByTestId("my-act").textContent).toContain("You pass this beat.");
    expect(within(screen.getByTestId("my-act")).queryByRole("button")).toBeNull();
    expect(screen.getByTestId("pending-act").textContent).toContain("passes");
  });

  it("shows each hotseat player's act under their name, and Change hands back their turn (DEL-365)", () => {
    const onChange = shown([
      pending(ME, "Anna", "I listen.", { hotseat: "hs_anna" }),
      pending(ME, "Ben", "", { kind: "pass", hotseat: "hs_ben" }),
    ]);
    const [anna, ben] = screen.getAllByTestId("my-act");
    expect(anna.textContent).toContain("Anna");
    expect(anna.textContent).toContain("Your act: I listen.");
    expect(ben.textContent).toContain("Ben");
    fireEvent.click(within(anna).getByRole("button", { name: "Change" }));
    expect(onChange).toHaveBeenCalledWith({ text: "I listen.", private: false, hotseat: "hs_anna" });
  });

  it("renders nothing for an empty list (an observer's)", () => {
    shown([]);
    expect(screen.queryByTestId("pending-acts")).toBeNull();
  });
});
