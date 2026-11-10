import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Fragment, useContext, useEffect, useRef, useState } from "react";
import { Link, useLocation } from "react-router-dom";
import { toast } from "sonner";
import {
  EventsContext,
  HISTORY_MAX_CHARS,
  NeedsToken,
  getHistory,
  putHistory,
  queryKeys,
  writeHistoryAgain,
  type CampaignDetail,
  type CampaignLink,
  type Conversion,
  type ConversionEvent,
  type HistoryView,
} from "../api";
import { useConfirm } from "../components/dialogs";
import { useT } from "../i18n";
import { countLine, useConversions } from "../module/conversions";
import { renderMarkdown } from "../play/markdown";

type Version = "dm" | "table";
const VERSIONS: Version[] = ["dm", "table"];

/**
 * The campaign page's History (carry-the-party-on plan Task 7), `id="history"`: where the party was carried on from
 * and to, as links, and the history its job wrote from the old campaign. The host reads the DM's version or the
 * table's (a toggle), edits both, and writes it again, asked first when that would replace an edit. While it is
 * written it shows the job's progress; a failed one its reason and Write again. Nothing when the campaign has neither
 * links nor a history.
 */
export default function HistorySection({ campaign }: { campaign: CampaignDetail }) {
  const t = useT();
  const { id } = campaign;
  const from = campaign.carried_from ?? null;
  const onward = campaign.carried_to ?? [];
  const history = useQuery({ queryKey: queryKeys.history(id), queryFn: () => getHistory(id) });
  const loadError = history.error && !(history.error instanceof NeedsToken) ? history.error : null;
  const heading = useRef<HTMLHeadingElement>(null);
  const { hash } = useLocation();
  const shown = from !== null || onward.length > 0 || history.data != null;

  // A job's end notice links to `#history`: the page scrolls to it once it is there.
  useEffect(() => {
    if (shown && hash === "#history") heading.current?.scrollIntoView?.({ block: "start" });
  }, [shown, hash]);

  if (!shown) return null;
  return (
    <section className="history-section" data-testid="history-section" aria-labelledby="history">
      <h2 id="history" ref={heading}>
        {t("history.title")}
      </h2>
      {from && (
        <p className="lede">
          {t("history.carriedFrom")} <CampaignLinks links={[from]} />
        </p>
      )}
      {onward.length > 0 && (
        <p className="lede">
          {t("history.carriedTo")} <CampaignLinks links={onward} />
        </p>
      )}
      {loadError && (
        <p role="alert" className="notice error">
          {t("history.loadFailed", { error: loadError.message })}
        </p>
      )}
      {history.data && <HistoryBody campaignId={id} history={history.data} canWrite={from !== null} />}
    </section>
  );
}

function CampaignLinks({ links }: { links: CampaignLink[] }) {
  return (
    <>
      {links.map((link, i) => (
        <Fragment key={link.id}>
          {i > 0 && ", "}
          <Link to={`/campaigns/${encodeURIComponent(link.id)}`}>{link.name}</Link>
        </Fragment>
      ))}
    </>
  );
}

