import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useEffect, useId, useMemo, useState } from "react";
import { NeedsToken, putJson, queryKeys, type Campaign, type Schedule } from "../api";
import TimeZonePicker, { closestZone, useTimeZones } from "../components/TimeZonePicker";
import { useLanguage, useT } from "../i18n";
import { scheduleRule, sessionWhen, viewerTimeZone } from "../play/NextSession";
import styles from "./TableSettings.module.css";

const EVERY = [1, 2, 3, 4];

const putSchedule = (id: string, schedule: Schedule | null) =>
  putJson<Campaign>(`/api/campaigns/${encodeURIComponent(id)}/schedule`, schedule);

/**
 * When the table plays, on the campaign page (DEL-204 part C): every one to four weeks from a first date (whose weekday
 * is the rule's), from a start to an end time in a time zone (the browser's by default). Saved with Save, cleared with
 * No schedule. Under it, the next sessions as the server reckons them, in the viewer's own time; players see them in
 * theirs. The host moves or skips the next one from the Table tab.
 */
export default function TableSchedule({ campaign }: { campaign: Campaign }) {
  const t = useT();
  const language = useLanguage();
  const client = useQueryClient();
  const ids = { every: useId(), first: useId(), start: useId(), end: useId(), zone: useId() };
  const zones = useTimeZones(campaign.schedule?.time_zone);
  const own = useMemo(() => closestZone(viewerTimeZone(), zones), [zones]);
  const blank = (): Schedule => ({ every_weeks: 1, first: "", start: "20:00", end: "22:00", time_zone: own, changes: [] });
  const [draft, setDraft] = useState<Schedule>(campaign.schedule ?? blank());
  // The campaign as read again (saved here or in another tab): the form follows it.
  useEffect(() => setDraft(campaign.schedule ?? blank()), [campaign.schedule]);
  // A new schedule's zone is the browser's as the server names it, known once its zones are read.
  useEffect(() => setDraft((was) => (campaign.schedule ? was : { ...was, time_zone: own })), [own]);
  const set = (patch: Partial<Schedule>) => setDraft((was) => ({ ...was, ...patch }));
  const save = useMutation({
    mutationFn: (next: Schedule | null) => putSchedule(campaign.id, next),
    onSuccess: () => {
      client.invalidateQueries({ queryKey: queryKeys.campaign(campaign.id) });
      client.invalidateQueries({ queryKey: queryKeys.campaigns });
    },
  });
  const ready = Boolean(draft.first && draft.start && draft.end && draft.time_zone);
  const weekday = draft.first
    ? new Date(`${draft.first}T12:00:00Z`).toLocaleDateString(language, { weekday: "long", timeZone: "UTC" })
    : null;

  return (
    <form
      className={styles.listing}
      data-testid="table-schedule"
      onSubmit={(e) => {
        e.preventDefault();
        if (ready) save.mutate(draft);
      }}
    >
      <div className={styles.settings}>
        <div className={`field ${styles.setting}`}>
          <label htmlFor={ids.every}>{t("schedule.every")}</label>
          <select id={ids.every} value={draft.every_weeks} onChange={(e) => set({ every_weeks: Number(e.target.value) })}>
            {EVERY.map((n) => (
              <option key={n} value={n}>
                {t(n === 1 ? "schedule.everyWeek" : "schedule.everyWeeks", { n: String(n) })}
              </option>
            ))}
          </select>
        </div>
        <div className={`field ${styles.setting}`}>
          <label htmlFor={ids.first}>{t("schedule.first")}</label>
          <input id={ids.first} type="date" value={draft.first} onChange={(e) => set({ first: e.target.value })} />
          {weekday && <p className="hint">{t("schedule.onWeekday", { weekday })}</p>}
        </div>
      </div>
      <div className={styles.settings}>
        <div className={`field ${styles.setting}`}>
          <label htmlFor={ids.start}>{t("schedule.start")}</label>
          <input id={ids.start} type="time" value={draft.start} onChange={(e) => set({ start: e.target.value })} />
        </div>
        <div className={`field ${styles.setting}`}>
          <label htmlFor={ids.end}>{t("schedule.end")}</label>
          <input id={ids.end} type="time" value={draft.end} onChange={(e) => set({ end: e.target.value })} />
          {draft.end && draft.start && draft.end <= draft.start && <p className="hint">{t("schedule.pastMidnight")}</p>}
        </div>
        <div className={`field ${styles.setting}`}>
          <label htmlFor={ids.zone}>{t("schedule.timeZone")}</label>
          <TimeZonePicker
            id={ids.zone}
            testId="schedule-time-zone"
            zones={zones}
            value={draft.time_zone}
            onChange={(time_zone) => set({ time_zone })}
            preferred={own}
          />
        </div>
      </div>

      {campaign.schedule && (
        <div className="schedule-preview" data-testid="schedule-preview">
          <p className="row-meta">{scheduleRule(t, campaign.schedule, language)}</p>
          {(campaign.next_sessions ?? []).length > 0 ? (
            <>
              <p className="hint">{t("schedule.nextInYourTime", { zone: own })}</p>
              <ul>
                {(campaign.next_sessions ?? []).map((session) => (
                  <li key={session.on}>
                    {sessionWhen(session, language)}
                    {session.moved && <span className="next-session-moved"> {t("schedule.moved")}</span>}
                  </li>
                ))}
              </ul>
            </>
          ) : (
            <p className="hint">{t("schedule.noneAhead")}</p>
          )}
        </div>
      )}

      <div className={styles.actions}>
        <button type="submit" className="primary" data-testid="schedule-save" disabled={!ready || save.isPending}>
          {t("schedule.save")}
        </button>
        {campaign.schedule && (
          <button type="button" data-testid="schedule-clear" disabled={save.isPending} onClick={() => save.mutate(null)}>
            {t("schedule.clear")}
          </button>
        )}
      </div>
      {save.error && !(save.error instanceof NeedsToken) && (
        <p role="alert" className="notice error">
          {t("schedule.saveFailed", { error: save.error.message })}
        </p>
      )}
    </form>
  );
}
