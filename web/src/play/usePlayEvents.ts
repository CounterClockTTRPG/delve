// The play screen's live updates (DEL-168): the app's event stream, for this campaign only, into the story, the
// talk, the typing seats and the queries the play screen reads. After a reload, the story and the state are read
// again instead.
import { useQueryClient } from "@tanstack/react-query";
import { useContext, useEffect, type Dispatch, type SetStateAction } from "react";
import { accountKeys } from "../account/api";
import { EventsContext, RECONNECTED } from "../api";
import { PLAY_EVENTS, playKeys, type RunningBeat, type TranslationStatus } from "./api";
import type { TypingStore } from "./typing";
import { eventEntry, type useStory } from "./useStory";

type StoryPages = ReturnType<typeof useStory>;

/** A beat as the stream last told it, and when. */
export interface HeardBeat {
  beat: RunningBeat | null;
  at: number;
}

export function usePlayEvents({
  campaignId,
  language,
  story,
  talkPages,
  typing,
  setHeard,
  setMapEvents,
  setTools,
}: {
  campaignId: string;
  /** The seat's language: a translation into another is not this page's. */
  language: string | undefined;
  story: StoryPages;
  /** The talk panel's own pages (DEL-219), which take translations too. */
  talkPages: StoryPages;
  typing: TypingStore;
  setHeard: (heard: HeardBeat) => void;
  /** Counts the map's changes, so the map reads its view again. */
  setMapEvents: Dispatch<SetStateAction<number>>;
  /** The host's and co-hosts' count of the running beat's tool calls. */
  setTools: (tools: { beatId: string; count: number }) => void;
}) {
  const client = useQueryClient();
  const subscribe = useContext(EventsContext);
  const refetchState = () => client.invalidateQueries({ queryKey: playKeys.state(campaignId) });
  useEffect(() => {
    const mine = (data: unknown) => (data as { campaign_id?: unknown } | null)?.campaign_id === campaignId;
    const handlers: Record<(typeof PLAY_EVENTS)[number], (data: unknown) => void> = {
      story: (data) => {
        const entry = eventEntry(data);
        if (entry) story.add(entry);
        else void story.refresh();
      },
      // The new words of the reply the DM is writing (DEL-241).
      story_text: (data) => {
        const { entry_id, at, text } = data as { entry_id?: unknown; at?: unknown; text?: unknown };
        if (typeof entry_id === "string" && typeof at === "number" && typeof text === "string")
          story.addText(entry_id, at, text);
      },
      beat: (data) => {
        const told = ((data as { beat?: unknown }).beat ?? data) as Partial<RunningBeat>;
        const known = typeof told.id === "string" && typeof told.status === "string";
        if (known) {
          setHeard({ beat: { elapsed_s: 0, ...told } as RunningBeat, at: Date.now() });
          if (told.status !== "open") typing.clear();
        }
        // The story's entries come as events of their own: it is read again only once the beat has ended, for what
        // the stream may have missed, not each time an open beat's deadline moves or it starts running (DEL-168).
        if (!known || (told.status !== "open" && told.status !== "running")) void story.refresh();
        refetchState();
        client.invalidateQueries({ queryKey: playKeys.pending(campaignId) });
      },
      // The app's own handlers read the characters and the world again (App.tsx): here, the state alone.
      characters: () => refetchState(),
      map_state: () => {
        refetchState();
        setMapEvents((n) => n + 1);
      },
      // The date and the weather are in the state.
      world: () => refetchState(),
      combat: () => refetchState(),
      // A DM's tool call, told once whatever it changed (DEL-168): the state is read once.
      changed: (data) => {
        const { areas } = data as { areas?: unknown };
        if (!Array.isArray(areas) || areas.length === 0) return;
        refetchState();
        if (areas.includes("map_state")) setMapEvents((n) => n + 1);
        // A PC the DM made for a player is that player's at once (DEL-253): who plays whom is read again.
        if (areas.includes("characters")) client.invalidateQueries({ queryKey: playKeys.seats(campaignId) });
      },
      // The stream came back after a break: what it missed beyond the replay is read again.
      reconnected: () => {
        void story.refresh();
        refetchState();
      },
      play_options: (data) => {
        refetchState();
        // The enemies' dice changed sides of the screen: this seat's story reads again (DEL-270).
        if ((data as { story?: unknown } | null)?.story === true) void story.reload();
      },
      scenes: () => refetchState(),
      // The session moved, or a hand went up or down.
      table: () => refetchState(),
      // Someone asked to join, wrote on a request, or was accepted or declined: the host's and co-hosts' alone.
      join_requests: () => client.invalidateQueries({ queryKey: accountKeys.tableRequests(campaignId) }),
      // The host changed the table's description, places or visibility.
      table_listing: () => client.invalidateQueries({ queryKey: playKeys.listing(campaignId) }),
      // A banner landed (or failed): the state says which is current.
      banner: () => refetchState(),
      // A seat came, went, or changed its role or characters: this seat's own role too.
      seats: () => {
        client.invalidateQueries({ queryKey: playKeys.seats(campaignId) });
        client.invalidateQueries({ queryKey: playKeys.listing(campaignId) });
        client.invalidateQueries({ queryKey: playKeys.me(campaignId) });
      },
      typing: (data) => {
        const { seat_id, state } = data as { seat_id?: unknown; state?: unknown };
        if (typeof seat_id === "string" && (state === "typing" || state === "idle"))
          typing.set(seat_id, state);
      },
      translation: (data) => {
        const told = data as { entry_id?: unknown; language?: unknown; text?: unknown; status?: unknown; answer?: unknown };
        if (typeof told.entry_id === "string" && language && told.language === language && typeof told.text === "string")
          for (const known of [story, talkPages])
            known.translate(told.entry_id, {
              language,
              text: told.text,
              status: told.status as TranslationStatus,
              ...(typeof told.answer === "string" ? { answer: told.answer } : {}),
            });
      },
      // Sent to the host and the co-hosts only.
      beat_tools: (data) => {
        const { beat_id, tool_count } = data as { beat_id?: unknown; tool_count?: unknown };
        if (typeof beat_id === "string" && typeof tool_count === "number") setTools({ beatId: beat_id, count: tool_count });
      },
    };
    return subscribe(
      Object.fromEntries(
        // The stream's own `reconnected` names no campaign.
        Object.entries(handlers).map(([type, handle]) => [
          type,
          (data: unknown) => (type === RECONNECTED || mine(data)) && handle(data),
        ]),
      ),
    );
    // story.add, story.addText, story.refresh and story.translate change only with the campaign and the language.
  }, [
    campaignId,
    client,
    subscribe,
    story.add,
    story.addText,
    story.refresh,
    story.translate,
    talkPages.translate,
    language,
    typing,
  ]);
}
