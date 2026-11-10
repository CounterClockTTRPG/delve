import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { I18nProvider } from "../i18n";
import HotseatTurns, { hotseatTurns, nextTurn, turnsTaken, type Turn } from "./HotseatTurns";
import type { Hotseat, PendingAct } from "./api";

const HOST = "seat_00000000000h";
const hotseat: Hotseat = {
  on: true,
  seat_id: HOST,
  players: [
    { id: "hs_anna", name: "Anna", characters: ["chr_a"] },
    { id: "hs_ben", name: "Ben", characters: ["chr_b"] },
  ],
};

function act(hotseatId: string | null, seat = HOST): PendingAct {
  return { seat_id: seat, name: "", kind: "act", text: "x", characters: [], private: false, at: "", hotseat: hotseatId };
}

describe("hotseat turns (DEL-365)", () => {
  it("are the players', then the host's own characters besides theirs", () => {
    expect(hotseatTurns(hotseat, HOST, ["chr_a", "chr_b", "chr_c"], "Raf")).toEqual([
      { id: "hs_anna", name: "Anna", characters: ["chr_a"] },
      { id: "hs_ben", name: "Ben", characters: ["chr_b"] },
      { id: null, name: "Raf", characters: ["chr_c"] },
    ]);
    expect(hotseatTurns(hotseat, HOST, ["chr_a", "chr_b"], "Raf")?.map((t) => t.id)).toEqual(["hs_anna", "hs_ben"]);
  });

  it("are no other screen's, and none while hotseat is off or has no players", () => {
    expect(hotseatTurns(hotseat, "seat_00000000000x", [], "Ana")).toBeNull();
    expect(hotseatTurns({ ...hotseat, on: false }, HOST, [], "Raf")).toBeNull();
    expect(hotseatTurns({ ...hotseat, players: [] }, HOST, [], "Raf")).toBeNull();
    expect(hotseatTurns(undefined, HOST, [], "Raf")).toBeNull();
  });

  it("go round to the next player who hasn't had theirs", () => {
    const turns = hotseatTurns(hotseat, HOST, ["chr_a", "chr_b", "chr_c"], "Raf") as Turn[];
    const taken = turnsTaken([act("hs_anna"), act(null, "seat_other")], HOST);
    expect([...taken]).toEqual(["hs_anna"]);
    expect(nextTurn(turns, taken, "hs_anna")).toBe("hs_ben");
    expect(nextTurn(turns, new Set(["hs_anna", "hs_ben"]), "hs_ben")).toBeNull();
    expect(nextTurn(turns, new Set(["hs_ben", null]), null)).toBe("hs_anna");
    expect(nextTurn(turns, new Set(["hs_anna", "hs_ben", null]), "hs_ben"), "all done: it stays").toBe("hs_ben");
  });

  it("show whose turn it is, tick those taken, and hand the box over on a click", () => {
    const onPick = vi.fn();
    const turns = hotseatTurns(hotseat, HOST, ["chr_a", "chr_b"], "Raf") as Turn[];
    render(
      <I18nProvider language="en">
        <HotseatTurns turns={turns} taken={new Set(["hs_anna"])} current="hs_ben" onPick={onPick} />
      </I18nProvider>,
    );
    const [anna, ben] = screen.getAllByTestId("hotseat-turn");
    expect(ben.getAttribute("aria-pressed")).toBe("true");
    expect(anna.querySelector("[aria-label='has had their turn']")).not.toBeNull();
    expect(ben.querySelector("[aria-label='has had their turn']")).toBeNull();
    expect(screen.getByTestId("hotseat-now").textContent).toBe("Pass the screen to Ben.");
    fireEvent.click(anna);
    expect(onPick).toHaveBeenCalledWith("hs_anna");
  });
});
