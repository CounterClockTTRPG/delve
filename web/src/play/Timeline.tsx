/**
 * The initiative timeline above the story (table voice and fixes Task B2.3): the fight's round, its order along
 * the initiative counts and its ongoing actions, as `GET /api/campaigns/{id}/timeline` shows them to this seat; a thin
 * row on a phone, scrolling sideways. Each combatant stands at the count it acts on, so two on one count stand
 * together; an ongoing action is a span to the count it completes on, running off the end when it lasts into the next
 * round. Who acted, went down, died or fled shows once the DM has told the round. Nothing renders without a fight.
 * The strip folds to its round, and can hide the enemies out of the fight (DEL-130); this browser remembers both.
 * A token is a framed square in its side's colour (DEL-275): a character's shows its portrait, with a bar of its hit
 * points left under it (DEL-10), and a monster's the picture of its kind when the install has one, else its initial;
 * a portrait or a picture enlarges on a click. The one acting stands raised and lit, those who acted are dimmed. The
 * table never sees an enemy's hit points. An organiser sees Paint on a monster without a picture: painted once, it is
 * every table's.
 */
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { ChevronDown, ChevronUp, Eye, EyeOff, Paintbrush } from "lucide-react";
import { useContext, useEffect, useState, type CSSProperties } from "react";
import { safeStorage } from "../desktop/storage";
import { EventsContext } from "../api";
import Portrait from "../components/Portrait";
import { MonsterFace, PaintMonster } from "../monsters/MonsterPictures";
import { useT, type Translate } from "../i18n";
import {
  TIMELINE_EVENTS,
  byCount,
  getTimeline,
  initial,
  outOfTheRound,
  raised,
  spans,
  timelineKey,
  type TimelineOngoing,
  type TimelineSlot,
} from "./timeline";
import styles from "./Timeline.module.css";
import { HP_COLOURS, hpLeft, hpTone, type TokenFace } from "./tokenFaces";

/** "casting *Sleep*", or for an enemy only its kind ("casting a spell"). */
function doing(t: Translate, ongoing: TimelineOngoing) {
  if (ongoing.what === null) return <>{t(`timeline.busy.${ongoing.kind}`)}</>;
  const [before, after = ""] = t(ongoing.kind === "spell" ? "timeline.casting" : `timeline.doing.${ongoing.kind}`, { what: "\u0000" }).split("\u0000");
  return (
    <>
      {before}
      <em>{ongoing.what}</em>
      {after}
    </>
  );
}

/** How the span ends: on its count, in the next round, done or broken (and why, when this seat may know). */
function ending(t: Translate, ongoing: TimelineOngoing): string {
  if (ongoing.state === "interrupted")
    return ongoing.reason ? t("timeline.interruptedBecause", { reason: ongoing.reason }) : t("timeline.interrupted");
  if (ongoing.state === "completed") return t("timeline.completed");
  return ongoing.next_round ? t("timeline.nextRound") : t("timeline.until", { count: String(ongoing.to) });
}

/** A switch this browser remembers. */
function useRemembered(key: string): [boolean, (on: boolean) => void] {
  const [on, setOn] = useState(() => safeStorage.getItem(key) === "1");
  return [
    on,
    (next) => {
      setOn(next);
      safeStorage.setItem(key, next ? "1" : "0");
    },
  ];
}

const OUT_OF_THE_FIGHT = new Set(["down", "dead", "fled"]);

/** An enemy down, dead or fled: what "Hide enemies out of the fight" leaves out. */
const outOfTheFight = (slot: TimelineSlot) => slot.side === "enemy" && OUT_OF_THE_FIGHT.has(slot.state);

/** The hit points left, a bar under the token's frame. */
function HpBar({ left }: { left: number }) {
  return (
    <span className={styles.hp} aria-hidden="true" data-hp-left={Math.round(left * 100) / 100}>
      <span style={{ width: `${Math.round(left * 1000) / 10}%`, background: HP_COLOURS[hpTone(left)] }} />
    </span>
  );
}

