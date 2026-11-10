import { useQuery } from "@tanstack/react-query";
import { Gauge } from "lucide-react";
import { useEffect, useState } from "react";
import { useT, type Translate } from "../i18n";
import { getAccountUsage, playKeys, type AccountUsage as Usage } from "./api";

/** How often the usage is read again; the CLI reports it with every turn of the DM. */
export const USAGE_EVERY_MS = 60_000;

export type UsageLevel = "ok" | "warn" | "bad";

export interface UsageLine {
  name: string;
  /** The share used in whole percent; null when unknown or once the window has reset. */
  percent: number | null;
  level: UsageLevel;
  /** "4 h 30 min" until the reset; null once it is past. */
  resetsIn: string | null;
  /** The same, as the header shows it: "4h 30m". */
  resetsShort: string | null;
}

function span(t: Translate, ms: number, short = false): string {
  const minutes = Math.max(1, Math.ceil(ms / 60_000));
  const days = Math.floor(minutes / 1440);
  const hours = Math.floor((minutes % 1440) / 60);
  const unit = (key: string) => (short ? `${key}Short` : key);
  if (days > 0) return t(unit("usage.days"), { days: String(days), hours: String(hours) });
  if (hours > 0) return t(unit("usage.hours"), { hours: String(hours), minutes: String(minutes % 60) });
  return t(unit("usage.minutes"), { minutes: String(minutes) });
}

/** Each window as shown: amber from 80 % (or a warning status), red from 95 % (or refused), as Guild's header. */
export function usageLines(t: Translate, usage: Usage | null | undefined, now: number): UsageLine[] {
  if (!usage) return [];
  const floor: UsageLevel = usage.status === "rejected" ? "bad" : usage.status === "allowed_warning" ? "warn" : "ok";
  return usage.windows.map((w) => {
    const left = Date.parse(w.resets_at) - now;
    const past = !(left > 0);
    const percent = past || w.utilization === null ? null : Math.round(w.utilization * 100);
    const share = percent ?? 0;
    const level: UsageLevel =
      past ? "ok" : share >= 95 || floor === "bad" ? "bad" : share >= 80 || floor === "warn" ? "warn" : "ok";
    return {
      name: w.name,
      percent,
      level,
      resetsIn: past ? null : span(t, left),
      resetsShort: past ? null : span(t, left, true),
    };
  });
}

function windowName(t: Translate, name: string): string {
  if (name === "five_hour") return t("usage.fiveHour");
  if (name === "seven_day") return t("usage.weekly");
  if (name === "seven_day_opus") return t("usage.weeklyOpus");
  return name.replace(/_/g, " ");
}

/** A window in words, as the tooltip and a screen reader have it: "5-hour 82% · resets in 1 h 50 min". */
function lineInWords(t: Translate, line: UsageLine): string {
  const share = line.percent !== null ? ` ${line.percent}%` : "";
  const reset = line.resetsIn === null ? t("usage.reset") : t("usage.resetsIn", { time: line.resetsIn });
  return `${windowName(t, line.name)}${share} · ${reset}`;
}

/**
 * The Claude account's usage in the play header, compactly (DEL-143): a gauge, then each window's share used and the
 * time until it resets, "82% 1h 50m"; the windows' names and the whole wording are in the tooltip. For the host only
 * (the subscription is theirs; the server refuses any other seat); nothing before the CLI reported any.
 */
export default function AccountUsage({ campaignId }: { campaignId: string }) {
  const t = useT();
  const usage = useQuery({
    queryKey: playKeys.usage(campaignId),
    queryFn: () => getAccountUsage(campaignId),
    refetchInterval: USAGE_EVERY_MS,
    retry: false,
  });
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const timer = setInterval(() => setNow(Date.now()), 30_000);
    return () => clearInterval(timer);
  }, []);

  const lines = usageLines(t, usage.data?.usage, now);
  if (lines.length === 0) return null;
  const title = [t("usage.title"), ...lines.map((line) => lineInWords(t, line))].join("\n");
  return (
    <p className="account-usage" data-testid="account-usage" title={title}>
      <Gauge size={16} aria-hidden="true" className="usage-icon" />
      {lines.map((line) => (
        <span key={line.name} className={`usage-window ${line.level}`}>
          <span className="visually-hidden">{lineInWords(t, line)}</span>
          <span aria-hidden="true">
            <span className="usage-percent">{line.percent !== null ? `${line.percent}%` : "–"}</span>
            {line.resetsShort !== null && <span className="usage-reset"> {line.resetsShort}</span>}
          </span>
        </span>
      ))}
    </p>
  );
}
