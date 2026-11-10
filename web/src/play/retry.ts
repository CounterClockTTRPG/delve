import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useContext, useEffect, useState } from "react";
import { EventsContext, apiFetch, postJson } from "../api";
import type { RunningBeat, StoryEntry, StoryPayload } from "./api";

/** Whether this seat may retry the campaign's latest beat (table voice and fixes Task D1), and when the usage limit
 * that stopped it ends (ISO 8601). */
export interface RetryState {
  beat_id: string | null;
  may_retry: boolean;
  resets_at: string | null;
}

const path = (campaignId: string) => `/api/campaigns/${encodeURIComponent(campaignId)}`;

export const retryKey = (campaignId: string) => ["campaign", campaignId, "retry"] as const;

export const getRetry = (campaignId: string) => apiFetch<RetryState>(`${path(campaignId)}/retry`);

export const retryBeat = (campaignId: string, beatId: string) =>
  postJson<{ beat: RunningBeat }>(`${path(campaignId)}/beats/${encodeURIComponent(beatId)}/retry`, {});

/** A `dm_error`'s payload as the beat runner writes it: whether the beat may be tried again, when the usage limit
 * ends, and whether it has been retried. */
export type ErrorPayload = StoryPayload & { retryable?: boolean; resets_at?: string | null; retried?: boolean };

/** Whether a `dm_error` entry is one the runner said may be tried again, and nobody has yet. Entries from before
 * retry existed say nothing, and aren't. */
export function retryable(entry: StoryEntry): boolean {
  const error = entry.payload as ErrorPayload;
  return entry.kind === "dm_error" && error.retryable === true && error.retried !== true;
}

/** Retry for the story's latest retryable error: whether it shows (the server says this seat may retry that beat),
 * when the limit ends, and the press. After a press it stays disabled until the next `beat` event, which also asks
 * again whether a retry is possible. */
export function useRetry(campaignId: string, entry: StoryEntry) {
  const client = useQueryClient();
  const subscribe = useContext(EventsContext);
  const [pressed, setPressed] = useState(false);
  const state = useQuery({ queryKey: retryKey(campaignId), queryFn: () => getRetry(campaignId) });
  useEffect(
    () =>
      subscribe({
        beat: (data) => {
          if ((data as { campaign_id?: unknown } | null)?.campaign_id !== campaignId) return;
          setPressed(false);
          void client.invalidateQueries({ queryKey: retryKey(campaignId) });
        },
      }),
    [subscribe, client, campaignId],
  );
  const press = useMutation({
    mutationFn: () => retryBeat(campaignId, entry.beat_id ?? ""),
    onMutate: () => setPressed(true),
    onError: () => {
      setPressed(false);
      void client.invalidateQueries({ queryKey: retryKey(campaignId) });
    },
  });
  const shown = state.data?.may_retry === true && state.data.beat_id === entry.beat_id;
  return { shown, resetsAt: shown ? state.data!.resets_at : null, pressed, retry: () => press.mutate(), error: press.error };
}
