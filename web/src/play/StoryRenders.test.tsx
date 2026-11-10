// How much the play screen renders while the DM writes (DEL-168): each streamed chunk of a reply re-rendered every
// entry's Markdown, 200 entries × 50 chunks = 10,000 renders; a keystroke at the table re-rendered the whole screen.
import { render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { I18nProvider } from "../i18n";
import Play from "../routes/Play";
import type { StoryEntry } from "./api";
import { renderMarkdown } from "./markdown";
import Story from "./Story";
import { CAMPAIGN, FakeEventSource, entry, hostSeat, playRoutes, playState, renderWith, seat, stubFetch } from "./testing";

const counts = vi.hoisted(() => ({ story: 0 }));

vi.mock("./markdown", async (original) => {
  const real = await original<typeof import("./markdown")>();
  return { ...real, renderMarkdown: vi.fn(real.renderMarkdown) };
});

vi.mock("./Story", async (original) => {
  const real = await original<typeof import("./Story")>();
  const Counted = (props: Parameters<typeof real.default>[0]) => {
    counts.story++;
    return real.default(props);
  };
  return { ...real, default: Counted };
});

const markdown = vi.mocked(renderMarkdown);

beforeEach(() => {
  FakeEventSource.open = [];
  vi.stubGlobal("EventSource", FakeEventSource);
  markdown.mockClear();
  counts.story = 0;
});

afterEach(() => {
  vi.unstubAllGlobals();
});

const told = (count: number) => Array.from({ length: count }, (_, i) => entry(i + 1, "dm_text", { text: `Line **${i + 1}**.` }));

describe("the story's renders (DEL-168)", () => {
  it("renders an entry's Markdown again only when its words change", () => {
    const entries = told(200);
    const story = (shown: StoryEntry[]) => (
      <I18nProvider language="en">
        <Story entries={shown} hasMore={false} onLoadEarlier={() => {}} names={{}} />
      </I18nProvider>
    );
    const { rerender } = render(story(entries));
    expect(markdown).toHaveBeenCalledTimes(200);
    // 50 chunks of a reply: the older entries keep their objects, as `merge` keeps them.
    let shown = entries;
    for (let chunk = 1; chunk <= 50; chunk++) {
      const growing = entry(201, "dm_text", { text: "The door ".repeat(chunk) });
      shown = [...entries, growing];
      rerender(story(shown));
    }
    expect(markdown).toHaveBeenCalledTimes(250);
    expect(screen.getByTestId("story").textContent).toContain("Line 1.");
  });

  it("on the play screen, a streamed chunk renders its entry alone, and talk being typed doesn't render the story", async () => {
    const bo = seat("seat_00000000000b", "Bo", { characters: ["chr_00000000000b"] });
    stubFetch(playRoutes(playState({ beat: { id: "beat_000000000001", status: "running", elapsed_s: 1 } }), told(50), { seats: [hostSeat, bo] }));
    renderWith(<Play />);
    expect(await screen.findByText("50", { selector: "strong" })).toBeTruthy();
    await waitFor(() => expect(markdown.mock.calls.length).toBeGreaterThanOrEqual(50));
    const before = markdown.mock.calls.length;
    for (let chunk = 1; chunk <= 20; chunk++)
      FakeEventSource.emit("story", { campaign_id: CAMPAIGN, entry: entry(51, "dm_text", { text: "You see ".repeat(chunk) }) });
    expect(screen.getByTestId("story").textContent).toContain("You see You see");
    expect(markdown.mock.calls.length - before).toBe(20);

    const renders = counts.story;
    for (let key = 0; key < 10; key++) {
      FakeEventSource.emit("typing", { campaign_id: CAMPAIGN, seat_id: bo.id, state: key % 2 ? "idle" : "typing" });
    }
    expect(screen.getByTestId("talk-panel")).toBeTruthy();
    expect(counts.story).toBe(renders);
  });
});
