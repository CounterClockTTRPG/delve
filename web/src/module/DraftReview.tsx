import * as Dialog from "@radix-ui/react-dialog";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { Link } from "react-router-dom";
import { ApiError, NeedsToken, attachmentUrl, dsl, getModuleSource, queryKeys } from "../api";
import { useConfirm } from "../components/dialogs";
import { SvgPreview } from "../editor/SvgPreview";
import { useT } from "../i18n";
import styles from "./DraftReview.module.css";
import { discardMapDraft, keepMapDraft, mapDraftsKey, type DraftMismatch, type MapDraft } from "./mapDrafts";

/**
 * A draft reviewed over the book's page (faithful modules B3): the page and the level being looked at side by side,
 * each large enough to judge (stacked on a narrow screen, the dialog full screen on a phone), a tab per level with its
 * part's title, the draft's warnings with the map's own first ("not connected"), and Keep (with "Keep anyway" for a
 * draft whose rooms don't match its part) and Discard. Once kept, it links to the first level in the map editor.
 */
export default function DraftReview({ moduleId, draft, onClose }: { moduleId: string; draft: MapDraft; onClose: () => void }) {
  const t = useT();
  const confirm = useConfirm();
  const [shown, setShown] = useState(0);
  const [kept, setKept] = useState<string | null>(null);
  const levels = draft.maps.length > 0 ? draft.maps : [];
  const level = levels[shown] ?? levels[0];
  const source = useQuery({ queryKey: queryKeys.moduleSource(moduleId), queryFn: () => getModuleSource(moduleId) });
  const titles = new Map((source.data?.texts ?? []).map((text) => [text.id, text.title]));
  const rendered = useQuery({
    queryKey: [...mapDraftsKey(moduleId), draft.id, "svg", level?.name ?? ""],
    queryFn: () => dsl.render(level?.source ?? "", moduleId),
    enabled: level !== undefined,
    staleTime: Infinity,
  });
  const { keep, discard } = useDraftActions(moduleId, draft);
  const busy = keep.isPending || discard.isPending;
  const failed = keep.error ?? discard.error;
  const warnings = [
    ...draft.warnings.filter((w) => w.code === "map-warning"),
    ...draft.warnings.filter((w) => w.code !== "map-warning"),
  ];

  return (
    <Dialog.Root open onOpenChange={(open) => !open && onClose()}>
      <Dialog.Portal>
        <Dialog.Overlay className="dialog-overlay" />
        <Dialog.Content className={`dialog ${styles.review}`} aria-describedby={undefined}>
          <Dialog.Title className="dialog-title">{t("draftReview.title", { name: draft.name })}</Dialog.Title>
          {levels.length > 1 && (
            <div className={styles.levels} role="tablist" aria-label={t("mapDrafts.levels")}>
              {levels.map((lv, n) => {
                const part = lv.part ? titles.get(lv.part) : undefined;
                return (
                  <button key={lv.name} type="button" role="tab" aria-selected={n === shown} onClick={() => setShown(n)}>
                    {part ? `${lv.title} · ${part}` : lv.title}
                  </button>
                );
              })}
            </div>
          )}
          <div className={styles.panes}>
            {draft.page && (
              <figure className={styles.page}>
                <figcaption>{t("draftReview.pageTitle")}</figcaption>
                <img src={attachmentUrl(moduleId, draft.page)} alt={t("draftReview.page", { page: draft.page })} />
              </figure>
            )}
            <figure className={styles.draft}>
              <figcaption>{t("draftReview.draft")}</figcaption>
              <div className={styles.canvas}>
                <SvgPreview svg={rendered.data?.svg ?? null} loading={rendered.isFetching} error={rendered.error?.message ?? null} />
              </div>
            </figure>
          </div>
          {warnings.length > 0 && (
            <ul className={styles.warnings} aria-label={t("draftReview.warnings")}>
              {warnings.map((warning, n) => (
                <li key={n} className={warning.code === "map-warning" ? styles.mapWarning : undefined}>
                  {warning.message}
                </li>
              ))}
            </ul>
          )}
          {failed && !(failed instanceof NeedsToken) && (
            <p role="alert" className="notice error">
              {t("mapDrafts.actionFailed", { error: failed.message })}
            </p>
          )}
          <div className="dialog-actions">
            {kept ? (
              <Link className="button-like primary" to={`/maps/${encodeURIComponent(moduleId)}/${encodeURIComponent(kept)}`}>
                {t("draftReview.open")}
              </Link>
            ) : (
              <>
                <button
                  type="button"
                  disabled={busy}
                  onClick={async () => {
                    if (await confirm({ title: t("mapDrafts.discardConfirm", { name: draft.name }), confirm: t("mapDrafts.discard"), danger: true })) {
                      discard.mutate(undefined, { onSuccess: onClose });
                    }
                  }}
                >
                  {t("mapDrafts.discard")}
                </button>
                <button
                  type="button"
                  className="primary"
                  disabled={busy || levels.length === 0}
                  onClick={() => keep.mutate(undefined, { onSuccess: (map) => map && setKept(map.name) })}
                >
                  {t("mapDrafts.keep")}
                </button>
              </>
            )}
            <Dialog.Close asChild>
              <button type="button">{t("mapDrafts.close")}</button>
            </Dialog.Close>
          </div>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}

/** Keep and Discard of a draft: Keep asks "Keep anyway" for a draft whose rooms don't match its part, and keeps it
 * with `force` if so; either refreshes the module and its drafts. Keep answers the first map kept, else null. */
export function useDraftActions(moduleId: string, draft: MapDraft) {
  const t = useT();
  const client = useQueryClient();
  const confirm = useConfirm();
  const done = () => {
    client.invalidateQueries({ queryKey: mapDraftsKey(moduleId) });
    client.invalidateQueries({ queryKey: queryKeys.module(moduleId) });
  };
  const keep = useMutation({
    mutationFn: async (name?: string) => {
      try {
        return await keepMapDraft(moduleId, draft.id, name, false);
      } catch (error) {
        const mismatch = error instanceof ApiError && error.status === 409 ? (error.body as Partial<DraftMismatch>) : null;
        if (!mismatch?.problems) throw error;
        const anyway = await confirm({
          title: t("mapDrafts.mismatch", { error: error instanceof Error ? error.message : "" }),
          body: mismatch.problems.join(" "),
          confirm: t("mapDrafts.keepAnyway"),
          danger: true,
        });
        return anyway ? keepMapDraft(moduleId, draft.id, name, true) : null;
      }
    },
    onSuccess: (kept) => kept && done(),
  });
  const discard = useMutation({ mutationFn: () => discardMapDraft(moduleId, draft.id), onSuccess: done });
  return { keep, discard };
}

