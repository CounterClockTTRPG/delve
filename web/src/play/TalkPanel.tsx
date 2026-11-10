import { ChevronDown, ChevronUp, Coffee, Hand, ImagePlus, Maximize2, Minimize2 } from "lucide-react";
import { useEffect, useLayoutEffect, useRef, useState, type KeyboardEvent, type ReactNode } from "react";
import Lightbox from "../components/Lightbox";
import { useLanguage, useT } from "../i18n";
import { TableAvatar, talkColourStyle, talkFaces } from "../profile/ProfileCard";
import type { COLOURS } from "../profile/api";
import type { AbsentChoice, RaisedHand, Seat, StoryEntry } from "./api";
import { COUNT_FROM, LIMITS } from "./limits";
import { renderMarkdown } from "./markdown";
import type { TypingState } from "./SeatIndicators";
import { Marks, shortWhen, shownText } from "./Story";
import "./talk.css";

/** The pictures a seat may paste into table talk (DEL-294), as the server takes them. */
export const TALK_PICTURE_TYPES = ["image/png", "image/jpeg", "image/webp", "image/gif"];

/** The table talk's emoji (the owner's bonus): faces and hands, then the table's own. */
export const EMOJI = ["😀", "😂", "😅", "😉", "😍", "🤔", "😬", "😱", "😢", "😡", "👍", "👎", "👏", "🙏", "🎲", "⚔️", "🛡️", "🏹", "🧙", "🐉", "🍺", "💰", "🔥", "💀"];
/** The box grows with its text up to this height (px), then scrolls. */
const MAX_TEXT_PX = 160;
const TYPING_EVERY_MS = 3000;
const IDLE_AFTER_MS = 5000;
/** Within this many pixels of the bottom, the reader is at the newest line, and the talk follows new lines. */
const AT_THE_END_PX = 48;
/** Scrolled this close to its top, the talk loads its earlier lines. */
const AT_THE_TOP_PX = 40;
/** A raised hand's point takes at most this many characters, as the server does. */
export const POINT_CHARS = 200;

/** Raising and lowering this seat's hand, from the talk's header (DEL-199). */
export interface HandControl {
  /** This seat's hand, when it is up. */
  mine: RaisedHand | undefined;
  onRaise: (point: string | null) => void;
  onLower: () => void;
  busy?: boolean;
}

/** Stepping away mid-session (DEL-224), from the talk's header: shown while the session is under way, for a seat that
 * plays. Once away, the line by the Act box has I'm back. */
export interface AwayControl {
  away: boolean;
  onStepAway: (part: AbsentChoice | null) => void;
  busy?: boolean;
}

const PARTS: (AbsentChoice | null)[] = [null, "in_character", "hold_back", "out"];

type Insert = { text: string; n: number };

/**
 * Table talk, in one place (DEL-199): at the foot of the side column on the desktop, the Table screen on a phone,
 * with its own box, so the box under the story only ever speaks to the DM. What the seats say to each other,
 * observers included, oldest first, in the seat's language when translated (spec §7.3); the DM never acts on it. A
 * shared Ask the DM answer shows under its question, clipped to three lines until "Show all" (plan 7 Task 18). Each
 * line has Quote, which puts it at the top of the box. The header shows who is at the table and holds Raise hand
 * (`hand`), Step away (`away`), Widen or Narrow (`onWiden`, the desktop's) and Fold (`foldable`): folded, the talk is
 * one line that says how many lines came since and the newest. The talk opens at the newest line and follows new ones while the reader
 * is there, as chat does; a reader scrolled up stays put. Scrolled to its top, it loads its earlier lines (`hasMore`,
 * `onLoadEarlier`, DEL-219), and Load earlier does it by hand; the lines in view stay where they are.
 */
