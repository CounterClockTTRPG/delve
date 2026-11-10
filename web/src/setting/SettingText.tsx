import type { MouseEvent } from "react";
import { useNavigate } from "react-router-dom";
import { useT } from "../i18n";
import { escapeHtml, renderMarkdown } from "../play/markdown";
import styles from "./Setting.module.css";

// A setting page's text: Markdown (`renderMarkdown`, which escapes first), its `[[Target|label]]` links, and its
// `::: dm` … `:::` sections. A link is taken out before the Markdown is rendered and put back after, so no Markdown
// mark inside a title can break it; its target and label are escaped like the rest.

const LINK = /\[\[([^\]|]+)(?:\|([^\]]+))?\]\]/g;
// A placeholder neither escaping nor the inline Markdown touches.
const SLOT = /\u0000(\d+)\u0000/g;

/** The text cut at its DM-only sections: a line `::: dm` opens one, the next line `:::` closes it, else the end. */
export function sections(text: string): { dm: boolean; text: string }[] {
  const out: { dm: boolean; text: string }[] = [];
  let dm = false;
  let lines: string[] = [];
  const flush = () => {
    if (lines.join("").trim()) out.push({ dm, text: lines.join("\n") });
    lines = [];
  };
  for (const line of text.split("\n")) {
    if (!dm && line.trim() === "::: dm") {
      flush();
      dm = true;
    } else if (dm && line.trim() === ":::") {
      flush();
      dm = false;
    } else lines.push(line);
  }
  flush();
  return out;
}

function linkedHtml(text: string, pageHref: (title: string) => string): string {
  const links: string[] = [];
  const marked = text.replace(LINK, (_, target: string, label?: string) => {
    const title = target.trim();
    links.push(
      `<a href="${escapeHtml(pageHref(title))}" data-page="${escapeHtml(title)}">${escapeHtml((label ?? target).trim())}</a>`,
    );
    return `\u0000${links.length - 1}\u0000`;
  });
  return renderMarkdown(marked).replace(SLOT, (_, i: string) => links[Number(i)]);
}

export default function SettingText({
  text,
  pageHref,
  dmMarked,
}: {
  text: string;
  pageHref: (title: string) => string;
  /** Show the `::: dm` sections as marked asides (the organisers' view). */
  dmMarked: boolean;
}) {
  const t = useT();
  const navigate = useNavigate();
  // A link opens its page through the router, not a page load.
  const follow = (e: MouseEvent<HTMLDivElement>) => {
    const link = (e.target as HTMLElement).closest("a[data-page]");
    if (!link || e.button !== 0 || e.metaKey || e.ctrlKey || e.shiftKey || e.altKey) return;
    e.preventDefault();
    navigate(pageHref(link.getAttribute("data-page")!));
  };
  return (
    <div className={styles.text} onClick={follow}>
      {sections(text).map((s, i) =>
        s.dm && dmMarked ? (
          <aside key={i} className="dm-only" aria-label={t("setting.dmOnly")}>
            <p className="dm-only-mark">{t("setting.dmOnly")}</p>
            <div dangerouslySetInnerHTML={{ __html: linkedHtml(s.text, pageHref) }} />
          </aside>
        ) : (
          <div key={i} dangerouslySetInnerHTML={{ __html: linkedHtml(s.text, pageHref) }} />
        ),
      )}
    </div>
  );
}
