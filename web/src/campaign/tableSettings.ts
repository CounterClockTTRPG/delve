// The campaign's table settings and a character's departure, as the server takes them (table voice and fixes Task S2).
import { putJson, type Campaign, type Character, type Visibility } from "../api";

export const VOICE_SETTINGS = ["allowed", "off"] as const;
export type VoiceSetting = (typeof VOICE_SETTINGS)[number];

export const INITIATIVE_MODES = ["combatant", "side"] as const;
export type InitiativeMode = (typeof INITIATIVE_MODES)[number];

/** Who may watch (DEL-215): anyone with the link, those a host lets in, or nobody. */
export const OBSERVER_RULES = ["anyone", "approved", "nobody"] as const;
export type ObserverRule = (typeof OBSERVER_RULES)[number];

/** Why a PC left the party: the order the campaign page offers them in. */
export const DEPARTURES = ["died", "retired", "left"] as const;
export type Departure = (typeof DEPARTURES)[number];

export interface TableSettingsChange {
  voice?: VoiceSetting;
  initiative?: InitiativeMode;
  observers?: ObserverRule;
}

const campaignPath = (id: string) => `/api/campaigns/${encodeURIComponent(id)}`;

/** The host sets voice and the initiative mode; a key left out stays as it is. Voice off disconnects everyone in it. */
export const putTableSettings = (id: string, change: TableSettingsChange) =>
  putJson<Campaign>(`${campaignPath(id)}/table-settings`, change);

/** A PC leaves the party for a reason, or comes back (null). */
export const putDeparture = (id: string, characterId: string, departure: Departure | null) =>
  putJson<Character>(`${campaignPath(id)}/characters/${encodeURIComponent(characterId)}/departure`, { departure });

/** The table's listing (DEL-204): who can find it, its description for players, and its places. */
export interface TableListing {
  visibility: Visibility;
  description: string;
  slots: number | null;
}

/** As the server takes them: a description of at most this many characters, and 1 to `MAX_SLOTS` places. */
export const DESCRIPTION_CHARS = 4000;
export const MAX_SLOTS = 20;

export const putListing = (id: string, listing: TableListing) => putJson<Campaign>(`${campaignPath(id)}/listing`, listing);
