import { Check } from "lucide-react";
import { useT } from "../i18n";
import type { Hotseat, PendingAct } from "./api";

/** One turn at the hotseat (DEL-365): a hotseat player's (`id`), or the host's own characters besides theirs (`id`
 * null), with the characters it acts for. */
export interface Turn {
  id: string | null;
  name: string;
  characters: string[];
}

/** The turns at this screen, in order, when the hotseat is on and is this seat's: each player's, then the seat's own
 * for the characters it plays that no player does. Null when this screen plays no hotseat. */
export function hotseatTurns(
  hotseat: Hotseat | undefined,
  mySeatId: string | null,
  myCharacters: string[],
  seatName: string,
): Turn[] | null {
  if (!hotseat?.on || hotseat.seat_id === null || hotseat.seat_id !== mySeatId || hotseat.players.length === 0) return null;
  const theirs = new Set(hotseat.players.flatMap((p) => p.characters));
  const rest = myCharacters.filter((id) => !theirs.has(id));
  const turns: Turn[] = hotseat.players.map((p) => ({ id: p.id, name: p.name, characters: p.characters }));
  if (rest.length > 0) turns.push({ id: null, name: seatName, characters: rest });
  return turns;
}

/** The turns this seat has taken in the open beat, an act or a pass each, by their `id` (null: its own). */
export function turnsTaken(pending: PendingAct[], mySeatId: string | null): Set<string | null> {
  return new Set(pending.filter((p) => p.seat_id === mySeatId).map((p) => p.hotseat ?? null));
}

/** The turn after `current` that hasn't been taken, round the table; `current` when every other turn has been. */
export function nextTurn(turns: Turn[], taken: Set<string | null>, current: string | null): string | null {
  const at = turns.findIndex((turn) => turn.id === current);
  for (let step = 1; step < turns.length; step++) {
    const turn = turns[(at + step) % turns.length];
    if (!taken.has(turn.id)) return turn.id;
  }
  return current;
}

/**
 * Whose turn it is at the hotseat, above the Act box: a button for each turn, the current one pressed, a tick on each
 * turn taken in the open beat, and the line under them says whose turn it is ("Pass the screen to Ben." once someone
 * has had theirs). A click hands the box to that player, to act or to change their act.
 */
export default function HotseatTurns({
  turns,
  taken,
  current,
  onPick,
}: {
  turns: Turn[];
  taken: Set<string | null>;
  current: string | null;
  onPick: (id: string | null) => void;
}) {
  const t = useT();
  const now = turns.find((turn) => turn.id === current) ?? turns[0];
  return (
    <section className="hotseat-turns" data-testid="hotseat-turns" aria-label={t("play.hotseatTurns")}>
      <div className="hotseat-turn-buttons" role="group" aria-label={t("play.hotseatTurns")}>
        {turns.map((turn) => (
          <button
            key={turn.id ?? "own"}
            type="button"
            aria-pressed={turn.id === now.id}
            data-testid="hotseat-turn"
            onClick={() => onPick(turn.id)}
          >
            {taken.has(turn.id) && <Check size={14} aria-label={t("play.hotseatHasActed")} />}
            {turn.name}
          </button>
        ))}
      </div>
      <p className="hotseat-now" role="status" data-testid="hotseat-now">
        {/* Once someone has had their turn, the screen goes round to the next. */}
        {t(taken.size > 0 && !taken.has(now.id) ? "play.hotseatNext" : "play.hotseatTurn", { name: now.name })}
      </p>
    </section>
  );
}
