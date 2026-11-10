import { useQuery } from "@tanstack/react-query";
import { Suspense, lazy, useState } from "react";
import Portrait from "../components/Portrait";
import { useT } from "../i18n";
import type { JourneyView, SeatView } from "../worldmap/api";
import { getSeatView, listWorldMaps, seatTileUrl } from "../worldmap/api";
import KnownPlaces from "../worldmap/KnownPlaces";
import { getWorld, playKeys } from "./api";
import { usePhone } from "./usePhone";

// Leaflet comes with the map, in its own chunk: the play screen opens without it.
const WorldMapView = lazy(() => import("../worldmap/WorldMapView"));

const KM_PER_MILE = 1.609344;

/** "On the way to Hardby on foot: 4 of 9 miles." in the map's units; the place stays unnamed while it isn't known. */
function journeyLine(t: ReturnType<typeof useT>, journey: JourneyView, view: SeatView): string {
  const miles = view.units === "miles";
  const show = (km: number) => String(Math.round(miles ? km / KM_PER_MILE : km));
  const vars = {
    mode: t(`worldMap.mode.${journey.mode}`),
    done: show(journey.done_km),
    total: show(journey.km),
    unit: t(`worldMap.unit.${view.units}`),
  };
  return journey.to_label ? t("worldMap.journeyTo", { ...vars, place: journey.to_label }) : t("worldMap.journey", vars);
}

/**
 * The world as the characters know it (plan 6, Decision 7; plan 7, Task 14): the world map in Leaflet, cut on the
 * server to what the party knows (the picture under its fog, the known places, the party and its journey), with a
 * picker when there are several maps and the known places listed beside it; the known quests with the notes they
 * know; the known factions with their standing word; the party's possessions with their portraits. Everything comes
 * from the seat's own routes, which leave out what the DM alone knows. A `world` event reads it again. On a phone the
 * map fills the screen, with the known places in a sheet over its foot; the rest follows below.
 */
