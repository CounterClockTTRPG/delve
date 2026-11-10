import * as ContextMenu from "@radix-ui/react-context-menu";
import { useQuery } from "@tanstack/react-query";
import { memo, useEffect, useLayoutEffect, useMemo, useRef, useState, type MouseEvent, type ReactNode } from "react";
import { Dices, RotateCcw } from "lucide-react";
import { toast } from "sonner";
import { copyText } from "../components/copyText";
import { useLanguage, useT, type Translate } from "../i18n";
import { queuedLine } from "../components/waiting";
import { TABLE_ROLES, getToolCall, imageUrl, pictureUrl, playKeys, type DiceLine, type PaintingScene, type SeatRole, type StoryEntry, type ToolStep } from "./api";
import { renderMarkdown } from "./markdown";
import { retryable, useRetry } from "./retry";
import SaidLine from "./SaidLine";
import { TOOL_KINDS, toolKind, type ToolKindName } from "./toolKinds";
import Lightbox from "../components/Lightbox";

/** The words of an entry, whichever key the kind keeps them under. */
export function entryText(entry: StoryEntry): string {
  const p = entry.payload;
  return p.text ?? p.message ?? p.answer ?? p.question ?? p.recap ?? "";
}

/**
 * The words to show the seat: the translation into its language once there is some of it, else the English. `mark`
 * says the translation is still coming (`translating`) or failed (`failed`), so the English shows marked.
 */
export function shownText(entry: StoryEntry): { text: string; mark: "translating" | "failed" | null } {
  const translation = entry.translation;
  if (!translation) return { text: entryText(entry), mark: null };
  if (translation.status === "failed") return { text: entryText(entry), mark: "failed" };
  const text = translation.text || entryText(entry);
  return { text, mark: translation.status === "translating" ? "translating" : null };
}

