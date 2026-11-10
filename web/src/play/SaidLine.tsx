import { emoteDuration, generate } from "portraitgen";
import { useEffect, useMemo, useState } from "react";
import Portrait from "../components/Portrait";
import { useT } from "../i18n";
import type { StoryEntry } from "./api";
import { plainInline, renderInline } from "./markdown";
import { Marks, shownText } from "./Story";

/** The moods a line may carry (`delve.dm.tools.say.MOODS`): each a portraitgen emote but `neutral`, talk only. */
export const MOODS = [
  "neutral", "smile", "laugh", "wink", "sneer", "angry", "afraid", "upset", "surprised", "sigh",
  "thinking", "shout", "cry", "disgusted", "nod", "shake",
] as const;

/** A portrait at rest: it blinks and breathes, and nothing else. */
export const IDLE_EMOTES = ["blink", "breathe"] as const;

/** How much faster than the portrait's own talk a line plays, words and lips alike. */
export const SPEECH_RATE = 2;
/** Without a drawn portrait to time the talking, a line shows at this pace, in ms per character. */
const PACE_MS = 60 / SPEECH_RATE;
/** How often a growing line shows more. */
const TICK_MS = 50;

type Phase = "talk" | "mood" | "rest";

function reducedMotion(): boolean {
  return typeof window.matchMedia === "function" && window.matchMedia("(prefers-reduced-motion: reduce)").matches;
}

/**
 * An NPC's line (a `say` entry) with the speaker's portrait. A `live` line, one that came in while the page was open,
 * shows its words growing at the talk animation's pace while the portrait talks them (`say`), then plays the line's
 * mood once, then rests on blink and breathe. A line from history, or any line under reduced motion, shows whole, the
 * portrait at rest (still, under reduced motion). The story makes only its newest live line `live`, so a newer line
 * stops an older one.
 */
export default function SaidLine({ entry, live }: { entry: StoryEntry; live: boolean }) {
  const t = useT();
  const { text, mark } = shownText(entry);
  const speaker = entry.payload.speaker;
  const name = speaker?.name ?? "";
  const mood = MOODS.find((m) => m === entry.payload.mood) ?? "neutral";
  const portrait = speaker?.portrait ?? null;
  const still = reducedMotion();
  const animate = live && !still;
  // The words the portrait says: those shown when the line came in, without their Markdown.
  const [spoken] = useState(() => plainInline(text));
  // Timed only for a line that plays: a long story of lines from history draws them at rest and times none.
  const { talkMs, moodMs } = useMemo(() => {
    if (!animate) return { talkMs: 0, moodMs: 0 };
    if (portrait?.kind !== "traits") return { talkMs: spoken.length * PACE_MS, moodMs: 0 };
    const traits = generate({ describe: portrait.describe, seed: portrait.seed });
    return {
      talkMs: emoteDuration(traits, { emotes: ["talk"], say: spoken }) / SPEECH_RATE,
      moodMs: mood === "neutral" ? 0 : emoteDuration(traits, { emotes: [mood] }),
    };
  }, [animate, portrait?.kind === "traits" && portrait.describe, portrait?.kind === "traits" && portrait.seed, spoken, mood]);
  const [phase, setPhase] = useState<Phase>(animate ? "talk" : "rest");
  const [elapsed, setElapsed] = useState(0);

  useEffect(() => {
    if (!animate) {
      setPhase("rest");
      return;
    }
    const start = Date.now();
    const tick = setInterval(() => {
      const at = Date.now() - start;
      setElapsed(at);
      if (at < talkMs) return;
      if (at < talkMs + moodMs) {
        setPhase("mood");
        return;
      }
      setPhase("rest");
      clearInterval(tick);
    }, TICK_MS);
    return () => clearInterval(tick);
  }, [animate, talkMs, moodMs]);

  // A growing line is cut anywhere, so an emphasis may be open: its asterisks, left unmatched, aren't shown.
  const shown =
    phase === "talk"
      ? renderInline(text.slice(0, Math.floor((text.length * elapsed) / Math.max(talkMs, 1)))).replace(/\*/g, "")
      : renderInline(text);
  const look =
    phase === "talk"
      ? { emotes: ["talk"], say: spoken, once: true }
      : phase === "mood"
        ? { emotes: [mood], once: true }
        : { emotes: still ? [] : [...IDLE_EMOTES] };
  const label = mood === "neutral" ? name : t("story.speakerMood", { name, mood: t(`story.mood.${mood}`) });
  return (
    <div className="entry said" data-live={phase !== "rest"}>
      <Portrait
        campaignId={entry.campaign_id}
        portrait={portrait}
        name={label}
        size={48}
        npc
        rate={phase === "talk" ? SPEECH_RATE : 1}
        {...look}
      />
      <div className="said-line">
        <span className="entry-who">{name}</span>
        {mark && <Marks entry={entry} mark={mark} />}
        <p className="said-text" data-testid="said-text" dangerouslySetInnerHTML={{ __html: shown }} />
      </div>
    </div>
  );
}
