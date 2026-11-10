import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useMemo, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { ApiError } from "../api";
import { useT } from "../i18n";
import { pictureTileUrl, type DmView, type Geometry } from "./api";
import { toLatLng, type Point } from "./crs";
import { getWorldMap, ownerPage, worldMapKey, type WorldMapDoc, type WorldMapOwner } from "./editorApi";
import { cellCentre } from "./fog";
import { accept, review, worldMapsKey, type Doubt, type Reading } from "./importApi";
import ReviewPanel, { type ReviewBody } from "./ReviewPanel";
import { useLeafletMap } from "./useLeaflet";
import WorldMapView from "./WorldMapView";
import styles from "./WorldImport.module.css";

/** The map as the organiser sees it whole, for `WorldMapView`: every feature, every cell known. */
export function reviewView(doc: WorldMapDoc): DmView {
  const { frame, grid, terrain, picture } = doc.geo.delve;
  return {
    name: doc.name,
    title: doc.title,
    units: frame.units,
    frame,
    grid,
    picture: picture
      ? { id: picture.id, width_px: picture.width_px, height_px: picture.height_px, km_per_px: picture.km_per_px }
      : null,
    tiles_version: "",
    known: { all: true, cells: [] },
    terrain,
    features: doc.geo.features.map((f) => ({
      id: f.id,
      layer: f.properties.layer,
      kind: f.properties.kind,
      name: f.properties.name,
      description: f.properties.description,
      dm_notes: f.properties.dm_notes,
      hidden: f.properties.hidden,
      tags: f.properties.tags,
      geometry: f.geometry,
      known: true,
    })),
    party: null,
    journey: null,
  };
}

function firstPoint(geometry: Geometry): Point {
  switch (geometry.type) {
    case "Point":
      return geometry.coordinates;
    case "LineString":
      return geometry.coordinates[Math.floor(geometry.coordinates.length / 2)];
    case "MultiLineString":
    case "Polygon":
      return geometry.coordinates[0][0];
    case "MultiPolygon":
      return geometry.coordinates[0][0][0];
  }
}

/** Where a doubt is, in km: its own `at`, its cell (`cell:<index>`), or the feature it is about. */
export function doubtPoint(doc: WorldMapDoc, doubt: Doubt): Point | null {
  if (doubt.data?.at) return doubt.data.at;
  const cell = /^cell:(\d+)$/.exec(doubt.ref);
  if (cell) return cellCentre(doc.geo.delve.grid, Number(cell[1]));
  const feature = doc.geo.features.find((f) => f.id === doubt.ref || f.properties.doubt === doubt.id);
  return feature ? firstPoint(feature.geometry) : null;
}

/** Flies the map of the nearest `WorldMapView` to `target`. */
function FlyTo({ target }: { target: { at: Point } | null }) {
  const map = useLeafletMap();
  useEffect(() => {
    if (!map || !target) return;
    map.flyTo(toLatLng(target.at), Math.max(map.getZoom(), map.getMaxZoom() - 1));
  }, [map, target]);
  return null;
}

/**
 * `/world-maps/:owner/:ownerId/:name/review`: the picture with the reading on top, and the review beside it. Each
 * decision goes to the server at once and its answer is the map held; selecting a doubt flies the map to it. Accept
 * makes the map ready and goes back to its owner's page.
 */
export default function ReviewPage({ owner, name }: { owner: WorldMapOwner; name: string }) {
  const t = useT();
  const client = useQueryClient();
  const navigate = useNavigate();
  const key = worldMapKey(owner, name);
  const map = useQuery({ queryKey: key, queryFn: () => getWorldMap(owner, name) });
  const [target, setTarget] = useState<{ at: Point } | null>(null);
  const held = (doc: WorldMapDoc) => client.setQueryData(key, doc);

  const decide = useMutation({ mutationFn: (body: ReviewBody) => review(owner, name, body), onSuccess: held });
  const accepted = useMutation({
    mutationFn: () => accept(owner, name),
    onSuccess: (doc) => {
      held(doc);
      client.invalidateQueries({ queryKey: worldMapsKey(owner) });
      navigate(ownerPage(owner));
    },
  });

  const doc = map.data;
  const view = useMemo(() => (doc ? reviewView(doc) : null), [doc]);
  const reading = (doc?.reading ?? null) as Reading | null;
  const error = decide.error ?? accepted.error ?? map.error;

  return (
    <main className={styles.page}>
      <header className={styles.header}>
        <Link to={ownerPage(owner)}>{t("worldReview.back")}</Link>
        <h1>{t("worldReview.title", { title: doc?.title || name })}</h1>
      </header>
      {error && (
        <p role="alert" className="notice error">
          {error instanceof ApiError ? (error.body.error ?? error.message) : error.message}
        </p>
      )}
      {doc && view && (
        <div className={styles.layout}>
          <div className={styles.map}>
            <WorldMapView view={view} tileUrl={doc.picture ? pictureTileUrl(doc.picture) : null}>
              <FlyTo target={target} />
            </WorldMapView>
          </div>
          {doc.status === "review" && reading ? (
            <ReviewPanel
              reading={reading}
              busy={decide.isPending || accepted.isPending}
              onReview={(body) => decide.mutate(body)}
              onAccept={() => accepted.mutate()}
              onSelect={(doubt) => {
                const at = doubtPoint(doc, doubt);
                if (at) setTarget({ at });
              }}
            />
          ) : (
            <p className="notice">{t("worldReview.notInReview")}</p>
          )}
        </div>
      )}
    </main>
  );
}
