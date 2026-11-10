// Whether "Did you know" shows while the DM thinks: a per-browser choice in Preferences, on unless turned off. On a
// phone the fact never shows (styles.css), whatever the choice.
import { useCallback, useSyncExternalStore } from "react";
import { safeStorage } from "../desktop/storage";

export const DID_YOU_KNOW_KEY = "delve.didYouKnow";

export function readDidYouKnow(): boolean {
  return safeStorage.getItem(DID_YOU_KNOW_KEY) !== "off";
}

// The choice held for this page view, so one the storage refused still holds until a reload.
let shown: boolean | null = null;
const listeners = new Set<() => void>();

function current(): boolean {
  if (shown === null) shown = readDidYouKnow();
  return shown;
}

function notify(): void {
  for (const listener of listeners) listener();
}

function onStorage(event: StorageEvent): void {
  if (event.key !== DID_YOU_KNOW_KEY && event.key !== null) return;
  shown = readDidYouKnow();
  notify();
}

function subscribe(listener: () => void): () => void {
  if (listeners.size === 0) window.addEventListener("storage", onStorage);
  listeners.add(listener);
  return () => {
    listeners.delete(listener);
    if (listeners.size === 0) window.removeEventListener("storage", onStorage);
  };
}

/** The choice and its setter; a change reaches every mounted reader, also in other tabs. */
export function useDidYouKnow(): [boolean, (on: boolean) => void] {
  const on = useSyncExternalStore(subscribe, current, () => true);
  const set = useCallback((next: boolean) => {
    shown = next;
    safeStorage.setItem(DID_YOU_KNOW_KEY, next ? "on" : "off");
    notify();
  }, []);
  return [on, set];
}

/** For tests: forget the held choice, so the next read is the storage's. */
export function resetDidYouKnow(): void {
  shown = null;
}
