// The DM's Markdown as HTML, ported from ttrpg2's /play page: the text is escaped first, and only then are the few
// Markdown forms turned into tags, so nothing the DM writes can become markup of its own.

export function escapeHtml(s: string): string {
  return s.replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]!);
}

/** `s` is already escaped. Triple asterisks before double, double before single, code spans first. */
function inline(s: string): string {
  return s
    .replace(/`([^`]+)`/g, "<code>$1</code>")
    .replace(/\*\*\*(.+?)\*\*\*/g, "<strong><em>$1</em></strong>")
    .replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>")
    .replace(/\*(.+?)\*/g, "<em>$1</em>")
    .replace(/(^|[^\w])_(.+?)_(?!\w)/g, "$1<em>$2</em>");
}

/** One line's inline Markdown (emphasis, strong, code) as HTML, escaped first: for a line that is no paragraph. */
export function renderInline(text: string): string {
  return inline(escapeHtml(text));
}

const ENTITIES: Record<string, string> = { "&amp;": "&", "&lt;": "<", "&gt;": ">", "&quot;": '"', "&#39;": "'" };

/** The words `renderInline` shows, without their Markdown: what is read out or mouthed. */
export function plainInline(text: string): string {
  return renderInline(text)
    .replace(/<[^>]*>/g, "")
    .replace(/&(?:amp|lt|gt|quot|#39);/g, (e) => ENTITIES[e]);
}

// A paragraph that is one quoted speech, with or without the `> `, reads as a blockquote (as in ttrpg2).
const SPEECH = /^\s*\*?\s*(?:&quot;|&ldquo;|“)[\s\S]*(?:&quot;|&rdquo;|”)\s*\*?\s*$/;
// Block forms are matched on the escaped text, so a Markdown ">" arrives as "&gt;".
const QUOTE = /^&gt;\s?/;
const BULLET = /^[-*+]\s+/;
// A table is a row of cells followed by its alignment row, such as `|---|:---:|`.
const TABLE_ROW = /^\|.*\|$/;
const ALIGN_ROW = /^\|(\s*:?-{3,}:?\s*\|)+$/;

/** A table row's cells: split on the pipes that aren't escaped, and an escaped pipe kept as a pipe. */
function cells(row: string): string[] {
  return row
    .slice(1, -1)
    .split(/(?<!\\)\|/)
    .map((c) => c.trim().replace(/\\\|/g, "|"));
}
const NUMBERED = /^\d+\.\s+/;

/** Read-aloud text and speech are blockquotes with the class `read-aloud`, styled apart from the narration. */
export function renderMarkdown(text: string): string {
  const lines = escapeHtml(text).split("\n");
  const out: string[] = [];
  let para: string[] = [];

  const flush = () => {
    if (para.length === 0) return;
    const joined = para.join(" ");
    out.push(SPEECH.test(joined) ? `<blockquote class="read-aloud">${inline(joined)}</blockquote>` : `<p>${inline(joined)}</p>`);
    para = [];
  };
  const run = (i: number, pattern: RegExp): [string[], number] => {
    const items: string[] = [];
    while (i < lines.length && pattern.test(lines[i].trim())) items.push(lines[i++].trim().replace(pattern, ""));
    return [items, i];
  };

  let i = 0;
  while (i < lines.length) {
    const t = lines[i].trim();
    if (!t) {
      flush();
      i++;
      continue;
    }
    const heading = /^(#{1,6})\s+(.+)$/.exec(t);
    if (heading) {
      flush();
      const level = Math.min(heading[1].length + 2, 6);
      out.push(`<h${level}>${inline(heading[2])}</h${level}>`);
      i++;
    } else if (/^(-{3,}|\*{3,}|_{3,})$/.test(t)) {
      flush();
      out.push("<hr>");
      i++;
    } else if (TABLE_ROW.test(t) && ALIGN_ROW.test(lines[i + 1]?.trim() ?? "")) {
      flush();
      const head = cells(t);
      const rows: string[] = [];
      let next = i + 2;
      while (next < lines.length && TABLE_ROW.test(lines[next].trim())) rows.push(lines[next++].trim());
      const row = (tag: string, cs: string[]) => `<tr>${cs.map((c) => `<${tag}>${inline(c)}</${tag}>`).join("")}</tr>`;
      out.push(
        `<table><thead>${row("th", head)}</thead>` +
          (rows.length ? `<tbody>${rows.map((r) => row("td", cells(r))).join("")}</tbody>` : "") +
          "</table>",
      );
      i = next;
    } else if (QUOTE.test(t)) {
      flush();
      const [items, next] = run(i, QUOTE);
      out.push(`<blockquote class="read-aloud">${items.map(inline).join("<br>")}</blockquote>`);
      i = next;
    } else if (BULLET.test(t) || NUMBERED.test(t)) {
      flush();
      const tag = BULLET.test(t) ? "ul" : "ol";
      const [items, next] = run(i, tag === "ul" ? BULLET : NUMBERED);
      out.push(`<${tag}>${items.map((it) => `<li>${inline(it)}</li>`).join("")}</${tag}>`);
      i = next;
    } else {
      para.push(t);
      i++;
    }
  }
  flush();
  return out.join("");
}
