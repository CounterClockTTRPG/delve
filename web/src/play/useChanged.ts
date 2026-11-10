import { useEffect, useState } from "react";

/**
 * Whether a panel changed since this seat last saw it, for the dot on its tab. `signature` sums up what the panel
 * shows (null while it loads); `seen`, whether the panel is on screen now. What the panel holds when it first loads,
 * and every change made while it is on screen, counts as seen.
 */
export function useChanged(signature: string | null, seen: boolean): boolean {
  const [base, setBase] = useState<string | null>(null);
  const settled = signature !== null && (base === null || seen);
  useEffect(() => {
    if (settled) setBase(signature);
  }, [settled, signature]);
  return !seen && signature !== null && base !== null && signature !== base;
}
