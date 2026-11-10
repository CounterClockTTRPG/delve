// Shapes from the play API (plateau 2b, task 7), in one place so they are easy to adjust.
import { apiFetch, deleteJson, postJson, putJson, type Effort, type NextSession, type Portrait, type Schedule } from "../api";
import type { ProfileSummary } from "../profile/api";

export type StoryKind =
  | "player_act" | "dm_text" | "tool" | "image" | "dm_error" | "recap" | "ask" | "answer" | "talk" | "scene" | "say";

/** A story entry. Its payload is already player-safe (the server built it through player_view). */
export interface StoryEntry {
  id: string;
  campaign_id: string;
  beat_id: string | null;
  seq: number;
  kind: StoryKind;
  payload: StoryPayload;
  at: string;
  /** Who may see it: null (or missing) for everyone; otherwise it was addressed to some characters or seats. */
  audience?: Audience | null;
  /** The entry in the seat's language, when the story was read with `language` or a `translation` event came. */
  translation?: Translation;
  /** Set by the page (`useStory`), never by the server: the entry came in while the page was open, not with a page
   * of the story. */
  live?: boolean;
}

export type Audience = { characters: string[] } | { seats: string[] };

export type TranslationStatus = "translating" | "done" | "failed";

export interface Translation {
  language: string;
  text: string;
  status: TranslationStatus;
  /** A shared Ask the DM answer's translation, beside its question's (`text`). */
  answer?: string;
}

/**
 * `dm_text`: {text}; `tool`: {name} or {name, failed} (spec §7.5's allow-list), with its `dice`; `image`: {asset, caption}, an image the
 * DM shows; `dm_error`: {message}; `recap`: {text, session, title}; `player_act`, `ask` and `answer` carry their words
 * as `text`; `talk`: {seat_id, name, text, original, language}, table talk, and when an Ask the DM answer was
 * shared, also {answer, shared} (the answer's id); `scene`: {image_id, caption}, a painted scene (plan 6), its bytes at
 * `pictureUrl`; `say`: {speaker: {id, name, portrait}, mood, text}, an NPC's line (the `say` tool).
 */
/** One roll a tool row shows (DEL-270), as the server filtered it for this seat: who rolled (a name, else `side`),
 * what for (a word of Delve's, `what`, and/or the DM's own words or a skill, ability or save, `detail`), the dice
 * without their modifier, every face rolled and the total of those kept. Never a modifier or a number needed. */
export interface DiceLine {
  who: string | null;
  side: "party" | "enemies" | "enemy" | null;
  what: string | null;
  detail: string | null;
  dice: string;
  faces: number[];
  total: number;
}

/** One step of a batch's tool row: its index in the batch, its tool, whether it was refused or never ran, and the
 * dice it rolled that this seat may read. */
export interface ToolStep {
  step: number;
  name: string;
  failed?: boolean;
  dice?: DiceLine[];
}

export interface StoryPayload {
  text?: string;
  message?: string;
  name?: string;
  failed?: boolean;
  /** A batch's steps, which the story shows as the calls they are (a tool row's). */
  steps?: ToolStep[];
  /** A tool row's dice this seat may read (DEL-270). */
  dice?: DiceLine[];
  question?: string;
  answer?: string;
  recap?: string;
  characters?: string[];
  asset?: string;
  image_id?: string;
  caption?: string;
  seat_id?: string;
  /** A player_act's hotseat player (DEL-365), whose name is `name`. */
  hotseat?: string;
  original?: string;
  language?: string;
  shared?: string;
  kind?: string;
  speaker?: { id: string; name: string; portrait: Portrait | null };
  mood?: string;
  /** A picture pasted into table talk (DEL-294), served by `talkPictureUrl`. */
  picture?: { blob: string; mime: string; width: number; height: number };
  /** The talk line's picture was taken down. */
  picture_removed?: boolean;
}

export interface StoryPage {
  entries: StoryEntry[];
  has_more: boolean;
}

export type BeatStatus = "open" | "running" | "done" | "failed" | "cancelled";

