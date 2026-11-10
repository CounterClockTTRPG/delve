import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useContext, useEffect, useState } from "react";
import { EventsContext, NeedsToken, dsl, type ConversionEvent } from "../api";
import { useConfirm } from "../components/dialogs";
import { useT } from "../i18n";
import DraftReview, { useDraftActions } from "./DraftReview";
import { listMapDrafts, mapDraftsKey, type MapDraft } from "./mapDrafts";
import styles from "./MapDrafts.module.css";

/**
 * The module's open drafts of dungeon maps, side by side so they can be compared: each drawn by `POST /api/dsl/render`,
 * with its warnings, Keep and Discard. A draft is kept as a new map, under the name typed, unless it is a book draft
 * drawn for a map, which it replaces. A book draft whose rooms don't match its part is kept only after "Keep anyway".
 * A book draft of several levels has a tab per level, and Keep keeps them all. The list is fetched again when a
 * conversion ends, so a draft shows once drawn. "Review" opens a draft over the book's page (`DraftReview`), which stays
 * open once the draft is kept, for its link to the map editor.
 * Nothing shows while there are no drafts, unless `empty` asks for the line that says so.
 */
export default function MapDrafts({ moduleId, empty = false }: { moduleId: string; empty?: boolean }) {
  const t = useT();
  const client = useQueryClient();
  const subscribe = useContext(EventsContext);
  const drafts = useQuery({ queryKey: mapDraftsKey(moduleId), queryFn: () => listMapDrafts(moduleId) });
  const [reviewing, setReviewing] = useState<MapDraft | null>(null);
  const review = reviewing && <DraftReview moduleId={moduleId} draft={reviewing} onClose={() => setReviewing(null)} />;

  useEffect(
    () =>
      subscribe({
        conversion: (data) => {
          const event = data as ConversionEvent | null;
          if (event && event.status !== "running") client.invalidateQueries({ queryKey: mapDraftsKey(moduleId) });
        },
      }),
    [subscribe, client, moduleId],
  );

  if (drafts.error && !(drafts.error instanceof NeedsToken)) {
    return (
      <p role="alert" className="notice error">
        {t("mapDrafts.failed", { error: drafts.error.message })}
      </p>
    );
  }
  const list = drafts.data ?? [];
  if (list.length === 0) {
    return (
      <>
        {empty && <p className="placeholder">{t("mapDrafts.none")}</p>}
        {review}
      </>
    );
  }
  return (
    <section className={styles.drafts} aria-label={t("mapDrafts.drafts")}>
      <h3>{t("mapDrafts.drafts")}</h3>
      <ul className={styles.grid}>
        {list.map((draft) => (
          <DraftCard key={draft.id} moduleId={moduleId} draft={draft} onReview={() => setReviewing(draft)} />
        ))}
      </ul>
      {review}
    </section>
  );
}

function DraftCard({ moduleId, draft, onReview }: { moduleId: string; draft: MapDraft; onReview: () => void }) {
  const t = useT();
  const confirm = useConfirm();
  const [name, setName] = useState(draft.name);
  const [shown, setShown] = useState(0);
  const levels = draft.maps ?? [];
  const level = levels[shown] ?? levels[0];
  const source = level?.source ?? draft.source;
  const rendered = useQuery({
    queryKey: [...mapDraftsKey(moduleId), draft.id, "svg", level?.name ?? draft.name],
    queryFn: () => dsl.render(source ?? "", moduleId),
    enabled: source !== null,
    staleTime: Infinity,
  });
  const named = draft.replaces === null;
  const { keep, discard } = useDraftActions(moduleId, draft);
  const busy = keep.isPending || discard.isPending;
  const failed = keep.error ?? discard.error;
  const field = `draft-${draft.id}-name`;

  return (
    <li className={styles.card} data-testid="map-draft">
      <p className={styles.head}>
        <strong>{draft.name}</strong> <span className="tag">{t(`mapDrafts.kind.${draft.kind}`)}</span>
      </p>
      {levels.length > 1 && (
        <div className={styles.levels} role="tablist" aria-label={t("mapDrafts.levels")}>
          {levels.map((lv, n) => (
            <button
              key={lv.name}
              type="button"
              role="tab"
              aria-selected={n === shown}
              title={t("mapDrafts.level", { n: String(n + 1), count: String(levels.length), name: lv.name })}
              onClick={() => setShown(n)}
            >
              {lv.title}
            </button>
          ))}
        </div>
      )}
      {draft.source === null ? (
        <p className="placeholder">{t("mapDrafts.notDrawn")}</p>
      ) : rendered.error ? (
        <p role="alert" className="notice error">
          {t("mapDrafts.renderFailed", { error: rendered.error.message })}
        </p>
      ) : (
        <div
          className={styles.svg}
          role="img"
          aria-label={level?.name ?? draft.name}
          dangerouslySetInnerHTML={{ __html: rendered.data?.svg ?? "" }}
        />
      )}
      {levels.length > 1 && <p className="row-meta">{t("mapDrafts.keepsLevels", { count: String(levels.length) })}</p>}
      {draft.warnings.length > 0 && (
        <ul className={styles.warnings}>
          {draft.warnings.map((warning, n) => (
            <li key={n}>{warning.message}</li>
          ))}
        </ul>
      )}
      <form
        className={styles.actions}
        onSubmit={(e) => {
          e.preventDefault();
          keep.mutate(named ? name.trim() : undefined);
        }}
      >
        {draft.source !== null &&
          (named ? (
            <span className="field">
              <label htmlFor={field}>{t("mapDrafts.keepAs")}</label>
              <input id={field} value={name} onChange={(e) => setName(e.target.value)} />
            </span>
          ) : (
            <span className="row-meta">{t("mapDrafts.replaces", { name: draft.replaces ?? draft.name })}</span>
          ))}
        {draft.source !== null && (
          <button type="submit" className="primary" disabled={busy || (named && !name.trim())}>
            {t("mapDrafts.keep")}
          </button>
        )}
        {draft.source !== null && (
          <button type="button" disabled={busy} onClick={onReview}>
            {t("draftReview.review")}
          </button>
        )}
        <button
          type="button"
          disabled={busy}
          onClick={async () =>
            (await confirm({ title: t("mapDrafts.discardConfirm", { name: draft.name }), confirm: t("mapDrafts.discard"), danger: true })) &&
            discard.mutate()
          }
        >
          {t("mapDrafts.discard")}
        </button>
      </form>
      {failed && !(failed instanceof NeedsToken) && (
        <p role="alert" className="notice error">
          {t("mapDrafts.actionFailed", { error: failed.message })}
        </p>
      )}
    </li>
  );
}
