import { Bold, Eye, Heading, ImagePlus, Italic, Link, List, ListOrdered, Pencil, Quote, X } from "lucide-react";
import { useEffect, useRef, useState, type ClipboardEvent } from "react";
import { useLanguage, useT, type MessageKey } from "../i18n";
import { useMailEnabled } from "../mail/api";
import { TALK_PICTURE_TYPES } from "../play/TalkPanel";
import { renderPost } from "./markdown";

// The board's post editor (DEL-297): Markdown in a plain textarea, with buttons that wrap the selection in it (bold,
// italic, a heading, lists, a link, a quote), a preview drawn as the post will be, and the length against the post's
// limit. While the zone takes pictures, one may be picked or pasted in: it goes with the post when it is sent. Where
// the page passes `follow`, while Delve sends email, "Email me about replies" asks to follow the topic (DEL-314).

/** The longest post, in characters after stripping (the server's limit). */
export const POST_LIMIT = 20_000;

/** Words to add to the box: a quote. `n` counts them, so the same words quoted twice still arrive. */
export interface Insert {
  text: string;
  n: number;
}

export type Format = "bold" | "italic" | "heading" | "bullets" | "numbers" | "link" | "quote";

const BUTTONS: { format: Format; label: MessageKey; icon: typeof Bold }[] = [
  { format: "bold", label: "board.format.bold", icon: Bold },
  { format: "italic", label: "board.format.italic", icon: Italic },
  { format: "heading", label: "board.format.heading", icon: Heading },
  { format: "bullets", label: "board.format.bullets", icon: List },
  { format: "numbers", label: "board.format.numbers", icon: ListOrdered },
  { format: "link", label: "board.format.link", icon: Link },
  { format: "quote", label: "board.format.quote", icon: Quote },
];

const INLINE: Partial<Record<Format, string>> = { bold: "**", italic: "*" };

/** `text` with its selection `start`–`end` in `format`, and the selection after: bold and italic around it, a link
 * with it as the words (the address selected to type over), and a heading, a list or a quote over its whole lines. */
export function formatted(text: string, start: number, end: number, format: Format): { text: string; start: number; end: number } {
  const marker = INLINE[format];
  if (marker) {
    const words = text.slice(start, end);
    const next = text.slice(0, start) + marker + words + marker + text.slice(end);
    return { text: next, start: start + marker.length, end: end + marker.length };
  }
  if (format === "link") {
    const address = "https://";
    const piece = `[${text.slice(start, end)}](${address})`;
    const at = start + piece.length - address.length - 1;
    return { text: text.slice(0, start) + piece + text.slice(end), start: at, end: at + address.length };
  }
  const from = text.lastIndexOf("\n", start - 1) + 1;
  const stop = text.indexOf("\n", end);
  const to = stop === -1 ? text.length : stop;
  const lines = text.slice(from, to).split("\n");
  const prefix = (n: number) => (format === "heading" ? "## " : format === "bullets" ? "- " : format === "numbers" ? `${n + 1}. ` : "> ");
  const block = lines.map((line, n) => prefix(n) + line).join("\n");
  return { text: text.slice(0, from) + block + text.slice(to), start: from, end: from + block.length };
}

