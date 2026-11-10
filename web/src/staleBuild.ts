// A page open since before a deploy still names the old build's files, which the new build took away: opening a screen
// that loads its code later (the world map, the map editor) fails. Reloading once gets the new build. Not again
// within a minute, so a server that is really down doesn't make the page reload over and over.

const KEY = "delve-reloaded-for-build";
const AGAIN_AFTER_MS = 60_000;

/** Whether the error is a part of the app that couldn't be fetched (each browser says it its own way). */
export function isStaleBuild(error: unknown): boolean {
  const message = error instanceof Error ? error.message : String(error ?? "");
  return /dynamically imported module|Importing a module script failed|Unable to preload CSS/i.test(message);
}

/** Reload the page for the new build, unless it did so less than a minute ago; whether it reloads. */
export function reloadForNewBuild(
  storage: Pick<Storage, "getItem" | "setItem"> | undefined = safeSession(),
  now: number = Date.now(),
  reload: () => void = () => window.location.reload(),
): boolean {
  if (!storage) return false;
  try {
    if (now - (Number(storage.getItem(KEY)) || 0) < AGAIN_AFTER_MS) return false;
    storage.setItem(KEY, String(now));
  } catch {
    return false; // without the guard a reload could loop
  }
  reload();
  return true;
}

/** Vite says when a part of the app couldn't be loaded: reload for the new build instead of failing. */
export function watchForNewBuild(): void {
  window.addEventListener("vite:preloadError", (event) => {
    if (reloadForNewBuild()) event.preventDefault();
  });
}

function safeSession(): Storage | undefined {
  try {
    return window.sessionStorage;
  } catch {
    return undefined;
  }
}
