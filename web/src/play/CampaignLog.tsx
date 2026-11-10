// `/campaigns/:campaignId/log`: the campaign's story from start to end, a page at a time (DEL-324). Its pages follow the
// sessions, each cut into even parts (`play.campaign_log` on the server); `?page=` is the page, so each has its own
// address, and `?all=1` shows the whole log on one page for print. The PDF comes from the browser's Print dialog, as
// the novel's and the module's do. Download Markdown saves the whole log as a `.md` file, as the page shows it (DEL-346).
import { useQueries, useQuery } from "@tanstack/react-query";
import { useEffect, useMemo, useState } from "react";
import { Link, useParams, useSearchParams } from "react-router-dom";
import { useLanguage, useT, type Translate } from "../i18n";
import { useNoLook } from "../looks/looks";
import mapStyles from "../routes/MapPrint.module.css";
import {
  getCampaignLog,
  imageUrl,
  pictureUrl,
  playKeys,
  type CampaignLog as Log,
  type DiceLine,
  type LogPage,
  type StoryEntry,
} from "./api";
import styles from "./CampaignLog.module.css";
import { renderMarkdown } from "./markdown";
import { actor, diceText, shownText } from "./Story";

export default function CampaignLog() {
  const { campaignId = "" } = useParams();
  const [search, setSearch] = useSearchParams();
  const t = useT();
  const language = useLanguage();
  useNoLook();
  const whole = search.get("all") === "1";
  const asked = Math.max(1, Number.parseInt(search.get("page") ?? "1", 10) || 1);
  const [dice, setDice] = useState(true);
  const [saving, setSaving] = useState(false);
  const first = useQuery({
    queryKey: playKeys.log(campaignId, asked, language),
    queryFn: () => getCampaignLog(campaignId, asked, language),
  });
  const pages = first.data?.pages ?? [];
  // The whole log: every page, each its own request, shown in order once all are in.
  const all = useQueries({
    queries: (whole ? pages : []).map((p) => ({
      queryKey: playKeys.log(campaignId, p.page, language),
      queryFn: () => getCampaignLog(campaignId, p.page, language),
    })),
  });
  const name = first.data?.campaign.name ?? "";

  useEffect(() => {
    if (name) document.title = t("log.documentTitle", { name });
  }, [name, t]);

  if (first.error) {
    return (
      <p role="alert" className="notice error">
        {t("log.failed", { error: first.error.message })}
      </p>
    );
  }
  if (!first.data) return <div className={mapStyles.loading}>{t("log.loading")}</div>;
  const log = first.data;
  const go = (page: number) => setSearch({ page: String(page) });
  const shown: { page: LogPage; entries: StoryEntry[] }[] = whole
    ? all.every((q) => q.data)
      ? all.map((q) => ({ page: pages[q.data!.page - 1], entries: q.data!.entries }))
      : []
    : log.page > 0
      ? [{ page: pages[log.page - 1], entries: log.entries }]
      : [];

  return (
    <div className={styles.page}>
      <div className={mapStyles.toolbar}>
        <Link to={`/play/${encodeURIComponent(campaignId)}`} className={mapStyles.back}>
          {t("log.back")}
        </Link>
        <label className={styles.check}>
          <input type="checkbox" checked={dice} onChange={(e) => setDice(e.target.checked)} /> {t("log.dice")}
        </label>
        {pages.length > 1 &&
          (whole ? (
            <Link to="?page=1" className={mapStyles.back}>
              {t("log.paged")}
            </Link>
          ) : (
            <Link to="?all=1" className={mapStyles.back}>
              {t("log.whole")}
            </Link>
          ))}
        <button
          type="button"
          className={mapStyles.back}
          data-testid="log-markdown"
          disabled={saving || pages.length === 0}
          onClick={async () => {
            setSaving(true);
            try {
              const all = await Promise.all(pages.map((p) => getCampaignLog(campaignId, p.page, language)));
              save(`${slug(log.campaign.name)}-log.md`, logMarkdown(log.campaign.name, all, dice, t, language));
            } finally {
              setSaving(false);
            }
          }}
        >
          {t("log.markdown")}
        </button>
        <button type="button" className={mapStyles.printBtn} onClick={() => window.print()}>
          {t("print.print")}
        </button>
      </div>

      <header className={styles.header}>
        <h1>{log.campaign.name}</h1>
        <p className={styles.subtitle}>{t("log.title")}</p>
        {!whole && pages.length > 1 && (
          <Pager pages={pages} page={log.page} go={go} t={t} language={language} />
        )}
      </header>

      {pages.length === 0 && <p className="placeholder">{t("log.empty")}</p>}
      {whole && shown.length === 0 && pages.length > 0 && <p className="placeholder">{t("log.loading")}</p>}

      {shown.map(({ page, entries }) => (
        <section key={page.page} className={styles.part} data-part="log-page" aria-label={pageName(t, page)}>
          <h2>{pageName(t, page)}</h2>
          <p className={styles.when}>{span(page, language)}</p>
          {entries.map((entry) => (
            <LogEntry key={entry.id} entry={entry} names={log.names} dice={dice} t={t} />
          ))}
        </section>
      ))}

      {!whole && pages.length > 1 && (
        <nav className={styles.foot} aria-label={t("log.pages")}>
          <button type="button" disabled={log.page <= 1} onClick={() => go(log.page - 1)}>
            {t("log.previous")}
          </button>
          <span>{t("log.pageOf", { page: String(log.page), pages: String(pages.length) })}</span>
          <button type="button" disabled={log.page >= pages.length} onClick={() => go(log.page + 1)}>
            {t("log.next")}
          </button>
        </nav>
      )}
    </div>
  );
}

