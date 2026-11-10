import type { NextSession as Session, Schedule } from "../api";
import { useLanguage, useT, type Translate } from "../i18n";

/** The viewer's own time zone, as the browser knows it: every session shows in it (DEL-204 part C). */
export const viewerTimeZone = (): string => Intl.DateTimeFormat().resolvedOptions().timeZone || "UTC";

/** A session as the viewer reads it, in their own time: "Sat 7 Nov, 20:00–22:00". */
export function sessionWhen(session: Session, language: string, timeZone = viewerTimeZone()): string {
  const start = new Date(session.starts_at);
  const end = new Date(session.ends_at);
  const day = start.toLocaleDateString(language, { weekday: "short", day: "numeric", month: "short", timeZone });
  const time = (at: Date) => at.toLocaleTimeString(language, { hour: "2-digit", minute: "2-digit", timeZone });
  return `${day}, ${time(start)}–${time(end)}`;
}

/** The rule in the host's words and time zone: "Every 2 weeks on Saturday, 20:00–22:00, Europe/Brussels time". */
export function scheduleRule(t: Translate, schedule: Schedule, language: string): string {
  // The first date's weekday, read at noon UTC so no time zone moves it to another day.
  const weekday = new Date(`${schedule.first}T12:00:00Z`).toLocaleDateString(language, { weekday: "long", timeZone: "UTC" });
  const times = `${schedule.start}–${schedule.end}`;
  return schedule.every_weeks === 1
    ? t("schedule.ruleWeekly", { weekday, times, zone: schedule.time_zone })
    : t("schedule.ruleEvery", { n: String(schedule.every_weeks), weekday, times, zone: schedule.time_zone });
}

/**
 * When the table plays next (DEL-204 part C): the next session in the viewer's own time, marked when the host moved
 * it, and, with `schedule`, the rule as the host set it. Nothing for a table without a schedule or a session ahead.
 */
export default function NextSessionLine({
  sessions,
  schedule = null,
  className = "next-session",
}: {
  sessions: Session[] | undefined;
  schedule?: Schedule | null;
  className?: string;
}) {
  const t = useT();
  const language = useLanguage();
  const next = sessions?.[0];
  if (!next && !schedule) return null;
  return (
    <p className={className} data-testid="next-session">
      {next && (
        <span className="next-session-when">
          {t("schedule.next", { when: sessionWhen(next, language) })}
          {next.moved && <span className="next-session-moved"> {t("schedule.moved")}</span>}
        </span>
      )}
      {schedule && <span className="next-session-rule">{scheduleRule(t, schedule, language)}</span>}
    </p>
  );
}