export default function TalkPanel({
  entries,
  mySeatId,
  seats = [],
  typing = {},
  onTalk,
  talking = false,
  error = null,
  onTyping,
  giveBack = null,
  hand,
  away,
  wide = false,
  onWiden,
  foldable = false,
  hasMore = false,
  loadingEarlier = false,
  onLoadEarlier,
  pictureUrl,
  onPicture,
  onTakeDown,
  mayTakeDown,
}: {
  entries: StoryEntry[];
  mySeatId: string | null;
  seats?: Seat[];
  typing?: Record<string, TypingState>;
  /** Given for a seat that may talk: the box below the talk. */
  onTalk?: (text: string) => void;
  talking?: boolean;
  error?: string | null;
  /** Given when others are at the table: they see the seat typing. */
  onTyping?: (state: TypingState) => void;
  /** Words the server refused, back in the box; `n` tells one from the next. */
  giveBack?: Insert | null;
  hand?: HandControl;
  away?: AwayControl;
  /** The talk has the side column's width: before a session and on a break. */
  wide?: boolean;
  onWiden?: () => void;
  foldable?: boolean;
  /** The talk has lines before its first: `onLoadEarlier` brings them. */
  hasMore?: boolean;
  loadingEarlier?: boolean;
  onLoadEarlier?: () => void;
  /** Where a pasted picture of the talk is served, by its entry (DEL-294). */
  pictureUrl?: (entryId: string) => string;
  /** Given while the seat may paste pictures: a picture pasted into the box, or picked, goes to the table. */
  onPicture?: (file: File) => void;
  /** Take a pasted picture down, for the lines `mayTakeDown` says this seat may. */
  onTakeDown?: (entryId: string) => void;
  mayTakeDown?: (entry: StoryEntry) => boolean;
}) {
  const t = useT();
  const [folded, setFolded] = useState(false);
  const [insert, setInsert] = useState<Insert | null>(null);
  useEffect(() => {
    if (giveBack) setInsert((last) => ({ text: giveBack.text, n: (last?.n ?? 0) + 1 }));
  }, [giveBack]);
  const quote = (text: string) => setInsert((last) => ({ text, n: (last?.n ?? 0) + 1 }));
  // The lines heard while folded, from the others: the folded line counts them.
  const seen = useRef<Set<string>>(new Set());
  const fresh = folded ? entries.filter((e) => !seen.current.has(e.id) && e.payload.seat_id !== mySeatId) : [];
  const typingNames = seats.filter((s) => s.id !== mySeatId && typing[s.id] === "typing").map((s) => s.name);

  // Land at the newest line, and follow the talk as it grows, while the reader is at the bottom.
  const box = useRef<HTMLOListElement>(null);
  const atTheEnd = useRef(true);
  const newest = entries.at(-1);
  // Earlier lines come in above: the reader stays on the lines they were reading.
  const firstId = entries[0]?.id;
  const height = useRef(0);
  const earlierFor = useRef<string | undefined>(undefined);
  useLayoutEffect(() => {
    const talk = box.current;
    if (!talk) return;
    if (earlierFor.current !== undefined && earlierFor.current !== firstId) talk.scrollTop += talk.scrollHeight - height.current;
    earlierFor.current = undefined;
    if (atTheEnd.current) talk.scrollTop = talk.scrollHeight;
  }, [entries.length, newest?.id, newest?.translation?.status, folded, wide, firstId]);
  function earlier() {
    if (!onLoadEarlier || !hasMore || loadingEarlier) return;
    height.current = box.current?.scrollHeight ?? 0;
    earlierFor.current = firstId;
    onLoadEarlier();
  }
  function scrolled() {
    const talk = box.current;
    if (!talk) return;
    atTheEnd.current = talk.scrollHeight - talk.scrollTop - talk.clientHeight <= AT_THE_END_PX;
    if (talk.scrollTop <= AT_THE_TOP_PX) earlier();
  }

  function fold() {
    seen.current = new Set(entries.map((e) => e.id));
    setFolded(true);
  }

  if (folded) {
    const last = fresh.at(-1) ?? newest;
    const lastWords = last ? split(shownText(last).text).own || (last.payload.picture ? "🖼" : "") : "";
    const who = last ? (last.payload.seat_id === mySeatId ? t("play.you") : (last.payload.name ?? "")) : "";
    return (
      <section className="talk-panel folded" data-testid="talk-panel" data-tour="talk" aria-label={t("play.talk")}>
        <button type="button" className="talk-unfold" data-testid="talk-unfold" aria-expanded="false" onClick={() => setFolded(false)}>
          <span className="talk-title">{t("play.talk")}</span>
          {fresh.length > 0 && (
            <span className="talk-new" data-testid="talk-new">
              {t("play.talkNew", { n: String(fresh.length) })}
            </span>
          )}
          {last && (
            <span className="talk-newest">
              {who}: {lastWords}
            </span>
          )}
          <ChevronUp size={16} aria-hidden="true" />
          <span className="visually-hidden">{t("play.talkUnfold")}</span>
        </button>
      </section>
    );
  }

  const { face, colour } = talkFaces(seats, 26);
  return (
    <section className={wide ? "talk-panel wide" : "talk-panel"} data-testid="talk-panel" data-tour="talk" aria-labelledby="talk-title">
      <header className="talk-head">
        <h2 id="talk-title">{t("play.talk")}</h2>
        <ul className="talk-faces" aria-label={t("play.atTheTable")}>
          {seats.map((seat) => (
            <li key={seat.id} className={seat.present ? undefined : "away"} title={seat.id === mySeatId ? t("play.you") : seat.name}>
              <TableAvatar profile={seat.profile} size={20} name={seat.name} />
            </li>
          ))}
        </ul>
        <span className="talk-head-tools">
          {hand && <RaiseHand hand={hand} />}
          {away && !away.away && <StepAway away={away} />}
          {onWiden && (
            <button type="button" className="icon-button" data-testid="talk-widen" onClick={onWiden}
              aria-label={t(wide ? "play.talkNarrow" : "play.talkWiden")} title={t(wide ? "play.talkNarrow" : "play.talkWiden")}>
              {wide ? <Minimize2 size={16} aria-hidden="true" /> : <Maximize2 size={16} aria-hidden="true" />}
            </button>
          )}
          {foldable && (
            <button type="button" className="icon-button" data-testid="talk-fold" onClick={fold}
              aria-expanded="true" aria-label={t("play.talkFold")} title={t("play.talkFold")}>
              <ChevronDown size={16} aria-hidden="true" />
            </button>
          )}
        </span>
      </header>
      <ol className="talk-list" ref={box} onScroll={scrolled} aria-label={t("play.talk")} tabIndex={0}>
        {hasMore && onLoadEarlier && (
          <li className="talk-earlier">
            <button type="button" className="link-button" data-testid="talk-earlier" disabled={loadingEarlier} onClick={earlier}>
              {t("play.loadEarlier")}
            </button>
          </li>
        )}
        {entries.length === 0 && <li className="placeholder">{t("play.noTalk")}</li>}
        <TalkList
          entries={entries}
          mySeatId={mySeatId}
          face={face}
          colour={colour}
          onQuote={onTalk ? quote : undefined}
          pictureUrl={pictureUrl}
          onTakeDown={onTakeDown}
          mayTakeDown={mayTakeDown}
        />
      </ol>
      {onTalk && (
        <TalkBox onTalk={onTalk} talking={talking} error={error} onTyping={onTyping} insert={insert} typingNames={typingNames}
          onPicture={onPicture} />
      )}
    </section>
  );
}

