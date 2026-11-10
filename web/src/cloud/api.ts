// The Storage API (cloud storage plan Tasks 4, 7 and 8): the backup store, the shared library's store, the backup time,
// Back up now and Restore, the install's owner's alone. A SAS or secret key goes in and never comes back out: a store's
// view says only whether its secret is set, and where the store is.
import { apiFetch, deleteJson, postJson, putJson, type ModuleDetail } from "../api";

export type StoreKind = "backup" | "library";
export type StoreProvider = "azure" | "s3" | "local";
export type Right = "read" | "publish" | "manage";
export type ItemKind = "module" | "campaign" | "setting";

/** A saved store, as `GET /api/storage` shows it. `expires` is an Azure SAS's `se=`; `choice` is the owner's cap on an
 * S3 library's write key. */
export interface StoreView {
  provider: StoreProvider;
  label: string;
  secret: "set" | "unset";
  right: Right | null;
  expires: string | null;
  choice: "publish" | "manage" | null;
}

/** What `PUT /api/storage/{kind}` takes. An absent secret (`sas_url` for Azure, `secret_access_key` for S3) keeps the
 * stored one. */
export interface StoreConfig {
  provider: StoreProvider;
  sas_url?: string;
  endpoint?: string;
  bucket?: string;
  access_key_id?: string;
  secret_access_key?: string;
  root?: string;
  right?: "publish" | "manage";
}

/** A failed item of a run; `index` is the backup's list itself (`index.json`), whose title older runs left empty. */
export interface BackupFailure {
  kind: ItemKind | "index";
  item_id: string;
  title: string;
  error: string;
}

/** A backup run's result (Task 7's `RunResult`), stored as the schedule's `last_run`. */
export interface BackupRun {
  started_at: string;
  finished_at: string;
  uploaded: string[];
  unchanged: number;
  failed: BackupFailure[];
  status?: "ok" | "partial" | "failed";
}

export interface Schedule {
  time: string;
  last_run: BackupRun | null;
  /** Whether a run is going now, as `GET /api/storage` says it. */
  running?: boolean;
}

export interface StorageState {
  backup: StoreView | null;
  library: StoreView | null;
  schedule: Schedule;
  install_id: string;
}

export interface StoreCheck {
  ok: boolean;
  right: Right | null;
  message: string;
}

/** An install that backed up to the backup store (its `index.json`). */
export interface BackedUpInstall {
  install_id: string;
  name: string;
  updated_at: string;
}

/** One item of an install's backup index. A campaign names its module and setting, so Restore brings them along. */
export interface BackupItem {
  kind: ItemKind;
  item_id: string;
  title: string;
  hash: string;
  size: number;
  backed_up_at: string;
  on_install: boolean;
  exists_here: boolean;
  module_id?: string | null;
  setting_id?: string | null;
}

export interface RestoreResult {
  kind: ItemKind;
  item_id: string;
  ok: boolean;
  warnings: string[];
  error: string | null;
  added?: boolean;
}

/** What a prune of the blob store would delete, or deleted (DEL-36): by type, largest first; `mime` is null for files
 * without their row. `kept` are files nothing uses yet but too new to go. */
export interface UnusedFiles {
  count: number;
  size: number;
  kept: number;
  kinds: { mime: string | null; count: number; size: number }[];
}

export const storageKey = ["storage"];
export const backupsKey = ["storage", "backups"];
export const backupIndexKey = (installId: string) => ["storage", "backups", installId];

export const getStorage = () => apiFetch<StorageState>("/api/storage");
export const putStore = (kind: StoreKind, config: StoreConfig) => putJson<StoreView>(`/api/storage/${kind}`, config);
export const removeStore = (kind: StoreKind) => deleteJson<null>(`/api/storage/${kind}`);
export const testStore = (kind: StoreKind) => postJson<StoreCheck>(`/api/storage/${kind}/test`);
export const putSchedule = (time: string) => putJson<Schedule>("/api/storage/schedule", { time });
/** Starts a run in the background (202); 409 while one runs. The run's result comes as `last_run`. */
export const backupNow = () => postJson<unknown>("/api/storage/backup");
export const getUnused = () => apiFetch<UnusedFiles>("/api/storage/unused");
export const deleteUnused = () => postJson<UnusedFiles>("/api/storage/unused/delete");
export const getBackups = () => apiFetch<BackedUpInstall[]>("/api/storage/backups");
export const getBackupIndex = (installId: string) =>
  apiFetch<BackupItem[]>(`/api/storage/backups/${encodeURIComponent(installId)}`);
