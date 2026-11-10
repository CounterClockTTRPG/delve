import { useT } from "../i18n";
import type { PendingAct } from "./api";

/**
 * The open beat's acts so far (plan 7 Task 17), as the server lets this seat see them: its own first, with Change,
 * then the others' that aren't private, marked draft. An observer gets none, so sees nothing here. At a hotseat
 * (DEL-365) the seat has one act for each of its players, each under the player's name.
 */
export default function PendingActs({
  pending,
  mySeatId,
  names = {},
  onChange,
}: {
  pending: PendingAct[];
  mySeatId: string | null;
  /** Character names by id. */
  names?: Record<string, string>;
  /** Change: the seat's act goes back into the Composer, with its private flag, and its hotseat player's turn. */
  onChange: (act: { text: string; private: boolean; hotseat?: string | null }) => void;
}) {
  const t = useT();
  if (pending.length === 0) return null;
  const mine = pending.filter((p) => p.seat_id === mySeatId);
  const theirs = pending.filter((p) => p.seat_id !== mySeatId);
  return (
    <section className="pending-acts" data-testid="pending-acts" aria-label={t("play.pendingActs")}>
      {mine.map((p) => (
        <div key={p.hotseat ?? "mine"} className="my-act" data-testid="my-act" role="status">
          {p.hotseat && <span className="entry-who">{p.name}</span>}
          <span>{p.kind === "act" ? t("play.myAct", { text: p.text }) : t("play.myPass")}</span>
          {p.private && (
            <span className="only-you" data-testid="private-act">
              {t("play.onlyTheDm")}
            </span>
          )}
          {p.kind === "act" && (
            <button
              type="button"
              className="link-button"
              onClick={() => onChange({ text: p.text, private: p.private, hotseat: p.hotseat ?? null })}
            >
              {t("play.change")}
            </button>
          )}
        </div>
      ))}
      {theirs.length > 0 && (
        <ul className="pending-list">
          {theirs.map((p) => {
            const playing = p.characters.map((id) => names[id]).filter(Boolean);
            return (
              <li key={p.seat_id ?? p.at} className="pending-act" data-testid="pending-act">
                <span className="entry-who">{playing.length > 0 ? `${p.name} · ${playing.join(", ")}` : p.name}</span>
                <span className="pending-draft">{t("play.draft")}</span>
                <span>{p.kind === "act" ? p.text : t("play.passes")}</span>
              </li>
            );
          })}
        </ul>
      )}
    </section>
  );
}
