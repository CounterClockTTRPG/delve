// The initiative timeline's answer and its layout (table voice and fixes Task B2.3): what
// `GET /api/campaigns/{id}/timeline` gives this seat, and how the strip lays it out along the round's counts.
import { apiFetch } from "../api";

export type OngoingKind = "spell" | "scroll" | "potion" | "item" | "other";

/** An ongoing action as a span on the round's axis. An enemy's has no `what` and no `reason`: those are the DM's. */
export interface TimelineOngoing {
  kind: OngoingKind;
  what: string | null;
  from: number;
  to: number;
  /** It runs past the round: the span runs off the axis's end. */
  next_round: boolean;
  state: "ongoing" | "completed" | "interrupted";
  reason: string | null;
}

export type SlotState = "waiting" | "acting" | "acted" | "down" | "dead" | "fled";

/** A seen combatant of the DM's that isn't a character (DEL-275): its kind, as the DM added it, and the slug and
 * version of that kind's picture (null for none), and whether one is being painted. */
export interface TimelineMonster {
  kind: string;
  picture: string | null;
  version: string | null;
  painting: boolean;
}

/** One combatant on the timeline. An unseen enemy has `name: null` and a `key` of `unseen-<n>`. A combatant down when
 * the round began has no count. `character_id` is a party member's, or an ally's that is a character (an NPC). */
export interface TimelineSlot {
  key: string;
  name: string | null;
  side: "party" | "ally" | "enemy";
  character_id: string | null;
  count: number | null;
  state: SlotState;
  ongoing: TimelineOngoing | null;
  /** Left out for the party, an unseen enemy, an ally that is a character, and by an older server. */
  monster?: TimelineMonster;
}

export interface TimelineFight {
  combat_id: string;
  round: number;
  mode: "combatant" | "side";
  /** The round's outcomes are told: the DM's text for it has arrived. */
  released: boolean;
  max_count: number;
  slots: TimelineSlot[];
}

export interface TimelineAnswer {
  fight: TimelineFight | null;
}

export const timelineKey = (campaignId: string) => ["timeline", campaignId] as const;

export const getTimeline = (campaignId: string) =>
  apiFetch<TimelineAnswer>(`/api/campaigns/${encodeURIComponent(campaignId)}/timeline`);

/** The events after which the strip reads the timeline again: the timeline's own, and a beat's (which closes with
 * whatever the DM's text released). */
export const TIMELINE_EVENTS = ["timeline", "beat"] as const;

/** The slots that act on one count, together. */
export interface CountGroup {
  count: number;
  slots: TimelineSlot[];
}

/** The slots with a count, grouped by it, in the order they act. */
export function byCount(slots: TimelineSlot[]): CountGroup[] {
  const groups = new Map<number, TimelineSlot[]>();
  for (const slot of slots) {
    if (slot.count === null) continue;
    groups.set(slot.count, [...(groups.get(slot.count) ?? []), slot]);
  }
  return [...groups.entries()].sort(([a], [b]) => a - b).map(([count, grouped]) => ({ count, slots: grouped }));
}

/** The counts whose names go above their tokens: every other count of a run of neighbouring counts, so that the
 * names of two neighbours don't run into each other. */
export function raised(groups: CountGroup[]): Set<number> {
  const up = new Set<number>();
  groups.forEach((group, i) => {
    const before = groups[i - 1];
    if (before && before.count === group.count - 1 && !up.has(before.count)) up.add(group.count);
  });
  return up;
}

/** The slots down (or dead) since before the round: they stand off the axis. */
export const outOfTheRound = (slots: TimelineSlot[]) => slots.filter((s) => s.count === null);

/** The slots busy with an ongoing action, in the order they act. */
export const spans = (slots: TimelineSlot[]) =>
  slots.filter((s): s is TimelineSlot & { ongoing: TimelineOngoing } => s.ongoing !== null && s.count !== null);

/** The token's letters: the name's initial, or a question mark for an unseen enemy. */
export const initial = (slot: TimelineSlot) => (slot.name ? slot.name.trim().charAt(0).toUpperCase() : "?");
