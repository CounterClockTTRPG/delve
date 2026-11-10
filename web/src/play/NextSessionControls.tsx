import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { postJson, type NextSession, type Schedule } from "../api";
import { useLanguage, useT } from "../i18n";
import { sessionWhen } from "./NextSession";
import { useMailEnabled } from "../mail/api";
import { playKeys } from "./api";

/** One change of the next session; `email` also tells the players by email (a reset tells nobody). */
type NextChange = ({ skip: true } | { to: string } | { reset: true }) & { email?: { note: string } };

const changeNext = (campaignId: string, change: NextChange) =>
  postJson<{ schedule: Schedule; next_sessions: NextSession[]; emailed: number }>(
    `/api/campaigns/${encodeURIComponent(campaignId)}/schedule/next`,
    change,
  );

/** A session's start as `<input type="datetime-local">` wants it, in the schedule's own time zone. */
function localStart(session: NextSession, timeZone: string): string {
  const parts = Object.fromEntries(
    new Intl.DateTimeFormat("en-CA", {
      timeZone,
      year: "numeric",
      month: "2-digit",
      day: "2-digit",
      hour: "2-digit",
      minute: "2-digit",
      hourCycle: "h23",
    })
      .formatToParts(new Date(session.starts_at))
      .map((part) => [part.type, part.value]),
  );
  return `${parts.year}-${parts.month}-${parts.day}T${parts.hour}:${parts.minute}`;
}

/**
 * The host's and co-hosts' hold on the next session of the table's schedule (DEL-204 part C), in Host controls: when
 * it is, in the viewer's own time; Skip it, Move it (a date and time in the schedule's time zone, the length kept), and
 * Undo a move. Nothing for a table without a schedule.
 */
export default function NextSessionControls({
  campaignId,
  schedule,
  sessions,
}: {
  campaignId: string;
  schedule: Schedule | null | undefined;
  sessions: NextSession[] | undefined;
}) {
  const t = useT();
  const language = useLanguage();
  const client = useQueryClient();
  const [moving, setMoving] = useState(false);
  const next = sessions?.[0];
  const [to, setTo] = useState("");
  const mail = useMailEnabled();
  const [tell, setTell] = useState(false);
  const [note, setNote] = useState("");
  const withMail = (step: NextChange): NextChange => (tell ? { ...step, email: { note: note.trim() } } : step);
  const change = useMutation({
    mutationFn: (step: NextChange) => changeNext(campaignId, step),
    onSuccess: () => {
      setMoving(false);
      setTell(false);
      setNote("");
      client.invalidateQueries({ queryKey: playKeys.listing(campaignId) });
      client.invalidateQueries({ queryKey: playKeys.state(campaignId) });
    },
  });
  if (!schedule) return null;
  return (
    <section className="next-session-controls" data-testid="next-session-controls" aria-labelledby="next-session-title">
      <h3 id="next-session-title">{t("schedule.nextTitle")}</h3>
      {next ? (
        <p>
          {sessionWhen(next, language)}
          {next.moved && <span className="next-session-moved"> {t("schedule.moved")}</span>}
        </p>
      ) : (
        <p className="placeholder">{t("schedule.noneAhead")}</p>
      )}
      {next && mail && (
        <div className="next-session-tell">
          <label className="check">
            <input type="checkbox" data-testid="next-tell" checked={tell} onChange={(e) => setTell(e.target.checked)} />
            {t("schedule.tell")}
          </label>
          {tell && (
            <input type="text" data-testid="next-note" maxLength={500} aria-label={t("schedule.tellNote")}
              placeholder={t("schedule.tellNote")} value={note} onChange={(e) => setNote(e.target.value)} />
          )}
        </div>
      )}
      {next && !moving && (
        <div className="request-actions">
          <button type="button" data-testid="next-move" disabled={change.isPending}
            onClick={() => {
              setTo(localStart(next, schedule.time_zone));
              setMoving(true);
            }}>
            {t("schedule.move")}
          </button>
          <button type="button" data-testid="next-skip" disabled={change.isPending} onClick={() => change.mutate(withMail({ skip: true }))}>
            {t("schedule.skip")}
          </button>
          {next.moved && (
            <button type="button" data-testid="next-reset" disabled={change.isPending} onClick={() => change.mutate({ reset: true })}>
              {t("schedule.undo")}
            </button>
          )}
        </div>
      )}
      {moving && (
        <form
          className="request-actions"
          onSubmit={(e) => {
            e.preventDefault();
            if (to) change.mutate(withMail({ to }));
          }}
        >
          <label htmlFor="next-to">{t("schedule.moveTo", { zone: schedule.time_zone })}</label>
          <input id="next-to" type="datetime-local" value={to} onChange={(e) => setTo(e.target.value)} />
          <button type="submit" className="primary" data-testid="next-move-save" disabled={!to || change.isPending}>
            {t("schedule.move")}
          </button>
          <button type="button" onClick={() => setMoving(false)}>
            {t("dialog.cancel")}
          </button>
        </form>
      )}
      {change.data && change.variables && "email" in change.variables && (
        <p className="notice" role="status" data-testid="next-told">
          {t("schedule.told", { count: String(change.data.emailed) })}
        </p>
      )}
      {change.error && (
        <p className="notice error" role="alert">
          {change.error.message}
        </p>
      )}
    </section>
  );
}
