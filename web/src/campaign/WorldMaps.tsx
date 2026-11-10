import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Suspense, lazy, type ReactNode } from "react";
import { Link } from "react-router-dom";
import { useConfirm } from "../components/dialogs";
import { useT } from "../i18n";
import { deleteWorldMap, pictureUrl, type WorldMapOwner } from "../worldmap/editorApi";
import { editorPath, listWorldMaps, reviewPath, worldMapsKey, type WorldMapRow } from "../worldmap/importApi";
import { Failed } from "./worldFields";

// Leaflet and Geoman stay out of the main bundle: the dialogs that draw a map, or import one, load with them.
const ImportWorldMap = lazy(() => import("../worldmap/ImportWorldMap"));
const StartKnowledge = lazy(() => import("../worldmap/StartKnowledge"));

const SOURCES = new Set(["module", "setting", "campaign"]);

/**
 * A list of world maps for the organisers, a campaign's or a module's: each with its status ("In review" until its
 * reading is accepted), Edit, Review while it is in review, Download the picture when it was read from one, the
 * owner's own `actions`, and Delete; and Import above the list.
 */
export function WorldMapList({
  owner,
  empty,
  actions,
}: {
  owner: WorldMapOwner;
  empty: string;
  actions?: (map: WorldMapRow) => ReactNode;
}) {
  const t = useT();
  const confirm = useConfirm();
  const client = useQueryClient();
  const key = worldMapsKey(owner);
  const maps = useQuery({ queryKey: key, queryFn: () => listWorldMaps(owner) });
  const remove = useMutation({
    mutationFn: (name: string) => deleteWorldMap(owner, name),
    onSuccess: () => {
      // A campaign's list is part of its world, with the play screen's: a `world` event would do the same.
      client.invalidateQueries({ queryKey: owner.kind === "campaign" ? ["campaign", owner.campaignId, "world"] : key });
    },
  });
  const listed = maps.data ?? [];

  return (
    <div className="world-maps">
      <Failed error={remove.error ?? maps.error} />
      <div className="world-maps-bar">
        <Suspense fallback={null}>
          <ImportWorldMap owner={owner} />
        </Suspense>
      </div>
      {listed.length === 0 && maps.isSuccess && <p className="placeholder">{empty}</p>}
      {listed.length > 0 && (
        <ul className="rows">
          {listed.map((map) => (
            <li key={map.name} className="row">
              <div>
                <strong>{map.title || map.name}</strong>{" "}
                {map.status === "review" && <span className="tag">{t("worldMaps.inReview")}</span>}
                {owner.kind === "campaign" && SOURCES.has(map.source) && (
                  <p className="row-meta">{t("worldMaps.source", { source: t(`worldMaps.source.${map.source}`) })}</p>
                )}
              </div>
              <div className="actions">
                <Link className="button-like" to={editorPath(owner, map.name)}>
                  {t("worldMaps.edit")}
                </Link>
                {map.status === "review" && (
                  <Link className="button-like primary" to={reviewPath(owner, map.name)}>
                    {t("worldMaps.review")}
                  </Link>
                )}
                {map.picture && (
                  <a className="button-like" href={pictureUrl(owner, map.name)} download>
                    {t("worldMaps.downloadPicture")}
                  </a>
                )}
                {actions?.(map)}
                <button
                  type="button"
                  className="danger"
                  disabled={remove.isPending}
                  onClick={async () =>
                    (await confirm({
                      title: t("worldMaps.deleteConfirm", { name: map.title || map.name }),
                      confirm: t("dialog.delete"),
                      danger: true,
                    })) && remove.mutate(map.name)
                  }
                >
                  {t("dialog.delete")}
                </button>
              </div>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

/**
 * The campaign's world maps, for the organisers: its own copies, made from its module's and its setting's when it
 * began, and any it imported since. A ready map also sets what the party knows of it at the start.
 */
export default function WorldMaps({ campaignId }: { campaignId: string }) {
  const t = useT();
  return (
    <WorldMapList
      owner={{ kind: "campaign", campaignId }}
      empty={t("worldMaps.none")}
      actions={(map) =>
        map.status === "ready" && (
          <Suspense fallback={null}>
            <StartKnowledge campaignId={campaignId} name={map.name} title={map.title} />
          </Suspense>
        )
      }
    />
  );
}
