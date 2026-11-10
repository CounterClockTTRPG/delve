import { fireEvent, screen, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { useT } from "../i18n";
import type { TableSession } from "./api";
import { RaisedHands, SessionControls, SessionNotice, StartDialog, actBlocked } from "./Session";
import { hostSeat, renderWith, seat } from "./testing";

const ana = seat("seat_00000000000a", "Ana", { characters: ["chr_a"], present: false });
const bo = seat("seat_00000000000b", "Bo", { characters: ["chr_b"] });
const party = [
  { id: "chr_a", name: "Sela", hp: 6, hp_max: 6, ac: 9, conditions: [] },
  { id: "chr_b", name: "Kael", hp: 15, hp_max: 15, ac: 4, conditions: [] },
];
const table = (over: Partial<TableSession> = {}): TableSession => ({
  state: "gathering",
  since: null,
  solo: false,
  absent: {},
  hands: [],
  away: [],
  ...over,
});

describe("StartDialog", () => {
  it("lists who is here, and asks what becomes of each absent player's character; the DM plays it by default", () => {
    const onStart = vi.fn();
    renderWith(<StartDialog seats={[hostSeat, ana, bo]} party={party} onStart={onStart} onClose={vi.fn()} />);
    const dialog = screen.getByTestId("start-dialog");
    expect(within(dialog).getByText("Bo").closest("li")?.textContent).toContain("Here");
    expect((within(dialog).getByLabelText("The DM plays Sela until Ana arrives") as HTMLInputElement).checked).toBe(true);
    fireEvent.click(within(dialog).getByLabelText("Sela stays in the background"));
    fireEvent.click(within(dialog).getByTestId("start-confirm"));
    expect(onStart).toHaveBeenCalledWith({ chr_a: "hold_back" });
  });
});

describe("SessionControls", () => {
  const controls = (session: TableSession) => (
    <SessionControls table={session} seats={[hostSeat]} party={party} busy={false}
      onStart={vi.fn()} onBreak={vi.fn()} onResume={vi.fn()} onEnd={vi.fn()} />
  );

  it("gives a solo table End the session alone, in play", () => {
    const { rerender } = renderWith(controls(table({ state: "playing", solo: true })));
    expect(screen.getByTestId("session-end")).toBeTruthy();
    expect(screen.queryByTestId("session-break")).toBeNull();
    expect(screen.queryByTestId("session-start")).toBeNull();
    rerender(controls(table({ state: "gathering", solo: true })));
    expect(screen.queryByTestId("session-controls"), "its first act starts the session").toBeNull();
  });

  it("gives a table of several seats Take a break and End the session in play", () => {
    renderWith(controls(table({ state: "playing" })));
    expect(screen.getByTestId("session-break")).toBeTruthy();
    expect(screen.getByTestId("session-end")).toBeTruthy();
  });
});

describe("RaisedHands", () => {
  const hands = [
    { seat_id: ana.id, at: "2026-10-27T20:30:00+00:00", point: null },
    { seat_id: bo.id, at: "2026-10-27T20:31:00+00:00", point: "Before anyone opens that door." },
  ];

  it("lets the host lower anyone's hand and take a break from the strip", () => {
    const onLower = vi.fn();
    const onBreak = vi.fn();
    renderWith(
      <RaisedHands hands={hands} seats={[hostSeat, ana, bo]} mySeatId={hostSeat.id} runsTheTable playing onLower={onLower} onBreak={onBreak} />,
    );
    const strip = screen.getByTestId("raised-hands");
    expect(strip.textContent).toContain("Before anyone opens that door.");
    fireEvent.click(within(within(strip).getByText("Bo").closest("li")!).getByRole("button", { name: "Lower" }));
    expect(onLower).toHaveBeenCalledWith(bo.id);
    fireEvent.click(screen.getByTestId("hands-break"));
    expect(onBreak).toHaveBeenCalled();
  });

  it("shows nothing without hands", () => {
    renderWith(<RaisedHands hands={[]} seats={[]} mySeatId={null} runsTheTable={false} playing onLower={vi.fn()} onBreak={vi.fn()} />);
    expect(screen.queryByTestId("raised-hands")).toBeNull();
  });
});

describe("the session's words", () => {
  function Blocked({ session }: { session: TableSession }) {
    const t = useT();
    return <p data-testid="blocked">{String(actBlocked(t, session))}</p>;
  }

  it("Act waits while gathering, except at a solo table, and on a break", () => {
    const { rerender } = renderWith(<Blocked session={table()} />);
    expect(screen.getByTestId("blocked").textContent).toContain("once the host starts the session");
    rerender(<Blocked session={table({ solo: true })} />);
    expect(screen.getByTestId("blocked").textContent).toBe("null");
    rerender(<Blocked session={table({ state: "break" })} />);
    expect(screen.getByTestId("blocked").textContent).toContain("on a break");
    rerender(<Blocked session={table({ state: "playing" })} />);
    expect(screen.getByTestId("blocked").textContent).toBe("null");
  });

  it("counts who is here while gathering, and says who starts", () => {
    const { rerender } = renderWith(<SessionNotice table={table()} seats={[hostSeat, ana, bo]} runsTheTable={false} />);
    expect(screen.getByTestId("session-notice").textContent).toContain("2 of 3 players are here. The host starts the session.");
    rerender(<SessionNotice table={table({ state: "playing" })} seats={[hostSeat]} runsTheTable />);
    expect(screen.queryByTestId("session-notice")).toBeNull();
  });
});