/**
 * The current beat. `open` waits for the table (spec §7.1); `running` is the DM answering. `submitted` holds the
 * seats that acted or passed (never what they wrote), and `deadline` is when the beat timer runs out, while open.
 * The tool count is no part of it: the host and co-hosts get it as `beat_tools` events.
 */
export interface RunningBeat {
  id: string;
  status: BeatStatus;
  elapsed_s: number;
  submitted?: string[];
  deadline?: string | null;
}

/**
 * An act or pass of the open beat, as `GET …/beat/pending` shows it to this seat: its own first, then the others'
 * that aren't private; none for an observer. `text` is the act's own words for a seat of its language, else English.
 */
export interface PendingAct {
  seat_id: string | null;
  name: string;
  kind: "act" | "pass";
  text: string;
  characters: string[];
  private: boolean;
  at: string;
  /** The hotseat player whose act it is (DEL-365), whose name is `name`; null for a seat's own. */
  hotseat?: string | null;
}

/** One of the players at the host's screen (DEL-365), with the PCs they play. */
export interface HotseatPlayer {
  /** Left out for a player the host has just added: the server gives one. */
  id?: string;
  name: string;
  characters: string[];
}

/** Hotseat as the play screen reads it: whether it is on, whose screen it is, and its players as they play now (only
 * those with a character the host's seat plays). */
export interface Hotseat {
  on: boolean;
  seat_id: string | null;
  players: (HotseatPlayer & { id: string })[];
}

/** A party member from the player-safe `primer` subset, in marching order. */
export interface PartyMember {
  id: string;
  name: string;
  race?: string;
  cls?: string;
  /** The level per lowercase class: {fighter: 1, thief: 1}. */
  levels?: Record<string, number>;
  hp: number;
  hp_max: number;
  ac: number;
  conditions: string[];
  spells?: { memorized: string[]; uncast: string[] };
}

/** Where one group of characters is. `characters` holds names (as `primer` gives them) or ids. */
export interface Position {
  map: string;
  location: string | null;
  label: string | null;
  characters: string[];
}

/** A painting's painter, and its place in that painter's queue while it waits there (DEL-138): null once it runs,
 * or when the painter doesn't say. Left out by an older server. */
export interface Waiting {
  provider?: string;
  queue?: number | null;
}

/** A scene still painting (DEL-115): its picture comes into the story as a `scene` entry once it lands. */
export interface PaintingScene extends Waiting {
  image_id: string;
  caption: string;
}

export interface PlayState {
  beat: RunningBeat | null;
  party: PartyMember[];
  positions: Position[];
  combat: unknown;
  session_number: number | null;
  /** The session has ended and the next hasn't started (DEL-182); left out by an older server. */
  session_over?: boolean;
  /** The ruleset or setting the campaign needs that isn't installed (DEL-307); null when it has both. */
  missing_pack?: { kind: "ruleset" | "setting"; id: string } | null;
  /** The party's average level outside the module's levels (DEL-187); null when it fits or the module doesn't say. */
  level_fit?: { min: number; max: number; party: number } | null;
  time_of_day: string | null;
  /** The campaign's date ("4 Planting 576 CY", or "Day 12" without a setting), and today's weather once asked. */
  date?: string | null;
  weather?: Weather | null;
  /** The style the campaign's portraits are drawn in (one of PORTRAIT_STYLES). */
  portrait_style?: string;
  /** The style NPCs' portraits are drawn in (DEL-252); left out by an older server. */
  npc_portrait_style?: string;
  /** The campaign's current banner, its bytes at `bannerUrl`; null while it has none. */
  banner?: string | null;
  /** The party's purse, by coin: pp, gp, ep, sp and cp. */
  coin?: Partial<Record<Coin, number>>;
  /** The campaign's ruleset's id, which the header's Rulesets link opens; left out by an older server. */
  ruleset?: string;
  /** Whether Paint this scene can paint now: paid images are on, or the scene's model is free. */
  scene_painting?: boolean;
  /** Whether painting a scene costs the host money (DEL-258); left out by an older server. */
  scene_paid?: boolean;
  /** Whether the seated players and the hosts may paste pictures into table talk (DEL-294). */
  talk_pictures?: boolean;
  /** Several players at the host's screen (DEL-365); left out by an older server. */
  hotseat?: Hotseat;
  /** The scenes still painting that this seat will see, oldest first: the story shows a placeholder for each. */
  painting_scenes?: PaintingScene[];
  /** Where the table's session is, which the host and co-hosts move, and the hands raised at it (DEL-199). */
  table: TableSession;
  /** The table's next sessions on its schedule, for the play header (DEL-204 part C); left out by an older server. */
  next_sessions?: NextSession[];
  /** Whether the table may talk in voice; left out by an older server (table voice and fixes). */
  voice?: "allowed" | "off";
  /** How the campaign's fights roll initiative; left out by an older server. */
  initiative?: "combatant" | "side";
  /** The PCs who left the party, apart from it (table voice and fixes Task C2); left out by an older server. */
  departed?: DepartedMember[];
}

