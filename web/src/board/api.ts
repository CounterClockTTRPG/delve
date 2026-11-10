// The message board's data (DEL-297): its zones, the topics in a zone, the posts in a topic, a post's picture, and a
// zone's moderators and members. The shapes are what `src/delve/web/routes/board.py` answers.
import { apiFetch, deleteJson, patchJson, postJson, putJson } from "../api";
import type { ProfileSummary } from "../profile/api";

/** Who may read or write in a zone: everybody (visitors too), any account, the zone's members, or the campaign's table. */
export type Level = "everybody" | "accounts" | "members" | "table";

/** What the caller may do in a zone, as the server worked it out for them. */
export interface ZoneRights {
  read: boolean;
  write: boolean;
  moderate: boolean;
  manage: boolean;
  manage_wide: boolean;
}

export interface Zone {
  id: string;
  name: string;
  description: string;
  position: number;
  read: Level;
  write: Level;
  pictures: boolean;
  campaign_id: string | null;
  rights: ZoneRights;
}

/** A zone in the board's list, with how many topics it has, how many of them are new to the caller, and the topic
 * written in last (none in an empty zone). */
export interface BoardZone extends Zone {
  topics: number;
  new_topics: number;
  latest: { topic_id: string; title: string; at: string; author: Author } | null;
}

export interface Topic {
  id: string;
  zone_id: string;
  title: string;
  author: Author;
  created_at: string;
  last_post_at: string;
  last_author: Author;
  posts: number;
  pinned: boolean;
  locked: boolean;
  /** Written in since the caller last read it (accounts only). */
  new: boolean;
  /** Whether the caller follows it, to be emailed about replies (DEL-314): on the topic's own page and a topic just
   * started or changed, not in a zone's list. */
  following?: boolean;
}

/** An author as the zone's readers see them. An author with no account (the owner by token, or one who is gone) has
 * no name, no avatar and no colour. */
export interface Author {
  account_id: string | null;
  display_name: string;
  avatar: ProfileSummary["avatar"] | null;
  colour: string | null;
  /** `organiser`, `moderator`, `host` or `cohost`. */
  badges: string[];
}

export interface Post {
  id: string;
  topic_id: string;
  author: Author;
  text: string;
  created_at: string;
  edited_at: string | null;
  /** Who removed it, its words and picture gone with it: its author, or who moderates. */
  removed: "author" | "moderator" | null;
  picture: { width: number; height: number } | null;
  /** The caller wrote it. */
  mine: boolean;
}

/** One page of a topic's posts, oldest first. */
export interface TopicPage {
  zone: Zone;
  topic: Topic;
  posts: Post[];
  page: number;
  pages: number;
  first_unread_page: number;
  /** The first post on this page the caller hasn't read (accounts only), which the page scrolls to. */
  first_unread_post: string | null;
}

export interface Board {
  zones: BoardZone[];
  may_create: boolean;
  signed_in: boolean;
}

/** The campaign's zone among the board's, when it has one the caller may read. */
export const zoneOfCampaign = (board: Board | undefined, campaignId: string): BoardZone | undefined =>
  board?.zones.find((zone) => zone.campaign_id === campaignId);

/** A moderator or member of a zone. */
export interface Person {
  account_id: string;
  display_name: string;
  username: string;
}

export interface ZonePeople {
  moderators: Person[];
  members: Person[];
}

/** The fields of a zone that may be sent when making or changing one. */
export interface ZoneFields {
  name?: string;
  description?: string;
  read?: Level;
  write?: Level;
  pictures?: boolean;
  campaign_id?: string | null;
}

export const boardKeys = {
  all: ["board"] as const,
  zone: (id: string) => ["board", "zone", id] as const,
  /** `page` undefined is the page the server picks (the first with something unread). */
  topic: (id: string, page?: number) => ["board", "topic", id, page ?? "unread"] as const,
  people: (id: string) => ["board", "people", id] as const,
};

const root = "/api/board";
const zonePath = (id: string) => `${root}/zones/${encodeURIComponent(id)}`;
const topicPath = (id: string) => `${root}/topics/${encodeURIComponent(id)}`;
const postPath = (id: string) => `${root}/posts/${encodeURIComponent(id)}`;

export const getBoard = () => apiFetch<Board>(root);
export const createZone = (fields: ZoneFields) => postJson<{ zone: Zone }>(`${root}/zones`, fields);
export const updateZone = (id: string, fields: ZoneFields) => patchJson<{ zone: Zone }>(zonePath(id), fields);
export const deleteZone = (id: string) => deleteJson(zonePath(id));
export const reorderZones = (zoneIds: string[]) => putJson<{ zones: Zone[] }>(`${root}/order`, { zone_ids: zoneIds });

export const getZonePeople = (id: string) => apiFetch<ZonePeople>(`${zonePath(id)}/people`);
export const setModerators = (id: string, usernames: string[]) =>
  putJson<ZonePeople>(`${zonePath(id)}/moderators`, { usernames });
export const addMember = (id: string, username: string) => postJson<ZonePeople>(`${zonePath(id)}/members`, { username });
export const removeMember = (id: string, accountId: string) =>
  deleteJson<ZonePeople>(`${zonePath(id)}/members/${encodeURIComponent(accountId)}`);

export const getZone = (id: string) => apiFetch<{ zone: Zone; topics: Topic[] }>(zonePath(id));
/** `follow`: the author follows the new topic. */
export const startTopic = (zoneId: string, title: string, text: string, follow = false) =>
  postJson<{ topic: Topic; post: Post }>(`${zonePath(zoneId)}/topics`, { title, text, ...(follow ? { follow } : {}) });
/** A page of the topic; without `page`, the first with something the caller hasn't read. */
export const getTopic = (id: string, page?: number) =>
  apiFetch<TopicPage>(page === undefined ? topicPath(id) : `${topicPath(id)}?page=${page}`);
export const setTopic = (id: string, change: { pinned?: boolean; locked?: boolean }) =>
  patchJson<{ topic: Topic }>(topicPath(id), change);
export const deleteTopic = (id: string) => deleteJson(topicPath(id));
/** Follow a topic, or stop: an email for a new reply, then none until the reader is back (DEL-314). */
export const followTopic = (id: string) => putJson<{ following: boolean }>(`${topicPath(id)}/follow`, {});
export const unfollowTopic = (id: string) => deleteJson<{ following: boolean }>(`${topicPath(id)}/follow`);

/** `follow`: the author follows the topic too. */
export const reply = (topicId: string, text: string, follow = false) =>
  postJson<{ post: Post }>(`${topicPath(topicId)}/posts`, { text, ...(follow ? { follow } : {}) });
export const editPost = (id: string, text: string) => patchJson<{ post: Post }>(postPath(id), { text });
export const deletePost = (id: string) => deleteJson<{ post: Post }>(postPath(id));

/** The picture of a post: the body is its bytes, the type its own. */
export const attachPicture = (postId: string, file: File) =>
  apiFetch<{ post: Post }>(`${postPath(postId)}/picture`, {
    method: "POST",
    headers: { "Content-Type": file.type || "application/octet-stream" },
    body: file,
  });
export const takeDownPicture = (postId: string) => deleteJson<{ post: Post }>(`${postPath(postId)}/picture`);
/** Where a post's picture, and its author's uploaded avatar, are served. */
export const postPictureUrl = (postId: string) => `${postPath(postId)}/picture`;
export const postAvatarUrl = (postId: string) => `${postPath(postId)}/avatar`;
