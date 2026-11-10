import { useT } from "../i18n";
import { TableAvatar } from "../profile/ProfileCard";
import type { Seat } from "./api";
import { useVoiceState, type VoiceState } from "./voice/useVoice";
import styles from "./voice/voice.module.css";

export type TypingState = "typing" | "idle";
type Shown = "idle" | "typing" | "submitted";

/**
 * Each acting seat's name with where it is in the beat: idle, typing or submitted (spec §7.1), and whether it is
 * away, with its player's avatar (players and tavern Task G3). Observers don't act, so they aren't shown. A seat in
 * voice is marked in voice, muted or listening only, a mark that lights while it speaks (table voice and fixes Task
 * V2.2): on the mark rather than round the avatar, as a seat without a profile has none.
 */
export default function SeatIndicators({
  seats,
  typing,
  submitted,
  mySeatId,
  away = [],
}: {
  seats: Seat[];
  typing: Record<string, TypingState>;
  submitted: string[];
  mySeatId: string | null;
  /** The seats away mid-session (DEL-224): Stepped away, tab open or not. */
  away?: string[];
}) {
  const t = useT();
  const voice = useVoiceState();
  const acting = seats.filter((s) => s.role !== "observer");
  return (
    <ul className="seat-indicators" data-testid="seat-indicators" aria-label={t("play.seatIndicators")}>
      {acting.map((seat) => {
        const state: Shown = submitted.includes(seat.id) ? "submitted" : typing[seat.id] === "typing" ? "typing" : "idle";
        return (
          <li key={seat.id} data-seat={seat.id} data-state={state} className={seat.present && !away.includes(seat.id) ? undefined : "away"}>
            <span className="seat-dot" aria-hidden="true" />
            <TableAvatar profile={seat.profile} size={22} />
            <span className="seat-name">{seat.id === mySeatId ? t("play.you") : seat.name}</span>
            {/* Not having acted yet is the ordinary state: said only to a screen reader, the dot shows it (DEL-260). */}
            <span className={away.includes(seat.id) || !seat.present || state !== "idle" ? "seat-state" : "seat-state visually-hidden"}>
              {t(
                away.includes(seat.id) ? "play.seatState.steppedAway" : seat.present ? `play.seatState.${state}` : "play.seatState.away",
              )}
            </span>
            <VoiceMark voice={voice} seatId={seat.id} mine={seat.id === mySeatId} />
          </li>
        );
      })}
    </ul>
  );
}

type VoiceShown = { voice: "talk" | "muted" | "listening"; speaking: boolean } | null;

/** How a seat is in voice, as this browser knows it: its own state for its own seat, the relay's for the others. */
function inVoice(voice: VoiceState | null, seatId: string, mine: boolean): VoiceShown {
  if (!voice || !voice.allowed || voice.status !== "in") return null;
  if (mine) return { voice: voice.mode === "listening-only" ? "listening" : voice.muted ? "muted" : "talk", speaking: false };
  const peer = voice.peers[seatId];
  if (!peer) return null;
  return { voice: !peer.talk || peer.listening_only ? "listening" : peer.muted ? "muted" : "talk", speaking: peer.speaking };
}

const VOICE_LABELS = { talk: "voice.inVoice", muted: "voice.muted", listening: "voice.listeningOnly" } as const;

function VoiceMark({ voice, seatId, mine }: { voice: VoiceState | null; seatId: string; mine: boolean }) {
  const t = useT();
  const shown = inVoice(voice, seatId, mine);
  if (!shown) return null;
  const label = t(VOICE_LABELS[shown.voice]);
  return (
    <span
      className={styles.mark}
      data-testid="voice-mark"
      data-voice={shown.voice}
      data-speaking={shown.speaking}
      aria-label={shown.speaking ? `${label}, ${t("voice.speaking")}` : undefined}
    >
      {label}
    </span>
  );
}
