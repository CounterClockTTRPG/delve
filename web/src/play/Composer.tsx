import { ImagePlus } from "lucide-react";
import { useEffect, useLayoutEffect, useRef, useState, type KeyboardEvent, type ReactNode } from "react";
import { useT } from "../i18n";
import type { TypingState } from "./SeatIndicators";
import type { Departure } from "./api";
import { COUNT_FROM, LIMITS } from "./limits";

/** An act put back into the Composer (Change): its words and its private flag; `n` tells one Change from the next. */
export interface Refill {
  text: string;
  private: boolean;
  n: number;
  /** The mode the words go back to: "ask" for a question the server refused (DEL-153); "own" otherwise. */
  mode?: "own" | "ask";
  /** Words the server refused: they go back before whatever was typed since, so nothing is lost (DEL-153). */
  refused?: boolean;
}

const TYPING_EVERY_MS = 3000;
/** The box grows with its text up to this height (px), then scrolls. */
const MAX_TEXT_PX = 220;
const IDLE_AFTER_MS = 5000;

/**
 * The box under the story, which speaks to the DM (spec §7.3; table talk has its own box, DEL-199). Its two modes
 * (plan 7 Task 18) say what Enter does: Act, which goes to the beat, or Ask the DM, out of band, whose answer shows in
 * the story for this seat alone; Ctrl-Enter asks in either. An observer, who doesn't act, only asks. Shift-Enter is a
 * new line. While a beat is open the seat can pass, and change its act (`refill`, from the pending acts' Change): Act
 * then replaces it. "Only the DM" makes the act private. While the DM answers, Act waits and the words stay in the
 * box, with Cancel for the host; Act waits too while `blocked` says why (the session hasn't started, a break). A
 * seat that plays more than one character picks who acts, in a menu beside the modes: the whole party or one character
 * in one click, several under "Several…". `notice` goes above the buttons (the raised hands' line).
 *
 * Who hears what is typed is shown on the box itself (the owner's report: lines went to the wrong place): the box
 * wears its channel's colour (`data-channel`) with a line above saying where Enter sends the words.
 *
 * Each channel takes as many characters as the server does (`LIMITS`, DEL-154): the box stops typing at its channel's
 * length and counts down near it, and words longer than a channel's length (typed for a longer one) are not sent on
 * it, but kept to be cut.
 *
 * At a hotseat (DEL-365) the box is the current player's (`actingAs`, with their `characters`), and nothing is for the
 * DM alone (`canPrivate`).
 */
