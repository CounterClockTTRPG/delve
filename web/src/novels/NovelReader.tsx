// `/novels/:id`: a novel to read (novelization spec, "Reading"), in a book-like column rather than the app's dense
// layout. The owner's alone: the server answers a seat 403. A novel being written is fetched again as its job moves.
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useContext, useEffect, useMemo, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { EventsContext } from "../api";
import { useLanguage, useT, type Translate } from "../i18n";
import { continueNovel, getNovel, novelKeys, renameNovel, writtenChapters, type Novel } from "./api";
import { chapterHtml } from "./markdown";
import styles from "./NovelReader.module.css";

/** "Short story · Grimdark · 20 Oct 2026": what the novel is, under its title (the reader's and the title page's). */
export function novelByline(novel: Novel, t: Translate, language: string): string {
  const tone = novel.tone === "custom" ? novel.custom_tone : t(`play.tone.${novel.tone}`);
  const date = new Date(novel.created_at).toLocaleDateString(language, { day: "numeric", month: "long", year: "numeric" });
  return [t(`novel.length.${novel.length}`), tone, date].filter(Boolean).join(" · ");
}

export default function NovelReader() {
  const { id = "" } = useParams();
  const t = useT();
  const language = useLanguage();
  const client = useQueryClient();
  const subscribe = useContext(EventsContext);
  const novel = useQuery({ queryKey: novelKeys.one(id), queryFn: () => getNovel(id) });
  const job = novel.data?.status === "writing" ? novel.data.conversion_id : null;

  // Each step of its job may have saved a chapter. The events carry no text, so the novel is fetched again.
  useEffect(() => {
    if (!job) return;
    return subscribe({
      conversion: (data) => {
        if ((data as { id?: unknown } | null)?.id === job) client.invalidateQueries({ queryKey: novelKeys.one(id) });
      },
    });
  }, [subscribe, client, id, job]);

  const resume = useMutation({
    mutationFn: () => continueNovel(id),
    onSuccess: (next) => {
      client.setQueryData(novelKeys.one(id), next);
      client.invalidateQueries({ queryKey: novelKeys.lists });
    },
  });

  useEffect(() => {
    if (novel.data?.title) document.title = t("print.documentTitle", { name: novel.data.title });
  }, [novel.data?.title, t]);

  const html = useMemo(() => new Map(writtenChapters(novel.data ?? { chapters: [] }).map((c) => [c, chapterHtml(c.text!)])), [novel.data]);

  if (novel.error) {
    return (
      <p role="alert" className="notice error">
        {t("novel.loadFailed", { error: novel.error.message })}
      </p>
    );
  }
  if (!novel.data) return <p className={styles.loading}>{t("novel.loading")}</p>;
  const n = novel.data;
  const written = writtenChapters(n).length;
  const counts = { written: String(written), total: String(n.chapters.length) };
  const back = n.campaign_id
    ? { to: `/campaigns/${encodeURIComponent(n.campaign_id)}`, label: t("novel.back.campaign") }
    : { to: `/modules/${encodeURIComponent(n.module_id ?? "")}`, label: t("novel.back.module") };

  return (
    <article className={styles.book} lang={n.language}>
      <div className={styles.toolbar}>
        <Link to={back.to}>{back.label}</Link>
        <Link to={`/novels/${encodeURIComponent(id)}/print`}>{t("novel.print")}</Link>
      </div>

      <header className={styles.header}>
        <Title novel={n} />
        <p className={styles.byline}>{novelByline(n, t, language)}</p>
      </header>

      {n.status !== "done" && (
        <div className={`notice ${styles.state}`}>
          <p>
            {n.status === "writing"
              ? n.chapters.length
                ? t("novel.writing", counts)
                : t("novel.outlining")
              : t("novel.unfinished", counts)}
          </p>
          {n.status !== "writing" && n.error && <p>{n.error}</p>}
          {n.status !== "writing" && (
            <button type="button" disabled={resume.isPending} onClick={() => resume.mutate()}>
              {t("novel.continue")}
            </button>
          )}
          {resume.error && (
            <p role="alert" className="notice error">
              {t("novel.continueFailed", { error: resume.error.message })}
            </p>
          )}
        </div>
      )}

      {n.chapters.length > 0 && (
        <nav className={styles.contents} aria-label={t("novel.contents")}>
          <h2>{t("novel.contents")}</h2>
          <ol>
            {n.chapters.map((chapter, i) => (
              <li key={i}>
                {chapter.text === null ? (
                  <span className={styles.planned}>
                    {chapter.title} <small>({t("novel.notWritten")})</small>
                  </span>
                ) : (
                  <a href={`#chapter-${i + 1}`}>{chapter.title}</a>
                )}
              </li>
            ))}
          </ol>
        </nav>
      )}

      {n.chapters.map(
        (chapter, i) =>
          chapter.text !== null && (
            <section key={i} id={`chapter-${i + 1}`} className={styles.chapter}>
              <h2>{chapter.title}</h2>
              <div className={styles.text} dangerouslySetInnerHTML={{ __html: html.get(chapter) ?? "" }} />
            </section>
          ),
      )}
    </article>
  );
}

/** The title, and Rename, which edits it in place: Enter or Save keeps it, Escape or Cancel leaves it. */
function Title({ novel }: { novel: Novel }) {
  const t = useT();
  const client = useQueryClient();
  const [draft, setDraft] = useState<string | null>(null);
  const rename = useMutation({
    mutationFn: (title: string) => renameNovel(novel.id, title),
    onSuccess: (next) => {
      client.setQueryData(novelKeys.one(novel.id), next);
      client.invalidateQueries({ queryKey: novelKeys.lists });
      setDraft(null);
    },
  });

  if (draft === null) {
    return (
      <div className={styles.title}>
        <h1>{novel.title}</h1>
        <button type="button" className={styles.rename} onClick={() => setDraft(novel.title)}>
          {t("novel.rename")}
        </button>
      </div>
    );
  }
  const next = draft.trim();
  return (
    <form
      className={styles.title}
      onSubmit={(e) => {
        e.preventDefault();
        if (!next || next === novel.title) setDraft(null);
        else rename.mutate(next);
      }}
    >
      <input
        aria-label={t("novel.title")}
        className={styles.titleInput}
        value={draft}
        autoFocus
        onChange={(e) => setDraft(e.target.value)}
        onKeyDown={(e) => e.key === "Escape" && setDraft(null)}
      />
      <button type="submit" disabled={rename.isPending || !next}>
        {t("novel.save")}
      </button>
      <button type="button" onClick={() => setDraft(null)}>
        {t("dialog.cancel")}
      </button>
      {rename.error && (
        <p role="alert" className="notice error">
          {t("novel.renameFailed", { error: rename.error.message })}
        </p>
      )}
    </form>
  );
}