/** Why a PC left the party. */
export type Departure = "died" | "retired" | "left";

/** A PC who left the party: still a sheet to open, no longer in the party, the marching order or Acting for. */
export interface DepartedMember {
  id: string;
  name: string;
  departure: Departure;
}

export const COINS = ["pp", "gp", "ep", "sp", "cp"] as const;
export type Coin = (typeof COINS)[number];

export interface Weather {
  label: string;
  effect: string;
}

/** A quest the characters know, with only the notes they know (plan 6, Decision 7). */
export interface WorldQuest {
  id: string;
  title: string;
  giver: string;
  scope: string;
  stakes: string;
  status: string;
  started_day: number | null;
  ended_day: number | null;
  log: { day: number; text: string }[];
}

/** A faction the characters know: its standing word, never the reputation number. */
export interface WorldFaction {
  id: string;
  name: string;
  standing: string;
}

/** A possession as the party knows it, without the DM's notes; `owner` is a name, null for the party's. */
export interface WorldPossession {
  id: string;
  name: string;
  kind: string;
  owner: string | null;
  owner_id: string | null;
  location: string;
  value_gp: number;
  description: string;
  inventory: string[];
  stats: Record<string, unknown>;
  portrait: Portrait | null;
}

/** `GET …/world`: what the characters know of the world, the same for every seat. */
export interface World {
  date: string;
  weather: Weather | null;
  position: { map: string; at_label: string | null } | null;
  quests: WorldQuest[];
  factions: WorldFaction[];
  possessions: WorldPossession[];
}

export interface LoreFact {
  text: string;
  category: string;
}

export const TONES = ["classic", "grimdark", "heroic", "horror", "comedic", "young"] as const;
/** A custom tone takes at most this many characters, as the server does. */
export const CUSTOM_TONE_CHARS = 2000;
export const DETAILS = [0, 1, 2, 3] as const;
/** What a campaign may award XP for (DEL-113), in the server's order; monsters, milestones and roleplay by default. */
export const XP_AWARDS = ["monsters", "milestones", "roleplay", "gold", "abilities"] as const;
export type XpAward = (typeof XP_AWARDS)[number];

export type Fallback = "hold_back" | "in_character";
export const FALLBACKS: Fallback[] = ["hold_back", "in_character"];
/** The beat timer's choices, in seconds; null is none. The server takes 30 to 1800. */
export const BEAT_TIMERS = [null, 60, 120, 180, 300, 600] as const;
/** The choices of paid pictures a day (DEL-153); 20 by default, the server takes 1 to 500. */
export const PAID_PER_DAY = [5, 10, 20, 40, 100] as const;

export interface PlaySettings {
  tone: string;
  detail: number;
  effort?: Effort | null;
  model?: string | null;
  beat_timer_s?: number | null;
  fallback?: Fallback;
  /** Paid images (Replicate): off until the host turns them on; only the host may. */
  paid_images?: boolean;
  /** How many paid pictures the campaign paints in 24 hours (DEL-153); the host's, as the switch is. */
  paid_images_per_day?: number;
  /** The style the campaign's portraits are drawn in, which only an organiser sets; null: as in Preferences. */
  portrait_style?: string | null;
  /** What the DM awards XP for, which only an organiser sets; gold is also awarded with each hoard. */
  xp_awards?: XpAward[];
  /** The host's own words for the DM's voice, used when `tone` is "custom" (DEL-204): what the DM should follow. */
  custom_tone?: string;
  /** Whether every seat reads the enemies' dice in the story (DEL-270); the host's, as paid images are. */
  enemy_dice?: EnemyDice;
  /** Whether the story shows any dice to the seats but the host's (DEL-280): off, it reads in words alone. */
  show_dice?: boolean;
  /** Whether the seated players and the hosts may paste pictures into table talk (DEL-294); the host's alone. */
  talk_pictures?: boolean;
  /** Several players at the host's screen, each acting for their own characters (DEL-365); the host's alone. */
  hotseat?: boolean;
  /** The players at the host's screen, as the host set them. */
  hotseat_players?: HotseatPlayer[];
}

