import * as Dialog from "@radix-ui/react-dialog";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { ApiError, NeedsToken, queryKeys } from "../api";
import { useConfirm } from "../components/dialogs";
import { useWide } from "../desktop/useMedia";
import { SvgPreview } from "../editor/SvgPreview";
import { useT } from "../i18n";
import styles from "./FixItReview.module.css";
import {
  STALE,
  fixitReviewKey,
  fixitsKey,
  getFixitReview,
  keepFixit,
  lineDiff,
  rejectFixit,
  rerunFixit,
  type FixitEntity,
  type FixitMapChange,
  type FixitTextChange,
} from "./fixits";

/**
 * What a fix-it job would change (table voice and fixes Task F2.3), before anything is saved: each text it changes as
 * a diff, line by line; each map before and after, drawn side by side (stacked on a narrow screen, the dialog full
 * screen on a phone); the entities added, changed and removed. Keep writes it as a new revision of the module, Reject
 * drops it. On a module changed since the job read it, Keep is refused: the dialog says so and offers to run the
 * comment again on the module as it is now.
 */
export default function FixItReview({
  moduleId,
  conversionId,
  onClose,
}: {
  moduleId: string;
  conversionId: string;
  onClose: () => void;
}) {
  const t = useT();
  const confirm = useConfirm();
  const client = useQueryClient();
  const wide = useWide();
  const review = useQuery({ queryKey: fixitReviewKey(moduleId, conversionId), queryFn: () => getFixitReview(conversionId) });
  const [kept, setKept] = useState<number | null>(null);
  const done = () => {
    client.invalidateQueries({ queryKey: fixitsKey(moduleId), exact: true });
    client.invalidateQueries({ queryKey: queryKeys.module(moduleId) });
    client.invalidateQueries({ queryKey: queryKeys.modules });
  };
  const keep = useMutation({
    mutationFn: () => keepFixit(conversionId),
    onSuccess: ({ revision }) => {
      setKept(revision);
      done();
    },
  });
  const reject = useMutation({ mutationFn: () => rejectFixit(conversionId), onSuccess: () => (done(), onClose()) });
  const rerun = useMutation({
    mutationFn: () => rerunFixit(review.data?.comments[0] ?? ""),
    onSuccess: () => (done(), onClose()),
  });
  const refused = keep.error instanceof ApiError && keep.error.status === 409 && (keep.error.body as { code?: string })?.code === STALE;
  const stale = refused || (review.data?.stale ?? false);
  const failed = [review.error, refused ? null : keep.error, reject.error, rerun.error].find((e) => e && !(e instanceof NeedsToken));
  const busy = keep.isPending || reject.isPending || rerun.isPending;
  const data = review.data;
  const nothing = data && data.texts.length + data.maps.length + countEntities(data.entities) === 0;

  return (
    <Dialog.Root open onOpenChange={(open) => !open && onClose()}>
      <Dialog.Portal>
        <Dialog.Overlay className="dialog-overlay" />
        <Dialog.Content className={`dialog ${styles.review}`} aria-describedby={undefined} data-testid="fixit-review">
          <Dialog.Title className="dialog-title">{t("fixit.reviewTitle")}</Dialog.Title>
          {!data && !review.error && <p className="placeholder">{t("fixit.loading")}</p>}
          {data?.summary && <p className={styles.summary}>{data.summary}</p>}
          {nothing && <p className="placeholder">{t("fixit.nothing")}</p>}
          {stale && kept === null && (
            <div className="notice" role="alert" data-testid="fixit-stale">
              <p>{t("fixit.stale")}</p>
              <button type="button" className="primary" disabled={busy || !data?.comments.length} onClick={() => rerun.mutate()}>
                {t("fixit.rerun")}
              </button>
            </div>
          )}
          <div className={styles.changes}>
            {data?.texts.map((text) => (
              <TextDiff key={text.id} change={text} />
            ))}
            {data?.maps.map((map) => (
              <MapChange key={map.name} change={map} layout={wide ? "side" : "stacked"} />
            ))}
            {data && countEntities(data.entities) > 0 && (
              <section className={styles.entities} aria-label={t("fixit.entities")}>
                <h3>{t("fixit.entities")}</h3>
                <EntityList label={t("fixit.entities.added")} entities={data.entities.added} />
                <EntityList label={t("fixit.entities.changed")} entities={data.entities.changed} />
                <EntityList label={t("fixit.entities.removed")} entities={data.entities.removed} />
              </section>
            )}
          </div>
          {kept !== null && (
            <p role="status" className="notice">
              {t("fixit.keptAs", { revision: String(kept) })}
            </p>
          )}
          {failed && (
            <p role="alert" className="notice error">
              {t("fixit.failed", { error: failed.message })}
            </p>
          )}
          <div className="dialog-actions">
            {kept === null && data && (
              <>
                <button
                  type="button"
                  disabled={busy}
                  onClick={async () =>
                    (await confirm({ title: t("fixit.rejectConfirm"), confirm: t("fixit.reject"), danger: true })) && reject.mutate()
                  }
                >
                  {t("fixit.reject")}
                </button>
                <button type="button" className="primary" disabled={busy || stale} onClick={() => keep.mutate()}>
                  {t("fixit.keep")}
                </button>
              </>
            )}
            <Dialog.Close asChild>
              <button type="button">{t("fixit.closeReview")}</button>
            </Dialog.Close>
          </div>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}

function countEntities(entities: { added: FixitEntity[]; changed: FixitEntity[]; removed: FixitEntity[] }): number {
  return entities.added.length + entities.changed.length + entities.removed.length;
}

function TextDiff({ change }: { change: FixitTextChange }) {
  const t = useT();
  const heading =
    change.before === null ? t("fixit.textAdded", { title: change.title }) : change.after === null ? t("fixit.textRemoved", { title: change.title }) : change.title;
  return (
    <section className={styles.text} aria-label={heading} data-testid="fixit-text">
      <h3>{heading}</h3>
      <pre className={styles.diff}>
        {lineDiff(change.before, change.after).map((line, n) => (
          <span key={n} className={styles[line.kind]} data-diff={line.kind}>
            {`${line.kind === "added" ? "+" : line.kind === "removed" ? "−" : " "} ${line.text}\n`}
          </span>
        ))}
      </pre>
    </section>
  );
}

function MapChange({ change, layout }: { change: FixitMapChange; layout: "side" | "stacked" }) {
  const t = useT();
  const pane = (which: "before" | "after", svg: string | null, source: string | null) => (
    <figure className={styles.pane} data-testid={`fixit-map-${which}`}>
      <figcaption>{t(`fixit.${which}`)}</figcaption>
      {source === null ? (
        <p className="placeholder">{t(which === "before" ? "fixit.mapNew" : "fixit.mapRemoved")}</p>
      ) : svg !== null ? (
        <div className={styles.canvas}>
          <SvgPreview svg={svg} />
        </div>
      ) : (
        <pre className={styles.source}>{source}</pre>
      )}
    </figure>
  );
  return (
    <section className={styles.map} aria-label={t("fixit.mapTitle", { name: change.name })}>
      <h3>{t("fixit.mapTitle", { name: change.name })}</h3>
      <div className={styles.panes} data-layout={layout}>
        {pane("before", change.before_svg, change.before)}
        {pane("after", change.after_svg, change.after)}
      </div>
    </section>
  );
}

function EntityList({ label, entities }: { label: string; entities: FixitEntity[] }) {
  if (entities.length === 0) return null;
  return (
    <>
      <h4>{label}</h4>
      <ul>
        {entities.map((entity) => (
          <li key={`${entity.kind}/${entity.id}`}>
            <strong>{entity.name}</strong> <span className="row-meta">{entity.kind}</span>
          </li>
        ))}
      </ul>
    </>
  );
}
