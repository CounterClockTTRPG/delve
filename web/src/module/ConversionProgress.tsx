import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useContext, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import {
  EventsContext,
  NeedsToken,
  cancelConversion,
  getConversion,
  queryKeys,
  resumeConversion,
  type Conversion,
  type ConversionEvent,
} from "../api";
import { useConfirm } from "../components/dialogs";
import { useLanguage, useT } from "../i18n";
import { countLine, makesModule, markSeen, pauseLine, stepLine } from "./conversions";

/**
 * One conversion as it runs: "Step 2 of 4" and its step, how far it is (pages, texts, images or maps done out of all;
 * an indeterminate bar while there is no count), the time since it started, what it cost so far, and Cancel. It
 * follows the `conversion` events on the app's one event stream; when one says the conversion ended, it fetches the
 * conversion again for its module, its warnings or its reason. A finished one links to its module, which opens with
 * the conversion's warnings.
 *
 * A paused thorough conversion says why (Delve stopped, the usage limit and when it resets, an error, the organiser)
 * and offers Resume, which puts it back in the queue. Cancelling a thorough one asks first: its work so far is deleted
 * (thorough conversion Task 8). A queued one says it waits its turn, and runs as soon as an event says it started.
 */
export default function ConversionProgress({ conversion }: { conversion: Conversion }) {
  const t = useT();
  const language = useLanguage();
  const client = useQueryClient();
  const subscribe = useContext(EventsContext);
  const [heard, setHeard] = useState<ConversionEvent | null>(null);
  const id = conversion.id;

  useEffect(
    () =>
      subscribe({
        conversion: (data) => {
          const event = data as ConversionEvent | null;
          if (event?.id !== id) return;
          setHeard(event);
          if (event.status !== "running" || conversion.status !== "running") {
            client.invalidateQueries({ queryKey: queryKeys.conversions });
            client.invalidateQueries({ queryKey: queryKeys.modules });
          }
        },
      }),
    [subscribe, client, id, conversion.status],
  );

  // An event that says it changed to a status other than running: fetch the whole conversion, for its end or pause.
  const ended = heard !== null && heard.status !== "running" && heard.status !== conversion.status;
  const fresh = useQuery({ queryKey: queryKeys.conversion(id), queryFn: () => getConversion(id), enabled: ended });
  const confirm = useConfirm();
  const cancel = useMutation({
    mutationFn: () => cancelConversion(id),
    onSuccess: (cancelled) => {
      client.setQueryData(queryKeys.conversion(id), cancelled);
      client.invalidateQueries({ queryKey: queryKeys.conversions });
    },
  });
  const resume = useMutation({
    mutationFn: () => resumeConversion(id),
    onSuccess: (resumed) => {
      setHeard(null);
      client.setQueryData(queryKeys.conversion(id), resumed);
      client.invalidateQueries({ queryKey: queryKeys.conversions });
    },
  });

  // The whole conversion once it has ended, paused or is queued, else the last event heard of it. Between the event
  // that says it ended and the whole conversion, it shows its last step without Cancel. A resumed or queued one runs
  // once an event (or the resume's answer) says so, until the list it came from has heard so too.
  let whole: Conversion | null;
  if (cancel.data) whole = cancel.data;
  else if (heard) {
    whole =
      heard.status === "running"
        ? null
        : fresh.data?.status === heard.status
          ? fresh.data
          : heard.status === conversion.status
            ? conversion
            : null;
  } else if (resume.data) whole = resume.data.status === "running" ? null : resume.data;
  else whole = conversion.status === "running" ? null : conversion;
  const shown: Conversion = whole ?? { ...(resume.data ?? conversion), ...(heard ?? {}) };
  const running = !whole;
  const paused = whole?.status === "paused" ? whole : null;
  const step = t(`conversion.step.${shown.step}`);
  const counted = countLine(t, shown);
  const count = shown.warnings.length;
  const cost = typeof shown.cost_usd === "number" ? shown.cost_usd.toFixed(2) : null;

  async function stop() {
    if (shown.thorough) {
      const sure = await confirm({
        title: t("conversion.cancelThorough"),
        body: t("conversion.cancelThoroughBody"),
        confirm: t("conversion.cancelThoroughConfirm"),
        danger: true,
      });
      if (!sure) return;
    }
    cancel.mutate();
  }

  return (
    <div className="notice conversion" data-testid="conversion-progress" data-status={shown.status}>
      <p className="conversion-title">
        <strong>{shown.title}</strong>{" "}
        {makesModule(shown) && <span className="tag">{t(`newModule.makes.${shown.mode}`)}</span>}
      </p>
      {running && (
        <>
          <p className="conversion-step">{stepLine(t, shown)}</p>
          {shown.total > 0 ? (
            <progress aria-label={step} value={shown.done} max={shown.total} />
          ) : (
            <progress aria-label={step} />
          )}
          <p className="row-meta">
            {counted && <span>{counted}</span>} <Elapsed since={shown.created_at} />
            {cost !== null && (
              <>
                {" · "}
                <span className="conversion-cost">{t("conversion.costSoFar", { amount: cost })}</span>
              </>
            )}
          </p>
          {shown.status === "running" && (
            <div className="actions">
              <button type="button" disabled={cancel.isPending} onClick={stop}>
                {t("conversion.cancel")}
              </button>
            </div>
          )}
        </>
      )}
      {paused && (
        <>
          <p className="conversion-step">{t("conversion.pausedAt", { step: stepLine(t, paused) })}</p>
          <p role="status">{pauseLine(t, paused, language)}</p>
          {(countLine(t, paused) || cost !== null) && (
            <p className="row-meta">
              {countLine(t, paused) && <span>{countLine(t, paused)}</span>}
              {countLine(t, paused) && cost !== null && " · "}
              {cost !== null && <span className="conversion-cost">{t("conversion.costSoFar", { amount: cost })}</span>}
            </p>
          )}
          <div className="actions">
            <button type="button" className="primary" disabled={resume.isPending} onClick={() => resume.mutate()}>
              {t("conversion.resume")}
            </button>
            <button type="button" disabled={cancel.isPending} onClick={stop}>
              {t("conversion.cancel")}
            </button>
          </div>
          {resume.error && !(resume.error instanceof NeedsToken) && (
            <p role="alert" className="notice error">
              {t("conversion.resumeFailed", { error: resume.error.message })}
            </p>
          )}
        </>
      )}
      {cancel.error && !(cancel.error instanceof NeedsToken) && (
        <p role="alert" className="notice error">
          {t("conversion.cancelFailed", { error: cancel.error.message })}
        </p>
      )}
      {whole?.status === "done" && (
        <>
          <p>
            {count === 0
              ? t("conversion.done")
              : count === 1
                ? t("conversion.doneWarnings.one")
                : t("conversion.doneWarnings", { count: String(count) })}
          </p>
          {shown.module_id && (
            <Link
              className="button-like primary"
              to={`/modules/${encodeURIComponent(shown.module_id)}`}
              state={{ warnings: shown.warnings, from: "conversion" }}
              onClick={() => markSeen(shown.id)}
            >
              {t("conversion.open")}
            </Link>
          )}
        </>
      )}
      {whole?.status === "queued" && (
        <>
          <p role="status">{t("conversion.queued")}</p>
          <div className="actions">
            <button type="button" disabled={cancel.isPending} onClick={stop}>
              {t("conversion.cancel")}
            </button>
          </div>
        </>
      )}
      {whole?.status === "cancelled" && <p>{t("conversion.cancelled")}</p>}
      {whole?.status === "failed" && (
        <p role="alert" className="notice error">
          {t("conversion.failed", { error: shown.error ?? "" })}
        </p>
      )}
    </div>
  );
}

/** The time since `since`, as 3:27 or 1:03:27, counted up every second. */
function Elapsed({ since }: { since: string }) {
  const t = useT();
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const timer = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(timer);
  }, []);
  const started = Date.parse(since);
  if (Number.isNaN(started)) return null;
  const seconds = Math.max(0, Math.floor((now - started) / 1000));
  const [h, m, s] = [Math.floor(seconds / 3600), Math.floor(seconds / 60) % 60, seconds % 60];
  const two = (n: number) => String(n).padStart(2, "0");
  const time = h > 0 ? `${h}:${two(m)}:${two(s)}` : `${m}:${two(s)}`;
  return <span className="conversion-elapsed">{t("conversion.elapsed", { time })}</span>;
}
