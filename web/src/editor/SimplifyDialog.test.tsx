import { cleanup, fireEvent, render } from "@testing-library/react";
import { afterEach, expect, test, vi } from "vitest";
import type { SimplifyResponse } from "./types";
import { SimplifyDialog } from "./SimplifyDialog";

afterEach(cleanup);

const RESULT: SimplifyResponse = {
  source: "…",
  changed: true,
  saved: false,
  stats: {
    "corridor.c97": {
      nodes: { before: 9, after: 5 },
      segments: { before: 8, after: 4 },
    },
  },
  changes: [
    { kind: "covered-spur", target: "corridor.c97", message: "spur n4 to n5 removed", line: 14, applied: true },
    { kind: "collinear-node", target: "corridor.c97", message: "node n4 merged", line: 6, applied: true },
    { kind: "covered-spur", target: "corridor.c12", message: "kept: door at 3,4", line: 30, applied: false },
  ],
};

function setup(over: Partial<Parameters<typeof SimplifyDialog>[0]> = {}) {
  const props = {
    result: RESULT,
    doorSpurs: false,
    loading: false,
    error: null,
    onDoorSpurs: vi.fn(),
    onApply: vi.fn(),
    onClose: vi.fn(),
    onJump: vi.fn(),
    ...over,
  };
  return { props, ...render(<SimplifyDialog {...props} />) };
}

test("lists applied changes per target with counts, and kept suggestions", () => {
  const { getByTestId, getByText } = setup();
  const changes = getByTestId("simplify-changes");
  expect(changes.textContent).toContain("corridor.c97");
  expect(changes.textContent).toContain("nodes 9 → 5, segments 8 → 4");
  expect(changes.textContent).toContain("stub inside the corridor");
  expect(getByTestId("simplify-kept").textContent).toContain("kept: door at 3,4");
  expect(getByText(/Apply \(2\)/)).toBeTruthy();
});

test("apply, jump, door-spur toggle and Escape call back", () => {
  const { props, getByText, getAllByTitle, getByRole } = setup();
  fireEvent.click(getByText(/Apply/));
  expect(props.onApply).toHaveBeenCalled();
  fireEvent.click(getAllByTitle("Show in editor")[0]);
  expect(props.onJump).toHaveBeenCalledWith(14);
  fireEvent.click(getByRole("checkbox"));
  expect(props.onDoorSpurs).toHaveBeenCalledWith(true);
  fireEvent.keyDown(window, { key: "Escape" });
  expect(props.onClose).toHaveBeenCalled();
});

test("nothing to simplify disables Apply", () => {
  const { getByTestId, getByText } = setup({
    result: { ...RESULT, changed: false, stats: {}, changes: [] },
  });
  expect(getByTestId("simplify-nothing")).toBeTruthy();
  expect((getByText(/Apply/) as HTMLButtonElement).disabled).toBe(true);
});
