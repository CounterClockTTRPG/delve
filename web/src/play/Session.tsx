import * as Dialog from "@radix-ui/react-dialog";
import { CircleStop, Coffee, Hand } from "lucide-react";
import { useState } from "react";
import { useConfirm } from "../components/dialogs";
import { useLanguage, useT } from "../i18n";
import { TableAvatar } from "../profile/ProfileCard";
import type { AbsentChoice, PartyMember, RaisedHand, Seat, TableSession } from "./api";
import { shortWhen } from "./Story";
import "./talk.css";

const CHOICES: AbsentChoice[] = ["in_character", "hold_back", "out"];

/**
 * The host's and co-hosts' session buttons in the play header (DEL-199): Start the session while the table gathers,
 * Take a break and End the session in play, Back to the story and End the session on a break. A solo table has End
 * the session alone, in play: its first act starts the session, and there is nobody to take a break with. End asks first, and
 * waits while a beat is open (the DM ends the session in a beat of its own: say go first). Start opens `StartDialog`.
 */
export function SessionControls({
  table,
  seats,
  party,
  busy,
  beatOpen = false,
  onStart,
  onBreak,
  onResume,
  onEnd,
}: {
  table: TableSession;
  seats: Seat[];
  party: PartyMember[];
  busy: boolean;
  /** A beat is open: End the session waits for it. */
  beatOpen?: boolean;
  onStart: (absent: Record<string, AbsentChoice>) => void;
  onBreak: () => void;
  onResume: () => void;
  onEnd: () => void;
}) {
  const t = useT();
  const confirm = useConfirm();
  const [starting, setStarting] = useState(false);
  if (table.solo && table.state !== "playing") return null;

  async function end() {
    const sure = await confirm({ title: t("session.endTitle"), body: t("session.endBody"), confirm: t("session.end") });
    if (sure) onEnd();
  }

  return (
    <div className="session-controls" data-testid="session-controls">
      {table.state === "gathering" && !table.solo && (
        <button type="button" className="primary" data-testid="session-start" disabled={busy} onClick={() => setStarting(true)}>
          {t("session.start")}
        </button>
      )}
      {table.state === "playing" && !table.solo && (
        <button
          type="button"
          data-testid="session-break"
          disabled={busy}
          aria-label={t("session.break")}
          title={t("session.break")}
          onClick={onBreak}
        >
          <Coffee size={16} aria-hidden="true" /> <span className="phone-hidden-label">{t("session.break")}</span>
        </button>
      )}
      {table.state === "break" && (
        <button type="button" className="primary" data-testid="session-resume" disabled={busy} onClick={onResume}>
          {t("session.resume")}
        </button>
      )}
      {table.state !== "gathering" && (
        // On a phone the icon alone, named for screen readers and on hover (DEL-317).
        <button
          type="button"
          data-testid="session-end"
          disabled={busy || beatOpen}
          aria-label={t("session.end")}
          title={beatOpen ? t("session.endWaits") : t("session.end")}
          onClick={() => void end()}
        >
          <CircleStop size={16} aria-hidden="true" /> <span className="phone-hidden-label">{t("session.end")}</span>
        </button>
      )}
      {starting && (
        <StartDialog
          seats={seats}
          party={party}
          onStart={(absent) => {
            setStarting(false);
            onStart(absent);
          }}
          onClose={() => setStarting(false)}
        />
      )}
    </div>
  );
}

/**
 * Start the session: who is at the table, and for each character of a player who isn't, what becomes of it this
 * session: the DM plays it until its player comes, it stays in the background, or it sits the session out.
 */