/** The talk's own box: Enter sends to the table, Shift-Enter starts a new line; emoji beside it. */
function TalkBox({
  onTalk,
  talking,
  error,
  onTyping,
  insert,
  typingNames,
  onPicture,
}: {
  onTalk: (text: string) => void;
  talking: boolean;
  error: string | null;
  onTyping?: (state: TypingState) => void;
  insert: Insert | null;
  typingNames: string[];
  onPicture?: (file: File) => void;
}) {
  const t = useT();
  const [text, setTextState] = useState("");
  const now = useRef("");
  const setText = (value: string) => {
    now.current = value;
    setTextState(value);
  };
  const box = useRef<HTMLTextAreaElement>(null);
  const lastTyping = useRef(0);
  const idle = useRef<ReturnType<typeof setTimeout> | null>(null);
  const words = text.trim();
  const limit = LIMITS.talk;

  useLayoutEffect(() => {
    const el = box.current;
    if (!el) return;
    el.style.height = "auto";
    // An empty box is one line, however its placeholder wraps.
    if (text && el.scrollHeight > el.clientHeight) el.style.height = `${Math.min(el.scrollHeight + 2, MAX_TEXT_PX)}px`;
  }, [text]);

  // The box going (the screen changed, the panel closed) while its words were being typed says idle, or the others
  // would see this seat typing until their TTL ran out.
  const typingTo = useRef(onTyping);
  useEffect(() => {
    typingTo.current = onTyping;
  }, [onTyping]);
  useEffect(
    () => () => {
      if (idle.current) clearTimeout(idle.current);
      if (lastTyping.current) typingTo.current?.("idle");
    },
    [],
  );

  // A quoted line (Quote) or words given back go at the top of the box, with the cursor after them.
  useEffect(() => {
    if (!insert) return;
    const base = now.current.trim();
    const next = base ? `${insert.text}\n${base}` : insert.text;
    setText(next);
    requestAnimationFrame(() => {
      const el = box.current;
      if (!el) return;
      el.focus();
      el.setSelectionRange(next.length, next.length);
    });
  }, [insert]);

  function stopTyping() {
    if (idle.current) clearTimeout(idle.current);
    idle.current = null;
    if (lastTyping.current) onTyping?.("idle");
    lastTyping.current = 0;
  }

  function change(value: string) {
    setText(value);
    if (!onTyping) return;
    const at = Date.now();
    if (at - lastTyping.current >= TYPING_EVERY_MS) {
      onTyping("typing");
      lastTyping.current = at;
    }
    if (idle.current) clearTimeout(idle.current);
    idle.current = setTimeout(stopTyping, IDLE_AFTER_MS);
  }

  function put(piece: string) {
    const el = box.current;
    const at = el ? el.selectionStart : now.current.length;
    const end = el ? el.selectionEnd : at;
    change(now.current.slice(0, at) + piece + now.current.slice(end));
    requestAnimationFrame(() => {
      if (!el) return;
      el.focus();
      el.setSelectionRange(at + piece.length, at + piece.length);
    });
  }

  function send() {
    if (!words || talking || words.length > limit) return;
    onTalk(words);
    setText("");
    stopTyping();
  }

  function onKeyDown(e: KeyboardEvent<HTMLTextAreaElement>) {
    if (e.key !== "Enter" || e.shiftKey) return;
    e.preventDefault();
    send();
  }

  return (
    <form
      className="talk-box"
      data-testid="talk-box"
      onSubmit={(e) => {
        e.preventDefault();
        send();
      }}
    >
      <p className="talk-typing" aria-live="polite">
        {typingNames.length > 0 && t("play.talkTyping", { who: typingNames.join(", ") })}
      </p>
      <div className="talk-box-row">
        <label className="visually-hidden" htmlFor="talk-text">
          {t("play.channelTalk")}
        </label>
        <textarea
          id="talk-text"
          ref={box}
          rows={1}
          maxLength={limit}
          value={text}
          placeholder={t("play.talkPlaceholder")}
          onChange={(e) => change(e.target.value)}
          onKeyDown={onKeyDown}
          onPaste={(e) => {
            // A picture on the clipboard goes to the table as it is; words paste as words.
            const picture = onPicture && [...(e.clipboardData?.files ?? [])].find((f) => f.type.startsWith("image/"));
            if (!picture) return;
            e.preventDefault();
            onPicture(picture);
          }}
        />
        {onPicture && (
          <label className="talk-picture" title={t("play.talkPicture")}>
            <ImagePlus size={16} aria-hidden="true" />
            <input
              type="file"
              className="visually-hidden"
              accept={TALK_PICTURE_TYPES.join(",")}
              aria-label={t("play.talkPicture")}
              onChange={(e) => {
                const file = e.target.files?.[0];
                e.target.value = "";
                if (file) onPicture(file);
              }}
            />
          </label>
        )}
        <EmojiPicker onPick={put} />
        <button type="submit" className="talk-send" data-testid="talk" disabled={!words || talking || words.length > limit}>
          {t("play.send")}
        </button>
      </div>
      {text.length >= limit * COUNT_FROM && (
        <span className={words.length <= limit ? "composer-count" : "composer-count over"} data-testid="talk-count" aria-live="polite">
          {text.length} / {limit}
        </span>
      )}
      {error && (
        <p className="notice error" role="alert">
          {error}
        </p>
      )}
    </form>
  );
}

