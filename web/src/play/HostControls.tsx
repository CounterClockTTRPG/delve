import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { queryKeys } from "../api";
import { useConfirm } from "../components/dialogs";
import { useT } from "../i18n";
import WriteToTable from "../mail/WriteToTable";
import {
  BEAT_TIMERS,
  FALLBACKS,
  PAID_PER_DAY,
  claimCharacter,
  comeBack,
  getListing,
  getPlaySettings,
  goBeat,
  playKeys,
  putSeat,
  putTableSettings,
  releaseCharacter,
  removeSeat,
  setPart,
  stepAway,
  type AbsentChoice,
  type Fallback,
  type PartyMember,
  type Seat,
  type SeatRole,
  type TableSession,
  type TableSettings,
} from "./api";
import HotseatSetup from "./HotseatSetup";
import InvitePanel from "./InvitePanel";
import JoinRequests from "./JoinRequests";
import NextSessionControls from "./NextSessionControls";

/**
 * What the host and the co-hosts run (spec §7.1, §7.2): Go, the beat timer and its fallback, the requests to join a
 * public table (DEL-204), Write to the table by email (DEL-314), the invite, the seats' roles, and who plays which
 * character; while a session is under way, who is away and the part a character takes while its player doesn't act (DEL-224). Only they see it; the server
 * refuses the rest anyway. Go is always in reach;
 * the invite is folded unless the host is alone at the table, and the rest is folded. Only the host turns paid images
 * on or off, and says how many may be painted a day while they are on (DEL-153); Paint this scene is the composer's,
 * for every seat that acts. The host sets up the hotseat too (DEL-365): the players at their own screen.
 */
