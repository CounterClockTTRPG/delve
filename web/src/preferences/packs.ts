// The install's packs (DEL-366): listed for the organisers, installed and removed by the owner, and the restart that
// makes Delve use what changed; and a setting's additions, exported and imported by an organiser.
import { apiFetch, deleteJson, postJson } from "../api";

export interface PackRow {
  id: string;
  kind: "ruleset" | "setting";
  title: string;
  version: string;
  /** In use since Delve started, at this version; else it waits for a restart. */
  active: boolean;
  /** The campaigns that name it. */
  campaigns: string[];
}

/** What a restart would do: whether one is needed, whether Delve can restart itself, and what it breaks off. */
export interface RestartState {
  possible: boolean;
  needed: boolean;
  /** The campaigns whose beat the DM is answering. */
  beats: string[];
  /** The running conversion's title. */
  conversion: string | null;
}

export interface PacksView {
  packs: PackRow[];
  /** Packs Delve still uses that are no longer installed. */
  removed: string[];
  can_install: boolean;
  restart: RestartState;
}

export const packKeys = { all: ["packs"] as const };

export const getPacks = () => apiFetch<PacksView>("/api/packs");
export const packDownloadUrl = (id: string) => `/api/packs/${encodeURIComponent(id)}/download`;

/** Install or update the pack in `file`, a `.delvepack`. */
export const uploadPack = (file: File) =>
  apiFetch<{ pack: PackRow; restart: RestartState }>("/api/packs", {
    method: "POST",
    headers: { "Content-Type": "application/zip" },
    body: file,
  });

/** Remove the pack; `force` also when campaigns use it (else 409 with them). */
export const removePack = (id: string, force = false) =>
  deleteJson<{ restart: RestartState }>(`/api/packs/${encodeURIComponent(id)}${force ? "?force=true" : ""}`);

export const restartDelve = () => postJson<{ restarting: boolean } & Pick<RestartState, "beats" | "conversion">>("/api/restart");

/** What an import of a setting's additions did. */
export interface ImportedAdditions {
  pages_added: number;
  pages_replaced: number;
  pages_kept: number;
  facts_added: number;
  facts_kept: number;
  maps_added: number;
  maps_replaced: number;
  maps_kept: number;
}

export const additionsExportUrl = (settingId: string) => `/api/settings/${encodeURIComponent(settingId)}/additions/export`;

/** Import a file of the setting's additions; `keep`: what this install has already stays as it is. */
export const importAdditions = (settingId: string, file: File, keep: boolean) =>
  apiFetch<{ imported: ImportedAdditions }>(
    `/api/settings/${encodeURIComponent(settingId)}/additions${keep ? "" : "?keep=false"}`,
    { method: "POST", headers: { "Content-Type": "application/zip" }, body: file },
  );
