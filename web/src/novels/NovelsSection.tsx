import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useContext, useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { EventsContext, NeedsToken, getModule, queryKeys, type Conversion, type ConversionEvent } from "../api";
import { useConfirm } from "../components/dialogs";
import { useLanguage, useT, type Translate } from "../i18n";
import { useConversions, runningOf } from "../module/conversions";
import { useMe } from "../account/useMe";
import { getPlaySettings, playKeys } from "../play/api";
import {
  cancelNovel,
  continueNovel,
  deleteNovel,
  listNovels,
  novelKeys,
  type ListedNovel,
  type NovelSource,
} from "./api";
import NovelizeForm, { choicesOf, defaultChoices, type NovelChoices } from "./NovelizeForm";

/** How much of the instructions a row shows. */
const INSTRUCTIONS_SHOWN = 60;

/** Whether this browser is the install's owner: the owner token, this machine or an owner account. False while it
 * isn't known: a seat sees no novel, an organiser seat or an organiser account included (owner decision 7). From the
 * app's one `useMe`. */
export function useOwner(): boolean {
  const me = useMe();
  return me.data !== undefined && (me.data.principal.id === "owner" || Boolean(me.data.account?.owner));
}

/**
 * The Novels of a campaign or a module, the owner's alone: Novelize, then the novels with their length, tone, the
 * start of their instructions, their date and their status. A novel being written shows its job's progress and
 * Cancel; a failed or cancelled one its reason and Continue; each has Write again (its choices in the form) and
 * Delete. A seat sees nothing and asks for nothing.
 */
export default function NovelsSection({ source }: { source: NovelSource }) {
  return useOwner() ? <Novels source={source} /> : null;
}

function Novels({ source }: { source: NovelSource }) {
  const t = useT();
  const language = useLanguage();
  const confirm = useConfirm();
  const client = useQueryClient();
  const subscribe = useContext(EventsContext);
  const campaign = source.kind === "campaign";
  const novels = useQuery({ queryKey: novelKeys.list(source), queryFn: () => listNovels(source) });
  const conversions = useConversions();
  const running = runningOf(conversions);
  // The form's defaults: a campaign's tone, else classic; a module's latest revision, for the older ones.
  const settings = useQuery({
    queryKey: playKeys.settings(source.id),
    queryFn: () => getPlaySettings(source.id),
    enabled: campaign,
  });
  const module = useQuery({ queryKey: queryKeys.module(source.id), queryFn: () => getModule(source.id), enabled: !campaign });
  // Write again: the form opens again with a novel's choices.
  const [again, setAgain] = useState<{ choices: NovelChoices; key: number } | null>(null);
  const form = useRef<HTMLDivElement>(null);

  const listed = novels.data ?? [];
  const jobs = useRef(new Set<string>());
  jobs.current = new Set(listed.flatMap((n) => (n.conversion_id ? [n.conversion_id] : [])));
  // A novel's job that ends changes its status: the list is fetched again. The events carry no text of the novel.
  const { kind, id } = source;
  useEffect(
    () =>
      subscribe({
        conversion: (data) => {
          const event = data as ConversionEvent | null;
          if (event?.id && event.status !== "running" && jobs.current.has(event.id))
            client.invalidateQueries({ queryKey: novelKeys.list({ kind, id }) });
        },
      }),
    [subscribe, client, kind, id],
  );

  const changed = () => {
    client.invalidateQueries({ queryKey: novelKeys.lists });
    client.invalidateQueries({ queryKey: queryKeys.conversions });
  };
  const change = useMutation({ mutationFn: (run: () => Promise<unknown>) => run(), onSuccess: changed });

  const tone = campaign ? (settings.data ?? (settings.isError ? { tone: "classic" } : null)) : { tone: "classic" };
  const failed = [novels.error, change.error].find((e) => e && !(e instanceof NeedsToken));

  return (
    <section className="novels">
      <h2>{t("novels.heading")}</h2>
      <p className="lede">{t(`novels.intro.${source.kind}`)}</p>
      {failed && (
        <p role="alert" className="notice error">
          {t("novels.changeFailed", { error: failed.message })}
        </p>
      )}
      {novels.data && listed.length === 0 && <p className="placeholder">{t("novels.empty")}</p>}
      {!novels.data && !novels.error && <p className="placeholder">{t("novels.loading")}</p>}
      {listed.length > 0 && (
        <ul className="rows novel-rows">
          {listed.map((novel) => (
            <NovelRow
              key={novel.id}
              novel={novel}
              job={conversions.find((c) => c.id === novel.conversion_id && c.status === "running") ?? null}
              busy={change.isPending}
              jobRunning={running !== null}
              onCancel={() => change.mutate(() => cancelNovel(novel.id))}
              onContinue={() => change.mutate(() => continueNovel(novel.id))}
              onDelete={async () =>
                (await confirm({
                  title: t("novels.deleteConfirm", { title: novel.title }),
                  confirm: t("dialog.delete"),
                  danger: true,
                })) && change.mutate(() => deleteNovel(novel.id))
              }
              onWriteAgain={() => {
                setAgain((old) => ({ choices: choicesOf(novel), key: (old?.key ?? 0) + 1 }));
                form.current?.scrollIntoView?.({ behavior: "smooth", block: "start" });
              }}
            />
          ))}
        </ul>
      )}
      <div ref={form}>
        {tone && (
          <NovelizeForm
            key={again?.key ?? 0}
            source={source}
            initial={again?.choices ?? defaultChoices(language, tone)}
            running={running}
            latestRevision={module.data?.head_revision ?? null}
            onStarted={changed}
          />
        )}
      </div>
    </section>
  );
}