/** Raise hand, with the point to make before anyone acts if the seat gives one; Lower hand once it is up. */
function RaiseHand({ hand }: { hand: HandControl }) {
  const t = useT();
  const [asking, setAsking] = useState(false);
  const [point, setPoint] = useState("");
  const here = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!asking) return;
    const away = (e: MouseEvent) => {
      if (here.current && !here.current.contains(e.target as Node)) setAsking(false);
    };
    document.addEventListener("mousedown", away);
    return () => document.removeEventListener("mousedown", away);
  }, [asking]);

  if (hand.mine) {
    return (
      <button type="button" className="raise-hand up" data-testid="lower-hand" aria-pressed="true" disabled={hand.busy} onClick={hand.onLower}>
        <Hand size={15} aria-hidden="true" /> <span className="raise-hand-label">{t("play.lowerHand")}</span>
      </button>
    );
  }
  return (
    <div className="raise-hand-wrap" ref={here}>
      <button type="button" className="raise-hand" data-testid="raise-hand" aria-pressed="false" aria-expanded={asking}
        disabled={hand.busy} onClick={() => setAsking(!asking)}>
        <Hand size={15} aria-hidden="true" /> <span className="raise-hand-label">{t("play.raiseHand")}</span>
      </button>
      {asking && (
        <form
          className="popover raise-hand-form"
          data-testid="raise-hand-form"
          onSubmit={(e) => {
            e.preventDefault();
            hand.onRaise(point.trim() || null);
            setPoint("");
            setAsking(false);
          }}
          onKeyDown={(e) => {
            if (e.key === "Escape") {
              e.stopPropagation();
              setAsking(false);
            }
          }}
        >
          <label htmlFor="hand-point">{t("play.handPoint")}</label>
          <input id="hand-point" autoFocus maxLength={POINT_CHARS} value={point} onChange={(e) => setPoint(e.target.value)}
            placeholder={t("play.handPointPlaceholder")} />
          <button type="submit" className="primary" data-testid="raise-hand-confirm">
            {t("play.raiseHand")}
          </button>
        </form>
      )}
    </div>
  );
}

