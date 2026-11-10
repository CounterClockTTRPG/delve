import { useQuery } from "@tanstack/react-query";
import { useId, useMemo, useState } from "react";
import { ApiError, getCharactersView, queryKeys } from "../api";
import { SvgPreview } from "../editor/SvgPreview";
import { usePortraitStyle } from "../components/portraitStyle";
import { useT } from "../i18n";
import type { PartyMember, Position } from "./api";
import { withTokenFaces, type TokenFace } from "./tokenFaces";

/**
 * The party's map: the characters' fog view of where they are, never the DM view. A split party has one view per
 * group, picked with a switcher (spec §7.4). It opens framed on the group's room and follows it as they move; the
 * toggle shows the whole map. On a phone (`fitWhole`) it opens on the whole known map instead, the room one tap away.
 * With no character yet, nobody is on a map (`mapState.noOneYet`); with no group on a map, the part being played has
 * no map (`mapState.noMap`); only a 409 from the view is "Map offline". In a fight, the party's tokens show their
 * `faces`, portraits and hit points left (DEL-10, `withTokenFaces`).
 */
const NO_FACES: Record<string, TokenFace> = {};

export default function MapPanel({
  campaignId,
  party,
  positions,
  viewable,
  fitWhole = false,
  faces = NO_FACES,
}: {
  campaignId: string;
  party: PartyMember[];
  positions: Position[];
  /** The characters whose view this seat may see (a player's own); left out, every group's (the host's). */
  viewable?: string[];
  /** Open fitted to the whole map, not framed on the party's room. */
  fitWhole?: boolean;
  /** By character id. */
  faces?: Record<string, TokenFace>;
}) {
  const t = useT();
  const style = usePortraitStyle();
  // useId gives ":r0:", and an SVG id that url(#…) refers to wants no colons.
  const idPrefix = `map${useId().replace(/[^A-Za-z0-9_-]/g, "")}`;
  const [picked, setPicked] = useState(0);
  // The positions name characters as primer does; ids are accepted too. A player sees only the groups their own
  // characters are in, as those characters know them.
  const groups = positions
    .map((p) => {
      const members = p.characters
        .map((who) => party.find((m) => m.id === who || m.name === who))
        .filter((m): m is PartyMember => m !== undefined && (!viewable || viewable.includes(m.id)));
      return { ...p, ids: members.map((m) => m.id), names: members.map((m) => m.name) };
    })
    // A group with none of the party in it (a PC who died or left, from before the server left them out) is no map.
    .filter((g) => g.ids.length > 0);
  const group = groups[Math.min(picked, groups.length - 1)];

  const view = useQuery({
    queryKey: group ? [...queryKeys.mapState(campaignId, group.map), "view", group.ids.join(",")] : ["no-map"],
    queryFn: () => getCharactersView(campaignId, group!.map, group!.ids),
    enabled: group !== undefined && group.ids.length > 0,
  });
  const raw = view.data?.svg ?? null;
  const svg = useMemo(
    () => (raw === null ? null : withTokenFaces(raw, faces, { campaignId, style, idPrefix })),
    [raw, faces, campaignId, style, idPrefix],
  );
  const noMap = !group || group.ids.length === 0;
  const offline = view.error instanceof ApiError && view.error.status === 409;

  return (
    <section className="map-panel" aria-label={t("play.map")}>
      <h2 className="panel-title">{t("play.map")}</h2>
      {groups.length > 1 && (
        <div className="map-groups" role="group" aria-label={t("play.groups")}>
          {groups.map((g, index) => (
            <button
              key={`${g.map}-${g.location}`}
              type="button"
              aria-pressed={g === group}
              onClick={() => setPicked(index)}
            >
              {t("play.groupLabel", { place: g.label ?? g.location ?? g.map, names: g.names.join(", ") })}
            </button>
          ))}
        </div>
      )}
      {party.length === 0 ? (
        <p role="status" className="offline">
          {t("mapState.noOneYet")}
        </p>
      ) : noMap ? (
        <p role="status" className="offline">
          {t("mapState.noMap")}
        </p>
      ) : offline ? (
        <p role="status" className="offline">
          {t("mapState.offline")}
        </p>
      ) : view.error ? (
        <p className="notice error" role="alert">
          {view.error.message}
        </p>
      ) : (
        <div className="view-svg play-map">
          <SvgPreview
            svg={svg}
            loading={view.isFetching}
            focusTarget={group.location ?? null}
            followTarget={!fitWhole}
            fitKnown={fitWhole}
          />
        </div>
      )}
    </section>
  );
}
