import { screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { translate, type Translate } from "../i18n";
import AccountUsage, { usageLines } from "./AccountUsage";
import type { AccountUsage as Usage } from "./api";
import { CAMPAIGN, base, json, renderWith, stubFetch } from "./testing";

beforeEach(() => {
  // Only Date is faked: the fixtures' reset times are fixed, and the timers react-query and waitFor use must run.
  vi.useFakeTimers({ toFake: ["Date"], now: Date.parse("2026-10-24T07:40:00Z") });
});

afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
});

const t: Translate = (key, vars) => translate("en", key, vars);
const now = Date.parse("2026-10-24T07:40:00Z");
const usage: Usage = {
  at: "2026-10-24T07:40:00Z",
  status: "allowed",
  windows: [
    { name: "five_hour", utilization: 0.82, resets_at: "2026-10-24T09:30:00Z" },
    { name: "seven_day", utilization: 0.41, resets_at: "2026-10-29T00:00:00Z" },
  ],
};

describe("usageLines", () => {
  it("reads each window as its share, its level and the time to its reset", () => {
    expect(usageLines(t, usage, now)).toEqual([
      { name: "five_hour", percent: 82, level: "warn", resetsIn: "1 h 50 min", resetsShort: "1h 50m" },
      { name: "seven_day", percent: 41, level: "ok", resetsIn: "4 d 16 h", resetsShort: "4d 16h" },
    ]);
    const full = { ...usage, windows: [{ ...usage.windows[0], utilization: 0.96 }] };
    expect(usageLines(t, full, now)[0].level).toBe("bad");
    expect(usageLines(t, { ...usage, status: "rejected" }, now)[1].level).toBe("bad");
  });

  it("a window past its reset reads as reset; none reads as nothing", () => {
    const [five] = usageLines(t, usage, Date.parse("2026-10-24T09:31:00Z"));
    expect(five).toEqual({ name: "five_hour", percent: null, level: "ok", resetsIn: null, resetsShort: null });
    expect(usageLines(t, null, now)).toEqual([]);
  });
});

describe("AccountUsage", () => {
  it("shows each window compactly, the whole wording in the tooltip", async () => {
    stubFetch({ [`GET ${base}/play/usage`]: () => json(200, { usage }) });
    renderWith(<AccountUsage campaignId={CAMPAIGN} />);
    const shown = await screen.findByTestId("account-usage");
    const visible = [...shown.querySelectorAll(".usage-window > [aria-hidden]")].map((s) => s.textContent);
    expect(visible).toEqual(["82% 1h 50m", "41% 4d 16h"]);
    expect(shown.title).toContain("5-hour 82% · resets in 1 h 50 min");
    expect(shown.title).toContain("Weekly 41% · resets in 4 d 16 h");
    expect(shown.querySelector(".usage-window.warn .visually-hidden")?.textContent).toBe(
      "5-hour 82% · resets in 1 h 50 min",
    );
  });

  it("shows nothing before the CLI reported any, or when refused", async () => {
    stubFetch({ [`GET ${base}/play/usage`]: () => json(403, { detail: "Only the host can do that." }) });
    const { container } = renderWith(<AccountUsage campaignId={CAMPAIGN} />);
    await new Promise((r) => setTimeout(r, 20));
    expect(container.querySelector("[data-testid=account-usage]")).toBeNull();
  });
});
