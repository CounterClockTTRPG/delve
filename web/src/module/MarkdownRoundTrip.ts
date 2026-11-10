// A module text's Markdown, to the editor's document and back (Review Focus 1).
//
// The tokens come from the lexer @tiptap/markdown ships (marked). The document and the Markdown it writes are our
// own, because the module format needs what @tiptap/markdown's serialiser doesn't keep: front matter, `{#anchor}`
// headings, `[[kind:id]]` refs, `asset:` images and wrapped lines.
//
// Saving an unchanged text gives the same bytes. Each top-level block remembers its source (`attrs.source`): the
// Markdown it was read from, and what the serialiser would write for it then. While the block still serialises the
// same, its source is written back as it was; once it is edited, it is written in the editor's own style, which is
// the style of `fixtures/everything.md`.
import {
  Extension,
  Mark,
  Node,
  decodeHtmlEntities,
  getSchema,
  mergeAttributes,
  textblockTypeInputRule,
  type AnyExtension,
  type JSONContent,
} from "@tiptap/core";
import Image from "@tiptap/extension-image";
import { Plugin } from "@tiptap/pm/state";
import { TableKit } from "@tiptap/extension-table";
import { MarkdownManager } from "@tiptap/markdown";
import StarterKit from "@tiptap/starter-kit";

/** What a top-level block remembers of the Markdown it was read from. */
export interface BlockSource {
  /** The block's Markdown, without the blank lines after it. */
  raw: string;
  /** What `toMarkdown` wrote for the block when it was read. */
  canon: string;
  /** The blank lines between it and the next block. */
  gap: string;
  /** Its place among the blocks it was read with. */
  pos: number;
}

const BLOCKS = ["paragraph", "heading", "blockquote", "bulletList", "orderedList", "codeBlock", "horizontalRule", "table", "rawBlock"];

