import { describe, expect, it } from "vitest";
import { History, MAX_STATES } from "./history";

describe("History", () => {
  it("undoes and redoes", () => {
    let h = History.of("a").push("b").push("c");
    expect(h.current).toBe("c");
    expect(h.canUndo).toBe(true);
    expect(h.canRedo).toBe(false);
    h = h.undo();
    expect(h.current).toBe("b");
    h = h.undo();
    expect(h.current).toBe("a");
    expect(h.canUndo).toBe(false);
    expect(h.undo()).toBe(h);
    h = h.redo().redo();
    expect(h.current).toBe("c");
    expect(h.canRedo).toBe(false);
    expect(h.redo()).toBe(h);
  });

  it("drops the redo on a push after an undo", () => {
    const h = History.of(1).push(2).push(3).undo().push(4);
    expect(h.current).toBe(4);
    expect(h.canRedo).toBe(false);
    expect(h.undo().current).toBe(2);
  });

  it("is pure: an older history is unchanged", () => {
    const before = History.of("a").push("b");
    const after = before.undo();
    expect(before.current).toBe("b");
    expect(after.current).toBe("a");
  });

  it(`keeps at most ${MAX_STATES} states`, () => {
    let h = History.of(0);
    for (let i = 1; i <= MAX_STATES + 20; i++) h = h.push(i);
    let undone = 0;
    while (h.canUndo) {
      h = h.undo();
      undone++;
    }
    expect(undone).toBe(MAX_STATES - 1);
    expect(h.current).toBe(21);
  });
});