/** The enemies' dice behind the screen (the host's alone) or in the open (every seat's). */
export const ENEMY_DICE = ["screen", "open"] as const;
export type EnemyDice = (typeof ENEMY_DICE)[number];

/** The host's part of the table options, which the host and co-hosts set. */
export interface TableSettings {
  beat_timer_s: number | null;
  fallback: Fallback;
  paid_images: boolean;
  paid_images_per_day: number;
  hotseat: boolean;
  hotseat_players: HotseatPlayer[];
}

export type SeatRole = "host" | "cohost" | "player" | "observer";
/** The roles that run the table: Go, the timer, the invite, the seats and the characters. */
export const TABLE_ROLES = new Set<SeatRole>(["host", "cohost"]);

/** A seat at the table, as every seat there sees it: `characters` are the ids of the PCs it plays, and `profile` its
 * account's face and name (players and tavern Task G3), null for a seat without an account, the owner's included. */
export interface Seat {
  id: string;
  name: string;
  language: string;
  role: SeatRole;
  organiser: boolean;
  present: boolean;
  characters: string[];
  profile: ProfileSummary | null;
}

/** Who this browser is; `seat` is its seat at the asked campaign's table (the owner's owner seat there). */
export interface Invite {
  url: string;
  join_token: string;
}

/** A pregenerated character of the module, as the host's picker reads it: never one the module keeps for the DM. */
export interface Pregen {
  id: string;
  name: string;
  race?: string;
  class?: string;
  level?: number | string;
  alignment?: string;
  gear?: string[];
  background?: string;
  stats?: Record<string, unknown>;
}

/** A house rule as a table shows it to its players: its title and its text in Markdown. */
export interface TableRule {
  id: string;
  title: string;
  body_md: string;
}

/** What a table tells its players and those about to join (DEL-204): its description (for players; the DM never reads
 * it), its places (null: no limit) and how many are taken, and the house rules in effect. */
export interface TableAboutData {
  description: string;
  slots: number | null;
  taken: number;
  house_rules: TableRule[];
  /** When it plays, and its next sessions (DEL-204 part C); left out by an older server. */
  schedule?: Schedule | null;
  next_sessions?: NextSession[];
}

/** Who may watch a table (DEL-215): anyone with the link, those a host lets in, or nobody. */
export type ObserverRule = "anyone" | "approved" | "nobody";

export interface JoinLink {
  /** The table's description, places and house rules are left out by an older server. */
  campaign: { name: string; module_title: string; host?: string | null } & Partial<TableAboutData> & {
    full?: boolean;
    observers?: ObserverRule;
  };
  languages: string[];
}

const campaignPath = (id: string) => `/api/campaigns/${encodeURIComponent(id)}`;

/** An image the DM showed: served only for the player images of the campaign's pinned revision. */
export const imageUrl = (id: string, asset: string) => `${campaignPath(id)}/images/${encodeURIComponent(asset)}`;

/** A painted picture (plan 6): a portrait for everyone at the table, a scene for its audience. */
export const pictureUrl = (id: string, imageId: string) =>
  `${campaignPath(id)}/pictures/${encodeURIComponent(imageId)}`;
/** The host's "Paint this scene": a side pass writes the brief, and the scene paints in the background. */
export const paintScene = (id: string, hint?: string) =>
  postJson<{ image_id: string; status: "painting" }>(`${campaignPath(id)}/scene`, hint ? { hint } : {});

