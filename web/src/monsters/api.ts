// The kinds of monsters' pictures, for every campaign (DEL-275): `delve.web.routes.monster_pictures`.
import { apiFetch } from "../api";

/** A kind's picture as Paint and a Rulesets entry show it; `paid` when painting it costs money. */
export interface MonsterPictureState {
  slug: string;
  picture: boolean;
  /** When the picture last changed, for the browser's cache; null without one. */
  version: string | null;
  painting: boolean;
  error: string | null;
  paid: boolean;
}

export const monsterKeys = {
  all: ["monster-picture"] as const,
  state: (name: string) => ["monster-picture", name] as const,
};

/** The kind's picture; `version` makes a repainted one load again. */
export const monsterPictureUrl = (slug: string, version?: string | null) =>
  `/api/monster-pictures/${encodeURIComponent(slug)}${version ? `?v=${encodeURIComponent(version)}` : ""}`;

export const getMonsterPicture = (name: string) =>
  apiFetch<MonsterPictureState>(`/api/monster-pictures?name=${encodeURIComponent(name)}`);

/** Paint the kind (again), for everyone; `campaignId` is the table that asked, whose strip reads it again. */
export const paintMonster = (name: string, campaignId?: string) =>
  apiFetch<MonsterPictureState>("/api/monster-pictures", {
    method: "POST",
    body: JSON.stringify({ name, campaign_id: campaignId ?? null }),
  });