/** An entry's words as a screen reader hears them: an NPC's line with who says it, without Markdown's marks. */
function spokenText(entry: StoryEntry): string {
  const text = shownText(entry).text.replace(/[*_`#>]+/g, "").trim();
  if (!text) return "";
  return entry.kind === "say" && entry.payload.speaker ? `${entry.payload.speaker.name}: ${text}` : text;
}

/** Table talk is the table's: the table panel shows it, not the story. Questions to the DM and their answers show in
 * the story, for who asked (plan 7 Task 18). */
export const PRIVATE_KINDS = new Set(["talk"]);

/** Whether a seat of `role` sees the tool row `entry`: the host and the co-hosts do, and only the host a refused one.
 * A player or an observer sees a row only for the dice it may read in it (DEL-270): the server sends them no other
 * row, and this keeps it so for rows from before. */
export function seesToolRow(entry: StoryEntry, role: SeatRole | null): boolean {
  if (role === null) return false;
  if (role === "host") return true;
  if (entry.payload.failed) return false;
  return TABLE_ROLES.has(role) || hasDice(entry);
}

function hasDice(entry: StoryEntry): boolean {
  return Boolean(entry.payload.dice?.length || entry.payload.steps?.some((step) => step.dice?.length));
}

/** A roll as the story reads it (DEL-270): "Garrek, attack — d20: 19", "Reggi wrestling, three falls — 3d20: 14, 7, 18
 * (39)". Who rolled and what for, the dice, the faces, and their total when there are several. */
export function diceText(line: DiceLine, t: Translate): string {
  const who = line.who ?? (line.side ? t(`dice.side.${line.side}`) : "");
  const what = line.what ? t(`dice.what.${line.what}`) + (line.detail ? ` (${line.detail})` : "") : (line.detail ?? "");
  const head = [who, what].filter(Boolean).join(", ");
  const faces = line.faces.join(", ") + (line.faces.length > 1 ? ` (${line.total})` : "");
  return `${head ? `${head} — ` : ""}${line.dice}: ${faces}`;
}

/** The calls a tool row stands for, as a seat of `role` sees them: a batch's steps (a co-host's without the refused
 * ones), or the row itself. */
export function toolCalls(entry: StoryEntry, role: SeatRole | null): (ToolStep | null)[] {
  const steps = entry.payload.steps;
  if (!steps?.length) return [null];
  return role === "host" ? steps : steps.filter((step) => !step.failed);
}

/** How near the bottom, in pixels, still counts as reading the newest entry. */
const AT_THE_END_PX = 48;

/**
 * The story, oldest first: the acts, the DM's narration (escaped, then Markdown), the tool rows (a tool's name and the
 * dice this seat may read, for the host and co-hosts, and for the others the rows with dice for them; consecutive
 * ones folded into one chip), the NPCs' lines with their portraits (only the
 * newest, if it came in live, talks), the images the DM shows, the painted scenes, the DM's errors and the recaps; while it is empty, the book's ink drawing. Every payload is already
 * player-safe. An entry addressed to some characters is marked "Only you"; each shows in the seat's language when
 * translated. A question to the DM shows with its answer, folded, marked "Only you" (the server sends them to who
 * asked alone), with Share; `asking` is a question still waiting for its answer. It opens at the newest entry and
 * follows new ones, unless the reader has scrolled up. Scrolling to the top loads the earlier page by itself (the
 * button stays, for keyboards), keeping the reader's place, down to the start of the story; "Back to the latest" shows
 * while the reader is more than a screen up.
 */
export default function Story({
  entries,
  hasMore,
  onLoadEarlier,
  loadingEarlier = false,
  mySeatId = null,
  names = {},
  role = null,
  waiting = false,
  asking: askingNow = null,
  onShare,
  campaignId,
  paintingScenes = [],
  running = false,
}: {
  entries: StoryEntry[];
  hasMore: boolean;
  onLoadEarlier: () => void;
  loadingEarlier?: boolean;
  /** This browser's seat: its own acts say "You". */
  mySeatId?: string | null;
  /** Character names by id, for the acts. */
  names?: Record<string, string>;
  /** This seat's role: the host and co-hosts see the tool rows. Left out, none. */
  role?: SeatRole | null;
  /** The table gathers until the host starts the session (not solo): the empty story says so, not "act" (DEL-262). */
  waiting?: boolean;
  /** A question this page asked that the DM hasn't answered yet. */
  asking?: string | null;
  /** Share an answer with the table, as table talk. */
  onShare?: (answerId: string) => void;
  /** The campaign, for the host's tool rows: given, the host opens a row to read its call and reply. */
  campaignId?: string;
  /** The scenes still painting that this seat will see: a placeholder for each at the end of the story. */
  paintingScenes?: PaintingScene[];
  /** The DM is writing: the newest entry may still be growing, so a screen reader hears it once it is done. */
  running?: boolean;
}) {
  const t = useT();
  const box = useRef<HTMLElement>(null);
  const top = useRef<HTMLDivElement>(null);
  const atTheEnd = useRef(true);
  // The height of what scrolls when last measured, so a page added above keeps the reader where they were.
  const height = useRef(0);
  // The newest entry is out of sight (DEL-95): "Back to the latest" shows, with the entries come in since the
  // reader left the end (`seenSeq`, the newest they had then).
  const [away, setAway] = useState(false);
  const seenSeq = useRef<number | null>(null);
  // The entry under a right-click, for the story's own menu.
  const [menuFor, setMenuFor] = useState<StoryEntry | null>(null);
  // The question asked is shown waiting until its entry comes in: the server tells it as an event, which may come
  // before the answer to the request does (DEL-168).
  const asking =
    askingNow && !entries.some((e) => e.kind === "ask" && e.live && (e.payload.original ?? e.payload.text) === askingNow)
      ? askingNow
      : null;
  const loadEarlier = useRef(onLoadEarlier);
  loadEarlier.current = onLoadEarlier;
  const shown = entries.filter((e) => !PRIVATE_KINDS.has(e.kind) && (e.kind !== "tool" || seesToolRow(e, role)));
  // A scene whose entry came in before the state was read again has landed: its picture stands in its place.
  const landed = new Set(shown.filter((e) => e.kind === "scene").map((e) => e.payload.image_id));
  const painting = paintingScenes.filter((scene) => !landed.has(scene.image_id));
  const last = shown.at(-1);
  const first = shown.at(0);
  const unseen = away && seenSeq.current !== null ? shown.filter((e) => e.seq > seenSeq.current!).length : 0;
  // The window's scroll listener is added once: it reads the newest entry from here.
  const lastSeq = useRef<number | null>(null);
  lastSeq.current = last?.seq ?? null;
  // Kept while the same answers are shared, so a growing reply re-renders no question (DEL-168).
  const sharedKey = entries.flatMap((e) => (e.kind === "talk" && e.payload.shared ? [e.payload.shared] : [])).join(" ");
  const shared = useMemo(() => new Set<string | undefined>(sharedKey ? sharedKey.split(" ") : []), [sharedKey]);
  // An answer shows with the question before it.
  const answers = new Map<string, StoryEntry>();
  shown.forEach((e, i) => {
    const next = shown[i + 1];
    if (e.kind === "ask" && next?.kind === "answer") answers.set(e.id, next);
  });
  const paired = new Set([...answers.values()].map((e) => e.id));
  // Consecutive tool rows fold into one chip: the first of a run carries the run, the others show in it. A batch
  // counts as its steps, so a lone batch of several is a chip too.
  const toolRuns = new Map<string, StoryEntry[]>();
  shown.forEach((e, i) => {
    if (e.kind !== "tool" || shown[i - 1]?.kind === "tool") return;
    let end = i;
    while (shown[end + 1]?.kind === "tool") end++;
    if (end > i || e.payload.steps?.length) toolRuns.set(e.id, shown.slice(i, end + 1));
  });
  const inRun = new Set([...toolRuns.values()].flatMap((run) => run.slice(1).map((e) => e.id)));
  // The said line that talks: the newest, if it came in while the page was open.
  const newestSaid = shown.filter((e) => e.kind === "say").at(-1);
  const talking = newestSaid?.live ? newestSaid.id : null;
  // Only the host reads a tool call's details; a co-host sees the rows alone (owner, 2026-10-22).
  const toolsOf = role === "host" ? campaignId : undefined;
  // Retry shows on the latest error that may be tried again, when the server says this seat may retry its beat.
  const retryOn = campaignId ? shown.filter(retryable).at(-1)?.id : undefined;

  // What a screen reader hears: each entry that came in live, once it is whole (a reply the DM is still writing is
  // heard when the beat ends or the next entry comes), never the pages loaded or each streamed word.
  const announced = useRef(new Set<string>());
  const [announcement, setAnnouncement] = useState("");
  const whole = shown.filter((e, i) => e.live && e.kind !== "tool" && (i < shown.length - 1 || !running));
  const wholeKey = whole.map((e) => e.id).join(" ");
  useEffect(() => {
    const fresh = whole.filter((e) => !announced.current.has(e.id));
    if (fresh.length === 0) return;
    fresh.forEach((e) => announced.current.add(e.id));
    const heard = fresh.map(spokenText).filter(Boolean);
    if (heard.length > 0) setAnnouncement(heard.join("\n"));
  }, [wholeKey]);

  // What scrolls: the story itself, in its box on every screen (DEL-311), or the page while the story fits its box.
  function scroller(): { el: Element; view: number } | null {
    const story = box.current;
    if (story && story.scrollHeight > story.clientHeight) return { el: story, view: story.clientHeight };
    const page = document.scrollingElement;
    return page ? { el: page, view: window.innerHeight } : null;
  }

  // Land at the newest entry, and follow the story as it grows, while the reader is there.
  useEffect(() => {
    const scrolling = scroller();
    if (scrolling && atTheEnd.current) scrolling.el.scrollTop = scrolling.el.scrollHeight;
    if (atTheEnd.current) seenSeq.current = last?.seq ?? null;
    else if (scrolling) setAway(newestOutOfSight(scrolling)); // what came in may have pushed the newest out of sight
  }, [last?.id, last && shownText(last).text.length, painting.length]);

  // An earlier page came in above: move down by what it added, so the entry being read stays in place.
  const shownFirst = useRef(first);
  useLayoutEffect(() => {
    const before = shownFirst.current;
    shownFirst.current = first;
    const scrolling = scroller();
    if (!scrolling) return;
    if (before && first && first.seq < before.seq && !atTheEnd.current) {
      scrolling.el.scrollTop += scrolling.el.scrollHeight - height.current;
    }
    height.current = scrolling.el.scrollHeight;
  });

  // The sentinel above the first entry: in sight, the earlier page loads. Observed afresh for each page, so a page
  // too short to push it out of sight loads the next one too.
  useEffect(() => {
    const sentinel = top.current;
    if (!sentinel || !hasMore || loadingEarlier || typeof IntersectionObserver === "undefined") return;
    const observer = new IntersectionObserver((seen) => {
      if (seen.some((e) => e.isIntersecting)) loadEarlier.current();
    });
    observer.observe(sentinel);
    return () => observer.disconnect();
  }, [hasMore, loadingEarlier, first?.id]);

  function scrolled() {
    const scrolling = scroller();
    if (!scrolling) return;
    const below = scrolling.el.scrollHeight - scrolling.el.scrollTop - scrolling.view;
    atTheEnd.current = below <= AT_THE_END_PX;
    height.current = scrolling.el.scrollHeight;
    if (atTheEnd.current) seenSeq.current = lastSeq.current;
    setAway(!atTheEnd.current && newestOutOfSight(scrolling));
  }

  // Whether the newest entry is below what shows: its top under the bottom of the story box, or of the window when
  // the page scrolls; without an entry to measure, a whole screen up, as before.
  function newestOutOfSight(scrolling: { el: Element; view: number }): boolean {
    const newest = [...(box.current?.querySelectorAll(".entry-slot > *") ?? [])].at(-1);
    if (!newest) return scrolling.el.scrollHeight - scrolling.el.scrollTop - scrolling.view > scrolling.view;
    const bottom = scrolling.el === box.current ? box.current.getBoundingClientRect().bottom : window.innerHeight;
    return newest.getBoundingClientRect().top >= bottom;
  }

  function toTheLatest() {
    const scrolling = scroller();
    if (scrolling) scrolling.el.scrollTop = scrolling.el.scrollHeight;
    atTheEnd.current = true;
    seenSeq.current = lastSeq.current;
    setAway(false);
  }

  useEffect(() => {
    window.addEventListener("scroll", scrolled, { passive: true });
    return () => window.removeEventListener("scroll", scrolled);
  }, []);

  // A right-click on an entry with words opens the story's menu. Elsewhere, or over selected text, the browser's own
  // menu shows (its Copy copies the selection). Decided at the button's press, before the menu is asked for.
  function onMouseDown(e: MouseEvent) {
    if (e.button !== 2) return;
    const slot = (e.target as Element).closest<HTMLElement>("[data-entry-id]");
    const entry = slot ? (shown.find((x) => x.id === slot.dataset.entryId) ?? null) : null;
    const selected = (window.getSelection()?.toString() ?? "").trim() !== "";
    setMenuFor(entry && !selected && entryText(entry).trim() ? entry : null);
  }
  const copy = (text: string) =>
    void copyText(text).then((done) =>
      done ? toast.success(t("play.copied"), { duration: 2000 }) : toast.error(t("play.copyFailed")),
    );
  const canShare = (entry: StoryEntry) => entry.kind === "answer" && onShare !== undefined && !shared.has(entry.id);

  return (
    <ContextMenu.Root modal={false} onOpenChange={(open) => !open && setMenuFor(null)}>
      <ContextMenu.Trigger asChild disabled={menuFor === null}>
        <section
          ref={box}
          className="story"
          data-testid="story"
          data-tour="story"
          aria-label={t("play.story")}
          onScroll={scrolled}
          onMouseDown={onMouseDown}
        >
          {hasMore && (
            <>
              <div ref={top} className="story-top" data-testid="story-top" aria-hidden="true" />
              <button type="button" className="load-earlier" onClick={onLoadEarlier} disabled={loadingEarlier}>
                {t("play.loadEarlier")}
              </button>
            </>
          )}
          {!hasMore && shown.length > 0 && <p className="story-start">{t("play.storyStart")}</p>}
          {shown.length === 0 && !hasMore && !asking && painting.length === 0 && (
            // The empty story (DEL-146): a quiet ink drawing in the look's own ink (a CSS mask, so it suits every look),
            // never the banner, which is too big here; and what to do first. An observer, who doesn't act, waits.
            <div className="story-empty" data-testid="story-empty">
              <span className="story-empty-art" aria-hidden="true" />
              <h2 className="story-empty-title">{t("play.emptyStoryTitle")}</h2>
              <p className="story-empty-text">
                {t(role === "observer" ? "play.emptyStoryObserver" : waiting ? "play.emptyStoryWaiting" : "play.emptyStory")}
              </p>
            </div>
          )}
          {shown.map((entry) =>
            inRun.has(entry.id) ? null : (
              // A slot names the entry for the story's menu, and takes no room of its own (display: contents).
              <div key={entry.id} className="entry-slot" data-entry-id={answerOf(entry, answers)}>
                {toolRuns.has(entry.id) ? (
                  <ToolChip rows={toolRuns.get(entry.id)!} role={role} campaignId={toolsOf} />
                ) : entry.kind === "ask" || entry.kind === "answer" ? (
                  paired.has(entry.id) ? null : (
                    <Asked
                      question={entry.kind === "ask" ? entry : null}
                      answer={entry.kind === "answer" ? entry : (answers.get(entry.id) ?? null)}
                      shared={shared}
                      open={entry === last || answers.get(entry.id) === last}
                      onShare={onShare}
                    />
                  )
                ) : (
                  <Entry
                    entry={entry}
                    mySeatId={mySeatId}
                    names={names}
                    talking={entry.id === talking}
                    toolsOf={toolsOf}
                    retryIn={entry.id === retryOn ? campaignId : undefined}
                  />
                )}
              </div>
            ),
          )}
          {painting.map((scene) => (
            <PaintingSceneSkeleton key={scene.image_id} scene={scene} />
          ))}
          {asking && (
            <details className="entry asked" data-testid="asked" open>
              <summary>
                <span className="entry-who">{t("play.youAsked")}</span>
                <span className="only-you">{t("play.onlyYouShort")}</span>
                <span className="asked-question">{asking}</span>
              </summary>
              <p className="placeholder">{t("play.answering")}</p>
            </details>
          )}
          {away && (
            <button type="button" className="back-to-latest" onClick={toTheLatest}>
              {unseen === 0
                ? t("play.backToLatest")
                : unseen === 1
                  ? t("play.backToLatestNew.one")
                  : t("play.backToLatestNew", { count: String(unseen) })}
            </button>
          )}
        </section>
      </ContextMenu.Trigger>
      <ContextMenu.Portal>
        <ContextMenu.Content className="menu" aria-label={t("play.entryMenu")}>
          {menuFor && (
            <>
              <ContextMenu.Item className="menu-item" onSelect={() => copy(entryText(menuFor))}>
                {t("play.copyEntry")}
              </ContextMenu.Item>
              {canShare(menuFor) && (
                <ContextMenu.Item className="menu-item" onSelect={() => onShare?.(menuFor.id)}>
                  {t("play.share")}
                </ContextMenu.Item>
              )}
            </>
          )}
        </ContextMenu.Content>
      </ContextMenu.Portal>
      {/* Beside the story, not in it: what it says is heard, and the story's own text is found once. */}
      <div className="visually-hidden" aria-live="polite" data-testid="story-announce">
        {announcement}
      </div>
    </ContextMenu.Root>
  );
}

/** The entry a slot's menu acts on: an asked question's answer, when it has one, else the entry itself. */
function answerOf(entry: StoryEntry, answers: Map<string, StoryEntry>): string {
  return entry.kind === "ask" ? (answers.get(entry.id)?.id ?? entry.id) : entry.id;
}

/** Who acted: "You" for this seat's own acts (and those from before seats), else the seat's name; with the
 * characters it acted for. */
export function actor(entry: StoryEntry, mySeatId: string | null, names: Record<string, string>, you: string): string {
  const { seat_id, name, characters, hotseat } = entry.payload;
  // A hotseat player's act (DEL-365) is theirs, by name, on the screen they share too.
  const who = hotseat && name ? name : !seat_id || seat_id === mySeatId || !name ? you : name;
  const playing = (characters ?? []).map((id) => names[id]).filter(Boolean);
  return playing.length > 0 && who !== you ? `${who} · ${playing.join(", ")}` : who;
}

/** The marks an entry carries: "Only you" when it was addressed, and where its translation is. */
export function Marks({ entry, mark }: { entry: StoryEntry; mark: "translating" | "failed" | null }) {
  const t = useT();
  return (
    <>
      {entry.audience && (
        <span className="only-you" data-testid="only-you">
          {t("play.onlyYouShort")}
        </span>
      )}
      {mark === "translating" && (
        <span className="translating" data-testid="translating">
          {t("play.translating")}
        </span>
      )}
      {mark === "failed" && (
        <span className="not-translated" data-testid="not-translated">
          {t("play.notTranslated")}
        </span>
      )}
    </>
  );
}

/** One entry of the story. Memoized (DEL-168): while the DM writes, only the entry that grows renders again, not
 * every entry before it and its Markdown; its props are kept stable for that (`names` by the play screen). */
const Entry = memo(function Entry({
  entry,
  mySeatId,
  names,
  talking,
  toolsOf,
  retryIn,
}: {
  entry: StoryEntry;
  mySeatId: string | null;
  names: Record<string, string>;
  talking: boolean;
  /** The campaign, when this seat is the host's: its tool rows open to their calls. */
  toolsOf?: string;
  /** The campaign, on the story's latest retryable error: it may offer Retry. */
  retryIn?: string;
}) {
  const t = useT();
  const { text, mark } = shownText(entry);
  const addressed = entry.audience ? " addressed" : "";
  const marks: ReactNode = (entry.audience || mark) && <Marks entry={entry} mark={mark} />;
  switch (entry.kind) {
    case "player_act":
      return (
        <div className={`entry player-act${addressed}`}>
          <span className="entry-who">{actor(entry, mySeatId, names, t("play.you"))}</span>
          {marks}
          <p>{text}</p>
        </div>
      );
    case "dm_text":
      return (
        <div className={`entry dm-text${addressed}`}>
          {marks && <div className="entry-marks">{marks}</div>}
          <Markdown text={text} />
        </div>
      );
    case "say":
      return <SaidLine entry={entry} live={talking} />;
    case "tool":
      return <ToolRow entry={entry} campaignId={toolsOf} />;
    case "image":
      return <ShownImage entry={entry} />;
    case "scene":
      return <Scene entry={entry} marks={marks} />;
    case "dm_error":
      return (
        <p className="entry dm-error" role="alert">
          <span>{text}</span>
          {retryIn && <Retry campaignId={retryIn} entry={entry} />}
        </p>
      );
    case "recap":
      return (
        <div className={`entry recap${addressed}`}>
          <span className="entry-who">{t("play.recap")}</span>
          {marks}
          <Markdown text={text} />
        </div>
      );
    default:
      return null;
  }
});

/** The DM's Markdown as HTML (escaped first, `renderMarkdown`), worked out again only when the words change. */
const Markdown = memo(function Markdown({ text, className }: { text: string; className?: string }) {
  const html = useMemo(() => renderMarkdown(text), [text]);
  return <div className={className} dangerouslySetInnerHTML={{ __html: html }} />;
});

/** Retry on a failed beat's error (table voice and fixes Task D2), a retry arrow named Retry: the press plays the beat again with the same acts,
 * and with a usage limit, when it ends, in the reader's time. Disabled from the press until the beat's next event. */
function Retry({ campaignId, entry }: { campaignId: string; entry: StoryEntry }) {
  const t = useT();
  const language = useLanguage();
  const { shown, resetsAt, pressed, retry, error } = useRetry(campaignId, entry);
  useEffect(() => {
    if (error) toast.error(t("retry.failed", { error: error.message }));
  }, [error, t]);
  if (!shown) return null;
  const label = pressed ? t("retry.pressed") : t("retry.button");
  return (
    <>
      {" "}
      <button type="button" className="icon-button retry-button" onClick={retry} disabled={pressed} data-testid="retry"
        aria-label={label} title={label}>
        <RotateCcw size={16} aria-hidden="true" className={pressed ? "retry-turning" : undefined} />
      </button>
      {resetsAt && <span data-testid="retry-resets"> {t("retry.resetsAt", { time: limitEnd(resetsAt, language) })}</span>}
    </>
  );
}

/** When a usage limit ends, in the reader's time: the time alone today, with the day otherwise. */
export const limitEnd = (at: string, language: string, now: Date = new Date()): string => shortWhen(at, language, now);

/** A moment in the reader's time: the time alone today, with the day otherwise (a usage limit's end, a talk line). */
export function shortWhen(at: string, language: string, now: Date = new Date()): string {
  const end = new Date(at);
  if (Number.isNaN(end.getTime())) return at;
  const today = end.toDateString() === now.toDateString();
  return today
    ? end.toLocaleTimeString(language, { hour: "2-digit", minute: "2-digit" })
    : end.toLocaleString(language, { weekday: "short", day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" });
}

/** A question to the DM and its answer, folded, for who asked (in the story, and in the tavern): the question in the
 * asker's own words, the answer in the seat's language once translated, with Share until it is shared. */
export const Asked = memo(function Asked({
  question,
  answer,
  shared,
  open,
  onShare,
}: {
  question: StoryEntry | null;
  answer: StoryEntry | null;
  shared: Set<string | undefined>;
  open: boolean;
  onShare?: (answerId: string) => void;
}) {
  const t = useT();
  const asked = question ? (question.payload.original ?? shownText(question).text) : "";
  const answered = answer ? shownText(answer) : null;
  return (
    <details className="entry asked" data-testid="asked" open={open}>
      <summary>
        <span className="entry-who">{t("play.youAsked")}</span>
        <span className="only-you" data-testid="only-you">
          {t("play.onlyYouShort")}
        </span>
        <span className="asked-question">{asked}</span>
        {/* The summary is a flex row, which drops the details' marker: say it opens (DEL-261). */}
        {answer && (
          <span className="asked-toggle" aria-hidden="true">
            <span className="when-closed">{t("play.askedShow")}</span>
            <span className="when-open">{t("play.askedHide")}</span>
          </span>
        )}
      </summary>
      {answer && answered ? (
        <>
          {answered.mark && <Marks entry={{ ...answer, audience: null }} mark={answered.mark} />}
          <Markdown className="asked-answer" text={answered.text} />
          {shared.has(answer.id) ? (
            <p className="hint">{t("play.shared")}</p>
          ) : (
            onShare && (
              <button type="button" className="link-button" onClick={() => onShare(answer.id)}>
                {t("play.share")}
              </button>
            )
          )}
        </>
      ) : (
        <p className="placeholder">{t("play.answering")}</p>
      )}
    </details>
  );
});

/** A tool row: its name, and for the host (`campaignId` given) its call and reply when it is opened. A batch's step
 * (`step`) is a row of its own, opening to that step's call. */
function ToolRow({ entry, step, campaignId }: { entry: StoryEntry; step?: ToolStep; campaignId?: string }) {
  const t = useT();
  const [open, setOpen] = useState(false);
  const { name, failed, dice } = step ?? entry.payload;
  const label = (
    <>
      <KindIcon kind={toolKind(name)} />
      <ToolName name={name} />
      {failed && <span>{t("play.toolRefused")}</span>}
    </>
  );
  // The dice come with the row, under it, in a chip that folds them with it: no jump when they arrive (DEL-270).
  const rolled = dice?.length ? <DiceLines lines={dice} /> : null;
  if (!campaignId)
    return (
      <>
        <p className={failed ? "entry tool-row failed" : "entry tool-row"}>{label}</p>
        {rolled}
      </>
    );
  return (
    <>
      <details
        className={failed ? "entry tool-row openable failed" : "entry tool-row openable"}
        onToggle={(e) => setOpen((e.currentTarget as HTMLDetailsElement).open)}
      >
        <summary>{label}</summary>
        {open && <ToolCallShown campaignId={campaignId} entryId={entry.id} step={step?.step} />}
      </details>
      {rolled}
    </>
  );
}

/** A row's dice, one line a roll, as a list a screen reader names "Dice". */
function DiceLines({ lines }: { lines: DiceLine[] }) {
  const t = useT();
  return (
    <ul className="tool-dice" aria-label={t("story.dice")}>
      {lines.map((line, i) => (
        <li key={i}>
          <Dices size={12} aria-hidden="true" /> {diceText(line, t)}
        </li>
      ))}
    </ul>
  );
}

/** A call's arguments and its reply, read from the DM log when the row opens; a batch's, step by step, or only its step
 * `step`. */
function ToolCallShown({ campaignId, entryId, step: only }: { campaignId: string; entryId: string; step?: number }) {
  const t = useT();
  const call = useQuery({
    queryKey: playKeys.toolCall(campaignId, entryId),
    queryFn: () => getToolCall(campaignId, entryId),
    staleTime: Infinity,
  });
  if (call.isPending) return <p className="placeholder">{t("play.toolReading")}</p>;
  if (!call.data) return <p className="placeholder">{t("play.toolMissing")}</p>;
  const { name, args, result } = call.data;
  if (name === "batch") {
    const steps = Array.isArray(args.steps) ? (args.steps as { tool?: string; args?: unknown }[]) : [];
    const results = isRecord(result) && Array.isArray(result.results) ? (result.results as Record<string, unknown>[]) : [];
    if (only !== undefined) {
      const answer = results.find((r) => r.step === only);
      return <CallParts args={steps[only]?.args ?? {}} result={answer ? (answer.result ?? answer.error) : undefined} />;
    }
    return (
      <ol className="tool-steps">
        {steps.map((step, i) => {
          const answer = results.find((r) => r.step === i);
          const refused = answer === undefined || "error" in answer || (isRecord(answer.result) && "error" in answer.result);
          return (
            <li key={i}>
              <details>
                <summary>
                  <ToolName name={step.tool === undefined ? "?" : String(step.tool)} />
                  {refused && <span>{t(answer === undefined ? "play.toolNotRun" : "play.toolRefused")}</span>}
                </summary>
                <CallParts args={step.args ?? {}} result={answer ? (answer.result ?? answer.error) : undefined} />
              </details>
            </li>
          );
        })}
      </ol>
    );
  }
  return <CallParts args={args} result={result} />;
}

function CallParts({ args, result }: { args: unknown; result: unknown }) {
  const t = useT();
  return (
    <div className="tool-call">
      <h4>{t("play.toolAsked")}</h4>
      <pre>{pretty(args)}</pre>
      {result !== undefined && (
        <>
          <h4>{t("play.toolAnswered")}</h4>
          <pre>{pretty(result)}</pre>
        </>
      )}
    </div>
  );
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function pretty(value: unknown): string {
  return typeof value === "string" ? value : JSON.stringify(value, null, 2);
}

/** A run of tool rows, folded: "3 tools", which opens to their names (and, for the host, each one's call). A batch
 * shows as its steps, each a row and counted, never as "batch". */
const ToolChip = memo(function ToolChip({ rows, role, campaignId }: { rows: StoryEntry[]; role: SeatRole | null; campaignId?: string }) {
  const t = useT();
  const calls = rows.flatMap((row) => toolCalls(row, role).map((step) => ({ row, step })));
  if (calls.length === 0) return null;
  // Each kind once, in the order the calls came.
  const kinds = [...new Set(calls.map(({ row, step }) => toolKind(step?.name ?? row.payload.name)))];
  return (
    <details className="entry tool-chip">
      <summary>
        {kinds.map((kind) => (
          <KindIcon key={kind} kind={kind} />
        ))}
        {t("story.tools", { count: String(calls.length) })}
      </summary>
      {calls.map(({ row, step }) => (
        <ToolRow key={step ? `${row.id}:${step.step}` : row.id} entry={row} step={step ?? undefined} campaignId={campaignId} />
      ))}
    </details>
  );
},
// A run is sliced afresh on each render: the same rows are the same chip.
(was, now) =>
  was.role === now.role &&
  was.campaignId === now.campaignId &&
  was.rows.length === now.rows.length &&
  was.rows.every((row, i) => row === now.rows[i]));

/** A tool's name in the reader's language (`tool.<name>`): English keeps the tool's own name, in the code font; the
 * others read a label, with the tool's name on hover. */
function ToolName({ name }: { name?: string }) {
  const t = useT();
  const label = name ? t(`tool.${name}`) : "";
  if (!name || label === name || label === `tool.${name}`) return <span className="tool-name">{name}</span>;
  return (
    <span className="tool-label" title={name}>
      {label}
    </span>
  );
}

/** A tool kind's icon, in its tone's colour (docs/style-guide.md); its name is the row's, so the icon is decoration. */
function KindIcon({ kind }: { kind: ToolKindName }) {
  const { icon: Icon, tone } = TOOL_KINDS[kind];
  return <Icon className={`tool-kind tone-${tone}`} data-kind={kind} size={14} aria-hidden="true" />;
}

function ShownImage({ entry }: { entry: StoryEntry }) {
  const t = useT();
  const { asset, caption } = entry.payload;
  if (!asset) return null;
  return (
    <figure className="entry image">
      <Enlarged url={imageUrl(entry.campaign_id, asset)} name={caption || t("play.shownImage")} />
      {caption && <figcaption>{caption}</figcaption>}
    </figure>
  );
}

/** A story's picture, which a click shows enlarged (`Lightbox`). */
function Enlarged({ url, name }: { url: string; name: string }) {
  const t = useT();
  return (
    <Lightbox
      label={t("play.enlarge", { name })}
      title={name}
      className="image-zoom"
      big={<img className="lightbox-image" src={url} alt={name} />}
    >
      <img src={url} alt={name} loading="lazy" />
    </Lightbox>
  );
}

/** A scene painted for the table (plan 6), served by the pictures route only to the seats its audience allows. */
function Scene({ entry, marks }: { entry: StoryEntry; marks: ReactNode }) {
  const t = useT();
  const { image_id, caption } = entry.payload;
  if (!image_id) return null;
  return (
    <figure className={`entry scene${entry.audience ? " addressed" : ""}`}>
      {marks && <div className="entry-marks">{marks}</div>}
      <Enlarged url={pictureUrl(entry.campaign_id, image_id)} name={caption || t("play.paintedScene")} />
      {caption && <figcaption>{caption}</figcaption>}
    </figure>
  );
}

/** A scene still painting (DEL-115): a placeholder the picture's size, until its `scene` entry comes in; while it
 * waits its turn at the painter, its place in the queue (DEL-138). */
function PaintingSceneSkeleton({ scene }: { scene: PaintingScene }) {
  const t = useT();
  const state = queuedLine(t, scene) ?? t("play.paintingScene");
  return (
    <figure className="entry scene painting" data-testid="painting-scene" aria-busy="true">
      <div className="scene-skeleton" role="img" aria-label={state} />
      <figcaption>{scene.caption ? `${scene.caption} · ${state}` : state}</figcaption>
    </figure>
  );
}

/** Where a gallery entry's bytes are, and what it is called: an image the DM showed, or a painted scene. */
function galleryItem(entry: StoryEntry, t: Translate): { url: string; caption: string } | null {
  const { asset, image_id, caption } = entry.payload;
  if (entry.kind === "image" && asset) return { url: imageUrl(entry.campaign_id, asset), caption: caption || t("play.shownImage") };
  if (entry.kind === "scene" && image_id) {
    return { url: pictureUrl(entry.campaign_id, image_id), caption: caption || t("play.paintedScene") };
  }
  return null;
}

/** The images the DM has shown and the scenes painted, newest first, in a strip above the story (spec §7.6). Each
 * opens enlarged, as in the story (DEL-309). */
export function GalleryStrip({ entries }: { entries: StoryEntry[] }) {
  const t = useT();
  const images = entries.flatMap((e) => {
    const item = galleryItem(e, t);
    return item ? [{ entry: e, ...item }] : [];
  }).reverse();
  if (images.length === 0) return null;
  return (
    <section className="gallery" data-testid="gallery" aria-label={t("play.gallery")}>
      <ul>
        {images.map(({ entry, url, caption }) => (
          <li key={entry.id} title={caption}>
            <Enlarged url={url} name={caption} />
          </li>
        ))}
      </ul>
    </section>
  );
}
