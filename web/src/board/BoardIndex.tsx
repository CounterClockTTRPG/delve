import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ChevronDown, ChevronUp, Dices, Globe, KeyRound, UserRound } from "lucide-react";
import { useState } from "react";
import { Link } from "react-router-dom";
import { ago } from "../components/ago";
import { useLanguage, useT } from "../i18n";
import { boardKeys, getBoard, reorderZones, type Level } from "./api";
import { authorName, levelsLabel, sayError } from "./show";
import ZoneSettings from "./ZoneSettings";

// `/board` (DEL-297): the zones the reader may read, in the owner's order, as one list: each with what it is for, who
// reads and posts there, the topic written in last, how many topics it has and how many of them are new to the reader.
// Organisers make zones (New zone) and, after Arrange zones, put them in order (Move up, Move down).

/** Who may read a zone, at a glance. */
const LEVEL_ICON: Record<Level, typeof Globe> = { everybody: Globe, accounts: UserRound, members: KeyRound, table: Dices };

export default function BoardIndex() {
  const t = useT();
  const language = useLanguage();
  const client = useQueryClient();
  const board = useQuery({ queryKey: boardKeys.all, queryFn: getBoard });
  const [making, setMaking] = useState(false);
  const [arranging, setArranging] = useState(false);
  const reorder = useMutation({
    mutationFn: reorderZones,
    onSuccess: () => client.invalidateQueries({ queryKey: boardKeys.all }),
  });
  const zones = board.data?.zones ?? [];
  const move = (index: number, by: -1 | 1) => {
    const ids = zones.map((z) => z.id);
    [ids[index], ids[index + by]] = [ids[index + by], ids[index]];
    reorder.mutate(ids);
  };
  return (
    <main className="board-main">
      <header className="board-page-head">
        <h1>{t("board.title")}</h1>
        {board.data?.may_create && (
          <div className="board-actions">
            {zones.length > 1 && (
              <button type="button" aria-pressed={arranging} onClick={() => setArranging((on) => !on)}>
                {t(arranging ? "board.done" : "board.arrange")}
              </button>
            )}
            <button type="button" className="primary" onClick={() => setMaking(true)}>
              {t("board.newZone")}
            </button>
          </div>
        )}
      </header>
      <p className="board-lede">{t("board.lede")}</p>
      {making && <ZoneSettings wide onDone={() => setMaking(false)} />}
      {reorder.isError && (
        <p className="notice error" role="alert">
          {sayError(reorder.error)}
        </p>
      )}
      {board.isPending ? (
        <p className="board-quiet">{t("board.loading")}</p>
      ) : board.isError ? (
        <p className="notice error" role="alert">
          {sayError(board.error)}
        </p>
      ) : board.data.zones.length === 0 ? (
        <p className="board-quiet">{t("board.noZones")}</p>
      ) : (
        <ul className="board-zones">
          {board.data.zones.map((zone, index) => {
            const Icon = LEVEL_ICON[zone.read];
            const zoneUrl = `/board/${encodeURIComponent(zone.id)}`;
            return (
              <li key={zone.id} className="board-zone">
                <div className="board-zone-words">
                  <Link className="board-zone-name" to={zoneUrl}>
                    {zone.name}
                  </Link>
                  {zone.description && <p className="board-zone-description">{zone.description}</p>}
                  <p className="board-meta board-access">
                    <Icon size={14} aria-hidden="true" />
                    <span>{levelsLabel(t, zone)}</span>
                  </p>
                </div>
                <div className="board-zone-latest">
                  {zone.latest ? (
                    <>
                      <Link className="board-latest-title" to={`${zoneUrl}/${encodeURIComponent(zone.latest.topic_id)}`}>
                        {zone.latest.title}
                      </Link>
                      <span className="board-meta">{t("board.latestBy", { name: authorName(t, zone.latest.author), when: ago(zone.latest.at, language) })}</span>
                    </>
                  ) : (
                    <span className="board-meta">{t("board.noTopics")}</span>
                  )}
                  {zone.topics > 0 && (
                    <span className="board-meta">
                      {t("board.topicCount", { count: String(zone.topics) })}
                      {zone.new_topics > 0 && <span className="board-pill">{t("board.newCount", { count: String(zone.new_topics) })}</span>}
                    </span>
                  )}
                </div>
                {arranging && zone.rights.manage_wide && (
                  <span className="board-zone-order">
                    <button type="button" disabled={index === 0 || reorder.isPending} aria-label={t("board.moveUp", { name: zone.name })} title={t("board.moveUpShort")} onClick={() => move(index, -1)}>
                      <ChevronUp size={16} aria-hidden="true" />
                    </button>
                    <button type="button" disabled={index === zones.length - 1 || reorder.isPending} aria-label={t("board.moveDown", { name: zone.name })} title={t("board.moveDownShort")} onClick={() => move(index, 1)}>
                      <ChevronDown size={16} aria-hidden="true" />
                    </button>
                  </span>
                )}
              </li>
            );
          })}
        </ul>
      )}
    </main>
  );
}