/** The campaign's banner on its page (`GET /api/campaigns/{id}`'s `banner`), for organisers: the current one, a
 * newer one that waits, paints or failed (its error only when failed), and whether Paint again may be pressed now. */
export interface CampaignBanner {
  image_id: string | null;
  /** The banner shown is the module's (DEL-123): the campaign has none of its own yet. */
  from_module?: boolean;
  pending: ({ status: "waiting" | "painting" | "failed"; error: string | null } & Waiting) | null;
  can_paint: boolean;
  /** Why Paint again can't be pressed now, when `can_paint` is false, in English for the API. */
  why_not: string | null;
  /** The same reason as a code the web app words in the reader's language (DEL-97): `banner.whyNot.<code>`. */
  why_not_code?: "paid_images_off" | null;
}

/** A module's campaign with a banner, as the module's page lists them. */
export interface ModuleBanner {
  campaign_id: string;
  name: string;
  image_id: string;
}

/** The table's next sessions as a calendar file, for a seat to import (DEL-236). */
export const scheduleCalendarUrl = (campaignId: string) => `${campaignPath(campaignId)}/schedule.ics`;
/** A banner address's query: `v` makes a new picture a new address; `size=card` asks for its small copy (DEL-234). */
function bannerQuery(imageId?: string, size?: "card"): string {
  const query = new URLSearchParams();
  if (imageId) query.set("v", imageId);
  if (size) query.set("size", size);
  const text = query.toString();
  return text ? `?${text}` : "";
}
/** The campaign's current banner, for every seat of its table. `imageId` makes a new banner a new address, since the
 * route answers whichever is current; `card` is its small copy, for the cards. */
export const bannerUrl = (campaignId: string, imageId?: string, size?: "card") =>
  `${campaignPath(campaignId)}/banner${bannerQuery(imageId, size)}`;
/** A campaign's banner on its module's page, for organisers. */
export const moduleBannerUrl = (moduleId: string, campaignId: string, imageId?: string, size?: "card") =>
  `/api/modules/${encodeURIComponent(moduleId)}/banners/${encodeURIComponent(campaignId)}${bannerQuery(imageId, size)}`;
/** Paint again, an organiser's: 422 while paid images are off, 409 while one paints; the old one stays till it lands. */
export const paintBannerAgain = (campaignId: string, hint: string) =>
  postJson<{ image_id: string; status: "painting" }>(`${campaignPath(campaignId)}/banner`, { hint });
export const getModuleBanners = (moduleId: string) =>
  apiFetch<ModuleBanner[]>(`/api/modules/${encodeURIComponent(moduleId)}/banners`);

export const getWorld = (id: string) => apiFetch<World>(`${campaignPath(id)}/world`);
/** The setting's lore facts at random, for "Did you know" while the DM thinks; never a campaign's own fact. */
export const getLore = (id: string, n = 20) => apiFetch<{ facts: LoreFact[] }>(`${campaignPath(id)}/lore/random?n=${n}`);

/** The pinned revision's pregens for the players; the host's and co-hosts' to read (403 for anyone else). */
export const getPregens = (id: string) => apiFetch<{ pregens: Pregen[] }>(`${campaignPath(id)}/pregens`);

/** Act; a `secret` act is for the DM alone (plan 7 Task 17): no other seat sees it, pending or in the story. */
/** `player`: a hotseat player at the host's screen (DEL-365), whose act it is. */
export const act = (id: string, text: string, characters?: string[], secret = false, player?: string) =>
  postJson<{ beat: RunningBeat }>(`${campaignPath(id)}/act`, {
    text,
    ...(characters ? { characters } : {}),
    ...(secret ? { private: true } : {}),
    ...(player ? { player } : {}),
  });
export const passBeat = (id: string, characters?: string[], player?: string) =>
  postJson<{ beat: RunningBeat }>(`${campaignPath(id)}/pass`, {
    ...(characters ? { characters } : {}),
    ...(player ? { player } : {}),
  });
/** A tool row's call and reply, from the DM log: the host's alone. */
export type ToolCallDetails = { name: string; args: Record<string, unknown>; ok: boolean; result: unknown };
export const getToolCall = (id: string, entryId: string) =>
  apiFetch<ToolCallDetails>(`${campaignPath(id)}/story/${encodeURIComponent(entryId)}/tool`);

