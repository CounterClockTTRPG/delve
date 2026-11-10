import { act, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { I18nProvider } from "../i18n";
import BeatTimer from "./BeatTimer";

beforeEach(() => {
  vi.useFakeTimers();
  vi.setSystemTime(new Date("2026-10-18T20:00:00Z"));
});

afterEach(() => {
  vi.useRealTimers();
});

function renderTimer(deadline: string | null) {
  return render(
    <I18nProvider language="en">
      <BeatTimer deadline={deadline} />
    </I18nProvider>,
  );
}

describe("BeatTimer", () => {
  it("counts down from the deadline to everyone, and stops at nought", () => {
    renderTimer("2026-10-18T20:01:05Z");
    expect(screen.getByTestId("beat-timer").textContent).toContain("1:05");

    act(() => vi.advanceTimersByTime(6_000));
    expect(screen.getByTestId("beat-timer").textContent).toContain("0:59");

    act(() => vi.advanceTimersByTime(120_000));
    expect(screen.getByTestId("beat-timer").textContent).toContain("0:00");
  });

  it("shows nothing without a timer", () => {
    renderTimer(null);
    expect(screen.queryByTestId("beat-timer")).toBeNull();
  });
});
