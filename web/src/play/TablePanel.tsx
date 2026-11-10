import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { boardKeys, createZone, getBoard, zoneOfCampaign } from "../board/api";
import { sayError } from "../board/show";
import { useConfirm } from "../components/dialogs";
import { useT } from "../i18n";
import { TableAvatar } from "../profile/ProfileCard";
import { getListing, leaveTable, playKeys, type Seat } from "./api";
import TableAbout from "./TableAbout";

/** The campaign's name as a zone's name, of at most 80 characters; "" for none (before the campaign is loaded). */
const zoneName = (name: string) => name.trim().slice(0, 80).trim();

/**
 * The table: who sits at it, and Leave the table. The Table tab beside the story, with the host's controls after it;
 * on a phone, the Table screen under the talk. Each seat shows its player's avatar, which opens their profile card
 * (players and tavern Task G3). Under the seats, what the table tells its players: its description, its places and its
 * house rules (DEL-204). Beside them the Board link: the table's own zone on the message board (DEL-297), which its host
 * may make when there is none. The talk has a place of its own (`TalkPanel`, DEL-199).
 */
export default function TablePanel({
  campaignId,
  campaignName,
  seats,
  mySeat,
  onLeft,
}: {
  campaignId: string;
  /** The zone the host makes is named for the table ("Table" while the name is unknown). */
  campaignName: string;
  seats: Seat[];
  mySeat: Pick<Seat, "id" | "role">;
  onLeft: () => void;
}) {
  const t = useT();
  const confirm = useConfirm();
  const leave = useMutation({ mutationFn: () => leaveTable(campaignId), onSuccess: onLeft });
  const client = useQueryClient();
  const board = useQuery({ queryKey: boardKeys.all, queryFn: getBoard });
  const tableZone = zoneOfCampaign(board.data, campaignId);
  const makeZone = useMutation({
    mutationFn: () => createZone({ name: zoneName(campaignName) || t("play.table"), read: "table", write: "table", campaign_id: campaignId }),
    onSuccess: () => client.invalidateQueries({ queryKey: boardKeys.all }),
  });
  const listing = useQuery({ queryKey: playKeys.listing(campaignId), queryFn: () => getListing(campaignId) });

  async function leaveTheTable() {
    const sure = await confirm({ title: t("play.leaveTitle"), body: t("play.leaveBody"), confirm: t("dialog.leave"), danger: true });
    if (sure) leave.mutate();
  }

  return (
    <section className="table-panel" data-testid="table-panel" aria-label={t("play.table")}>
      <h2>{t("play.atTheTable")}</h2>
      <ul className="table-seats" data-testid="table-seats">
        {seats.map((seat) => (
          <li key={seat.id} className={seat.present ? "present" : "away"}>
            <span className="seat-dot" aria-hidden="true" />
            <TableAvatar profile={seat.profile} size={28} />
            <span className="seat-name">{seat.id === mySeat.id ? `${seat.name} (${t("play.you")})` : seat.name}</span>
            <span className="seat-role">{t(`play.role.${seat.role}`)}</span>
            {!seat.present && <span className="seat-state">{t("play.seatState.away")}</span>}
          </li>
        ))}
      </ul>
      {listing.data && <TableAbout about={listing.data} calendarFor={campaignId} />}
      {tableZone && (
        <Link className="button-like board-link" to={`/board/${encodeURIComponent(tableZone.id)}`}>
          {t("play.board")}
        </Link>
      )}
      {!tableZone && board.data && mySeat.role === "host" && (
        <button type="button" onClick={() => makeZone.mutate()} disabled={makeZone.isPending}>
          {t("play.makeZone")}
        </button>
      )}
      {makeZone.error && (
        <p className="notice error" role="alert">
          {sayError(makeZone.error)}
        </p>
      )}
      {mySeat.role !== "host" && (
        <button type="button" className="danger leave-table" onClick={() => void leaveTheTable()} disabled={leave.isPending}>
          {t("play.leave")}
        </button>
      )}
      {leave.error && (
        <p className="notice error" role="alert">
          {leave.error.message}
        </p>
      )}
    </section>
  );
}