/** The page's heading: its session and title, and its part when the session has several. */
export function pageName(t: Translate, page: LogPage): string {
  const session =
    page.session === null
      ? t("log.before")
      : [t("log.session", { number: String(page.session) }), page.title].filter(Boolean).join(": ");
  return page.parts > 1 ? `${session} (${t("log.part", { part: String(page.part), parts: String(page.parts) })})` : session;
}

/** When the page was played, in the reader's language: "24 Oct 2026, 08:24–09:15", or two dates over midnight. */
function span(page: LogPage, language: string): string {
  const from = new Date(page.from);
  const to = new Date(page.to);
  const day = new Intl.DateTimeFormat(language, { dateStyle: "medium" });
  const time = new Intl.DateTimeFormat(language, { timeStyle: "short" });
  if (day.format(from) === day.format(to)) return `${day.format(from)}, ${time.format(from)}–${time.format(to)}`;
  const both = new Intl.DateTimeFormat(language, { dateStyle: "medium", timeStyle: "short" });
  return `${both.format(from)} – ${both.format(to)}`;
}

/** The contents: every page by its session and when it was played, then Previous and Next. */
function Pager({
  pages,
  page,
  go,
  t,
  language,
}: {
  pages: LogPage[];
  page: number;
  go: (page: number) => void;
  t: Translate;
  language: string;
}) {
  return (
    <nav className={styles.pager} aria-label={t("log.pages")}>
      <button type="button" disabled={page <= 1} onClick={() => go(page - 1)} aria-label={t("log.previous")}>
        ‹
      </button>
      <select aria-label={t("log.contents")} value={page} onChange={(e) => go(Number(e.target.value))}>
        {pages.map((p) => (
          <option key={p.page} value={p.page}>
            {`${p.page}. ${pageName(t, p)} · ${span(p, language)}`}
          </option>
        ))}
      </select>
      <button type="button" disabled={page >= pages.length} onClick={() => go(page + 1)} aria-label={t("log.next")}>
        ›
      </button>
    </nav>
  );
}

function Markdown({ text }: { text: string }) {
  const html = useMemo(() => renderMarkdown(text), [text]);
  return <div className={styles.prose} dangerouslySetInnerHTML={{ __html: html }} />;
}