export default function HostControls({
  campaignId,
  seats,
  party,
  mySeat,
  beatOpen,
  table: session,
}: {
  campaignId: string;
  seats: Seat[];
  party: PartyMember[];
  mySeat: Pick<Seat, "id" | "role">;
  beatOpen: boolean;
  /** The table's session: away seats and parts are set while it is under way. */
  table?: TableSession;
}) {
  const t = useT();
  const confirm = useConfirm();
  const client = useQueryClient();
  const settings = useQuery({ queryKey: playKeys.settings(campaignId), queryFn: () => getPlaySettings(campaignId) });
  const listing = useQuery({ queryKey: playKeys.listing(campaignId), queryFn: () => getListing(campaignId) });
  const changed = () => {
    client.invalidateQueries({ queryKey: playKeys.seats(campaignId) });
    client.invalidateQueries({ queryKey: queryKeys.characters(campaignId) });
  };

  const go = useMutation({
    mutationFn: () => goBeat(campaignId),
    onSettled: () => client.invalidateQueries({ queryKey: playKeys.state(campaignId) }),
  });
  const table = useMutation({
    mutationFn: (patch: Partial<TableSettings>) => putTableSettings(campaignId, patch),
    onSuccess: (saved) => client.setQueryData(playKeys.settings(campaignId), saved),
  });
  const role = useMutation({
    mutationFn: ({ seat, to }: { seat: string; to: SeatRole }) => putSeat(campaignId, seat, { role: to }),
    onSettled: changed,
  });
  const give = useMutation({
    mutationFn: async ({ character, from, to }: { character: string; from: string | null; to: string | null }) => {
      // A character another seat plays is let go first: claiming it would be refused.
      if (from) await releaseCharacter(campaignId, character);
      if (to) await claimCharacter(campaignId, character, to);
    },
    onSettled: changed,
  });

  // Away mid-session and the characters' parts (DEL-224): the table's state is read again.
  const refreshTable = () => client.invalidateQueries({ queryKey: playKeys.state(campaignId) });
  const away = useMutation({
    mutationFn: ({ seat, back }: { seat: string; back: boolean }) =>
      back ? comeBack(campaignId, seat) : stepAway(campaignId, null, seat),
    onSettled: refreshTable,
  });
  const part = useMutation({
    mutationFn: ({ character, to }: { character: string; to: AbsentChoice | null }) => setPart(campaignId, character, to),
    onSettled: refreshTable,
  });

  // Remove from the table (DEL-204): the seat leaves as if it had left itself, its characters free again.
  const remove = useMutation({
    mutationFn: (seat: string) => removeSeat(campaignId, seat),
    onSettled: () => {
      changed();
      client.invalidateQueries({ queryKey: playKeys.listing(campaignId) });
    },
  });

  async function removeFromTable(seat: Seat) {
    const sure = await confirm({
      title: t("play.removeTitle", { name: seat.name }),
      body: t("play.removeBody"),
      confirm: t("play.removeConfirm"),
      danger: true,
    });
    if (sure) remove.mutate(seat.id);
  }

  async function handOver(seat: Seat) {
    const sure = await confirm({
      title: t("play.handOverTitle", { name: seat.name }),
      body: t("play.handOverBody"),
      confirm: t("play.handOverConfirm"),
    });
    if (sure) role.mutate({ seat: seat.id, to: "host" });
  }

  // The host is alone while no other seat is present: then the invite is what they need, open.
  const alone = !seats.some((s) => s.id !== mySeat.id && s.present);
  const playedBy = (characterId: string) => seats.find((s) => s.characters.includes(characterId))?.id ?? null;
  const actors = seats.filter((s) => s.role !== "observer");
  const current = settings.data;
  const error = go.error ?? table.error ?? role.error ?? give.error ?? remove.error ?? away.error ?? part.error;
  const underWay = session !== undefined && session.state !== "gathering";
  const awaySeats = new Set(session?.away.map((a) => a.seat_id) ?? []);

  return (
    <section className="host-controls" data-testid="host-controls" aria-label={t("play.hostControls")}>
      {/* Go stays in reach; the invite and the rest fold away, so the party and the map stay near. */}
      <button
        type="button"
        className="primary host-go"
        data-testid="go"
        disabled={!beatOpen || go.isPending}
        title={t("play.goHint")}
        onClick={() => go.mutate()}
      >
        {t("play.go")}
      </button>

      <NextSessionControls campaignId={campaignId} schedule={listing.data?.schedule} sessions={listing.data?.next_sessions} />

      <WriteToTable campaignId={campaignId} seats={seats} mySeatId={mySeat.id} />

      <JoinRequests campaignId={campaignId} full={listing.data ? listing.data.slots !== null && listing.data.taken >= listing.data.slots : false} />

      <details className="host-fold" data-testid="host-invite" open={alone}>
        <summary>{t("play.invite")}</summary>
        <InvitePanel campaignId={campaignId} />
      </details>

      <details className="host-fold host-table" data-testid="host-table">
        <summary>{t("play.hostControls")}</summary>
        <div className="host-beat">
          <label htmlFor="host-timer">{t("play.beatTimer")}</label>
          <select
            id="host-timer"
            data-testid="host-timer"
            value={current?.beat_timer_s ?? ""}
            disabled={!current}
            onChange={(e) => table.mutate({ beat_timer_s: e.target.value ? Number(e.target.value) : null })}
          >
            {current?.beat_timer_s && !(BEAT_TIMERS as readonly (number | null)[]).includes(current.beat_timer_s) && (
              <option value={current.beat_timer_s}>{t("play.timer.minutes", { count: String(current.beat_timer_s / 60) })}</option>
            )}
            {BEAT_TIMERS.map((seconds) => (
              <option key={seconds ?? "none"} value={seconds ?? ""}>
                {seconds === null ? t("play.timer.none") : t("play.timer.minutes", { count: String(seconds / 60) })}
              </option>
            ))}
          </select>
          <label htmlFor="host-fallback">{t("play.fallback")}</label>
          <select
            id="host-fallback"
            data-testid="host-fallback"
            value={current?.fallback ?? "hold_back"}
            disabled={!current}
            onChange={(e) => table.mutate({ fallback: e.target.value as Fallback })}
          >
            {FALLBACKS.map((fallback) => (
              <option key={fallback} value={fallback}>
                {t(`play.fallback.${fallback}`)}
              </option>
            ))}
          </select>
          <p className="hint">{t("play.fallbackHint")}</p>
          {mySeat.role === "host" && (
            <label className="host-paid">
              <input
                type="checkbox"
                checked={current?.paid_images ?? false}
                disabled={!current || table.isPending}
                onChange={(e) => table.mutate({ paid_images: e.target.checked })}
              />
              {t("play.paidImages")}
            </label>
          )}
          {mySeat.role === "host" && current?.paid_images && (
            <>
              <label htmlFor="host-paid-per-day">{t("play.paidPerDay")}</label>
              <select
                id="host-paid-per-day"
                data-testid="host-paid-per-day"
                value={current.paid_images_per_day ?? 20}
                disabled={table.isPending}
                onChange={(e) => table.mutate({ paid_images_per_day: Number(e.target.value) })}
              >
                {current.paid_images_per_day && !(PAID_PER_DAY as readonly number[]).includes(current.paid_images_per_day) && (
                  <option value={current.paid_images_per_day}>{current.paid_images_per_day}</option>
                )}
                {PAID_PER_DAY.map((n) => (
                  <option key={n} value={n}>
                    {n}
                  </option>
                ))}
              </select>
            </>
          )}
        </div>
        {mySeat.role === "host" && <p className="hint">{t("play.paidImagesHint")}</p>}
        {mySeat.role === "host" && current?.paid_images && <p className="hint">{t("play.paidPerDayHint")}</p>}

        {/* Several players at the host's own screen (DEL-365): the screen is the host's, so the setup is theirs. */}
        {mySeat.role === "host" && (
          <HotseatSetup
            settings={current}
            party={party}
            free={new Set(party.filter((m) => [null, mySeat.id].includes(playedBy(m.id))).map((m) => m.id))}
            busy={table.isPending}
            onChange={(patch) => table.mutate(patch)}
          />
        )}

        <h3>{t("play.seatsHeading")}</h3>
        <ul className="host-seats">
          {seats
            .filter((s) => s.id !== mySeat.id)
            .map((seat) => (
              <li key={seat.id} data-testid={`seat-row-${seat.id}`}>
                <span className="seat-name">{seat.name}</span>
                <span className="seat-role">{t(`play.role.${seat.role}`)}</span>
                <span className="seat-actions">
                  {seat.role === "player" && (
                    <button type="button" onClick={() => role.mutate({ seat: seat.id, to: "cohost" })}>
                      {t("play.makeCoHost")}
                    </button>
                  )}
                  {(seat.role === "cohost" || seat.role === "observer") && (
                    <button type="button" onClick={() => role.mutate({ seat: seat.id, to: "player" })}>
                      {t("play.makePlayer")}
                    </button>
                  )}
                  {seat.role === "player" && (
                    <button type="button" onClick={() => role.mutate({ seat: seat.id, to: "observer" })}>
                      {t("play.makeObserver")}
                    </button>
                  )}
                  {underWay && seat.role !== "observer" && (
                    <button type="button" data-testid={`mark-away-${seat.id}`} disabled={away.isPending}
                      onClick={() => away.mutate({ seat: seat.id, back: awaySeats.has(seat.id) })}>
                      {t(awaySeats.has(seat.id) ? "play.markBack" : "play.markAway")}
                    </button>
                  )}
                  {mySeat.role === "host" && seat.role !== "observer" && (
                    <button type="button" onClick={() => void handOver(seat)}>
                      {t("play.handOver")}
                    </button>
                  )}
                  {seat.role !== "host" && (mySeat.role === "host" || seat.role !== "cohost") && (
                    <button type="button" className="danger" data-testid={`remove-${seat.id}`} disabled={remove.isPending}
                      onClick={() => void removeFromTable(seat)}>
                      {t("play.remove")}
                    </button>
                  )}
                </span>
              </li>
            ))}
        </ul>

        {party.length > 0 && (
          <>
            <h3>{t("play.charactersHeading")}</h3>
            <ul className="host-characters">
              {party.map((member) => {
                const from = playedBy(member.id);
                return (
                  <li key={member.id}>
                    <label htmlFor={`plays-${member.id}`}>{member.name}</label>
                    <select
                      id={`plays-${member.id}`}
                      aria-label={t("play.whoPlays", { name: member.name })}
                      value={from ?? ""}
                      disabled={give.isPending}
                      onChange={(e) => give.mutate({ character: member.id, from, to: e.target.value || null })}
                    >
                      <option value="">{t("play.nobody")}</option>
                      {actors.map((seat) => (
                        <option key={seat.id} value={seat.id}>
                          {seat.name}
                        </option>
                      ))}
                    </select>
                  </li>
                );
              })}
            </ul>
          </>
        )}

        {underWay && party.length > 0 && (
          <>
            <h3>{t("play.partsHeading")}</h3>
            <p className="hint">{t("play.partsHint")}</p>
            <ul className="host-characters host-parts" data-testid="host-parts">
              {party.map((member) => (
                <li key={member.id}>
                  <label htmlFor={`part-${member.id}`}>{member.name}</label>
                  <select
                    id={`part-${member.id}`}
                    aria-label={t("play.partOf", { name: member.name })}
                    value={session.absent[member.id] ?? ""}
                    disabled={part.isPending}
                    onChange={(e) => part.mutate({ character: member.id, to: (e.target.value || null) as AbsentChoice | null })}
                  >
                    <option value="">{t("play.part.player")}</option>
                    {(["in_character", "hold_back", "out"] as const).map((choice) => (
                      <option key={choice} value={choice}>
                        {t(`play.part.${choice}`)}
                      </option>
                    ))}
                  </select>
                </li>
              ))}
            </ul>
          </>
        )}
      </details>

      {error && (
        <p className="notice error" role="alert">
          {error.message}
        </p>
      )}
    </section>
  );
}
