import { act, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import DidYouKnow, { FACT_EVERY_MS } from "./DidYouKnow";
import { CAMPAIGN, base, json, renderWith, stubFetch } from "./testing";

afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
});

const facts = [
  { text: "Hardby is ruled by a Despotrix.", category: "places" },
  { text: "The Selintan flows into Woolly Bay.", category: "places" },
];

describe("DidYouKnow", () => {
  it("shows the setting's facts in turn, every 8 seconds", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    const fetchMock = stubFetch({ [`GET ${base}/lore/random?n=20`]: () => json(200, { facts }) });
    renderWith(<DidYouKnow campaignId={CAMPAIGN} />);

    expect(await screen.findByText("Hardby is ruled by a Despotrix.")).toBeTruthy();
    expect(screen.getByText("Did you know?")).toBeTruthy();
    expect(FACT_EVERY_MS).toBe(8000);
    act(() => {
      vi.advanceTimersByTime(8000);
    });
    expect(screen.getByText("The Selintan flows into Woolly Bay.")).toBeTruthy();
    act(() => {
      vi.advanceTimersByTime(8000);
    });
    expect(screen.getByText("Hardby is ruled by a Despotrix.")).toBeTruthy();
    // The facts are read once, not on every turn of the wheel.
    expect(fetchMock.mock.calls.filter(([p]) => String(p).includes("lore/random"))).toHaveLength(1);
  });

  it("shows nothing without a setting's facts", async () => {
    stubFetch({ [`GET ${base}/lore/random?n=20`]: () => json(200, { facts: [] }) });
    const { container } = renderWith(<DidYouKnow campaignId={CAMPAIGN} />);
    await act(async () => {});
    expect(container.textContent).toBe("");
  });
});
