import { act, renderHook, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { base, CAMPAIGN, entry, json, stubFetch } from "./testing";
import { grow, merge, useStory } from "./useStory";

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("useStory", () => {
  it("marks the entries that arrived live, and never one read from the story (Review Focus 4)", async () => {
    const read = entry(1, "say", { text: "Read before." });
    stubFetch({ [`GET ${base}/story?limit=50`]: () => json(200, { entries: [read], has_more: false }) });
    const { result } = renderHook(() => useStory(CAMPAIGN));
    await waitFor(() => expect(result.current.entries).toHaveLength(1));
    expect(result.current.entries[0].live).toBeFalsy();

    // An entry the page already has, heard again, stays as it was; a new one is live, and stays so when re-read.
    act(() => result.current.add(read));
    act(() => result.current.add(entry(2, "say", { text: "Heard now." })));
    expect(result.current.entries.map((e) => e.live ?? false)).toEqual([false, true]);
    await act(() => result.current.refresh());
    expect(result.current.entries.map((e) => e.live ?? false)).toEqual([false, true]);
  });

  it("marks live a new entry that a later fetch brings before its event, but never an earlier page's", async () => {
    const read = entry(5, "say", { text: "Read before." });
    const said = entry(6, "say", { text: "Said now." });
    const earlier = entry(1, "say", { text: "Long ago." });
    let entries = [read];
    stubFetch({
      [`GET ${base}/story?limit=50`]: () => json(200, { entries, has_more: true }),
      [`GET ${base}/story?limit=50&before=5`]: () => json(200, { entries: [earlier], has_more: false }),
    });
    const { result } = renderHook(() => useStory(CAMPAIGN));
    await waitFor(() => expect(result.current.entries).toHaveLength(1));

    // Another event made the page fetch again, and the answer holds the line its own event is still bringing.
    entries = [read, said];
    await act(() => result.current.refresh());
    act(() => result.current.add(said));
    await act(() => result.current.loadEarlier());
    expect(result.current.entries.map((e) => [e.seq, e.live ?? false])).toEqual([
      [1, false],
      [5, false],
      [6, true],
    ]);
  });

  it("adds a reply's streamed words; a reload or a missed delta still ends whole (DEL-241)", async () => {
    const stored = entry(1, "dm_text", { text: "The door" });
    let entries = [stored];
    stubFetch({ [`GET ${base}/story?limit=50`]: () => json(200, { entries, has_more: false }) });
    const { result } = renderHook(() => useStory(CAMPAIGN));
    await waitFor(() => expect(result.current.entries).toHaveLength(1));
    const text = () => result.current.entries[0].payload.text;

    act(() => result.current.addText(stored.id, 8, " creaks"));
    act(() => result.current.addText(stored.id, 8, " creaks"));
    expect(text()).toBe("The door creaks");
    // A fetch brings the reply as last stored, behind what streamed: the streamed words stay.
    await act(() => result.current.refresh());
    expect(text()).toBe("The door creaks");
    // A delta missed (this one follows 20 characters): nothing changes until the reply's next `story` brings it whole.
    act(() => result.current.addText(stored.id, 20, " wide."));
    expect(text()).toBe("The door creaks");
    act(() => result.current.add(entry(1, "dm_text", { text: "The door creaks open wide." })));
    expect(text()).toBe("The door creaks open wide.");
    // A reload rebuilds the reply from the server alone.
    entries = [entry(1, "dm_text", { text: "The door creaks open wide." })];
    const reloaded = renderHook(() => useStory(CAMPAIGN));
    await waitFor(() => expect(reloaded.result.current.entries[0]?.payload.text).toBe("The door creaks open wide."));
  });
});

describe("grow and merge", () => {
  it("place a delta by its offset, and a stored text that isn't behind replaces the known one", () => {
    const known = [entry(1, "dm_text", { text: "Dark." })];
    expect(grow(known, "ste_000000000009", 0, "x")).toBe(known);
    expect(grow(known, known[0].id, 4, " and cold.")[0].payload.text).toBe("Dark and cold."); // its words from `at` win
    // A shorter text that isn't the start of the known one (the reply's end trims it) replaces it, fetched or not.
    const ahead = [entry(1, "dm_text", { text: "Dark.\n\n" })];
    expect(merge(ahead, [entry(1, "dm_text", { text: "Dark." })])[0].payload.text).toBe("Dark.");
    expect(merge(ahead, [entry(1, "dm_text", { text: "Dim." })], false, true)[0].payload.text).toBe("Dim.");
  });
});