export function StartDialog({
  seats,
  party,
  onStart,
  onClose,
}: {
  seats: Seat[];
  party: PartyMember[];
  onStart: (absent: Record<string, AbsentChoice>) => void;
  onClose: () => void;
}) {
  const t = useT();
  const names = new Map(party.map((m) => [m.id, m.name]));
  const acting = seats.filter((s) => s.role !== "observer");
  const away = acting.filter((s) => !s.present);
  const theirs = away.flatMap((s) => s.characters.filter((id) => names.has(id)));
  const [choices, setChoices] = useState<Record<string, AbsentChoice>>(() =>
    Object.fromEntries(theirs.map((id) => [id, "in_character" as AbsentChoice])),
  );

  return (
    <Dialog.Root open onOpenChange={(isOpen) => isOpen || onClose()}>
      <Dialog.Portal>
        <Dialog.Overlay className="dialog-overlay" />
        <Dialog.Content className="dialog start-dialog" data-testid="start-dialog" aria-describedby="start-about">
          <Dialog.Title className="dialog-title">{t("session.start")}</Dialog.Title>
          <p id="start-about" className="dialog-body">
            {t("session.startAbout")}
          </p>
          <ul className="start-seats">
            {acting.map((seat) => {
              const pcs = seat.characters.filter((id) => names.has(id));
              const played = pcs.map((id) => names.get(id)).join(", ");
              return (
                <li key={seat.id} className={seat.present ? "here" : "away"} data-seat={seat.id}>
                  <TableAvatar profile={seat.profile} size={28} name={seat.name} />
                  {seat.present || pcs.length === 0 ? (
                    <>
                      <span className="start-who">
                        <strong>{seat.name}</strong>
                        {played && `, ${played}`}
                      </span>
                      <span className="start-here">{t(seat.present ? "session.here" : "session.away")}</span>
                    </>
                  ) : (
                    <div className="start-away">
                      {pcs.map((id) => (
                        <fieldset key={id}>
                          <legend>{t("session.awayWith", { who: seat.name, character: names.get(id) ?? "" })}</legend>
                          {CHOICES.map((choice) => (
                            <label key={choice}>
                              <input
                                type="radio"
                                name={`absent-${id}`}
                                value={choice}
                                checked={choices[id] === choice}
                                onChange={() => setChoices((was) => ({ ...was, [id]: choice }))}
                              />
                              {t(`session.absent.${choice}`, { character: names.get(id) ?? "", who: seat.name })}
                            </label>
                          ))}
                        </fieldset>
                      ))}
                    </div>
                  )}
                </li>
              );
            })}
          </ul>
          <div className="dialog-actions">
            <Dialog.Close asChild>
              <button type="button">{t("session.notYet")}</button>
            </Dialog.Close>
            <button type="button" className="primary" data-testid="start-confirm" onClick={() => onStart(choices)}>
              {t("session.start")}
            </button>
          </div>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}

/**
 * What the story column says while the table isn't playing: gathering (how many players are here, and that the host
 * starts the session; at a solo table, that the first act starts it) or on a break (the story waits where it stopped).
 */
export function SessionNotice({ table, seats, runsTheTable }: { table: TableSession; seats: Seat[]; runsTheTable: boolean }) {
  const t = useT();
  if (table.state === "playing") return null;
  const acting = seats.filter((s) => s.role !== "observer");
  const here = acting.filter((s) => s.present).length;
  const gathering = table.state === "gathering";
  return (
    <section className="session-notice" data-testid="session-notice" data-state={table.state} role="status">
      <h2>{t(gathering ? "session.gathering" : "session.onBreak")}</h2>
      <p>
        {gathering
          ? table.solo
            ? t("session.soloStarts")
            : `${t("session.hereCount", { n: String(here), total: String(acting.length) })} ${t(runsTheTable ? "session.youStart" : "session.hostStarts")}`
          : t("session.breakAbout")}
      </p>
    </section>
  );
}

/** Why Act waits, for the composer: the session hasn't started, or the table is on a break; null when it can act. */
export function actBlocked(t: ReturnType<typeof useT>, table: TableSession | undefined): string | null {
  if (!table) return null;
  if (table.state === "gathering" && !table.solo) return t("session.actWaitsStart");
  if (table.state === "break") return t("session.actWaitsBreak");
  return null;
}

/**
 * The hands raised at the table (DEL-199), in a strip of their own at the top of the side column (the phone's Table
 * screen), so they are seen whichever tab is open and when the talk is folded: who, since when, and the point they
 * want to make before anyone acts. A seat lowers its own hand; the host and co-hosts lower anyone's and can take a
 * break from here.
 */
export function RaisedHands({
  hands,
  seats,
  mySeatId,
  runsTheTable,
  playing,
  onLower,
  onBreak,
}: {
  hands: RaisedHand[];
  seats: Seat[];
  mySeatId: string | null;
  runsTheTable: boolean;
  playing: boolean;
  onLower: (seatId: string) => void;
  onBreak: () => void;
}) {
  const t = useT();
  const language = useLanguage();
  if (hands.length === 0) return null;
  const names = new Map(seats.map((s) => [s.id, s.name]));
  return (
    <section className="raised-hands" data-testid="raised-hands" role="status" aria-label={t("hands.title")}>
      <Hand size={20} aria-hidden="true" className="raised-hands-icon" />
      <ul>
        {hands.map((hand) => (
          <li key={hand.seat_id} data-seat={hand.seat_id}>
            <span className="raised-who">
              <strong>{hand.seat_id === mySeatId ? t("play.you") : (names.get(hand.seat_id) ?? "")}</strong>{" "}
              {t("hands.raised", { when: shortWhen(hand.at, language) })}
            </span>
            {hand.point && <span className="raised-point">{hand.point}</span>}
            {(hand.seat_id === mySeatId || runsTheTable) && (
              <button type="button" className="raised-lower" onClick={() => onLower(hand.seat_id)}>
                {t("hands.lower")}
              </button>
            )}
          </li>
        ))}
      </ul>
      {runsTheTable && playing && (
        <button type="button" className="raised-break" data-testid="hands-break" onClick={onBreak}>
          {t("session.break")}
        </button>
      )}
    </section>
  );
}

/** The line by the Act box while hands are up: someone wants a word before anyone acts. */
/** By the Act box while this seat is away mid-session (DEL-224): the table plays on, and I'm back. Acting or passing
 * brings the seat back too. */
export function AwayLine({ onBack, busy }: { onBack: () => void; busy?: boolean }) {
  const t = useT();
  return (
    <p className="hands-line away-line" data-testid="away-line" role="note">
      <Coffee size={15} aria-hidden="true" /> {t("play.awayLine")}{" "}
      <button type="button" className="link-button" data-testid="im-back" disabled={busy} onClick={onBack}>
        {t("play.imBack")}
      </button>
    </p>
  );
}

export function HandsLine({ hands, seats, mySeatId }: { hands: RaisedHand[]; seats: Seat[]; mySeatId: string | null }) {
  const t = useT();
  const others = hands.filter((h) => h.seat_id !== mySeatId);
  if (others.length === 0) return null;
  const names = new Map(seats.map((s) => [s.id, s.name]));
  const who = others.map((h) => names.get(h.seat_id) ?? "").join(", ");
  return (
    <p className="hands-line" data-testid="hands-line" role="note">
      <Hand size={15} aria-hidden="true" /> {t(others.length === 1 ? "hands.beforeActingOne" : "hands.beforeActingMany", { who })}
    </p>
  );
}
