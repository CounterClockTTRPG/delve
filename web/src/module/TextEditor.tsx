import { useMutation } from "@tanstack/react-query";
import { Extension, type JSONContent, type Editor as TiptapEditor } from "@tiptap/core";
import type { Node as PMNode } from "@tiptap/pm/model";
import { Plugin } from "@tiptap/pm/state";
import { Decoration, DecorationSet } from "@tiptap/pm/view";
import {
  EditorContent,
  NodeViewContent,
  NodeViewWrapper,
  ReactNodeViewRenderer,
  useEditor,
  useEditorState,
  type NodeViewProps,
} from "@tiptap/react";
import { Bold, Heading2, Heading3, Heading4, Italic, Link as LinkIcon, List, ListOrdered, Quote, Table } from "lucide-react";
import {
  createContext,
  forwardRef,
  useCallback,
  useContext,
  useEffect,
  useImperativeHandle,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from "react";
import { useBlocker, type BlockerFunction } from "react-router-dom";
import {
  NeedsToken,
  attachmentUrl,
  putText,
  type Attachment,
  type Audience,
  type ModuleSource,
  type ModuleTextDoc,
  type RoomLink,
  type SourceWarning,
  type TextSaved,
} from "../api";
import { useConfirm, usePrompt } from "../components/dialogs";
import Tip from "../components/Tip";
import { useT } from "../i18n";
import KeyChip from "./KeyChip";
import { EntityRef, ModuleHeading, fromMarkdown, headingAnchor, headingKey, moduleTextExtensions, toMarkdown } from "./MarkdownRoundTrip";
import { readAloud, type Block } from "./readAloud";

/** The format's ref kinds that name an entity, and the list each one is in. */
const ENTITY_LISTS: Record<string, string> = {
  npc: "npcs",
  encounter: "encounters",
  faction: "factions",
  quest: "quests",
  rumor: "rumors",
  secret: "secrets",
};

interface TextView {
  textId: string;
  links: RoomLink[];
  warnings: SourceWarning[];
  /** An entity's name, or undefined when the module has no such entity. */
  nameOf: (kind: string, id: string) => string | undefined;
}

// The node views (headings, refs) render inside the editor's React tree, so they read the links from here.
const TextViewContext = createContext<TextView>({ textId: "", links: [], warnings: [], nameOf: () => undefined });

function HeadingView({ node }: NodeViewProps) {
  const view = useContext(TextViewContext);
  const level = Number(node.attrs.level) || 2;
  const anchor = headingAnchor(level, node.textContent, node.attrs.anchor ?? null);
  const link = anchor ? view.links.find((l) => l.text_id === view.textId && l.anchor === anchor) : undefined;
  const warning = anchor
    ? view.warnings.find((w) => w.code === "key-without-room" && w.ref === `text:${view.textId}#${anchor}`)
    : undefined;
  return (
    <NodeViewWrapper as={`h${level}` as "h2"} className="keyed-heading">
      <NodeViewContent<"span"> as="span" />
      {link ? (
        <KeyChip label={link.label} map={link.map} />
      ) : warning ? (
        <KeyChip label={headingKey(level, node.textContent) ?? anchor!} warning={warning.message} />
      ) : null}
    </NodeViewWrapper>
  );
}

function RefView({ node }: NodeViewProps) {
  const view = useContext(TextViewContext);
  const { kind, id } = node.attrs as { kind: string; id: string };
  const isEntity = kind in ENTITY_LISTS;
  const name = isEntity ? view.nameOf(kind, id) : id;
  return (
    <NodeViewWrapper as="span" className={`ref-chip${name === undefined ? " missing" : ""}`} title={`${kind}:${id}`}>
      {name ?? id}
    </NodeViewWrapper>
  );
}

/** Read-aloud quotes (`readAloud`: every quote under a keyed heading, the leading ones under another); the editor
 * styles them so. */
const ReadAloud = Extension.create({
  name: "readAloud",
  addProseMirrorPlugins: () => [
    new Plugin({
      props: {
        decorations(state) {
          const children: { node: PMNode; offset: number }[] = [];
          state.doc.forEach((node, offset) => children.push({ node, offset }));
          const boxed = readAloud(
            children.map(({ node }): Block => {
              if (node.type.name === "heading") return { heading: { level: Number(node.attrs.level), text: node.textContent } };
              return node.type.name === "blockquote" ? { quote: true } : { other: true };
            }),
          );
          const marks = children
            .filter((_, i) => boxed[i])
            .map(({ node, offset }) => Decoration.node(offset, offset + node.nodeSize, { class: "read-aloud" }));
          return DecorationSet.create(state.doc, marks);
        },
      },
    }),
  ],
});

/** A keyed heading of the open text, for the outline: its words ("7. Dining Room") and where it starts. */
interface OutlineEntry {
  text: string;
  pos: number;
}

function keyedHeadings(doc: PMNode): OutlineEntry[] {
  const found: OutlineEntry[] = [];
  doc.descendants((node, pos) => {
    if (node.type.name !== "heading") return true;
    if (headingKey(Number(node.attrs.level), node.textContent) !== null) found.push({ text: node.textContent.trim(), pos });
    return false;
  });
  return found;
}

/** The outline of the text's keyed headings, filtered by a search: a click puts the cursor on the heading and
 * scrolls to it. Nothing shows for a text without keys. */
function Outline({ editor, edits }: { editor: TiptapEditor; edits: number }) {
  const t = useT();
  const [search, setSearch] = useState("");
  // Read again on every edit, so the outline follows the text as it is typed.
  const headings = useMemo(() => keyedHeadings(editor.state.doc), [editor, edits]);
  if (headings.length === 0) return null;
  const wanted = search.trim().toLowerCase();
  const shown = wanted ? headings.filter((h) => h.text.toLowerCase().includes(wanted)) : headings;

  function go(pos: number) {
    editor.chain().focus().setTextSelection(pos + 1).run();
    (editor.view.nodeDOM(pos) as HTMLElement | null)?.scrollIntoView?.({ block: "start" });
  }

  return (
    <nav className="text-outline" aria-label={t("text.outline")}>
      <input
        type="search"
        aria-label={t("text.outlineSearch")}
        placeholder={t("text.outlineSearch")}
        value={search}
        onChange={(e) => setSearch(e.target.value)}
      />
      <ul>
        {shown.map((h) => (
          <li key={h.pos}>
            <button type="button" onClick={() => go(h.pos)}>
              {h.text}
            </button>
          </li>
        ))}
      </ul>
    </nav>
  );
}

/** The warnings that belong to this text: its keyed headings, and the refs it makes. */
export function warningsOf(text: ModuleTextDoc, warnings: SourceWarning[]): SourceWarning[] {
  return warnings.filter((w) => {
    if (w.code === "key-without-room") return w.ref.startsWith(`text:${text.id}#`);
    if (w.code === "missing-attachment" || w.code === "missing-entity" || w.code === "missing-key") return text.markdown.includes(w.ref);
    return false;
  });
}

/** What the module page asks of the open text: Insert in text, from the attachments. */
export interface TextEditorHandle {
  insertAttachment: (attachment: Attachment) => void;
}

/** An attachment as its own paragraph: an image shows as itself, a PDF as a link to it. */
function attachmentBlock(attachment: Attachment): JSONContent {
  const src = `asset:${attachment.id}`;
  const label = attachment.description || attachment.id;
  const inline: JSONContent = attachment.type.startsWith("image/")
    ? { type: "image", attrs: { src, alt: attachment.description || null } }
    : { type: "text", text: label, marks: [{ type: "link", attrs: { href: src } }] };
  return { type: "paragraph", content: [inline] };
}

export interface TextEditorProps {
  moduleId: string;
  text: ModuleTextDoc;
  links: RoomLink[];
  attachments: Attachment[];
  /** The module's warnings; the editor lists the ones of this text. */
  warnings?: SourceWarning[];
  /** The module's entities, for the names of `[[npc:…]]` refs. */
  entities?: ModuleSource["entities"];
  /** The module's map names, for the text's map. */
  maps?: string[];
  onSaved: (saved: TextSaved) => void;
  onDirtyChange?: (dirty: boolean) => void;
}

/** How long the editor waits after a keystroke to write the text as Markdown again (DEL-172): 9 ms a keystroke at 76k
 * characters, 20 ms at 300k. Saving writes it at once. */
export const MARKDOWN_AFTER_MS = 300;

/** One module text in a light word processor. The Markdown is what it saves, and is never shown. */
const TextEditor = forwardRef<TextEditorHandle, TextEditorProps>(function TextEditor(
  { moduleId, text, links, attachments, warnings = [], entities = {}, maps = [], onSaved, onDirtyChange },
  ref,
) {
  const t = useT();
  const [title, setTitle] = useState(text.title);
  const [audience, setAudience] = useState<Audience>(text.audience);
  const [map, setMap] = useState<string | null>(text.map);
  const [markdown, setMarkdown] = useState(text.markdown);
  // Each edit, for the outline; and an edit whose Markdown isn't written yet, which is unsaved work all the same.
  const [edits, setEdits] = useState(0);
  const [unwritten, setUnwritten] = useState(false);
  const writing = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);
  useEffect(() => () => clearTimeout(writing.current), []);
  // What the editor wrote for the text as it was loaded or last saved: no change means no save.
  const baseline = useRef(text.markdown);
  const loaded = useRef(text.markdown);

  const extensions = useMemo(
    () => [
      ...moduleTextExtensions({
        assetUrl: (src) => attachmentUrl(moduleId, src.slice("asset:".length)),
        overrides: [
          ModuleHeading.extend({ addNodeView: () => ReactNodeViewRenderer(HeadingView) }),
          EntityRef.extend({ addNodeView: () => ReactNodeViewRenderer(RefView, { as: "span" }) }),
        ],
      }),
      ReadAloud,
    ],
    [moduleId],
  );
  const editor = useEditor({
    extensions,
    content: fromMarkdown(text.markdown),
    onCreate: ({ editor }) => {
      baseline.current = toMarkdown(editor.getJSON());
      setMarkdown(baseline.current);
    },
    onUpdate: ({ editor }) => {
      setEdits((n) => n + 1);
      setUnwritten(true);
      clearTimeout(writing.current);
      writing.current = setTimeout(() => {
        setMarkdown(toMarkdown(editor.getJSON()));
        setUnwritten(false);
      }, MARKDOWN_AFTER_MS);
    },
  });

  const insertAttachment = useCallback(
    (attachment: Attachment) => editor?.chain().focus().insertContent(attachmentBlock(attachment)).run(),
    [editor],
  );
  useImperativeHandle(ref, () => ({ insertAttachment }), [insertAttachment]);

  const dirty = unwritten || markdown !== baseline.current || title !== text.title || audience !== text.audience || map !== text.map;
  useEffect(() => onDirtyChange?.(dirty), [dirty, onDirtyChange]);

  // The text changed on the server (another window): take it, unless there is work here to keep.
  useEffect(() => {
    if (!editor || text.markdown === loaded.current || dirty) return;
    loaded.current = text.markdown;
    editor.commands.setContent(fromMarkdown(text.markdown), { emitUpdate: false });
    baseline.current = toMarkdown(editor.getJSON());
    setMarkdown(baseline.current);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [editor, text.markdown]);

  const save = useMutation({
    mutationFn: (md: string) => putText(moduleId, text.id, { title: title.trim() || text.title, audience, map, markdown: md }),
    onSuccess: (saved, md) => {
      baseline.current = md;
      loaded.current = saved.text.markdown;
      setMarkdown(md);
      onSaved(saved);
    },
  });
  const onSave = useCallback(() => {
    if (editor && dirty && !save.isPending) save.mutate(toMarkdown(editor.getJSON()));
  }, [editor, dirty, save]);

  // Warn before unloading the tab with unsaved changes; in-app navigation asks through the router's blocker.
  useEffect(() => {
    if (!dirty) return;
    function onBeforeUnload(e: BeforeUnloadEvent) {
      e.preventDefault();
      e.returnValue = "";
    }
    window.addEventListener("beforeunload", onBeforeUnload);
    return () => window.removeEventListener("beforeunload", onBeforeUnload);
  }, [dirty]);
  const shouldBlock = useCallback<BlockerFunction>(
    ({ currentLocation, nextLocation }) => dirty && currentLocation.pathname !== nextLocation.pathname,
    [dirty],
  );
  const blocker = useBlocker(shouldBlock);
  const confirm = useConfirm();
  const asking = useRef(false);
  useEffect(() => {
    if (blocker.state !== "blocked" || asking.current) return;
    asking.current = true;
    void confirm({ title: t("text.leaveUnsaved"), confirm: t("dialog.leave") }).then((leave) => {
      asking.current = false;
      if (leave) blocker.proceed();
      else blocker.reset();
    });
  }, [blocker, confirm, t]);

  const view = useMemo<TextView>(
    () => ({
      textId: text.id,
      links,
      warnings,
      nameOf: (kind, id) => entities[ENTITY_LISTS[kind]]?.find((record) => record.id === id)?.name,
    }),
    [text.id, links, warnings, entities],
  );
  const own = warningsOf({ ...text, markdown }, warnings);
  const failed = save.error && !(save.error instanceof NeedsToken) ? save.error : null;

  return (
    <div
      className="text-editor"
      onKeyDown={(e) => {
        if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "s") {
          e.preventDefault();
          onSave();
        }
      }}
    >
      <div className="text-meta">
        <div className="field">
          <label htmlFor="text-title">{t("text.title")}</label>
          <input id="text-title" value={title} onChange={(e) => setTitle(e.target.value)} />
        </div>
        <div className="field">
          <label htmlFor="text-audience">{t("audience.label")}</label>
          <select id="text-audience" value={audience} onChange={(e) => setAudience(e.target.value as Audience)}>
            <option value="gm">{t("audience.dm")}</option>
            <option value="player">{t("audience.player")}</option>
          </select>
        </div>
        <div className="field">
          <label htmlFor="text-map">{t("text.map")}</label>
          <select id="text-map" value={map ?? ""} onChange={(e) => setMap(e.target.value || null)}>
            <option value="">{t("text.defaultMap")}</option>
            {maps.map((name) => (
              <option key={name} value={name}>
                {name}
              </option>
            ))}
          </select>
        </div>
        <button type="button" className="primary" disabled={!dirty || save.isPending} onClick={onSave}>
          {t("text.save")}
        </button>
      </div>

      {editor && <Toolbar editor={editor} attachments={attachments} onInsert={insertAttachment} />}
      <div className="text-body">
        {editor && <Outline editor={editor} edits={edits} />}
        <TextViewContext.Provider value={view}>
          <EditorContent editor={editor} className="text-page markdown" />
        </TextViewContext.Provider>
      </div>

      {failed && (
        <p role="alert" className="notice error">
          {t("text.saveFailed", { error: failed.message })}
        </p>
      )}
      {own.length > 0 && (
        <div className="notice" role="note">
          <p>{t("text.warnings")}</p>
          <ul>
            {own.map((w) => (
              <li key={`${w.code} ${w.ref}`}>{w.message}</li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
});

export default TextEditor;

function Toolbar({
  editor,
  attachments,
  onInsert,
}: {
  editor: TiptapEditor;
  attachments: Attachment[];
  onInsert: (attachment: Attachment) => void;
}) {
  const t = useT();
  const prompt = usePrompt();
  // The buttons show what is active at the cursor, so they follow every change of the selection.
  const active = useEditorState({
    editor,
    selector: ({ editor: e }) => ({
      h2: e.isActive("heading", { level: 2 }),
      h3: e.isActive("heading", { level: 3 }),
      h4: e.isActive("heading", { level: 4 }),
      bold: e.isActive("bold"),
      italic: e.isActive("italic"),
      bulletList: e.isActive("bulletList"),
      orderedList: e.isActive("orderedList"),
      blockquote: e.isActive("blockquote"),
      link: e.isActive("link"),
    }),
  });
  const chain = () => editor.chain().focus();
  const heading = (level: number) => chain().toggleNode("heading", "paragraph", { level }).run();

  async function link() {
    const current = String(editor.getAttributes("link").href ?? "");
    const href = await prompt({ title: t("text.link"), label: t("text.linkPrompt"), initial: current, confirm: t("dialog.ok") });
    if (href === null) return;
    if (href.trim() === "") chain().extendMarkRange("link").unsetLink().run();
    else chain().extendMarkRange("link").setLink({ href: href.trim() }).run();
  }

  const button = (name: keyof typeof active | "table", label: string, icon: ReactNode, run: () => unknown) => (
    <Tip label={label}>
      <button
        type="button"
        className="icon"
        aria-label={label}
        aria-pressed={name === "table" ? undefined : active[name]}
        onMouseDown={(e) => e.preventDefault()}
        onClick={() => run()}
      >
        {icon}
      </button>
    </Tip>
  );

  return (
    <div className="toolbar text-toolbar" role="toolbar" aria-label={t("text.toolbar")}>
      {button("h2", t("text.heading2"), <Heading2 aria-hidden size={16} />, () => heading(2))}
      {button("h3", t("text.heading3"), <Heading3 aria-hidden size={16} />, () => heading(3))}
      {button("h4", t("text.heading4"), <Heading4 aria-hidden size={16} />, () => heading(4))}
      {button("bold", t("text.bold"), <Bold aria-hidden size={16} />, () => chain().toggleBold().run())}
      {button("italic", t("text.italic"), <Italic aria-hidden size={16} />, () => chain().toggleItalic().run())}
      {button("bulletList", t("text.bulletList"), <List aria-hidden size={16} />, () => chain().toggleBulletList().run())}
      {button("orderedList", t("text.orderedList"), <ListOrdered aria-hidden size={16} />, () =>
        chain().toggleOrderedList().run(),
      )}
      {button("blockquote", t("text.readAloud"), <Quote aria-hidden size={16} />, () => chain().toggleBlockquote().run())}
      {button("link", t("text.link"), <LinkIcon aria-hidden size={16} />, link)}
      {button("table", t("text.table"), <Table aria-hidden size={16} />, () =>
        chain().insertTable({ rows: 3, cols: 3, withHeaderRow: true }).run(),
      )}
      <select
        aria-label={t("text.insertAttachment")}
        value=""
        disabled={attachments.length === 0}
        onChange={(e) => {
          const attachment = attachments.find((a) => a.id === e.target.value);
          if (attachment) onInsert(attachment);
        }}
      >
        <option value="">{t("text.insertAttachment")}</option>
        {attachments.map((a) => (
          <option key={a.id} value={a.id}>
            {a.description || a.id}
          </option>
        ))}
      </select>
    </div>
  );
}