export const getPending = (id: string) => apiFetch<{ pending: PendingAct[] }>(`${campaignPath(id)}/beat/pending`);
export const goBeat = (id: string) => postJson<{ beat: RunningBeat }>(`${campaignPath(id)}/go`);
export const sendTyping = (id: string, state: "typing" | "idle") =>
  postJson<unknown>(`${campaignPath(id)}/typing`, { state });
export const talk = (id: string, text: string) => postJson<{ entry: StoryEntry }>(`${campaignPath(id)}/talk`, { text });
/** A picture into table talk (DEL-294): the body is its bytes, the type its own. */
export const pasteTalkPicture = (id: string, file: File) =>
  apiFetch<{ entry: StoryEntry }>(`${campaignPath(id)}/talk/picture`, {
    method: "POST",
    headers: { "Content-Type": file.type || "application/octet-stream" },
    body: file,
  });
/** Where a picture of table talk is served, by its entry. */
export const talkPictureUrl = (id: string, entryId: string) => `${campaignPath(id)}/talk/pictures/${encodeURIComponent(entryId)}`;
export const takeDownTalkPicture = (id: string, entryId: string) =>
  deleteJson<{ entry: StoryEntry }>(talkPictureUrl(id, entryId));
export const askDm = (id: string, question: string) =>
  postJson<{ answer: string }>(`${campaignPath(id)}/ask`, { question });
export const shareAnswer = (id: string, answerId: string) =>
  postJson<{ entry: StoryEntry }>(`${campaignPath(id)}/ask/${encodeURIComponent(answerId)}/share`);
export const cancelBeat = (id: string) => postJson<unknown>(`${campaignPath(id)}/cancel`);

/** The table's listing as its seats read it (DEL-204). */
export const getListing = (id: string) =>
  apiFetch<TableAboutData & { visibility: "private" | "public" }>(`${campaignPath(id)}/listing`);
/** The host or a co-host takes a seat from the table, as if it had left: its characters are free again. */
export const removeSeat = (id: string, seatId: string) =>
  postJson<{ seat: Seat }>(`${campaignPath(id)}/seats/${encodeURIComponent(seatId)}/remove`);

/** What becomes of an absent player's character for the session: the DM plays it, it stays in the background, or it
 * sits the session out. */
export type AbsentChoice = "in_character" | "hold_back" | "out";

/** A hand raised at the table, with the point its seat wants to make before anyone acts, if it gave one. */
export interface RaisedHand {
  seat_id: string;
  at: string;
  point: string | null;
}

/** A seat away mid-session (DEL-224): beats don't wait for it, and its PCs take `part` meanwhile (null: the table's
 * fallback), unless the host chose another for one. */
export interface AwaySeat {
  seat_id: string;
  at: string;
  part: AbsentChoice | null;
}

/**
 * The table's session (DEL-199): gathering before a session (talk and Ask the DM, no acting, until the host starts
 * it), playing, or on a break. A solo table (one seat that acts) starts on its first act. `absent` holds the host's
 * choice for the PCs whose players aren't there, at the start or since (DEL-224); `hands`, oldest first, the hands
 * raised; `away` the seats away mid-session, oldest first.
 */
export interface TableSession {
  state: "gathering" | "playing" | "break";
  since: string | null;
  solo: boolean;
  absent: Record<string, AbsentChoice>;
  hands: RaisedHand[];
  away: AwaySeat[];
}

const sessionPath = (id: string, step: string) => `${campaignPath(id)}/session/${step}`;
/** Start the session: the DM opens the scene, playing or not the absent players' characters as `absent` says. */
export const startSession = (id: string, absent: Record<string, AbsentChoice>) =>
  postJson<{ table: TableSession; beat: RunningBeat }>(sessionPath(id, "start"), { absent });