function Token({
  slot,
  t,
  campaignId,
  face,
  canPaint,
}: {
  slot: TimelineSlot;
  t: Translate;
  campaignId: string;
  face?: TokenFace;
  canPaint: boolean;
}) {
  const name = slot.name ?? t("timeline.unseen");
  const marked = slot.state !== "waiting" && slot.state !== "acting";
  const left = hpLeft(face);
  const monster = slot.monster;
  // A character's portrait, else its kind's picture (DEL-275), else its initial; the first two enlarge on a click.
  const shown = face?.portrait ? "portrait" : monster?.picture ? "monster" : undefined;
  return (
    <li className={styles.token} data-side={slot.side} data-state={slot.state} data-testid={`timeline-slot-${slot.key}`}>
      <span className={styles.frame} data-face={shown} data-unseen={slot.name === null || undefined}>
        {face?.portrait ? (
          <Portrait campaignId={campaignId} portrait={face.portrait} name={name} size={FACE_SIZE} />
        ) : monster?.picture ? (
          <MonsterFace name={name} slug={monster.picture} version={monster.version} size={FACE_SIZE} />
        ) : (
          <span className={styles.initial} aria-hidden="true">
            {initial(slot)}
          </span>
        )}
        {!shown && monster && canPaint && (
          <PaintMonster
            name={monster.kind}
            campaignId={campaignId}
            trigger={(open) => (
              <button
                type="button"
                className={styles.paint}
                data-painting={monster.painting || undefined}
                aria-label={t(monster.painting ? "monsters.paintingNow" : "monsters.paintOne", { name: monster.kind })}
                title={t(monster.painting ? "monsters.paintingNow" : "monsters.paintOne", { name: monster.kind })}
                onClick={open}
              >
                <Paintbrush size={11} aria-hidden="true" />
              </button>
            )}
          />
        )}
      </span>
      {left !== null && <HpBar left={left} />}
      <span className={styles.name} title={name}>
        {name}
      </span>
      {marked && <span className={styles.mark}>{t(`timeline.state.${slot.state}`)}</span>}
    </li>
  );
}

/** A face's size in px inside the frame; the CSS sizes the frame, so a phone's smaller chip scales it down. */
const FACE_SIZE = 48;

const NO_FACES: Record<string, TokenFace> = {};

