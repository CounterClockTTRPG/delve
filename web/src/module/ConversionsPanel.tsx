import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useContext, useEffect } from "react";
import { Link } from "react-router-dom";
import {
  EventsContext,
  NeedsToken,
  cancelConversion,
  getConversionQueue,
  pauseConversion,
  queryKeys,
  resumeConversion,
  setConversionQueuePaused,
  type Conversion,
  type ConversionEvent,
  type ConversionQueue,
} from "../api";
import { useConfirm } from "../components/dialogs";
import { useLanguage, useT } from "../i18n";
import { countLine, pauseLine, stepLine } from "./conversions";

/**
 * The conversion queue (thorough conversion, owner addition 2026-10-23): the jobs that aren't over, in the order they
 * get the slot (`GET /api/conversions/queue`): the running one with its step, the queued ones with their place, the
 * paused ones with why, each with what it cost so far. A running thorough conversion can be paused, a paused one
 * resumed (it goes back in the queue), and any of them cancelled, after a confirm. The queue's switch pauses it, so
 * that no waiting conversion starts (to run them at night, when nobody plays), and unpauses it.
 *
 * It follows the `conversion` events: a step moves its job in place; any other change, and a `conversion-queue`
 * event, fetches the queue again.
 */
export default function ConversionsPanel() {
  const t = useT();
  const client = useQueryClient();
  const subscribe = useContext(EventsContext);
  const queue = useQuery({ queryKey: queryKeys.conversionQueue, queryFn: getConversionQueue });

  useEffect(
    () =>
      subscribe({
        conversion: (data) => {
          const event = data as ConversionEvent | null;
          if (!event?.id) return;
          const known = client.getQueryData<ConversionQueue>(queryKeys.conversionQueue);
          const job = known?.jobs.find((c) => c.id === event.id);
          if (job && job.status === event.status) {
            client.setQueryData<ConversionQueue>(queryKeys.conversionQueue, (old) =>
              old ? { ...old, jobs: old.jobs.map((c) => (c.id === event.id ? { ...c, ...event } : c)) } : old,
            );
            return;
          }
          client.invalidateQueries({ queryKey: queryKeys.conversionQueue });
        },
        "conversion-queue": () => client.invalidateQueries({ queryKey: queryKeys.conversionQueue }),
      }),
    [subscribe, client],
  );

  const changed = (fresh?: ConversionQueue) => {
    if (fresh) client.setQueryData(queryKeys.conversionQueue, fresh);
    else client.invalidateQueries({ queryKey: queryKeys.conversionQueue });
    client.invalidateQueries({ queryKey: queryKeys.conversions });
  };
  const toggle = useMutation({ mutationFn: setConversionQueuePaused, onSuccess: changed });

  const paused = queue.data?.paused ?? false;
  const jobs = queue.data?.jobs ?? [];
  const failure = (error: Error | null, key: string) =>
    error && !(error instanceof NeedsToken) ? (
      <p role="alert" className="notice error">
        {t(key, { error: error.message })}
      </p>
    ) : null;

  return (
    <section className="conversions-panel" aria-labelledby="conversions-title" data-testid="conversions-panel">
      <h2 id="conversions-title">{t("conversions.title")}</h2>
      <p className="hint">{t("conversions.hint")}</p>
      <div className="actions queue-switch" data-paused={paused}>
        <p role="status">{paused ? t("conversions.queuePaused") : t("conversions.queueRuns")}</p>
        <button type="button" disabled={!queue.data || toggle.isPending} onClick={() => toggle.mutate(!paused)}>
          {paused ? t("conversions.unpauseQueue") : t("conversions.pauseQueue")}
        </button>
      </div>
      {failure(toggle.error, "conversions.queueFailed")}
      {queue.data && jobs.length === 0 && <p className="hint">{t("conversions.empty")}</p>}
      {jobs.length > 0 && (
        <ol className="conversion-queue" aria-label={t("conversions.list")}>
          {jobs.map((job) => (
            <QueuedJob
              key={job.id}
              job={job}
              position={job.status === "queued" ? jobs.filter((c) => c.status === "queued").indexOf(job) + 1 : 0}
              changed={() => changed()}
            />
          ))}
        </ol>
      )}
    </section>
  );
}

/** One job of the queue: its title and how it converts, its status and where it is, its cost, and its actions. */
function QueuedJob({ job, position, changed }: { job: Conversion; position: number; changed: () => void }) {
  const t = useT();
  const language = useLanguage();
  const confirm = useConfirm();
  const pause = useMutation({ mutationFn: () => pauseConversion(job.id), onSuccess: changed });
  const resume = useMutation({ mutationFn: () => resumeConversion(job.id), onSuccess: changed });
  const cancel = useMutation({ mutationFn: () => cancelConversion(job.id), onSuccess: changed });
  const counted = countLine(t, job);
  const cost = typeof job.cost_usd === "number" ? job.cost_usd.toFixed(2) : null;
  const busy = pause.isPending || resume.isPending || cancel.isPending;

  async function stop() {
    const sure = await confirm(
      job.thorough
        ? {
            title: t("conversion.cancelThorough"),
            body: t("conversion.cancelThoroughBody"),
            confirm: t("conversion.cancelThoroughConfirm"),
            danger: true,
          }
        : {
            title: t("conversions.cancelTitle"),
            body: t("conversions.cancelBody"),
            confirm: t("conversions.cancelConfirm"),
            danger: true,
          },
    );
    if (sure) cancel.mutate();
  }

  const error = [pause, resume, cancel].map((m) => m.error).find((e) => e && !(e instanceof NeedsToken));
  return (
    <li className="queued-job" data-status={job.status} data-testid={`queued-${job.id}`}>
      <p className="conversion-title">
        <strong>{job.title}</strong>{" "}
        <span className="tag">{t(`conversions.status.${job.status}`)}</span>{" "}
        {job.kind === "pdf" && <span className="tag">{t(job.thorough ? "conversions.thorough" : "conversions.quick")}</span>}
        {job.kind === "fixit" && <span className="tag">{t("fixit.job")}</span>}
        {job.kind === "fixit" && job.target?.module_id && (
          <Link to={`/modules/${encodeURIComponent(job.target.module_id)}`}>{t("fixit.openModule")}</Link>
        )}
      </p>
      <p className="row-meta">
        {job.status === "running" && (
          <>
            <span>{stepLine(t, job)}</span>
            {counted && <span>{` · ${counted}`}</span>}
          </>
        )}
        {job.status === "queued" && <span>{t("conversions.position", { position: String(position) })}</span>}
        {job.status === "paused" && <span>{pauseLine(t, job, language)}</span>}
        {cost !== null && <span className="conversion-cost">{` · ${t("conversion.costSoFar", { amount: cost })}`}</span>}
      </p>
      <div className="actions">
        {job.status === "running" && job.thorough && (
          <button type="button" disabled={busy} onClick={() => pause.mutate()}>
            {t("conversions.pause")}
          </button>
        )}
        {job.status === "paused" && (
          <button type="button" className="primary" disabled={busy} onClick={() => resume.mutate()}>
            {t("conversion.resume")}
          </button>
        )}
        <button type="button" disabled={busy} onClick={stop}>
          {t("conversion.cancel")}
        </button>
      </div>
      {error && (
        <p role="alert" className="notice error">
          {t(error === pause.error ? "conversions.pauseFailed" : error === resume.error ? "conversion.resumeFailed" : "conversion.cancelFailed", {
            error: error.message,
          })}
        </p>
      )}
    </li>
  );
}