function NovelRow({
  novel,
  job,
  busy,
  jobRunning,
  onCancel,
  onContinue,
  onDelete,
  onWriteAgain,
}: {
  novel: ListedNovel;
  /** Its job, while it runs. */
  job: Conversion | null;
  busy: boolean;
  /** Whether any job runs: Continue waits for it. */
  jobRunning: boolean;
  onCancel: () => void;
  onContinue: () => void;
  onDelete: () => void;
  onWriteAgain: () => void;
}) {
  const t = useT();
  const language = useLanguage();
  const writing = novel.status === "writing";
  const unfinished = novel.status === "failed" || novel.status === "cancelled";
  const written = novel.chapters.filter((c) => c.written).length;
  return (
    <li className="row novel-row" data-status={novel.status}>
      <Link className="row-title" to={`/novels/${encodeURIComponent(novel.id)}`}>
        {novel.title}
      </Link>
      <span className="row-meta">{metaLine(t, novel, language)}</span>
      <span className="tag">{t(`novels.status.${novel.status}`)}</span>
      {writing && <WritingProgress job={job} />}
      {unfinished && (
        <span className="row-meta">
          {t("novels.chapters", { written: String(written), total: String(novel.chapters.length) })}
          {novel.error && <> · {novel.error}</>}
        </span>
      )}
      <div className="actions">
        {writing && (
          <button type="button" disabled={busy} onClick={onCancel}>
            {t("conversion.cancel")}
          </button>
        )}
        {unfinished && (
          <button type="button" className="primary" disabled={busy || jobRunning} onClick={onContinue}>
            {t("novel.continue")}
          </button>
        )}
        <button type="button" onClick={onWriteAgain}>
          {t("novels.writeAgain")}
        </button>
        <button type="button" className="danger" disabled={busy || writing} onClick={onDelete}>
          {t("dialog.delete")}
        </button>
      </div>
    </li>
  );
}

/** A writing novel's job: its chapters done out of all while it writes them, an indeterminate bar before. */
function WritingProgress({ job }: { job: Conversion | null }) {
  const t = useT();
  const counted = job && job.step === "writing" && job.total > 0;
  return (
    <span className="novel-progress">
      {counted ? (
        <progress aria-label={t("novels.status.writing")} value={job.done} max={job.total} />
      ) : (
        <progress aria-label={t("novels.status.writing")} />
      )}
      {counted && (
        <span className="row-meta">{t("novels.chapters", { written: String(job.done), total: String(job.total) })}</span>
      )}
    </span>
  );
}

/** "Short story · Grimdark · Tell it from Ned's point of view… · 20/10/2026". */
function metaLine(t: Translate, novel: ListedNovel, language: string): string {
  const tone = novel.tone === "custom" ? novel.custom_tone : t(`play.tone.${novel.tone}`);
  const said = novel.instructions.trim();
  const instructions = said.length > INSTRUCTIONS_SHOWN ? `${said.slice(0, INSTRUCTIONS_SHOWN).trimEnd()}…` : said;
  const date = new Date(novel.created_at).toLocaleDateString(language);
  return [t(`novel.length.${novel.length}`), tone, instructions, date].filter(Boolean).join(" · ");
}
