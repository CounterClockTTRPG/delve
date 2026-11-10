import { act, render, screen } from "@testing-library/react";
import { emoteDuration, generate, render as drawPortrait, type RenderOptions } from "portraitgen";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { I18nProvider } from "../i18n";
import SaidLine, { IDLE_EMOTES, SPEECH_RATE } from "./SaidLine";
import type { StoryEntry } from "./api";
import { entry } from "./testing";

// portraitgen's render, watched: the options each drawing of the portrait got.
vi.mock("portraitgen", async (original) => {
  const real = await original<typeof import("portraitgen")>();
  return { ...real, render: vi.fn(real.render) };
});

const TIRA = { kind: "traits", describe: "a young female halfling innkeeper", seed: "npc_00000000000a" } as const;
const LINE = "Welcome to the Sleeping Dragon, travellers. Mind the step.";

function said(seq: number, text = LINE, mood = "smile", portrait: NonNullable<StoryEntry["payload"]["speaker"]>["portrait"] = TIRA): StoryEntry {
  return entry(seq, "say", { speaker: { id: "npc_00000000000a", name: "Tira", portrait }, mood, text, said: true } as never);
}

function show(line: StoryEntry, live: boolean) {
  return render(
    <I18nProvider language="en">
      <SaidLine entry={line} live={live} />
    </I18nProvider>,
  );
}

/** The emotes and line of the portrait's last drawing. */
function lastLook(): Pick<RenderOptions, "emotes" | "say" | "once"> {
  const calls = vi.mocked(drawPortrait).mock.calls;
  const { emotes, say, once } = calls.at(-1)?.[1] ?? {};
  return { emotes, say, once };
}

const traits = () => generate({ describe: TIRA.describe, seed: TIRA.seed });
const shownText = () => screen.getByTestId("said-text").textContent;

function reduceMotion(reduce: boolean) {
  vi.stubGlobal("matchMedia", (query: string) => ({
    matches: reduce && query.includes("prefers-reduced-motion"),
    media: query,
    addEventListener: () => {},
    removeEventListener: () => {},
  }));
}

beforeEach(() => {
  vi.useFakeTimers();
  vi.mocked(drawPortrait).mockClear();
  reduceMotion(false);
});

afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
});