function HistoryBody({ campaignId, history, canWrite }: { campaignId: string; history: HistoryView; canWrite: boolean }) {
  const t = useT();
  const confirm = useConfirm();
  const client = useQueryClient();
  const subscribe = useContext(EventsContext);
  const conversions = useConversions();
  const [version, setVersion] = useState<Version>("dm");
  const [editing, setEditing] = useState<{ dm_md: string; table_md: string } | null>(null);
  // Only the host gets the DM's text; any other seat, a co-host too, reads the table's alone.
  const host = history.dm_md !== undefined;
  const writing = history.status === "writing";
  const job = conversions.find((c) => c.id === history.conversion_id && c.status === "running") ?? null;

  // Its job's events move the progress, and its end brings the texts.
  const jobId = history.conversion_id;
  useEffect(
    () =>
      subscribe({
        conversion: (data) => {
          const event = data as ConversionEvent | null;
          if (event?.id && event.id === jobId) client.invalidateQueries({ queryKey: queryKeys.history(campaignId) });
        },
      }),
    [subscribe, client, campaignId, jobId],
  );

  const stored = (next: HistoryView) => client.setQueryData(queryKeys.history(campaignId), next);
  const save = useMutation({
    mutationFn: (texts: { dm_md: string; table_md: string }) => putHistory(campaignId, texts),
    onSuccess: (next) => {
      stored(next);
      setEditing(null);
      toast(t("history.saved"));
    },
  });
  const again = useMutation({
    mutationFn: (overwrite: boolean) => writeHistoryAgain(campaignId, overwrite),
    onSuccess: (next) => {
      stored(next);
      client.invalidateQueries({ queryKey: queryKeys.conversions });
    },
  });
  const writeAgain = async () => {
    if (
      history.edited &&
      !(await confirm({ title: t("history.overwriteTitle"), body: t("history.overwriteBody"), confirm: t("history.writeAgain") }))
    )
      return;
    again.mutate(!!history.edited);
  };

  const failed = [save.error, again.error].find((e) => e && !(e instanceof NeedsToken));
  const text = host && version === "dm" ? history.dm_md! : history.table_md;
  return (
    <div className="history" data-status={history.status}>
      <p className="lede">{t("history.intro")}</p>
      <p className="history-status">
        <span className="tag">{t(`history.status.${history.status}`)}</span>
        {history.edited && <span className="tag">{t("history.edited")}</span>}
        {writing && <WritingProgress job={job} />}
      </p>
      {history.status === "failed" && (
        <p role="alert" className="notice error">
          {t("history.failed", { error: history.error ?? "" })}
        </p>
      )}
      {failed && (
        <p role="alert" className="notice error">
          {t("history.changeFailed", { error: failed.message })}
        </p>
      )}

      {editing ? (
        <form
          className="history-edit"
          onSubmit={(e) => {
            e.preventDefault();
            save.mutate(editing);
          }}
        >
          <HistoryText
            id="history-dm"
            label={t("history.dmText")}
            value={editing.dm_md}
            onChange={(dm_md) => setEditing({ ...editing, dm_md })}
          />
          <HistoryText
            id="history-table"
            label={t("history.tableText")}
            value={editing.table_md}
            onChange={(table_md) => setEditing({ ...editing, table_md })}
          />
          <div className="actions">
            <button type="submit" className="primary" disabled={save.isPending}>
              {t("history.save")}
            </button>
            <button type="button" onClick={() => setEditing(null)}>
              {t("dialog.cancel")}
            </button>
          </div>
        </form>
      ) : (
        !writing && (
          <>
            {host && (
              <div className="side-tabs" role="tablist" aria-label={t("history.versions")}>
                {VERSIONS.map((v) => (
                  <button
                    key={v}
                    type="button"
                    role="tab"
                    id={`history-tab-${v}`}
                    aria-selected={version === v}
                    aria-controls="history-text"
                    onClick={() => setVersion(v)}
                  >
                    {t(`history.${v}`)}
                  </button>
                ))}
              </div>
            )}
            <div id="history-text" role={host ? "tabpanel" : undefined} aria-labelledby={host ? `history-tab-${version}` : undefined}>
              {text.trim() ? (
                <div className="history-text" dangerouslySetInnerHTML={{ __html: renderMarkdown(text) }} />
              ) : (
                <p className="placeholder">{t("history.empty")}</p>
              )}
            </div>
          </>
        )
      )}

      {host && !editing && (
        <div className="actions">
          {!writing && (
            <button type="button" onClick={() => setEditing({ dm_md: history.dm_md ?? "", table_md: history.table_md })}>
              {t("history.edit")}
            </button>
          )}
          {canWrite && !writing && (
            <button type="button" disabled={again.isPending} onClick={() => void writeAgain()}>
              {t("history.writeAgain")}
            </button>
          )}
        </div>
      )}
    </div>
  );
}

function HistoryText({ id, label, value, onChange }: { id: string; label: string; value: string; onChange: (value: string) => void }) {
  const t = useT();
  return (
    <div className="field">
      <label htmlFor={id}>{label}</label>
      <textarea id={id} rows={12} maxLength={HISTORY_MAX_CHARS} value={value} onChange={(e) => onChange(e.target.value)} />
      <span className="hint">{t("history.length", { count: String(value.length), max: String(HISTORY_MAX_CHARS) })}</span>
    </div>
  );
}

/** The history's job: its texts done out of two while it writes them, an indeterminate bar before. */
function WritingProgress({ job }: { job: Conversion | null }) {
  const t = useT();
  const count = job ? countLine(t, job) : null;
  return (
    <span className="history-progress">
      {job && job.step === "writing" && job.total > 0 ? (
        <progress aria-label={t("history.status.writing")} value={job.done} max={job.total} />
      ) : (
        <progress aria-label={t("history.status.writing")} />
      )}
      {count && <span className="row-meta">{count}</span>}
    </span>
  );
}
