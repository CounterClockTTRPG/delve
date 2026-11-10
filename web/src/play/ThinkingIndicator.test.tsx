import { act, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { I18nProvider } from "../i18n";
import ThinkingIndicator from "./ThinkingIndicator";
import { DID_YOU_KNOW_KEY, resetDidYouKnow } from "./didYouKnowSetting";
import { CAMPAIGN, base, json, renderWith, stubFetch } from "./testing";

afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
  localStorage.clear();
  resetDidYouKnow();
});

describe("ThinkingIndicator", () => {
  it("counts tools and time", () => {
    vi.useFakeTimers();
    const { rerender } = render(
      <I18nProvider language="en">
        <ThinkingIndicator elapsedS={5} toolCount={1} />
      </I18nProvider>,
    );
    const thinking = screen.getByTestId("thinking");
    expect(thinking.textContent).toContain("0:05");
    expect(thinking.textContent).toContain("1 tool call");
    expect(thinking.textContent).not.toContain("This is a big one");

    act(() => {
      vi.advanceTimersByTime(26_000);
    });
    rerender(
      <I18nProvider language="en">
        <ThinkingIndicator elapsedS={5} toolCount={3} />
      </I18nProvider>,
    );
    expect(thinking.textContent).toContain("0:31");
    expect(thinking.textContent).toContain("3 tool calls");
    expect(thinking.textContent).toContain("This is a big one…");
  });

  it("shows no tool count to a seat that isn't given one (a player or an observer)", () => {
    render(
      <I18nProvider language="en">
        <ThinkingIndicator elapsedS={5} />
      </I18nProvider>,
    );
    const thinking = screen.getByTestId("thinking");
    expect(thinking.textContent).toContain("0:05");
    expect(thinking.textContent).not.toContain("tool");
  });

  it("shows the setting's fact unless this browser turned Did you know off", async () => {
    const facts = [{ text: "Hardby is ruled by a Despotrix.", category: "places" }];
    const fetchMock = stubFetch({ [`GET ${base}/lore/random?n=20`]: () => json(200, { facts }) });
    const shown = renderWith(<ThinkingIndicator elapsedS={5} campaignId={CAMPAIGN} />);
    expect(await screen.findByText("Hardby is ruled by a Despotrix.")).toBeTruthy();
    shown.unmount();

    localStorage.setItem(DID_YOU_KNOW_KEY, "off");
    resetDidYouKnow();
    fetchMock.mockClear();
    renderWith(<ThinkingIndicator elapsedS={5} campaignId={CAMPAIGN} />);
    await act(async () => {});
    expect(screen.queryByTestId("did-you-know")).toBeNull();
    // Turned off, the facts aren't even read.
    expect(fetchMock.mock.calls.filter(([p]) => String(p).includes("lore/random"))).toHaveLength(0);
  });
});
