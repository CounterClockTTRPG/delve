// A look is a set of CSS tokens under `:root[data-look="…"]`, chosen per browser. `public/look.js` sets the attribute
// before the first paint; this module reads, applies and remembers the choice. Delve today sets no attribute.
import { useCallback, useLayoutEffect, useSyncExternalStore } from "react";

export const LOOKS = ["delve", "gold-wood", "dark-dungeon"] as const;
export type Look = (typeof LOOKS)[number];

export const LOOK_KEY = "delve.look";

function isLook(value: unknown): value is Look {
  return (LOOKS as readonly unknown[]).includes(value);
}

/** The stored choice; Delve today for none, junk, or a storage that throws (a private window, blocked site data). */
export function readLook(): Look {
  try {
    const stored = localStorage.getItem(LOOK_KEY);
    return isLook(stored) ? stored : "delve";
  } catch {
    return "delve";
  }
}

export function applyLook(look: Look): void {
  const root = document.documentElement;
  if (look === "delve") delete root.dataset.look;
  else root.dataset.look = look;
}

export function editorTheme(look: Look): "dmap-paper" | "dmap-night" {
  return look === "delve" ? "dmap-paper" : "dmap-night";
}

// The page's attribute is the look in use, so a choice the storage refused still holds for this page view.
const listeners = new Set<() => void>();

function current(): Look {
  const look = document.documentElement.dataset.look;
  return isLook(look) ? look : "delve";
}

function notify(): void {
  for (const listener of listeners) listener();
}

// While a print view is mounted the page shows no look; a choice made in another tab waits until it closes.
let plainViews = 0;
let heldLook: Look = "delve";

function onStorage(event: StorageEvent): void {
  if (event.key !== LOOK_KEY && event.key !== null) return;
  if (plainViews > 0) {
    heldLook = readLook();
    return;
  }
  applyLook(readLook());
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

/** The look in use, and a setter that applies it, remembers it in this browser, and re-renders every user. */
export function useLook(): [Look, (look: Look) => void] {
  const look = useSyncExternalStore(subscribe, current);
  const choose = useCallback((next: Look) => {
    try {
      localStorage.setItem(LOOK_KEY, next);
    } catch {
      // No storage: the look holds for this page view only.
    }
    applyLook(next);
    notify();
  }, []);
  return [look, choose];
}

/** Print views never follow the look: it is taken off `<html>` while one is mounted, and put back after. */
export function useNoLook(): void {
  useLayoutEffect(() => {
    if (plainViews++ === 0) {
      heldLook = current() === "delve" ? readLook() : current();
      applyLook("delve");
    }
    return () => {
      if (--plainViews === 0) applyLook(heldLook);
    };
  }, []);
}