/** One entry as the log prints it: plainer than the story, no portraits, controls or live marks. */
function LogEntry({ entry, names, dice, t }: { entry: StoryEntry; names: Record<string, string>; dice: boolean; t: Translate }) {
  const { text } = shownText(entry);
  const { caption, asset, image_id } = entry.payload;
  switch (entry.kind) {
    case "player_act":
      return (
        <div className={styles.act}>
          <span className={styles.who}>{actor(entry, null, names, t("play.you"))}</span>
          <p>{text}</p>
        </div>
      );
    case "dm_text":
      return <Markdown text={text} />;
    case "say":
      return (
        <blockquote className={styles.said}>
          <span className={styles.who}>{entry.payload.speaker?.name}</span>
          <Markdown text={text} />
        </blockquote>
      );
    case "recap":
      return (
        <div className={styles.recap}>
          <span className={styles.who}>{t("play.recap")}</span>
          <Markdown text={text} />
        </div>
      );
    case "ask":
    case "answer":
      return (
        <div className={styles.asked}>
          <span className={styles.who}>{t(entry.kind === "ask" ? "log.asked" : "log.answered")}</span>
          <Markdown text={text} />
        </div>
      );
    case "image":
    case "scene": {
      const url = entry.kind === "image" && asset ? imageUrl(entry.campaign_id, asset) : image_id ? pictureUrl(entry.campaign_id, image_id) : null;
      if (!url) return null;
      return (
        <figure className={styles.figure}>
          <img src={url} alt={caption || t("play.shownImage")} loading="lazy" />
          {caption && <figcaption>{caption}</figcaption>}
        </figure>
      );
    }
    case "tool":
      if (!dice) return null;
      return (
        <ul className={styles.dice}>
          {((entry.payload as { dice?: DiceLine[] }).dice ?? []).map((line, i) => (
            <li key={i}>{diceText(line, t)}</li>
          ))}
        </ul>
      );
    default:
      return null;
  }
}


/** The whole log as Markdown, as the page reads it: the campaign's name, each page under its heading with when it was
 * played, the acts quoted with who made them, the DM's words as written, the lines said with their speaker, the
 * recaps and questions, the pictures by their caption, and the dice when `dice`. */
export function logMarkdown(name: string, pages: Log[], dice: boolean, t: Translate, language: string): string {
  const out: string[] = [`# ${name}`, "", `*${t("log.title")}*`];
  for (const page of pages) {
    const at = page.pages[page.page - 1];
    if (!at) continue;
    out.push("", `## ${pageName(t, at)}`, "", `*${span(at, language)}*`);
    for (const entry of page.entries) {
      const block = entryMarkdown(entry, page.names, dice, t);
      if (block) out.push("", block);
    }
  }
  return out.join("\n") + "\n";
}

function entryMarkdown(entry: StoryEntry, names: Record<string, string>, dice: boolean, t: Translate): string | null {
  const { text } = shownText(entry);
  const { caption } = entry.payload;
  const quoted = (body: string) =>
    body
      .split("\n")
      .map((line) => (line ? `> ${line}` : ">"))
      .join("\n");
  switch (entry.kind) {
    case "player_act":
      return quoted(`**${actor(entry, null, names, t("play.you"))}:** ${text}`);
    case "dm_text":
      return text;
    case "say":
      return `**${entry.payload.speaker?.name ?? ""}:** ${text}`;
    case "recap":
      return `### ${t("play.recap")}\n\n${text}`;
    case "ask":
    case "answer":
      return quoted(`**${t(entry.kind === "ask" ? "log.asked" : "log.answered")}:** ${text}`);
    case "image":
    case "scene":
      return `*[${caption || t(entry.kind === "image" ? "play.shownImage" : "play.paintedScene")}]*`;
    case "tool": {
      const lines = (entry.payload as { dice?: DiceLine[] }).dice ?? [];
      return dice && lines.length ? lines.map((line) => `- *${diceText(line, t)}*`).join("\n") : null;
    }
    default:
      return null;
  }
}

function slug(name: string): string {
  return (
    name
      .normalize("NFKD")
      .replace(/[\u0300-\u036f]/g, "")
      .toLowerCase()
      .replace(/[^a-z0-9]+/g, "-")
      .replace(/^-|-$/g, "") || "campaign"
  );
}

/** The browser saves `text` as the file `filename`. */
function save(filename: string, text: string): void {
  const url = URL.createObjectURL(new Blob([text], { type: "text/markdown;charset=utf-8" }));
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  document.body.appendChild(link);
  link.click();
  link.remove();
  URL.revokeObjectURL(url);
}
