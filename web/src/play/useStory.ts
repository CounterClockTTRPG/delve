import { useCallback, useEffect, useRef, useState } from "react";
import { getStory, type StoryEntry, type Translation } from "./api";

export function merge(known: StoryEntry[], incoming: StoryEntry[], live = false, fetched = false): StoryEntry[] {
  const byId = new Map(known.map((e) => [e.id, e]));
  // An entry seen again replaces the old one: a reply's text grows while the DM writes it. Its translation stays,
  // unless the new one carries its own: a `story` event never does. Whether it came in live stays too: only an entry
  // the page didn't have yet is live, so a said line already shown never talks again. A `fetched` page may hold a
  // reply as last stored, behind the words its `story_text` events brought (DEL-241): those stay.
  for (const entry of incoming) {
    const before = byId.get(entry.id);
    const translation = entry.translation ?? before?.translation;
    const heard = before ? before.live : live;
    const behind = fetched && before !== undefined && isAhead(before, entry);
    const payload = behind ? before.payload : entry.payload;
    byId.set(entry.id, { ...entry, payload, ...(translation && { translation }), ...(heard && { live: true }) });
  }
  return [...byId.values()].sort((a, b) => a.seq - b.seq);
}

/** Whether `known` is the reply `stored` with more words after it, which the page heard as they streamed. */
function isAhead(known: StoryEntry, stored: StoryEntry): boolean {
  const had = known.payload.text;
  const has = stored.payload.text;
  return typeof had === "string" && typeof has === "string" && had.length > has.length && had.startsWith(has);
}

/**
 * A `story_text` event's words added to the reply they follow (DEL-241): `text` comes after the reply's first `at`
 * characters. The story as it was when the page doesn't have the reply, or has less of it than `at` (it missed some
 * words): the reply's next `story` event brings it whole.
 */
export function grow(known: StoryEntry[], entryId: string, at: number, text: string): StoryEntry[] {
  const index = known.findIndex((e) => e.id === entryId);
  const had = index < 0 ? undefined : known[index].payload.text;
  if (typeof had !== "string" || had.length < at || had.length >= at + text.length) return known;
  const entry = known[index];
  const grown = { ...entry, payload: { ...entry.payload, text: had.slice(0, at) + text } };
  return [...known.slice(0, index), grown, ...known.slice(index + 1)];
}

/**
 * The campaign's story as far as the page knows it: the newest page on opening (so a reload rebuilds it), earlier
 * pages on request (one at a time, however often it is asked), and entries from the event stream as they come, marked
 * `live`, as is a new entry a later fetch of the newest page brings. With `language`, each entry carries its
 * translation into it; `enabled` false waits (for the seat's language) before the first page. With `kind`, only the
 * entries of that kind, in pages of their own: the talk panel's (DEL-219), which a page of every kind left with few
 * lines or none in a busy session.
 */
export function useStory(campaignId: string, language?: string, enabled = true, kind?: StoryEntry["kind"]) {
  const [entries, setEntries] = useState<StoryEntry[]>([]);
  const [hasMore, setHasMore] = useState(false);
  const [loadingEarlier, setLoadingEarlier] = useState(false);
  const [error, setError] = useState<Error | null>(null);
  // The campaign shown now, so a late answer for another one is dropped; and whether its first page is in.
  const shown = useRef(campaignId);
  const loaded = useRef(false);
  const loadingBefore = useRef(false);
  shown.current = campaignId;

  const refresh = useCallback(async () => {
    try {
      const page = await getStory(campaignId, undefined, 50, language, kind);
      if (shown.current !== campaignId) return;
      // Only the first page says whether there is more before it. After it, an entry the page didn't have came in
      // while it was open: live, even when this answer brings it before its own event does.
      const live = loaded.current;
      if (!live) setHasMore(page.has_more);
      loaded.current = true;
      setEntries((known) => merge(known, page.entries, live, true));
      setError(null);
    } catch (e) {
      setError(e as Error);
    }
  }, [campaignId, language, kind]);

  useEffect(() => {
    if (!enabled) return;
    // A page read in another language goes; entries this page added while it waited stay.
    if (loaded.current) {
      setEntries([]);
      setHasMore(false);
    }
    loaded.current = false;
    void refresh();
  }, [refresh, enabled]);

  const loadEarlier = useCallback(async () => {
    const first = entries[0];
    if (!first || loadingBefore.current) return;
    loadingBefore.current = true;
    setLoadingEarlier(true);
    try {
      const page = await getStory(campaignId, first.seq, 50, language, kind);
      if (shown.current !== campaignId) return;
      setEntries((known) => merge(known, page.entries, false, true));
      setHasMore(page.has_more);
    } catch (e) {
      setError(e as Error);
    } finally {
      loadingBefore.current = false;
      setLoadingEarlier(false);
    }
  }, [campaignId, entries, language, kind]);

  /** The newest page afresh, without what the page knew: what this seat may see of the entries it has changed (the
   * enemies' dice, DEL-270), and an entry it may no longer see goes. */
  const reload = useCallback(async () => {
    try {
      const page = await getStory(campaignId, undefined, 50, language, kind);
      if (shown.current !== campaignId) return;
      loaded.current = true;
      setEntries(merge([], page.entries));
      setHasMore(page.has_more);
      setError(null);
    } catch (e) {
      setError(e as Error);
    }
  }, [campaignId, language, kind]);

  /** An entry from the event stream or an answer: live, if the page didn't have it. */
  const add = useCallback((entry: StoryEntry) => setEntries((known) => merge(known, [entry], true)), []);

  /** A `story_text` event: the reply's new words (`grow`). */
  const addText = useCallback(
    (entryId: string, at: number, text: string) => setEntries((known) => grow(known, entryId, at, text)),
    [],
  );

  /** A `translation` event: the entry's words in the seat's language, so far. */
  const translate = useCallback(
    (entryId: string, translation: Translation) =>
      setEntries((known) => known.map((e) => (e.id === entryId ? { ...e, translation } : e))),
    [],
  );

  return { entries, hasMore, loadingEarlier, error, loadEarlier, add, addText, refresh, reload, translate };
}

/** A `story` event's entry, if it carries one (`{entry}` or the entry itself); otherwise the page fetches again. */
export function eventEntry(data: unknown): StoryEntry | null {
  const candidate = (data as { entry?: unknown } | null)?.entry ?? data;
  const e = candidate as Partial<StoryEntry> | null;
  return e && typeof e.id === "string" && typeof e.seq === "number" && typeof e.kind === "string" && e.payload
    ? (e as StoryEntry)
    : null;
}
