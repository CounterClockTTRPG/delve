import { act, renderHook } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { useChanged } from "./useChanged";

describe("useChanged", () => {
  it("says nothing changed while the panel loads, nor when it first arrives", () => {
    const { result, rerender } = renderHook(({ sig, seen }) => useChanged(sig, seen), {
      initialProps: { sig: null as string | null, seen: false },
    });
    expect(result.current).toBe(false);
    rerender({ sig: "a", seen: false });
    expect(result.current).toBe(false);
  });

  it("marks a change made while the panel is out of sight, until the panel is shown", () => {
    const { result, rerender } = renderHook(({ sig, seen }) => useChanged(sig, seen), {
      initialProps: { sig: "a" as string | null, seen: false },
    });
    rerender({ sig: "b", seen: false });
    expect(result.current).toBe(true);
    act(() => rerender({ sig: "b", seen: true }));
    expect(result.current).toBe(false);
    rerender({ sig: "b", seen: false });
    expect(result.current).toBe(false);
  });

  it("never marks a change made while the panel is shown", () => {
    const { result, rerender } = renderHook(({ sig, seen }) => useChanged(sig, seen), {
      initialProps: { sig: "a" as string | null, seen: true },
    });
    rerender({ sig: "b", seen: true });
    rerender({ sig: "b", seen: false });
    expect(result.current).toBe(false);
  });

  it("forgets the change when it is undone before anyone looks", () => {
    const { result, rerender } = renderHook(({ sig, seen }) => useChanged(sig, seen), {
      initialProps: { sig: "a" as string | null, seen: false },
    });
    rerender({ sig: "b", seen: false });
    rerender({ sig: "a", seen: false });
    expect(result.current).toBe(false);
  });
});
