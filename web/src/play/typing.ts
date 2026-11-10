import { useSyncExternalStore } from "react";
import type { TypingState } from "./SeatIndicators";

export type Typing = Record<string, TypingState>;

/** A seat's "typing" with no word since for this long is taken as idle: its "idle" may never come (a closed tab, a
 * dropped stream). A typing seat says so again every 3 s (the boxes' TYPING_EVERY_MS), well within it. */
export const TYPING_TTL_MS = 8000;

/** Who is typing at the table, as the `typing` events say, outside React's state (DEL-168): a keystroke elsewhere at
 * the table re-renders the seats and the talk that show it, never the whole play screen and its story. */
export interface TypingStore {
  get: () => Typing;
  set: (seatId: string, state: TypingState) => void;
  clear: () => void;
  subscribe: (listener: () => void) => () => void;
}

export function typingStore(): TypingStore {
  let typing: Typing = {};
  const listeners = new Set<() => void>();
  const expiries = new Map<string, ReturnType<typeof setTimeout>>();
  const change = (next: Typing) => {
    typing = next;
    listeners.forEach((listener) => listener());
  };
  const set = (seatId: string, state: TypingState) => {
    const expiry = expiries.get(seatId);
    if (expiry) clearTimeout(expiry);
    expiries.delete(seatId);
    if (state === "typing") expiries.set(seatId, setTimeout(() => set(seatId, "idle"), TYPING_TTL_MS));
    if (typing[seatId] !== state) change({ ...typing, [seatId]: state });
  };
  return {
    get: () => typing,
    set,
    clear: () => {
      expiries.forEach((expiry) => clearTimeout(expiry));
      expiries.clear();
      if (Object.keys(typing).length > 0) change({});
    },
    subscribe: (listener) => {
      listeners.add(listener);
      return () => void listeners.delete(listener);
    },
  };
}

/** Who is typing now: the component that reads it renders again when it changes. */
export function useTyping(store: TypingStore): Typing {
  return useSyncExternalStore(store.subscribe, store.get);
}