/** Ref kinds of the format (§6), allowed as link targets. */
const REF_KINDS = "map|text|key|asset|npc|faction|quest|rumor|secret|encounter|worldmap|monster|item|spell";
const REF_URL = new RegExp(`^(?:${REF_KINDS}):`);
const SHORTHAND = /\[\[([a-z]+):([^[\]\s]+)\]\]/g;
const ANCHOR = /\s*\{#([A-Za-z0-9][A-Za-z0-9._-]*)\}\s*$/;
// The format's `_KEY_RX`: "## 31." is a key with an empty title; `headingKey` asks for a digit, so "## Treasure:" isn't.
const KEY = /^([^\s.:]{1,12})[.:](?:\s+(.*))?$/;

// --- the schema ----------------------------------------------------------------------------------------------------

const LEVELS = [1, 2, 3, 4, 5, 6];

/** A heading. Our own rather than StarterKit's, so the editor can give it a node view (its room chip). */
export const ModuleHeading = Node.create({
  name: "heading",
  group: "block",
  content: "inline*",
  defining: true,
  addAttributes: () => ({
    level: { default: 2, rendered: false },
    // The `{#anchor}` goes with the heading's text: Enter at its start leaves an empty heading above.
    anchor: { default: null, rendered: false },
  }),
  parseHTML: () => LEVELS.map((level) => ({ tag: `h${level}`, attrs: { level } })),
  renderHTML: ({ node, HTMLAttributes }) => [`h${node.attrs.level}`, HTMLAttributes, 0],
  addKeyboardShortcuts() {
    return Object.fromEntries(
      [2, 3, 4].map((level) => [`Mod-Alt-${level}`, () => this.editor.commands.toggleNode(this.name, "paragraph", { level })]),
    );
  },
  addInputRules() {
    return [
      textblockTypeInputRule({ find: /^(#{1,6})\s$/, type: this.type, getAttributes: (match) => ({ level: match[1].length }) }),
    ];
  },
  addProseMirrorPlugins() {
    // A split heading has its anchor twice; the first of them with text keeps it (anchors are unique in a text).
    return [
      new Plugin({
        appendTransaction: (transactions, _old, state) => {
          if (!transactions.some((tr) => tr.docChanged)) return null;
          const owner = new Map<string, number>();
          state.doc.descendants((node, pos) => {
            const anchor = node.type.name === this.name ? node.attrs.anchor : null;
            if (!anchor) return;
            const held = owner.get(anchor);
            if (held === undefined || (!state.doc.nodeAt(held)!.textContent && node.textContent)) owner.set(anchor, pos);
          });
          const tr = state.tr;
          state.doc.descendants((node, pos) => {
            const anchor = node.type.name === this.name ? node.attrs.anchor : null;
            if (anchor && owner.get(anchor) !== pos) tr.setNodeAttribute(pos, "anchor", null);
          });
          return tr.docChanged ? tr : null;
        },
      }),
    ];
  },
});

/** A wrapped line inside a paragraph: a space on screen, a line break in the Markdown. */
const SoftBreak = Node.create({
  name: "softBreak",
  group: "inline",
  inline: true,
  selectable: false,
  atom: true,
  renderText: () => " ",
  parseHTML: () => [{ tag: "span[data-soft-break]" }],
  renderHTML: () => ["span", { "data-soft-break": "" }, " "],
});

/** `[[npc:brother-ansel]]`: a ref to an entity, shown as its name. */
export const EntityRef = Node.create({
  name: "entityRef",
  group: "inline",
  inline: true,
  atom: true,
  addAttributes: () => ({ kind: { default: "npc" }, id: { default: "" } }),
  renderText: ({ node }) => `[[${node.attrs.kind}:${node.attrs.id}]]`,
  parseHTML: () => [
    {
      tag: "span[data-ref]",
      getAttrs: (el) => {
        const [kind, ...id] = String((el as HTMLElement).dataset.ref).split(":");
        return { kind, id: id.join(":") };
      },
    },
  ],
  renderHTML: ({ node }) => ["span", { "data-ref": `${node.attrs.kind}:${node.attrs.id}`, class: "ref-chip" }, `${node.attrs.kind}:${node.attrs.id}`],
});

/** Markdown the editor can't edit (HTML, task lists, link definitions…), kept as it was. */
const RawBlock = Node.create({
  name: "rawBlock",
  group: "block",
  atom: true,
  addAttributes: () => ({ raw: { default: "", rendered: false } }),
  parseHTML: () => [{ tag: "pre[data-raw-block]", getAttrs: (el) => ({ raw: (el as HTMLElement).textContent ?? "" }) }],
  renderHTML: ({ node }) => ["pre", { "data-raw-block": "", class: "raw-block" }, node.attrs.raw],
});

const RawInline = Node.create({
  name: "rawInline",
  group: "inline",
  inline: true,
  atom: true,
  addAttributes: () => ({ raw: { default: "", rendered: false } }),
  renderText: ({ node }) => node.attrs.raw,
  parseHTML: () => [{ tag: "code[data-raw-inline]", getAttrs: (el) => ({ raw: (el as HTMLElement).textContent ?? "" }) }],
  renderHTML: ({ node }) => ["code", { "data-raw-inline": "", class: "raw-inline" }, node.attrs.raw],
});

/** The attributes the Markdown needs and the stock extensions don't have. */
const MarkdownAttributes = Extension.create({
  name: "markdownAttributes",
  addGlobalAttributes: () => [
    {
      types: ["doc"],
      attributes: {
        frontMatter: { default: "", rendered: false },
        trailing: { default: null, rendered: false },
      },
    },
    { types: BLOCKS, attributes: { source: { default: null, rendered: false, keepOnSplit: false } } },
    { types: ["bulletList"], attributes: { marker: { default: "-", rendered: false } } },
    { types: ["orderedList"], attributes: { delimiter: { default: ".", rendered: false } } },
    { types: ["bulletList", "orderedList"], attributes: { tight: { default: true, rendered: false } } },
    { types: ["codeBlock"], attributes: { fence: { default: null, rendered: false } } },
    { types: ["hardBreak"], attributes: { marker: { default: "\\", rendered: false } } },
    { types: ["link"], attributes: { form: { default: null, rendered: false } } },
    {
      types: ["tableCell", "tableHeader"],
      attributes: {
        align: {
          default: null,
          parseHTML: (el) => (el as HTMLElement).style.textAlign || null,
          renderHTML: (attrs) => (attrs.align ? { style: `text-align: ${attrs.align}` } : {}),
        },
      },
    },
  ],
});

// The code mark may sit inside bold or a link: `**`+1`**` is common in modules.
const CodeMark = Mark.create({
  name: "code",
  excludes: "",
  code: true,
  parseHTML: () => [{ tag: "code" }],
  renderHTML: ({ HTMLAttributes }) => ["code", mergeAttributes(HTMLAttributes), 0],
});

export interface TextExtensionOptions {
  /** The image URL of an `asset:` src. */
  assetUrl?: (src: string) => string;
  /** Extensions that replace the stock ones by name (the editor's node views). */
  overrides?: AnyExtension[];
}

/** The editor's schema: StarterKit, tables and images, and the nodes of the module format. */
export function moduleTextExtensions({ assetUrl, overrides = [] }: TextExtensionOptions = {}): AnyExtension[] {
  const replaced = new Set(overrides.map((extension) => extension.name));
  const all: AnyExtension[] = [
    StarterKit.configure({
      code: false,
      underline: false,
      heading: false,
      link: {
        openOnClick: false,
        autolink: false,
        linkOnPaste: false,
        isAllowedUri: (url, ctx) => REF_URL.test(url) || ctx.defaultValidate(url),
      },
    }),
    ModuleHeading,
    CodeMark,
    Image.extend({
      renderHTML({ node, HTMLAttributes }) {
        const src = String(node.attrs.src ?? "");
        return ["img", mergeAttributes(HTMLAttributes, { src: assetUrl && src.startsWith("asset:") ? assetUrl(src) : src })];
      },
    }).configure({ inline: true, allowBase64: false }),
    TableKit.configure({ table: { resizable: false } }),
    SoftBreak,
    EntityRef,
    RawBlock,
    RawInline,
    MarkdownAttributes,
  ];
  return [...all.filter((extension) => !replaced.has(extension.name)), ...overrides];
}

let schema: ReturnType<typeof getSchema> | null = null;
function moduleSchema() {
  schema ??= getSchema(moduleTextExtensions());
  return schema;
}

// --- headings ------------------------------------------------------------------------------------------------------

/** A heading's anchor as the format finds it (§5.2): the explicit `{#anchor}`, else the key's slug, else none. */
export function headingAnchor(level: number, text: string, anchor: string | null): string | null {
  if (anchor) return anchor;
  const key = headingKey(level, text);
  if (!key) return null;
  // The format's `refs.slugify`, exactly, so the anchor is the one the server links.
  return key.toLowerCase().replace(/[^a-z0-9._-]+/g, "-").replace(/^[-.]+|[-.]+$/g, "") || "x";
}

/** An id for a new text or entity from its name: "Brother Ansel" is `brother-ansel`. Ids start with a letter or digit. */
export function slugify(name: string): string {
  return name.toLowerCase().replace(/[^a-z0-9._-]+/g, "-").replace(/^[-._]+|[-._]+$/g, "") || "x";
}

/** A heading's key ("C1" of "C1. Entry Hall"): only on level 2 and deeper, and only with a digit in it. */
export function headingKey(level: number, text: string): string | null {
  const key = level >= 2 ? KEY.exec(text.trim()) : null;
  return key && /\d/.test(key[1]) ? key[1] : null;
}

// --- Markdown to the document --------------------------------------------------------------------------------------

type Token = {
  type: string;
  raw: string;
  text?: string;
  tokens?: Token[];
  [key: string]: unknown;
};

const marked = new MarkdownManager({ extensions: [] }).instance;
type MarkJSON = NonNullable<JSONContent["marks"]>[number];

function splitFrontMatter(md: string): [string, string] {
  const fm = /^---\r?\n[\s\S]*?\r?\n---[ \t]*(?:\r?\n|$)/.exec(md);
  const head = fm ? fm[0] : "";
  const blank = /^(?:[ \t]*\r?\n)*/.exec(md.slice(head.length))![0];
  return [head + blank, md.slice(head.length + blank.length)];
}

/** The editor's document of a text's Markdown. */
export function fromMarkdown(md: string): JSONContent {
  const [frontMatter, body] = splitFrontMatter(md);
  const tokens = new marked.Lexer({ gfm: true }).lex(body) as unknown as Token[];
  const content: JSONContent[] = [];
  // The raws of the top-level tokens add up to the body; where they don't, nothing is remembered.
  let offset = 0;
  let exact = true;
  let last: JSONContent | null = null;
  let trailing = "";
  for (const token of tokens) {
    if (exact && body.startsWith(token.raw, offset)) offset += token.raw.length;
    else exact = false;
    if (token.type === "space") {
      if (last?.attrs?.source) last.attrs.source.gap += token.raw;
      trailing += token.raw;
      continue;
    }
    const raw = token.raw.replace(/\n+$/, "");
    const gap = token.raw.slice(raw.length);
    const node = checked(block(token), raw);
    const canon = serialiseBlock(node);
    node.attrs = { ...node.attrs, source: exact ? { raw, canon, gap, pos: content.length } : null };
    content.push(node);
    last = node;
    trailing = gap;
  }
  return {
    type: "doc",
    attrs: { frontMatter, trailing: content.length && exact ? trailing : null },
    content,
  };
}

/** The node if the schema takes it, else the Markdown kept as it is. */
function checked(node: JSONContent, raw: string): JSONContent {
  try {
    moduleSchema().nodeFromJSON(node).check();
    return node;
  } catch {
    return { type: "rawBlock", attrs: { raw } };
  }
}

function block(token: Token): JSONContent {
  switch (token.type) {
    case "paragraph":
    case "text":
      return { type: "paragraph", content: inlineOf(token) };
    case "heading": {
      const text = String(token.text ?? "");
      const anchor = ANCHOR.exec(text);
      const inline = anchor ? (marked.Lexer.lexInline(text.slice(0, anchor.index)) as unknown as Token[]) : token.tokens ?? [];
      return { type: "heading", attrs: { level: token.depth, anchor: anchor?.[1] ?? null }, content: inlines(inline, []) };
    }
    case "blockquote":
      return { type: "blockquote", content: blocks(token.tokens ?? []) };
    case "list":
      return list(token);
    case "code": {
      const fence = /^ {0,3}(`{3,}|~{3,})/.exec(token.raw)?.[1] ?? null;
      const text = String(token.text ?? "");
      return {
        type: "codeBlock",
        attrs: { language: (token.lang as string) || null, fence },
        content: text ? [{ type: "text", text }] : [],
      };
    }
    case "hr":
      return { type: "horizontalRule" };
    case "table":
      return table(token);
    default:
      return { type: "rawBlock", attrs: { raw: token.raw.replace(/\n+$/, "") } };
  }
}

function blocks(tokens: Token[]): JSONContent[] {
  return tokens.filter((t) => t.type !== "space").map(block);
}

function list(token: Token): JSONContent {
  const items = token.items as (Token & { task: boolean })[];
  if (items.some((item) => item.task)) return { type: "rawBlock", attrs: { raw: token.raw.replace(/\n+$/, "") } };
  const content = items.map((item) => ({ type: "listItem", content: blocks(item.tokens ?? []) }));
  const tight = !token.loose;
  if (token.ordered) {
    const delimiter = /^ {0,3}\d+([.)])/.exec(token.raw)?.[1] ?? ".";
    return { type: "orderedList", attrs: { start: Number(token.start) || 1, delimiter, tight }, content };
  }
  const marker = /^ {0,3}([-+*])/.exec(token.raw)?.[1] ?? "-";
  return { type: "bulletList", attrs: { marker, tight }, content };
}

function table(token: Token): JSONContent {
  const align = token.align as (string | null)[];
  const row = (cells: { tokens: Token[] }[], type: string) => ({
    type: "tableRow",
    content: cells.map((cell, i) => ({
      type,
      attrs: { align: align[i] ?? null },
      content: [{ type: "paragraph", content: inlines(cell.tokens, []) }],
    })),
  });
  const header = token.header as { tokens: Token[] }[];
  const rows = token.rows as { tokens: Token[] }[][];
  return { type: "table", content: [row(header, "tableHeader"), ...rows.map((cells) => row(cells, "tableCell"))] };
}

function inlineOf(token: Token): JSONContent[] {
  const tokens = token.tokens ?? (marked.Lexer.lexInline(String(token.text ?? "")) as unknown as Token[]);
  return inlines(tokens, []);
}

function inlines(tokens: Token[], marks: MarkJSON[]): JSONContent[] {
  const out: JSONContent[] = [];
  const withMarks = (node: JSONContent): JSONContent => (marks.length ? { ...node, marks } : node);
  for (const token of tokens) {
    switch (token.type) {
      case "text":
        if (token.tokens) out.push(...inlines(token.tokens, marks));
        else out.push(...textNodes(decodeHtmlEntities(String(token.text ?? "")), marks));
        break;
      case "escape":
        out.push(...textNodes(String(token.text ?? ""), marks));
        break;
      case "strong":
        out.push(...inlines(token.tokens ?? [], [...marks, { type: "bold" }]));
        break;
      case "em":
        out.push(...inlines(token.tokens ?? [], [...marks, { type: "italic" }]));
        break;
      case "del":
        out.push(...inlines(token.tokens ?? [], [...marks, { type: "strike" }]));
        break;
      case "codespan":
        out.push({ type: "text", text: String(token.text ?? ""), marks: [...marks, { type: "code" }] });
        break;
      case "link": {
        const href = String(token.href ?? "");
        const form = token.raw === href ? "bare" : token.raw === `<${href}>` ? "angle" : null;
        const link = { type: "link", attrs: { href, title: (token.title as string) || null, form } };
        out.push(...inlines(token.tokens ?? [], [...marks, link]));
        break;
      }
      case "image":
        out.push(withMarks({ type: "image", attrs: { src: token.href, alt: token.text || null, title: token.title || null } }));
        break;
      case "br":
        out.push(withMarks({ type: "hardBreak", attrs: { marker: token.raw.startsWith("\\") ? "\\" : token.raw.replace(/\n$/, "") } }));
        break;
      case "html":
        out.push(withMarks({ type: "rawInline", attrs: { raw: token.raw } }));
        break;
      default:
        out.push(...textNodes(token.raw, marks));
    }
  }
  return out.filter((node) => node.type !== "text" || node.text);
}

/** Text with its refs as nodes and its line breaks as soft breaks. */
function textNodes(text: string, marks: MarkJSON[]): JSONContent[] {
  const out: JSONContent[] = [];
  const push = (node: JSONContent) => out.push(marks.length ? { ...node, marks } : node);
  const lines = text.split("\n");
  lines.forEach((line, i) => {
    if (i > 0) push({ type: "softBreak" });
    let at = 0;
    for (const ref of line.matchAll(SHORTHAND)) {
      if (ref.index > at) push({ type: "text", text: line.slice(at, ref.index) });
      push({ type: "entityRef", attrs: { kind: ref[1], id: ref[2] } });
      at = ref.index + ref[0].length;
    }
    if (at < line.length) push({ type: "text", text: line.slice(at) });
  });
  return out;
}

// --- the document to Markdown --------------------------------------------------------------------------------------

/** A text's Markdown from the editor's document. */
export function toMarkdown(doc: JSONContent): string {
  const attrs = doc.attrs ?? {};
  const frontMatter = String(attrs.frontMatter ?? "");
  const nodes = (doc.content ?? []).filter((node) => !isEmpty(node));
  let out = "";
  let previous: { node: JSONContent; raw: boolean; marker: string | null } | null = null;
  for (const node of nodes) {
    const source = node.attrs?.source as BlockSource | null | undefined;
    let canon = serialiseBlock(node);
    let raw = !!source && source.canon === canon;
    // Two lists of the same kind in a row would read back as one: the second takes the other marker.
    let marker = listMarker(node);
    if (previous && marker !== null && previous.marker === marker) {
      marker = otherMarker(node, marker);
      canon = serialiseBlock({ ...node, attrs: { ...node.attrs, ...markerAttrs(node, marker) } });
      raw = false;
    }
    if (previous) out += gap(previous.node, previous.raw, node, raw);
    out += raw ? source!.raw : canon;
    previous = { node, raw, marker };
  }
  if (!previous) return frontMatter;
  return frontMatter + out + (typeof attrs.trailing === "string" ? attrs.trailing : "\n");
}

/** An empty paragraph or heading: Markdown has no way to write one, and it says nothing. */
function isEmpty(node: JSONContent): boolean {
  return (node.type === "paragraph" || node.type === "heading") && !(node.content ?? []).length;
}

/** The blank lines the source had between two blocks, when they were blocks that stood next to each other. */
function gap(before: JSONContent, beforeRaw: boolean, after: JSONContent, afterRaw: boolean): string {
  const a = before.attrs?.source as BlockSource | null | undefined;
  const b = after.attrs?.source as BlockSource | null | undefined;
  if (!a) return "\n\n";
  if ((a.gap.match(/\n/g) ?? []).length >= 2) return a.gap;
  if (beforeRaw && afterRaw && b && b.pos === a.pos + 1 && a.gap) return a.gap;
  return "\n\n";
}

function listMarker(node: JSONContent): string | null {
  if (node.type === "bulletList") return String(node.attrs?.marker ?? "-");
  if (node.type === "orderedList") return String(node.attrs?.delimiter ?? ".");
  return null;
}

function otherMarker(node: JSONContent, marker: string): string {
  if (node.type === "orderedList") return marker === "." ? ")" : ".";
  return marker === "-" ? "*" : "-";
}

function markerAttrs(node: JSONContent, marker: string) {
  return node.type === "orderedList" ? { delimiter: marker } : { marker };
}

/** The block in the editor's own style. */
export function serialiseBlock(node: JSONContent): string {
  const attrs = node.attrs ?? {};
  const content = node.content ?? [];
  switch (node.type) {
    case "paragraph":
      return escapeLineStarts(inline(content));
    case "heading": {
      let text = inline(content).replace(/\n/g, " ").trim();
      if (text.endsWith("#")) text = `${text.slice(0, -1)}\\#`;
      const anchor = attrs.anchor ? ` {#${attrs.anchor}}` : "";
      return `${"#".repeat(Number(attrs.level) || 2)} ${text}${anchor}`;
    }
    case "blockquote":
      return joinBlocks(content)
        .split("\n")
        .map((line) => (line ? `> ${line}` : ">"))
        .join("\n");
    case "bulletList":
    case "orderedList":
      return listBlock(node);
    case "codeBlock": {
      const text = content.map((child) => child.text ?? "").join("");
      let fence = String(attrs.fence ?? "```");
      const runs = text.match(new RegExp(`${fence[0] === "~" ? "~" : "`"}{3,}`, "g")) ?? [];
      while (runs.some((run) => run.length >= fence.length)) fence += fence[0];
      return `${fence}${attrs.language ?? ""}\n${text ? `${text}\n` : ""}${fence}`;
    }
    case "horizontalRule":
      return "---";
    case "table":
      return tableBlock(node);
    case "rawBlock":
      return String(attrs.raw ?? "");
    default:
      return "";
  }
}

function joinBlocks(nodes: JSONContent[]): string {
  return nodes
    .filter((node) => !isEmpty(node))
    .map(serialiseBlock)
    .join("\n\n");
}

function listBlock(node: JSONContent): string {
  const attrs = node.attrs ?? {};
  const tight = attrs.tight !== false;
  const start = Number(attrs.start ?? 1);
  return (node.content ?? [])
    .map((item, i) => {
      const marker = node.type === "orderedList" ? `${start + i}${attrs.delimiter ?? "."}` : String(attrs.marker ?? "-");
      const indent = " ".repeat(marker.length + 1);
      const children = (item.content ?? []).filter((child) => !isEmpty(child));
      const body = children
        .map((child, j) => {
          const text = serialiseBlock(child);
          if (j === 0) return text;
          const isList = child.type === "bulletList" || child.type === "orderedList";
          return (tight && isList ? "\n" : "\n\n") + text;
        })
        .join("");
      const lines = body.split("\n").map((line, j) => (j === 0 || !line ? line : indent + line));
      return `${marker}${lines[0] ? ` ${lines[0]}` : ""}${lines.length > 1 ? `\n${lines.slice(1).join("\n")}` : ""}`;
    })
    .join(tight ? "\n" : "\n\n");
}

function tableBlock(node: JSONContent): string {
  const rows = node.content ?? [];
  const cells = (row: JSONContent) =>
    (row.content ?? []).map((cell) =>
      (cell.content ?? [])
        .map((child) => inline(child.content ?? []))
        .join(" ")
        .replace(/\n/g, " ")
        .replace(/\|/g, "\\|"),
    );
  const line = (texts: string[]) => `| ${texts.join(" | ")} |`;
  if (!rows.length) return "";
  const head = rows[0];
  const separator = (head.content ?? []).map((cell) => {
    const align = cell.attrs?.align;
    return align === "left" ? ":---" : align === "right" ? "---:" : align === "center" ? ":---:" : "---";
  });
  return [line(cells(head)), line(separator), ...rows.slice(1).map((row) => line(cells(row)))].join("\n");
}

// --- inline Markdown -----------------------------------------------------------------------------------------------

/** Spaces at the edge of these marks go outside them: `**bold** text`, never `**bold **text`. */
const EXPELLED = new Set(["bold", "italic", "strike"]);
const OPEN_ORDER = ["link", "bold", "italic", "strike", "code"];

interface Segment {
  text: string;
  marks: MarkJSON[];
  /** Markdown as it is: not escaped. */
  raw: boolean;
}

function sameMark(a: MarkJSON, b: MarkJSON): boolean {
  if (a.type !== b.type) return false;
  if (a.type !== "link") return true;
  return a.attrs?.href === b.attrs?.href && (a.attrs?.title ?? null) === (b.attrs?.title ?? null);
}

const has = (marks: MarkJSON[], mark: MarkJSON) => marks.some((m) => sameMark(m, mark));

function segments(nodes: JSONContent[]): Segment[] {
  const out: Segment[] = [];
  nodes.forEach((node, i) => {
    const marks = node.marks ?? [];
    const before = nodes[i - 1]?.marks ?? [];
    const after = nodes[i + 1]?.marks ?? [];
    const keep = (neighbours: MarkJSON[][]) => marks.filter((m) => !EXPELLED.has(m.type) || neighbours.every((n) => has(n, m)));
    switch (node.type) {
      case "text": {
        const text = node.text ?? "";
        if (has(marks, { type: "code" })) {
          out.push({ text, marks, raw: false });
          break;
        }
        const lead = /^\s*/.exec(text)![0];
        if (lead.length === text.length) {
          out.push({ text, marks: keep([before, after]), raw: false });
          break;
        }
        const trail = /\s*$/.exec(text)![0];
        if (lead) out.push({ text: lead, marks: keep([before]), raw: false });
        out.push({ text: text.slice(lead.length, text.length - trail.length), marks, raw: false });
        if (trail) out.push({ text: trail, marks: keep([after]), raw: false });
        break;
      }
      case "softBreak":
        out.push({ text: "\n", marks: keep([before, after]), raw: true });
        break;
      case "hardBreak":
        out.push({ text: `${node.attrs?.marker ?? "\\"}\n`, marks: keep([before, after]), raw: true });
        break;
      case "entityRef":
        out.push({ text: `[[${node.attrs?.kind}:${node.attrs?.id}]]`, marks, raw: true });
        break;
      case "image": {
        const alt = escapeText(String(node.attrs?.alt ?? ""));
        const title = node.attrs?.title ? ` "${String(node.attrs.title).replace(/"/g, '\\"')}"` : "";
        out.push({ text: `![${alt}](${destination(String(node.attrs?.src ?? ""))}${title})`, marks, raw: true });
        break;
      }
      case "rawInline":
        out.push({ text: String(node.attrs?.raw ?? ""), marks, raw: true });
        break;
    }
  });
  return out;
}

interface Open {
  mark: MarkJSON;
  out: string;
  /** The text inside, unescaped: a bare link is written as its URL only when that is still its text. */
  plain: string;
}

function inline(nodes: JSONContent[]): string {
  const root: Open = { mark: { type: "root" }, out: "", plain: "" };
  const stack: Open[] = [root];
  const top = () => stack[stack.length - 1];
  const close = () => {
    const done = stack.pop()!;
    const parent = top();
    parent.out += wrap(done);
    parent.plain += done.plain;
  };
  for (const segment of segments(nodes)) {
    // Close what this segment doesn't have, from the innermost out.
    let keep = 1;
    while (keep < stack.length && has(segment.marks, stack[keep].mark)) keep++;
    while (stack.length > keep) close();
    const missing = segment.marks
      .filter((m) => !stack.some((open) => sameMark(open.mark, m)))
      .sort((a, b) => OPEN_ORDER.indexOf(a.type) - OPEN_ORDER.indexOf(b.type));
    for (const mark of missing) stack.push({ mark, out: "", plain: "" });
    const inCode = stack.some((open) => open.mark.type === "code");
    top().out += segment.raw || inCode ? segment.text : escapeText(segment.text);
    top().plain += segment.text;
  }
  while (stack.length > 1) close();
  return root.out;
}

function wrap({ mark, out, plain }: Open): string {
  switch (mark.type) {
    case "bold":
      return `**${out}**`;
    case "italic":
      return `*${out}*`;
    case "strike":
      return `~~${out}~~`;
    case "code": {
      const longest = Math.max(0, ...(out.match(/`+/g) ?? []).map((run) => run.length));
      const fence = "`".repeat(longest + 1);
      const pad = out.startsWith("`") || out.endsWith("`") || (/^ .*[^ ].* $/.test(out)) ? " " : "";
      return `${fence}${pad}${out}${pad}${fence}`;
    }
    case "link": {
      const href = String(mark.attrs?.href ?? "");
      if (mark.attrs?.form === "bare" && plain === href) return href;
      if (mark.attrs?.form === "angle" && plain === href) return `<${href}>`;
      const title = mark.attrs?.title ? ` "${String(mark.attrs.title).replace(/"/g, '\\"')}"` : "";
      return `[${out}](${destination(href)}${title})`;
    }
    default:
      return out;
  }
}

function destination(href: string): string {
  return /[\s<>]|\([^)]*$|^[^(]*\)/.test(href) ? `<${href.replace(/>/g, "%3E")}>` : href;
}

/** Text that reads back as itself: what would be Markdown is escaped. */
function escapeText(text: string): string {
  return text
    .replace(/[\\*`[\]~]/g, "\\$&")
    .replace(/_/g, (m, at: number) => (/\w/.test(text[at - 1] ?? "") && /\w/.test(text[at + 1] ?? "") ? m : "\\_"))
    .replace(/<(?=[A-Za-z/!?])/g, "\\<")
    .replace(/&(?=#?\w+;)/g, "&amp;");
}

/** What would start a heading, a quote, a list or a rule at the start of a line is escaped. */
function escapeLineStarts(md: string): string {
  return md
    .split("\n")
    .map((line) =>
      line
        .replace(/^(#{1,6})(?=[ \t]|$)/, "\\$1")
        .replace(/^>/, "\\>")
        .replace(/^([-+])(?=[ \t]|$)/, "\\$1")
        .replace(/^(\d{1,9})([.)])(?=[ \t]|$)/, "$1\\$2")
        .replace(/^([=-])(?=[=-]*[ \t]*$)/, "\\$1"),
    )
    .join("\n");
}
