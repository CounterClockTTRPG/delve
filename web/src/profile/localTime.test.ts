import { describe, expect, it } from "vitest";
import { localTime } from "./localTime";

describe("localTime", () => {
  // 19:40 UTC on 24 October 2026 is 21:40 in Brussels (summer time until the 25th), and 20:40 on 26 October.
  it("says the time in the player's time zone", () => {
    expect(localTime("Europe/Brussels", new Date("2026-10-24T19:40:00Z"), "en")).toBe("21:40");
    expect(localTime("Europe/Brussels", new Date("2026-10-26T19:40:00Z"), "nl")).toBe("20:40");
    expect(localTime("America/New_York", new Date("2026-10-24T19:40:00Z"), "en")).toBe("15:40");
  });

  it("says nothing for a time zone it doesn't know", () => {
    expect(localTime("Mars/Olympus", new Date("2026-10-24T19:40:00Z"), "en")).toBe("");
  });
});
