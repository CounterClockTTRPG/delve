/** The time it is now in `timeZone`, as hours and minutes in the reader's `language` ("21:40"); empty for a time zone
 * this browser doesn't know. */
export function localTime(timeZone: string, now: Date, language: string): string {
  try {
    return new Intl.DateTimeFormat(language, { timeZone, hour: "2-digit", minute: "2-digit", hourCycle: "h23" }).format(now);
  } catch {
    return "";
  }
}