export default function Composer({
  running,
  asking,
  error,
  canAct = true,
  canCancel = true,
  beatOpen = false,
  replacing = false,
  refill = null,
  characters: offered = [],
  onAct,
  onPass = () => {},
  onAsk,
  onCancel,
  onTyping,
  onPaint,
  painting = false,
  painted = false,
  blocked = null,
  notice = null,
  canPrivate = true,
  actingAs = null,
}: {
  running: boolean;
  asking: boolean;
  error: string | null;
  canAct?: boolean;
  canCancel?: boolean;
  beatOpen?: boolean;
  /** The seat has an act in the open beat: Act replaces it. */
  replacing?: boolean;
  refill?: Refill | null;
  /** The characters the seat acts for, by id and name; one that left the party (`departure`) is never offered. */
  characters?: { id: string; name: string; departure?: Departure | null }[];
  /** `characters` is left out when the seat acts for all of its own. */
  onAct: (text: string, characters?: string[], secret?: boolean) => void;
  onPass?: (characters?: string[]) => void;
  onAsk: (question: string) => void;
  onCancel: () => void;
  /** Given when others are at the table: they see the seat typing. */
  onTyping?: (state: TypingState) => void;
  /** Given while a scene can be painted (paid images on) for a seat that acts: Paint this scene, beside the modes. */
  onPaint?: () => void;
  painting?: boolean;
  /** The last Paint this scene was taken: the picture comes into the story when it is painted. */
  painted?: boolean;
  /** Why Act waits, when the table can't act now: the session hasn't started, or a break. */
  blocked?: string | null;
  notice?: ReactNode;
  /** Whether an act can be for the DM alone: not on a shared screen (hotseat, DEL-365). */
  canPrivate?: boolean;
  /** The hotseat player whose turn it is (DEL-365): the box asks what they do. */
  actingAs?: string | null;
}) {
  const t = useT();
  const characters = offered.filter((c) => !c.departure);
  const [text, setTextState] = useState("");
  // The words as they are now, for the effects below.
  const now = useRef("");
  const setText = (value: string) => {
    now.current = value;
    setTextState(value);
  };
  const [left, setLeft] = useState<Set<string>>(new Set());
  const [secret, setSecret] = useState(false);
  const [chosen, setMode] = useState<"own" | "ask">("own");
  const mode = canAct ? chosen : "ask";
  // While the DM answers, or while the table can't act, Act waits: the words stay in the box.
  const waiting = running || blocked !== null;
  const channel = mode === "ask" ? "ask" : "act";
  const acting = canAct && mode !== "ask";
  const lastTyping = useRef(0);
  const idle = useRef<ReturnType<typeof setTimeout> | null>(null);
  const words = text.trim();
  const fits = (kind: "act" | "ask") => words.length <= LIMITS[kind];
  const limit = LIMITS[channel];
  const picked = characters.filter((c) => !left.has(c.id)).map((c) => c.id);
  const forWhom = picked.length === characters.length ? undefined : picked;
  const nobody = characters.length > 0 && picked.length === 0;
  const box = useRef<HTMLTextAreaElement>(null);

  // The box starts two lines tall and grows with what is typed.
  useLayoutEffect(() => {
    const el = box.current;
    if (!el) return;
    el.style.height = "auto";
    if (el.scrollHeight > el.clientHeight) el.style.height = `${Math.min(el.scrollHeight + 2, MAX_TEXT_PX)}px`;
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

  useEffect(() => {
    if (!refill) return;
    const typed = refill.refused ? now.current.trim() : "";
    setText(typed ? `${refill.text}\n${typed}` : refill.text);
    setSecret(refill.private);
    setMode(refill.mode ?? "own");
  }, [refill]);

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

  function send(kind: "act" | "ask") {
    if (!words || !fits(kind)) return;
    if (kind === "act" && (!canAct || waiting || nobody)) return;
    if (kind === "ask" && asking) return;
    if (kind === "act") onAct(words, forWhom, (canPrivate && secret) || undefined);
    else onAsk(words);
    setText("");
    if (kind === "act") setSecret(false);
    stopTyping();
  }

  function onKeyDown(e: KeyboardEvent<HTMLTextAreaElement>) {
    if (e.key !== "Enter" || e.shiftKey) return;
    e.preventDefault();
    send(e.ctrlKey || e.metaKey ? "ask" : channel);
  }

  return (
    <form
      className="composer"
      data-testid="composer"
      data-tour="composer"
      data-channel={channel}
      onSubmit={(e) => {
        e.preventDefault();
        send(channel);
      }}
    >
      <div className="composer-top">
        {canAct && (
          <div className="composer-modes" role="group" aria-label={t("play.composerMode")}>
            <button type="button" data-testid="mode-own" aria-pressed={mode === "own"} onClick={() => setMode("own")}>
              {t("play.act")}
            </button>
            <button type="button" data-testid="mode-ask" aria-pressed={mode === "ask"} onClick={() => setMode("ask")}>
              {t("play.ask")}
            </button>
          </div>
        )}
        {onPaint && (
          <button
            type="button"
            className="composer-paint link-button"
            data-testid="paint-scene"
            disabled={painting || painted}
            onClick={onPaint}
            aria-label={t("play.paintScene")}
            title={t("play.paintScene")}
          >
            {/* On a phone the icon alone (DEL-323). */}
            <ImagePlus size={16} aria-hidden="true" />
            <span className="composer-paint-label">{t("play.paintScene")}</span>
          </button>
        )}
        {onPaint && painted && (
          <span className="hint" role="status">
            {t("play.painting")}
          </span>
        )}
        {acting && characters.length > 1 && <ActingFor characters={characters} left={left} onChange={setLeft} />}
      </div>
      <label className="composer-channel" htmlFor="composer-text" data-testid="composer-channel">
        {t(channel === "ask" ? "play.channelAsk" : "play.channelAct")}
      </label>
      <textarea
        id="composer-text"
        ref={box}
        rows={2}
        maxLength={limit}
        value={text}
        placeholder={
          mode === "ask"
            ? t("play.askPlaceholder")
            : actingAs
              ? t("play.hotseatPlaceholder", { name: actingAs })
              : t("play.composerPlaceholder")
        }
        onChange={(e) => change(e.target.value)}
        onKeyDown={onKeyDown}
      />
      {text.length >= limit * COUNT_FROM && (
        <span className={fits(channel) ? "composer-count" : "composer-count over"} data-testid="composer-count" aria-live="polite">
          {text.length} / {limit}
        </span>
      )}
      {error && (
        <p className="notice error" role="alert">
          {error}
        </p>
      )}
      {notice}
      <div className="composer-actions">
        <span className="composer-hint" data-testid="composer-hint">
          {mode === "ask"
            ? t("play.askHint")
            : blocked !== null
              ? blocked
              : running
                ? t("play.composerHintWaiting")
                : t(canAct ? "play.composerHint" : "play.composerHintObserver")}
        </span>
        {running && canCancel && (
          <button type="button" className="danger" onClick={onCancel}>
            {t("play.cancel")}
          </button>
        )}
        {channel === "ask" && (
          <button type="submit" className="primary" data-testid="ask" disabled={!words || asking || !fits("ask")}>
            {t("play.ask")}
          </button>
        )}
        {acting && beatOpen && (
          <button type="button" data-testid="pass" disabled={waiting || nobody} onClick={() => onPass(forWhom)}>
            {t("play.pass")}
          </button>
        )}
        {acting && canPrivate && (
          <label className="only-dm" data-testid="only-dm">
            <input type="checkbox" checked={secret} onChange={(e) => setSecret(e.target.checked)} />
            {t("play.onlyTheDm")}
          </label>
        )}
        {acting && (
          <button type="submit" className="primary" data-testid="act" disabled={!words || waiting || nobody || !fits("act")}>
            {t(beatOpen && replacing ? "play.replaceAct" : "play.act")}
          </button>
        )}
      </div>
    </form>
  );
}

/**
 * Who the seat acts for: a button that says so ("Acting for: whole party", "Acting for: Birch", "Acting for: 2 of 3")
 * and opens a menu. One click picks the whole party or one character; "Several…" shows a tick per character.
 */
function ActingFor({
  characters,
  left,
  onChange,
}: {
  characters: { id: string; name: string }[];
  /** The characters left out. */
  left: Set<string>;
  onChange: (left: Set<string>) => void;
}) {
  const t = useT();
  const [open, setOpen] = useState(false);
  const [several, setSeveral] = useState(false);
  const here = useRef<HTMLDivElement>(null);
  const picked = characters.filter((c) => !left.has(c.id));
  const who =
    picked.length === characters.length
      ? t("play.actForParty")
      : picked.length === 1
        ? picked[0].name
        : picked.length === 0
          ? t("play.actForNobody")
          : t("play.actForSome", { n: String(picked.length), total: String(characters.length) });

  useEffect(() => {
    if (!open) return;
    const away = (e: MouseEvent) => {
      if (here.current && !here.current.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener("mousedown", away);
    return () => document.removeEventListener("mousedown", away);
  }, [open]);

  function only(id: string | null) {
    onChange(new Set(id === null ? [] : characters.filter((c) => c.id !== id).map((c) => c.id)));
    setOpen(false);
  }

  function toggle(id: string) {
    const next = new Set(left);
    if (next.has(id)) next.delete(id);
    else next.add(id);
    onChange(next);
  }

  function onKeyDown(e: KeyboardEvent<HTMLElement>) {
    if (e.key === "Escape") {
      e.stopPropagation();
      setOpen(false);
    }
  }

  return (
    <div className="act-for" ref={here}>
      <button
        type="button"
        data-testid="act-for"
        aria-haspopup="menu"
        aria-expanded={open}
        onClick={() => {
          setSeveral(false);
          setOpen(!open);
        }}
      >
        {t("play.actingFor", { who })} <span aria-hidden="true">▾</span>
      </button>
      {open && !several && (
        <div className="popover act-for-menu" role="menu" aria-label={t("play.actFor")} onKeyDown={onKeyDown}>
          <button type="button" role="menuitemradio" aria-checked={left.size === 0} onClick={() => only(null)}>
            {t("play.actForWholeParty")}
          </button>
          {characters.map((c) => (
            <button
              type="button"
              role="menuitemradio"
              key={c.id}
              aria-checked={picked.length === 1 && picked[0].id === c.id}
              onClick={() => only(c.id)}
            >
              {c.name}
            </button>
          ))}
          <hr />
          <button type="button" role="menuitem" onClick={() => setSeveral(true)}>
            {t("play.actForSeveral")}
          </button>
        </div>
      )}
      {open && several && (
        <fieldset className="popover act-for-several" onKeyDown={onKeyDown}>
          <legend>{t("play.actFor")}</legend>
          {characters.map((c) => (
            <label key={c.id}>
              <input type="checkbox" checked={!left.has(c.id)} onChange={() => toggle(c.id)} />
              {c.name}
            </label>
          ))}
          <button type="button" onClick={() => setOpen(false)}>
            {t("play.actForDone")}
          </button>
        </fieldset>
      )}
    </div>
  );
}

