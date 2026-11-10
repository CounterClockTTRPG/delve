import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useContext, useEffect } from "react";
import { EventsContext, NeedsToken, getHistory, queryKeys } from "../api";
import { useT } from "../i18n";
import { renderMarkdown } from "./markdown";

/** Whether the campaign has a history, for the play screen's History tab: the same query as the panel's. A `history`
 * event (its job started, stored a text, ended, or the host edited it) reads it again, for the tab and the panel alike:
 * the panel no longer asks every five seconds while it is written (DEL-172). */
export function useHasHistory(campaignId: string): boolean {
  const client = useQueryClient();
  const subscribe = useContext(EventsContext);
  const history = useQuery({ queryKey: queryKeys.history(campaignId), queryFn: () => getHistory(campaignId) });
  useEffect(
    () =>
      subscribe({
        history: (data) => {
          if ((data as { campaign_id?: unknown } | null)?.campaign_id === campaignId)
            client.invalidateQueries({ queryKey: queryKeys.history(campaignId) });
        },
      }),
    [subscribe, client, campaignId],
  );
  return history.data != null;
}

/**
 * The play screen's History tab (carry-the-party-on plan Task 7): the party's history as the table knows it, the
 * table's text alone, which holds only what the whole table was told. Read-only, whoever's seat it is; the host edits
 * it on the campaign page.
 */
export default function HistoryPanel({ campaignId }: { campaignId: string }) {
  const t = useT();
  // Read again on a `history` event (`useHasHistory`, which the play screen holds).
  const history = useQuery({ queryKey: queryKeys.history(campaignId), queryFn: () => getHistory(campaignId) });
  const none = history.data === null;
  const failed = history.error && !(history.error instanceof NeedsToken) ? history.error : null;
  const data = history.data;
  return (
    <section className="history-panel" aria-label={t("play.history")} data-testid="history-panel">
      {failed && (
        <p role="alert" className="notice error">
          {t("history.loadFailed", { error: failed.message })}
        </p>
      )}
      {none && <p className="placeholder">{t("history.none")}</p>}
      {data?.status === "writing" && <p className="placeholder">{t("play.history.writing")}</p>}
      {data && data.status !== "writing" &&
        (data.table_md.trim() ? (
          <div className="history-text" dangerouslySetInnerHTML={{ __html: renderMarkdown(data.table_md) }} />
        ) : (
          <p className="placeholder">{t("play.history.none")}</p>
        ))}
    </section>
  );
}
