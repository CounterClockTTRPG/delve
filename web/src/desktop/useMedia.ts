import { useEffect, useState } from "react";

/** From 900 px the screens sit side by side (styles.css), and their dividers can be dragged. */
export const WIDE_QUERY = "(min-width: 900px)";

function matches(query: string): boolean {
  return typeof window.matchMedia === "function" && window.matchMedia(query).matches;
}

/** Whether `query` matches now, following the window as it is resized. */
export function useMedia(query: string): boolean {
  const [now, setNow] = useState(() => matches(query));
  useEffect(() => {
    if (typeof window.matchMedia !== "function") return;
    const list = window.matchMedia(query);
    const changed = () => setNow(list.matches);
    changed();
    list.addEventListener?.("change", changed);
    return () => list.removeEventListener?.("change", changed);
  }, [query]);
  return now;
}

export function useWide(): boolean {
  return useMedia(WIDE_QUERY);
}
