import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { TYPING_TTL_MS, typingStore } from "./typing";

const ANA = "seat_00000000000a";
const BO = "seat_00000000000b";

beforeEach(() => vi.useFakeTimers());
afterEach(() => vi.useRealTimers());

describe("typingStore", () => {
  it("takes a typing seat as idle when it says nothing more for the TTL", () => {
    const store = typingStore();
    const heard = vi.fn();
    store.subscribe(heard);
    store.set(ANA, "typing");
    store.set(BO, "typing");
    vi.advanceTimersByTime(TYPING_TTL_MS - 3000);
    // Ana types on: her sender says so again every 3 s, and each time the TTL starts again.
    store.set(ANA, "typing");
    vi.advanceTimersByTime(3000);
    expect(store.get()).toEqual({ [ANA]: "typing", [BO]: "idle" });
    vi.advanceTimersByTime(TYPING_TTL_MS - 3000);
    expect(store.get()[ANA]).toBe("idle");
    expect(heard).toHaveBeenCalledTimes(4);
  });

  it("an idle seat, and a cleared store, have nothing left to expire", () => {
    const store = typingStore();
    store.set(ANA, "typing");
    store.set(ANA, "idle");
    store.set(BO, "typing");
    store.clear();
    const heard = vi.fn();
    store.subscribe(heard);
    vi.advanceTimersByTime(TYPING_TTL_MS * 2);
    expect(store.get()).toEqual({});
    expect(heard).not.toHaveBeenCalled();
  });
});