export const takeBreak = (id: string) => postJson<{ table: TableSession }>(sessionPath(id, "break"));
export const resumeSession = (id: string) => postJson<{ table: TableSession }>(sessionPath(id, "resume"));
/** End the session: the DM brings the scene to a pause and writes the recap; the table gathers again. */
export const endSession = (id: string) => postJson<{ table: TableSession; beat: RunningBeat }>(sessionPath(id, "end"));
export const raiseHand = (id: string, point: string | null) =>
  postJson<{ table: TableSession }>(`${campaignPath(id)}/hand`, { point });
/** Lower a seat's hand: one's own, or anyone's for the host and co-hosts. */
export const lowerHand = (id: string, seatId: string) =>
  deleteJson<{ table: TableSession }>(`${campaignPath(id)}/hand/${encodeURIComponent(seatId)}`);
/** Step away mid-session (DEL-224): this seat, or `seatId` for the host and co-hosts, its PCs taking `part` meanwhile. */
export const stepAway = (id: string, part: AbsentChoice | null, seatId?: string) =>
  postJson<{ table: TableSession }>(`${campaignPath(id)}/away`, seatId ? { part, seat_id: seatId } : { part });
/** Back at the table: one's own seat, or anyone's for the host and co-hosts. */
export const comeBack = (id: string, seatId: string) =>
  deleteJson<{ table: TableSession }>(`${campaignPath(id)}/away/${encodeURIComponent(seatId)}`);
/** The host sets a PC's part for the rest of the session while its player doesn't act; null leaves it to its player. */
export const setPart = (id: string, characterId: string, part: AbsentChoice | null) =>
  putJson<{ table: TableSession }>(`${campaignPath(id)}/parts/${encodeURIComponent(characterId)}`, { part });

/** A page of the story; with `language` (not English), each entry carries its translation, if it has one. */
export function getStory(id: string, before?: number, limit = 50, language?: string, kind?: StoryEntry["kind"]) {
  const query = new URLSearchParams({ limit: String(limit) });
  if (before !== undefined) query.set("before", String(before));
  if (language && language !== "en") query.set("language", language);
  if (kind) query.set("kind", kind);
  return apiFetch<StoryPage>(`${campaignPath(id)}/story?${query}`);
}

export const getSeats = (id: string) => apiFetch<Seat[]>(`${campaignPath(id)}/seats`);
export const putSeat = (id: string, seatId: string, change: { role: SeatRole }) =>
  putJson<Seat>(`${campaignPath(id)}/seats/${encodeURIComponent(seatId)}`, change);
/** Play a free PC; the host gives it to `seat`. */
export const claimCharacter = (id: string, characterId: string, seat?: string) =>
  postJson<unknown>(`${campaignPath(id)}/characters/${encodeURIComponent(characterId)}/claim`, seat ? { seat } : {});
export const releaseCharacter = (id: string, characterId: string) =>
  postJson<unknown>(`${campaignPath(id)}/characters/${encodeURIComponent(characterId)}/release`);
export const leaveTable = (id: string) => postJson<unknown>(`${campaignPath(id)}/leave`);
export const getInvite = (id: string) => apiFetch<Invite>(`${campaignPath(id)}/invite`);
export const newInvite = (id: string) => postJson<Invite>(`${campaignPath(id)}/invite`);
/** The table options alone: the host isn't always an organiser, who sets the rest. */
export const putTableSettings = (id: string, settings: Partial<TableSettings>) =>
  putJson<PlaySettings>(`${campaignPath(id)}/play/options`, settings);

const joinPath = (token: string) => `/api/join/${encodeURIComponent(token)}`;
export const getJoinLink = (token: string) => apiFetch<JoinLink>(joinPath(token));

export const getPlayState = (id: string) => apiFetch<PlayState>(`${campaignPath(id)}/play/state`);
/** The Claude account's usage as the CLI last reported it: each window's share used (0..1, null unknown) and reset. */
export interface AccountUsage {
  at: string;
  status: string;
  windows: { name: string; utilization: number | null; resets_at: string }[];
}

/** The host's alone (403 for any other seat); `usage` is null before the CLI reported any. */
export const getAccountUsage = (id: string) =>
  apiFetch<{ usage: AccountUsage | null }>(`${campaignPath(id)}/play/usage`);
/** A page of the campaign's log (DEL-324): the session it is of (null before the first), its part of that session, its
 * first and last time and how many entries it holds. */