/** Step away, with the part this seat's characters take meanwhile: the table's setting, or one of the host's choices.
 * Choosing one steps away. */
function StepAway({ away }: { away: AwayControl }) {
  const t = useT();
  const [asking, setAsking] = useState(false);
  const here = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!asking) return;
    const outside = (e: MouseEvent) => {
      if (here.current && !here.current.contains(e.target as Node)) setAsking(false);
    };
    document.addEventListener("mousedown", outside);
    return () => document.removeEventListener("mousedown", outside);
  }, [asking]);

  return (
    <div className="step-away-wrap" ref={here}>
      <button type="button" className="raise-hand" data-testid="step-away" aria-expanded={asking} disabled={away.busy}
        onClick={() => setAsking(!asking)}>
        <Coffee size={15} aria-hidden="true" /> <span className="raise-hand-label">{t("play.stepAway")}</span>
      </button>
      {asking && (
        <div
          className="popover raise-hand-form step-away-form"
          data-testid="step-away-form"
          role="group"
          aria-labelledby="step-away-hint"
          onKeyDown={(e) => {
            if (e.key === "Escape") {
              e.stopPropagation();
              setAsking(false);
            }
          }}
        >
          <p id="step-away-hint">{t("play.stepAwayHint")}</p>
          {PARTS.map((choice) => (
            <button
              key={choice ?? "table"}
              type="button"
              className="step-away-part"
              data-testid={`step-away-${choice ?? "table"}`}
              onClick={() => {
                away.onStepAway(choice);
                setAsking(false);
              }}
            >
              {t(`play.part.${choice ?? "table"}`)}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}

/** Lines a speaker says within this long of their last one join it, under one name and face, as a chat does. */
const RUN_MS = 5 * 60 * 1000;

/** A talk line's words, as a quote of them begins a reply: `> Name: line`, each line quoted. */
export function quoteOf(name: string, text: string): string {
  return text
    .split("\n")
    .filter((line) => line.trim() && !line.startsWith("> "))
    .map((line, i) => `> ${i ? "" : `${name}: `}${line}`)
    .join("\n");
}

/** A talk line's words: the `> ` lines it starts with (a quote of another line) apart from its own. */
function split(text: string): { quote: string[]; own: string } {
  const lines = text.split("\n");
  let n = 0;
  while (n < lines.length && lines[n].startsWith("> ")) n++;
  return { quote: lines.slice(0, n).map((l) => l.slice(2)), own: lines.slice(n).join("\n").trim() };
}

/**
 * The lines of table talk (DEL-199): flat, each under its speaker's face and name in their colour, this seat's own as
 * "You" on the same side as the others, since the side column is narrow. A speaker's lines within a few minutes of
 * each other run together under one name, face and time; a later line of a run shows its time on hover. A line that
 * quotes another (Quote, `> Name: words`) shows the quoted words set in, apart from its own. With `onQuote`, each line
 * has Quote, on hover or keyboard focus. Each line carries its speaker's `data-seat`; `face`, when given, draws the
 * speaker's avatar, and `colour` names their colour.
 */
export function TalkList({
  entries,
  mySeatId,
  face,
  colour,
  onQuote,
  pictureUrl,
  onTakeDown,
  mayTakeDown,
}: {
  entries: StoryEntry[];
  mySeatId: string | null;
  face?: (seatId: string | undefined) => ReactNode;
  colour?: (seatId: string | undefined) => keyof typeof COLOURS | undefined;
  /** Quote this line: its words as `quoteOf` makes them. */
  onQuote?: (quote: string) => void;
  /** Where a pasted picture is served, by its entry (DEL-294); without it, pictures don't show. */
  pictureUrl?: (entryId: string) => string;
  onTakeDown?: (entryId: string) => void;
  mayTakeDown?: (entry: StoryEntry) => boolean;
}) {
  const t = useT();
  const language = useLanguage();
  let previous: StoryEntry | null = null;
  return (
    <>
      {entries.map((entry) => {
        if (entry.kind !== "talk") return null;
        const { text, mark } = shownText(entry);
        const { seat_id, name } = entry.payload;
        const translated = entry.translation?.status === "done" ? entry.translation.answer : undefined;
        const answer = translated || entry.payload.answer;
        const tint = colour?.(seat_id);
        const run =
          previous !== null &&
          previous.payload.seat_id === seat_id &&
          Date.parse(entry.at) - Date.parse(previous.at) < RUN_MS;
        previous = entry;
        const who = seat_id === mySeatId ? t("play.you") : (name ?? "");
        const when = shortWhen(entry.at, language);
        const { quote, own } = split(text);
        const classes = ["talk", seat_id === mySeatId && "mine", run && "run"].filter(Boolean).join(" ");
        return (
          <li key={entry.id} className={classes} data-seat={seat_id} data-colour={tint} style={talkColourStyle(tint)}>
            {!run && <span className="talk-face">{face?.(seat_id)}</span>}
            <div className="talk-body">
              {!run && (
                <div className="talk-line-head">
                  <span className="talk-who">{who}</span>
                  <time className="talk-time" dateTime={entry.at} title={new Date(entry.at).toLocaleString(language)}>
                    {when}
                  </time>
                </div>
              )}
              <Marks entry={entry} mark={mark} />
              {quote.length > 0 && (
                <blockquote className="talk-quote" data-testid="talk-quote">
                  {quote.join("\n")}
                </blockquote>
              )}
              {own && <p className="talk-text">{own}</p>}
              {entry.payload.picture && pictureUrl && (
                <TalkPicture url={pictureUrl(entry.id)} who={name ?? ""} picture={entry.payload.picture}
                  onTakeDown={onTakeDown && mayTakeDown?.(entry) ? () => onTakeDown(entry.id) : undefined} />
              )}
              {entry.payload.picture_removed && <p className="talk-text talk-picture-gone">{t("play.talkPictureGone")}</p>}
              {answer && (
                <div className="talk-answer">
                  <span className="talk-answer-label">{t("play.dmAnswered")}</span>
                  <SharedAnswer answer={answer} />
                </div>
              )}
            </div>
            <span className="talk-tools">
              {run && (
                <time className="talk-time" dateTime={entry.at} title={new Date(entry.at).toLocaleString(language)}>
                  {when}
                </time>
              )}
              {onQuote && (
                <button type="button" className="talk-quote-button" data-testid="talk-quote-button"
                  aria-label={t("play.quoteLine", { who })} title={t("play.quoteLine", { who })}
                  onClick={() => onQuote(quoteOf(who, text))}>
                  {t("play.quote")}
                </button>
              )}
            </span>
          </li>
        );
      })}
    </>
  );
}

/** A picture pasted into the talk (DEL-294): small in the line, enlarged on a click; Take down for who may. */
function TalkPicture({
  url,
  who,
  picture,
  onTakeDown,
}: {
  url: string;
  who: string;
  picture: { width?: number; height?: number };
  onTakeDown?: () => void;
}) {
  const t = useT();
  const alt = t("play.talkPictureOf", { who });
  return (
    <div className="talk-picture-line">
      <Lightbox label={t("play.enlarge", { name: alt })} title={alt} className="image-zoom"
        big={<img className="lightbox-image" src={url} alt={alt} />}>
        <img src={url} alt={alt} width={picture.width} height={picture.height} loading="lazy" />
      </Lightbox>
      {onTakeDown && (
        <button type="button" className="link-button" onClick={onTakeDown}>
          {t("play.talkPictureTakeDown", { who })}
        </button>
      )}
    </div>
  );
}

/** An answer this long, or of more than one line, may not fit in three lines. */
const LONG_ANSWER = 160;

function SharedAnswer({ answer }: { answer: string }) {
  const t = useT();
  const long = answer.length > LONG_ANSWER || answer.trim().includes("\n");
  const [all, setAll] = useState(!long);
  return (
    <>
      <div className={all ? "talk-answer-text" : "talk-answer-text clipped"} dangerouslySetInnerHTML={{ __html: renderMarkdown(answer) }} />
      {!all && (
        <button type="button" className="link-button" onClick={() => setAll(true)}>
          {t("play.showAll")}
        </button>
      )}
    </>
  );
}

/** A button that opens the table talk's emoji, one click each to put it in the box. */
function EmojiPicker({ onPick }: { onPick: (emoji: string) => void }) {
  const t = useT();
  const [open, setOpen] = useState(false);
  const here = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    const away = (e: MouseEvent) => {
      if (here.current && !here.current.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener("mousedown", away);
    return () => document.removeEventListener("mousedown", away);
  }, [open]);

  return (
    <div className="emoji-picker" ref={here}>
      <button type="button" data-testid="emoji" aria-haspopup="true" aria-expanded={open} aria-label={t("play.emoji")}
        title={t("play.emoji")} onClick={() => setOpen(!open)}>
        <span aria-hidden="true">🙂</span>
      </button>
      {open && (
        <div className="popover emoji-grid" role="group" aria-label={t("play.emoji")}
          onKeyDown={(e) => {
            if (e.key === "Escape") {
              e.stopPropagation();
              setOpen(false);
            }
          }}>
          {EMOJI.map((emoji) => (
            <button type="button" key={emoji} onClick={() => onPick(emoji)}>
              {emoji}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}