export default function WorldPanel({ campaignId }: { campaignId: string }) {
  const t = useT();
  const phone = usePhone();
  const world = useQuery({ queryKey: playKeys.world(campaignId), queryFn: () => getWorld(campaignId) });
  const maps = useQuery({
    queryKey: [...playKeys.world(campaignId), "maps"],
    queryFn: () => listWorldMaps(campaignId),
  });
  const [picked, setPicked] = useState<string | null>(null);
  const [selected, setSelected] = useState<string | null>(null);
  const [sheet, setSheet] = useState(false);

  const listed = maps.data ?? [];
  const here = world.data?.position?.map;
  const shown = listed.find((m) => m.name === picked) ?? listed.find((m) => m.name === here) ?? listed[0] ?? null;
  const view = useQuery({
    queryKey: [...playKeys.world(campaignId), "maps", shown?.name, "view"],
    queryFn: () => getSeatView(campaignId, shown!.name),
    enabled: shown !== null,
  });
  const data = world.data;
  const seen = view.data && view.data.name === shown?.name ? view.data : null;
  const atLabel = data?.position?.map === shown?.name ? data?.position?.at_label : null;
  // A campaign with no world map says so; "offline" is for a map that won't load (DEL-265).
  const none = shown === null && maps.isSuccess && listed.length === 0;
  const offline = shown === null ? !maps.isPending && !none : view.isError;

  const picker = listed.length > 1 && (
    <div className="field world-map-picker">
      <label htmlFor="world-map-picker">{t("world.map")}</label>
      <select id="world-map-picker" value={shown?.name ?? ""} onChange={(e) => setPicked(e.target.value)}>
        {listed.map((m) => (
          <option key={m.name} value={m.name}>
            {m.title || m.name}
          </option>
        ))}
      </select>
    </div>
  );
  const map = none ? (
    <p className="placeholder" data-testid="world-none">
      {t("world.noMap")}
    </p>
  ) : offline ? (
    <p role="status" className="offline">
      {t("mapState.offline")}
    </p>
  ) : (
    seen && (
      <div className={phone ? "world-map world-map-full" : "world-map"}>
        <Suspense fallback={null}>
          <WorldMapView
            view={seen}
            tileUrl={seen.picture ? seatTileUrl(campaignId, seen.name, seen.tiles_version) : null}
            onSelect={setSelected}
          />
        </Suspense>
      </div>
    )
  );
  const places = seen && !offline && (
    <>
      <h3>{t("worldMap.knownPlaces")}</h3>
      <KnownPlaces view={seen} here={atLabel} selected={selected} onSelect={setSelected} />
    </>
  );
  const whereabouts = (
    <>
      {data?.position?.at_label && <p className="world-here">{t("world.here", { place: data.position.at_label })}</p>}
      {seen?.journey && !offline && <p className="world-journey-line">{journeyLine(t, seen.journey, seen)}</p>}
    </>
  );

  const rest = (
    <>
      {world.error && (
        <p className="notice error" role="alert">
          {world.error.message}
        </p>
      )}

      {data && (
        <>
          <h3>{t("world.quests")}</h3>
          {data.quests.length === 0 ? (
            <p className="placeholder">{t("world.noQuests")}</p>
          ) : (
            <ul className="world-quests">
              {data.quests.map((quest) => (
                <li key={quest.id} className="world-quest">
                  <span className="world-quest-title">{quest.title}</span>{" "}
                  <span className="world-quest-status">{t(`quest.status.${quest.status}`)}</span>
                  {quest.giver && <p className="row-meta">{t("world.givenBy", { giver: quest.giver })}</p>}
                  {quest.stakes && <p className="world-quest-stakes">{quest.stakes}</p>}
                  {quest.log.length > 0 && (
                    <ul className="world-quest-log">
                      {quest.log.map((note, index) => (
                        <li key={index}>{note.text}</li>
                      ))}
                    </ul>
                  )}
                </li>
              ))}
            </ul>
          )}

          <h3>{t("world.factions")}</h3>
          {data.factions.length === 0 ? (
            <p className="placeholder">{t("world.noFactions")}</p>
          ) : (
            <ul className="world-factions">
              {data.factions.map((faction) => (
                <li key={faction.id}>
                  <span>{faction.name}</span> <span className="standing">{faction.standing}</span>
                </li>
              ))}
            </ul>
          )}

          <h3>{t("world.possessions")}</h3>
          {data.possessions.length === 0 ? (
            <p className="placeholder">{t("world.noPossessions")}</p>
          ) : (
            <ul className="world-possessions">
              {data.possessions.map((p) => (
                <li key={p.id}>
                  <Portrait campaignId={campaignId} portrait={p.portrait} name={p.name} size={32} />
                  <span className="world-possession-name">{p.name}</span>
                  <span className="row-meta">
                    {[t(`possession.kind.${p.kind}`), p.owner ?? t("world.theParty")].join(" · ")}
                  </span>
                </li>
              ))}
            </ul>
          )}
        </>
      )}
    </>
  );

  return (
    <section
      className={phone ? "world-panel world-phone" : "world-panel"}
      aria-label={t("play.world")}
      data-testid="world-panel"
      data-tour="world"
    >
      {!phone && <h2 className="panel-title">{t("play.world")}</h2>}
      {picker}
      {map}
      {phone ? (
        <div className="world-sheet-wrap">
          <button
            type="button"
            className="world-sheet-toggle"
            aria-expanded={sheet}
            aria-controls="world-sheet"
            onClick={() => setSheet((open) => !open)}
          >
            {t("worldMap.knownPlaces")}
          </button>
          {sheet && (
            <div id="world-sheet" className="world-sheet">
              {whereabouts}
              {places}
            </div>
          )}
        </div>
      ) : (
        <>
          {whereabouts}
          {places}
        </>
      )}
      {rest}
    </section>
  );
}