export interface LogPage {
  page: number;
  session: number | null;
  title: string;
  part: number;
  parts: number;
  from: string;
  to: string;
  entries: number;
}

/** The campaign's log: the index of its pages, page `page`'s entries as the seat saw them (a tool row as the dice the
 * players read: `payload.dice`), and the names of the characters the acts were for. */
export interface CampaignLog {
  campaign: { id: string; name: string };
  pages: LogPage[];
  page: number;
  entries: StoryEntry[];
  names: Record<string, string>;
}

export const getCampaignLog = (id: string, page: number, language?: string) =>
  apiFetch<CampaignLog>(
    `${campaignPath(id)}/log?page=${page}${language ? `&language=${encodeURIComponent(language)}` : ""}`,
  );
export const getPlaySettings = (id: string) => apiFetch<PlaySettings>(`${campaignPath(id)}/play/options`);
/** The options sent, and only those: the server changes what the body names (DEL-168), so a tone changed doesn't touch
 * the beat timer, and two quick changes don't undo each other. */
export const putPlaySettings = (id: string, settings: Partial<PlaySettings>) =>
  putJson<PlaySettings>(`${campaignPath(id)}/play/options`, settings);
/** The campaign's portrait style alone, which an organiser sets on the campaign page. */
export const putPortraitStyle = (id: string, style: string | null) =>
  putJson<PlaySettings>(`${campaignPath(id)}/play/options`, { portrait_style: style });

/** The PCs' new marching order, front first, by id (set_marching_order, through a host route). */
export const putMarchingOrder = (id: string, order: string[]) =>
  putJson<unknown>(`${campaignPath(id)}/marching-order`, { order });

export const playKeys = {
  log: (id: string, page: number, language: string) => ["campaign", id, "log", page, language],
  state: (id: string) => ["campaign", id, "play", "state"],
  /** The open beat's acts so far, which a `beat` event refreshes. */
  pending: (id: string) => ["campaign", id, "beat", "pending"],
  settings: (id: string) => ["campaign", id, "play", "settings"],
  seats: (id: string) => ["campaign", id, "seats"],
  invite: (id: string) => ["campaign", id, "invite"],
  me: (id: string) => ["me", id],
  usage: (id: string) => ["campaign", id, "play", "usage"],
  /** The world and its maps' list, which a `world` event refreshes. */
  world: (id: string) => ["campaign", id, "world"],
  lore: (id: string) => ["campaign", id, "lore"],
  pregens: (id: string) => ["campaign", id, "pregens"],
  /** The table's listing as its seats read it, which a `table_listing` or `seats` event refreshes. */
  listing: (id: string) => ["campaign", id, "listing"],
  /** A tool row's call and reply, which never change. */
  toolCall: (id: string, entryId: string) => ["campaign", id, "tool", entryId],
  /** Under `campaigns`, so that a `campaigns` event (a banner landed or failed) refreshes it too. */
  moduleBanners: (moduleId: string) => ["campaigns", "banners", moduleId],
} as const;

/** The SSE events the play screen listens to; each carries the campaign's id as `campaign_id`. */
export const PLAY_EVENTS = [
  "story",
  /** The new words of the reply the DM is writing, `{entry_id, at, text}` (DEL-241): `story` brings it whole. */
  "story_text",
  "beat",
  "characters",
  "map_state",
  "combat",
  "seats",
  "typing",
  "translation",
  "world",
  "beat_tools",
  /** The host turned paid images on or off: the state says again whether a scene can be painted. */
  "play_options",
  "banner",
  /** A scene began painting, landed or failed: the state says again which are still painting. */
  "scenes",
  /** The table's session moved (started, a break, ended) or a hand went up or down: the state says again. */
  "table",
  /** The host changed the table's description, places or visibility: the listing is read again. */
  "table_listing",
  /** A request to join the table came, got a message, or was decided (the host's and co-hosts' alone, DEL-204). */
  "join_requests",
  /** A DM's tool call changed something, once for the call: `{campaign_id, areas, maps}` (DEL-168). */
  "changed",
  /** Not the server's: the app's stream says it is back after a break (`sharedEvents`, DEL-168). */
  "reconnected",
] as const;