export const restore = (installId: string, items: { kind: ItemKind; item_id: string }[], replace: boolean) =>
  postJson<RestoreResult[]>("/api/storage/restore", { install_id: installId, items, replace });

/** A run's status: its own when the server says it, else from what it uploaded and what failed. */
export function runStatus(run: BackupRun): "ok" | "partial" | "failed" {
  if (run.status) return run.status;
  if (run.failed.length === 0) return "ok";
  return run.uploaded.length > 0 || run.unchanged > 0 ? "partial" : "failed";
}

const R2_ENDPOINT = /^https:\/\/([0-9a-z]+)\.r2\.cloudflarestorage\.com\/?$/i;

/** R2's endpoint for an account id. */
export const r2Endpoint = (account: string) => `https://${account.trim()}.r2.cloudflarestorage.com`;

/** The R2 account id of an endpoint, or null for another S3-compatible store. */
export function r2Account(endpoint: string): string | null {
  return R2_ENDPOINT.exec(endpoint.trim())?.[1] ?? null;
}

const DAY = 24 * 60 * 60 * 1000;

/** How near an Azure SAS's expiry is: amber within 14 days, red once past. */
export function expiryTone(expires: string, now: Date = new Date()): "ok" | "soon" | "past" {
  const left = new Date(expires).getTime() - now.getTime();
  if (left <= 0) return "past";
  return left <= 14 * DAY ? "soon" : "ok";
}

/** A size as Restore shows it: "800 B", "12 kB", "2.4 MB". */
export function sizeText(language: string, bytes: number): string {
  const units = ["B", "kB", "MB", "GB"];
  let value = bytes;
  let unit = 0;
  while (value >= 1000 && unit < units.length - 1) {
    value /= 1000;
    unit += 1;
  }
  const number = new Intl.NumberFormat(language, { maximumFractionDigits: unit === 0 ? 0 : 1 }).format(value);
  return `${number} ${units[unit]}`;
}

/** A day, as the reader's language writes it. */
export function dayText(language: string, at: string): string {
  return new Date(at).toLocaleDateString(language, { dateStyle: "medium" });
}

/** A day and a time, as the reader's language writes them. */
export function whenText(language: string, at: string): string {
  return new Date(at).toLocaleString(language, { dateStyle: "medium", timeStyle: "short" });
}

// The library (cloud storage plan Tasks 9 and 10), for organisers: browse, download, publish, delete and update.

/** The newest version of one library entry; `local` is the module here that came from it or went to it. */
export interface LibraryEntry {
  key: string;
  version: number;
  title: string;
  summary: string;
  author: string;
  created_at: string;
  updated_at: string;
  size: number;
  hash: string;
  publisher: string;
  format: number;
  local: { module_id: string; origin: "published" | "downloaded"; version: number } | null;
}

/** `GET /api/library`: this install's right, the entries (newest updated first), and the entries it couldn't read. */
export interface Library {
  right: Right | null;
  entries: LibraryEntry[];
  warnings: string[];
}

export const libraryKey = ["library"];

/** 409 when no library store is set up. */
export const getLibrary = () => apiFetch<Library>("/api/library");
export const downloadEntry = (key: string) => postJson<ModuleDetail>("/api/library/download", { key });
/** The module's next version, or a new entry; the server's author (the account's name) unless one is given. */
export const publishModule = (moduleId: string, author?: string) =>
  postJson<LibraryEntry>(`/api/modules/${encodeURIComponent(moduleId)}/publish`, author ? { author } : {});
/** The entry's newest version as a new revision of the module; `keepCopy` first keeps it as it is as a module. */
export const updateModule = (moduleId: string, keepCopy: boolean) =>
  postJson<ModuleDetail>(`/api/modules/${encodeURIComponent(moduleId)}/library-update`, { keep_copy: keepCopy });
/** Every version of the entry, or only `version`. */
export const deleteEntry = (key: string, version?: number) =>
  deleteJson<null>(`/api/library/${encodeURIComponent(key)}${version === undefined ? "" : `?version=${version}`}`);

/** Whether this install may add a version to the entry from its module here, one it published (a downloaded one
 * publishes as a new entry): with manage always; with publish only while the entry's newest version is still its own
 * (the server checks the publisher again). */
export function mayAddVersion(right: Right | null, entry: Pick<LibraryEntry, "version" | "local">): boolean {
  if (entry.local?.origin !== "published") return false;
  return right === "manage" || (right === "publish" && entry.local.version === entry.version);
}