export default function PostEditor({
  initial = "",
  onSubmit,
  pictures,
  busy,
  insert,
  submitLabel,
  onCancel,
  label,
  follow,
}: {
  initial?: string;
  onSubmit: (text: string, picture: File | null) => void;
  /** The zone takes pictures: one may be picked or pasted in. */
  pictures: boolean;
  busy: boolean;
  insert?: Insert;
  /** The send button's words: Post unless given. */
  submitLabel?: string;
  onCancel?: () => void;
  /** The box's name for a screen reader. */
  label?: string;
  /** "Email me about replies", shown while Delve sends email. */
  follow?: { checked: boolean; onChange(value: boolean): void };
}) {
  const t = useT();
  const language = useLanguage();
  const [text, setTextState] = useState(initial);
  const now = useRef(initial);
  const setText = (value: string) => {
    now.current = value;
    setTextState(value);
  };
  const [picture, setPicture] = useState<File | null>(null);
  const [preview, setPreview] = useState(false);
  const box = useRef<HTMLTextAreaElement>(null);
  const length = text.trim().length;
  const over = length > POST_LIMIT;

  const select = (start: number, end: number) =>
    requestAnimationFrame(() => {
      const el = box.current;
      if (!el) return;
      el.focus();
      el.setSelectionRange(start, end);
    });

  // A quote goes at the end of the box, with the cursor after it. The insert the editor was made with is no news.
  const seen = useRef(insert?.n);
  useEffect(() => {
    if (!insert || insert.n === seen.current) return;
    seen.current = insert.n;
    const base = now.current.trimEnd();
    const next = base ? `${base}\n\n${insert.text}` : insert.text;
    setText(next);
    setPreview(false);
    select(next.length, next.length);
  }, [insert]);

  function format(which: Format) {
    const el = box.current;
    const start = el ? el.selectionStart : now.current.length;
    const end = el ? el.selectionEnd : start;
    const done = formatted(now.current, start, end, which);
    setText(done.text);
    select(done.start, done.end);
  }

  function onPaste(e: ClipboardEvent<HTMLTextAreaElement>) {
    // A picture on the clipboard goes with the post, while the zone takes them; words paste as words.
    const pasted = pictures && [...(e.clipboardData?.files ?? [])].find((f) => f.type.startsWith("image/"));
    if (!pasted) return;
    e.preventDefault();
    setPicture(pasted);
  }

  const send = () => {
    if (!length || over || busy) return;
    onSubmit(text.trim(), pictures ? picture : null);
  };

  return (
    <form
      className="board-editor"
      onSubmit={(e) => {
        e.preventDefault();
        send();
      }}
    >
      <div className="board-editor-tools" role="toolbar" aria-label={t("board.format")}>
        {BUTTONS.map(({ format: which, label: name, icon: Icon }) => (
          <button key={which} type="button" className="icon" title={t(name)} aria-label={t(name)} disabled={preview} onClick={() => format(which)}>
            <Icon size={16} aria-hidden="true" />
          </button>
        ))}
        {pictures && (
          <label className="board-editor-picture" title={t("board.addPicture")}>
            <ImagePlus size={16} aria-hidden="true" />
            <input
              type="file"
              className="visually-hidden"
              accept={TALK_PICTURE_TYPES.join(",")}
              aria-label={t("board.addPicture")}
              onChange={(e) => {
                const file = e.target.files?.[0];
                e.target.value = "";
                if (file) setPicture(file);
              }}
            />
          </label>
        )}
        <button type="button" className="board-editor-preview" aria-pressed={preview} onClick={() => setPreview(!preview)}>
          {preview ? <Pencil size={16} aria-hidden="true" /> : <Eye size={16} aria-hidden="true" />}
          <span>{t(preview ? "board.compose" : "board.preview")}</span>
        </button>
      </div>
      {preview ? (
        <div className="board-text board-editor-shown" data-testid="board-preview" dangerouslySetInnerHTML={{ __html: renderPost(text) }} />
      ) : (
        <textarea
          ref={box}
          value={text}
          aria-label={label ?? t("board.yourPost")}
          placeholder={t("board.placeholder")}
          onChange={(e) => setText(e.target.value)}
          onPaste={onPaste}
        />
      )}
      {pictures && picture && (
        <p className="board-editor-chosen">
          <span>{t("board.pictureChosen", { name: picture.name || t("board.pastedPicture") })}</span>
          <button type="button" className="icon" aria-label={t("board.dropPicture")} title={t("board.dropPicture")} onClick={() => setPicture(null)}>
            <X size={14} aria-hidden="true" />
          </button>
        </p>
      )}
      <div className="board-editor-foot">
        <span className={over ? "composer-count over" : "composer-count"} data-testid="board-count">
          {t("board.count", { count: length.toLocaleString(language), limit: POST_LIMIT.toLocaleString(language) })}
        </span>
        {follow && <FollowBox {...follow} />}
        {onCancel && (
          <button type="button" onClick={onCancel} disabled={busy}>
            {t("board.cancel")}
          </button>
        )}
        <button type="submit" className="primary" disabled={!length || over || busy}>
          {submitLabel ?? t("board.post")}
        </button>
      </div>
    </form>
  );
}

/** "Email me about replies", while Delve sends email (asked only where the page offers following). */
function FollowBox({ checked, onChange }: { checked: boolean; onChange(value: boolean): void }) {
  const t = useT();
  if (!useMailEnabled()) return null;
  return (
    <label className="check board-editor-follow">
      <input type="checkbox" checked={checked} onChange={(e) => onChange(e.target.checked)} />
      <span>{t("board.emailMe")}</span>
    </label>
  );
}
