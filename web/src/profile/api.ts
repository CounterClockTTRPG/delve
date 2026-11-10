// The profile routes (players and tavern Task D3): an account's own profile and avatar, and the profiles of the
// players at its tables, as `delve.play.profiles.card` lets the caller read them.
import { apiFetch, deleteJson, putJson } from "../api";

/** The looks' accents, a player's colour, by the server's names (`delve.domain.accounts.COLOURS`). */
export const COLOURS = { teal: "#2c7a6b", jade: "#62b9a5", gold: "#e0bc74", ember: "#e08a3c" } as const;
export type ColourName = keyof typeof COLOURS;
export const COLOUR_NAMES = Object.keys(COLOURS) as ColourName[];

/** What a table shows of a player: an uploaded picture (by the start of its sha) wins over the emblem. */
export interface ProfileSummary {
  account_id: string;
  display_name: string;
  pronouns: string;
  avatar: { emblem: string } | { picture: string };
  colour: string;
}

/** A profile as the caller may read it: `host_note` and `time_zone` for a host of the player's tables, and
 * `language` and `avatar_emblem` for the player alone. */
export interface ProfileCard extends ProfileSummary {
  about: string;
  host_note?: string;
  time_zone?: string | null;
  language?: string;
  avatar_emblem?: string;
}

/** The fields an account may change (`delve.play.profiles.updated`). */
export interface ProfileChanges {
  display_name?: string;
  pronouns?: string;
  avatar_emblem?: string;
  colour?: string;
  language?: string;
  about?: string;
  host_note?: string;
  time_zone?: string | null;
}

/** The avatar's upload: the types the server takes, and its limit in bytes. */
export const AVATAR_TYPES = ["image/png", "image/jpeg", "image/webp"];
export const AVATAR_LIMIT = 2 * 1024 * 1024;

export const profileKeys = {
  own: ["account", "profile"] as const,
  card: (accountId: string) => ["profile", accountId] as const,
};

export const avatarUrl = (accountId: string, picture: string) =>
  `/api/profiles/${encodeURIComponent(accountId)}/avatar?v=${encodeURIComponent(picture)}`;

export const getProfile = (accountId: string) => apiFetch<ProfileCard>(`/api/profiles/${encodeURIComponent(accountId)}`);
export const getOwnProfile = () => apiFetch<ProfileCard>("/api/account/profile");
export const putProfile = (changes: ProfileChanges) => putJson<ProfileCard>("/api/account/profile", changes);
/** Uploads the picture as it is: the body is the file, its type the file's. */
export const uploadAvatar = (file: File) =>
  apiFetch<ProfileCard>("/api/account/avatar", { method: "POST", headers: { "Content-Type": file.type }, body: file });
export const removeAvatar = () => deleteJson<ProfileCard>("/api/account/avatar");