export default function Timeline({
  campaignId,
  phone,
  faces = NO_FACES,
  canPaint = false,
}: {
  campaignId: string;
  phone: boolean;
  /** The party's faces by character id: their portraits and hit points. */
  faces?: Record<string, TokenFace>;
  /** An organiser's: a monster without a picture offers Paint (DEL-275). */
  canPaint?: boolean;
}) {
  const t = useT();
  const token = (slot: TimelineSlot) => (
    <Token
      key={slot.key}
      slot={slot}
      t={t}
      campaignId={campaignId}
      face={slot.character_id ? faces[slot.character_id] : undefined}
      canPaint={canPaint}
    />
  );
  const client = useQueryClient();
  const subscribe = useContext(EventsContext);
  const timeline = useQuery({ queryKey: timelineKey(campaignId), queryFn: () => getTimeline(campaignId) });

  // The events say only that the timeline changed: it is read again, as this seat may see it.
  useEffect(() => {
    const again = (data: unknown) => {
      if ((data as { campaign_id?: unknown } | null)?.campaign_id === campaignId)
        client.invalidateQueries({ queryKey: timelineKey(campaignId) });
    };
    return subscribe(Object.fromEntries(TIMELINE_EVENTS.map((type) => [type, again])));
  }, [subscribe, client, campaignId]);

  const [folded, setFolded] = useRemembered("delve.timeline.folded");
  const [hideOut, setHideOut] = useRemembered("delve.timeline.hideOut");

  const fight = timeline.data?.fight;
  if (!fight) return null;
  const hidden = fight.slots.filter(outOfTheFight).length;
  const slots = hideOut ? fight.slots.filter((slot) => !outOfTheFight(slot)) : fight.slots;
  const groups = byCount(slots);
  const up = raised(groups);
  const busy = spans(slots);
  const down = outOfTheRound(slots);
  const acting = fight.slots.find((slot) => slot.state === "acting");
  const fold = (
    <button
      type="button"
      className={`icon ${styles.tool}`}
      aria-expanded={!folded}
      aria-label={t(folded ? "timeline.unfold" : "timeline.fold")}
      title={t(folded ? "timeline.unfold" : "timeline.fold")}
      onClick={() => setFolded(!folded)}
    >
      {folded ? <ChevronDown size={16} aria-hidden="true" /> : <ChevronUp size={16} aria-hidden="true" />}
    </button>
  );
  const hide = (
    <button
      type="button"
      className={`icon ${styles.tool}`}
      aria-pressed={hideOut}
      aria-label={t("timeline.hideOut")}
      title={t("timeline.hideOut")}
      onClick={() => setHideOut(!hideOut)}
    >
      {hideOut ? <EyeOff size={16} aria-hidden="true" /> : <Eye size={16} aria-hidden="true" />}
      {hideOut && hidden > 0 && <span className={styles.hidden}>{hidden}</span>}
    </button>
  );
  const tools = (
    <span className={styles.tools}>
      {!folded && (hidden > 0 || hideOut) && hide}
      {fold}
    </span>
  );
  const head = (
    <div className={styles.head}>
      <span className={styles.medallion} aria-hidden="true">
        {fight.round}
      </span>
      <span className={styles.round}>{t("timeline.round", { round: String(fight.round) })}</span>
      {acting && <span className={styles.note}>{t("timeline.acting", { name: acting.name ?? t("timeline.unseen") })}</span>}
      {fight.mode === "side" && <span className={styles.note}>{t("timeline.perSide")}</span>}
      {!folded && !fight.released && fight.slots.some((s) => s.state === "waiting") && !phone && (
        <span className={styles.note}>{t("timeline.untold")}</span>
      )}
      {tools}
    </div>
  );

  if (folded) {
    return (
      <section
        className={`${styles.strip} ${phone ? styles.phone : ""}`}
        aria-label={t("timeline.label")}
        data-testid="timeline"
        data-folded
      >
        {head}
      </section>
    );
  }

  if (phone) {
    return (
      <section className={`${styles.strip} ${styles.phone}`} aria-label={t("timeline.label")} data-testid="timeline">
        <ol className={styles.row} data-layout="row">
          <li className={styles.rowRound}>{t("timeline.round", { round: String(fight.round) })}</li>
          <li className={styles.rowTools}>{tools}</li>
          {groups.map((group) => (
            <li key={group.count} className={styles.chip} data-count={group.count}>
              <span className={styles.count}>{group.count}</span>
              <ul className={styles.stack}>
                {group.slots.map(token)}
              </ul>
              {group.slots
                .filter((slot) => slot.ongoing)
                .map((slot) => (
                  <span
                    key={slot.key}
                    className={styles.mini}
                    data-state={slot.ongoing!.state}
                    title={slot.ongoing!.reason ?? undefined}
                  >
                    {doing(t, slot.ongoing!)} · {ending(t, slot.ongoing!)}
                  </span>
                ))}
            </li>
          ))}
          {down.length > 0 && (
            <li className={styles.chip}>
              <ul className={styles.stack}>
                {down.map(token)}
              </ul>
            </li>
          )}
        </ol>
      </section>
    );
  }

  const columns = { gridTemplateColumns: `repeat(${fight.max_count}, minmax(3.1rem, 1fr))` } as CSSProperties;
  return (
    <section className={styles.strip} aria-label={t("timeline.label")} data-testid="timeline" data-layout="axis">
      {head}
      <div className={styles.scroll}>
        <div className={styles.axis} style={columns}>
          {Array.from({ length: fight.max_count }, (_, i) => (
            <span key={i} className={styles.tick} style={{ gridColumn: i + 1, gridRow: 1 }} aria-hidden="true">
              {i + 1}
            </span>
          ))}
          {groups.map((group) => (
            <ul
              key={group.count}
              className={styles.stack}
              style={{ gridColumn: group.count, gridRow: 2 }}
              data-count={group.count}
              data-raised={up.has(group.count) || undefined}
              aria-label={t("timeline.count", { count: String(group.count) })}
            >
              {group.slots.map(token)}
            </ul>
          ))}
          {busy.map((slot, i) => {
            // The span's row runs to the axis's end, so its words can be read; its bar covers its counts only.
            const { from, to, next_round } = slot.ongoing;
            const covered = next_round ? 100 : ((to - from + 1) / (fight.max_count - from + 1)) * 100;
            const style = { gridColumn: `${from} / ${fight.max_count + 1}`, gridRow: 3 + i, "--covered": `${covered}%` };
            return (
              <div
                key={slot.key}
                className={styles.span}
                style={style as CSSProperties}
                data-side={slot.side}
                data-state={slot.ongoing.state}
                data-from={from}
                data-to={to}
                data-next-round={next_round || undefined}
                data-testid={`timeline-span-${slot.key}`}
              >
                <span className={styles.who}>{slot.name ?? t("timeline.unseen")}</span>
                <span className={styles.doing}>{doing(t, slot.ongoing)}</span>
                <span className={styles.end}>{ending(t, slot.ongoing)}</span>
              </div>
            );
          })}
        </div>
      </div>
      {down.length > 0 && (
        <div className={styles.downRow}>
          <span className={styles.downLabel} aria-hidden="true">
            {t("timeline.outOfTheRound")}
          </span>
          <ul className={`${styles.stack} ${styles.down}`} aria-label={t("timeline.outOfTheRound")}>
            {down.map(token)}
          </ul>
        </div>
      )}
    </section>
  );
}
