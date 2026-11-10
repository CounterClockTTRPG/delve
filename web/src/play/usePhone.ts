import { useEffect, useState } from "react";

/** Under 600 px the play screen is the phone's: the story and the input box, the panels one tap away (spec §7.6). */
export const PHONE_QUERY = "(max-width: 599px)";

function matches(): boolean {
  return typeof window.matchMedia === "function" && window.matchMedia(PHONE_QUERY).matches;
}

export function usePhone(): boolean {
  const [phone, setPhone] = useState(matches);
  useEffect(() => {
    if (typeof window.matchMedia !== "function") return;
    const query = window.matchMedia(PHONE_QUERY);
    const changed = () => setPhone(query.matches);
    query.addEventListener?.("change", changed);
    return () => query.removeEventListener?.("change", changed);
  }, []);
  return phone;
}