describe("SaidLine", () => {
  it("shows a live line growing at twice the talk animation's pace", () => {
    const talking = emoteDuration(traits(), { emotes: ["talk"], say: LINE }) / SPEECH_RATE;
    expect(SPEECH_RATE).toBe(2);
    expect(talking).toBeGreaterThan(500);
    show(said(1), true);
    expect(screen.getByText("Tira")).toBeTruthy();
    act(() => void vi.advanceTimersByTime(talking / 2));
    const half = shownText() ?? "";
    expect(half.length).toBeGreaterThan(0);
    expect(half.length).toBeLessThan(LINE.length);
    expect(LINE.startsWith(half)).toBe(true);
    act(() => void vi.advanceTimersByTime(talking / 2 + 100));
    expect(shownText()).toBe(LINE);
  });

  it("plays the portrait's talk as fast as the words, and its mood at its own pace", () => {
    const rates: number[] = [];
    const animation = {
      set playbackRate(rate: number) {
        rates.push(rate);
      },
    };
    Element.prototype.getAnimations = vi.fn(() => [animation as unknown as Animation]);
    try {
      const talking = emoteDuration(traits(), { emotes: ["talk"], say: LINE }) / SPEECH_RATE;
      show(said(1), true);
      expect(rates.at(-1)).toBe(SPEECH_RATE);
      act(() => void vi.advanceTimersByTime(talking + 100));
      expect(rates.at(-1)).toBe(1);
    } finally {
      delete (Element.prototype as { getAnimations?: unknown }).getAnimations;
    }
  });

  it("talks, then plays the mood once, then rests on blink and breathe", () => {
    const talking = emoteDuration(traits(), { emotes: ["talk"], say: LINE });
    const smiling = emoteDuration(traits(), { emotes: ["smile"] });
    show(said(1), true);
    expect(lastLook()).toEqual({ emotes: ["talk"], say: LINE, once: true });
    act(() => void vi.advanceTimersByTime(talking + 100));
    expect(lastLook()).toEqual({ emotes: ["smile"], say: undefined, once: true });
    act(() => void vi.advanceTimersByTime(smiling + 100));
    expect(lastLook()).toEqual({ emotes: [...IDLE_EMOTES], say: undefined, once: undefined });
  });

  it("rests after talking when the mood is neutral", () => {
    const talking = emoteDuration(traits(), { emotes: ["talk"], say: LINE });
    show(said(1, LINE, "neutral"), true);
    act(() => void vi.advanceTimersByTime(talking + 100));
    expect(lastLook().emotes).toEqual([...IDLE_EMOTES]);
  });

  it("shows a line from history whole, resting", () => {
    show(said(1), false);
    expect(shownText()).toBe(LINE);
    expect(lastLook()).toEqual({ emotes: [...IDLE_EMOTES], say: undefined, once: undefined });
    expect(vi.mocked(drawPortrait).mock.calls.some(([, o]) => o?.emotes?.includes("talk"))).toBe(false);
  });

  it("shows a live line whole and still under reduced motion", () => {
    reduceMotion(true);
    show(said(1), true);
    expect(shownText()).toBe(LINE);
    expect(lastLook().emotes).toEqual([]);
    act(() => void vi.advanceTimersByTime(60_000));
    expect(vi.mocked(drawPortrait).mock.calls.every(([, o]) => (o?.emotes ?? []).length === 0)).toBe(true);
  });

  it("stops a line's animation when a newer one takes over", () => {
    const { rerender } = show(said(1), true);
    act(() => void vi.advanceTimersByTime(300));
    expect(shownText()).not.toBe(LINE);
    rerender(
      <I18nProvider language="en">
        <SaidLine entry={said(1)} live={false} />
      </I18nProvider>,
    );
    expect(shownText()).toBe(LINE);
    expect(lastLook().emotes).toEqual([...IDLE_EMOTES]);
    vi.mocked(drawPortrait).mockClear();
    act(() => void vi.advanceTimersByTime(60_000));
    expect(vi.mocked(drawPortrait)).not.toHaveBeenCalled();
  });

  it("shows the speaker's initial without a portrait, and still reveals the line", () => {
    show(said(1, LINE, "smile", null), true);
    expect(screen.getByText("T")).toBeTruthy();
    expect(shownText()).not.toBe(LINE);
    act(() => void vi.advanceTimersByTime(60_000));
    expect(shownText()).toBe(LINE);
  });

  it("names the speaker and the mood for a screen reader", () => {
    show(said(1, LINE, "angry"), false);
    expect(screen.getByRole("img", { name: "Tira, angry" })).toBeTruthy();
  });

  it("shows the translation of the line", () => {
    show({ ...said(1), translation: { language: "nl", text: "Welkom, reizigers.", status: "done" } }, false);
    expect(shownText()).toBe("Welkom, reizigers.");
  });

  const SENT = "*Mine now,* she sends smugly into Beren's head. **He doesn't mind.**";
  const SENT_PLAIN = "Mine now, she sends smugly into Beren's head. He doesn't mind.";

  it("shows the line's Markdown as emphasis, not as asterisks", () => {
    show(said(1, SENT), false);
    expect(shownText()).toBe(SENT_PLAIN);
    expect(screen.getByTestId("said-text").querySelector("em")?.textContent).toBe("Mine now,");
    expect(screen.getByTestId("said-text").querySelector("strong")?.textContent).toBe("He doesn't mind.");
  });

  it("never shows a stray asterisk while a live line grows, and the portrait talks the plain words", () => {
    show(said(1, SENT), true);
    expect(lastLook().say).toBe(SENT_PLAIN);
    for (let at = 0; at < 20_000; at += 50) {
      act(() => void vi.advanceTimersByTime(50));
      expect(shownText()).not.toContain("*");
    }
    expect(shownText()).toBe(SENT_PLAIN);
  });

  it("keeps markup in a line as text", () => {
    show(said(1, "<b>bold</b> & *sly*"), false);
    expect(shownText()).toBe("<b>bold</b> & sly");
    expect(screen.getByTestId("said-text").querySelector("b")).toBeNull();
  });
});
