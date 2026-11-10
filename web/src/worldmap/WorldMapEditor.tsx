import "./leafletGlobal";
import "@geoman-io/leaflet-geoman-free";
import "@geoman-io/leaflet-geoman-free/dist/leaflet-geoman.css";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import L from "leaflet";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Link, useBlocker, type BlockerFunction } from "react-router-dom";
import { ApiError } from "../api";
import { useConfirm } from "../components/dialogs";
import { Button } from "../editor/Primitives";
import { useLanguage, useT } from "../i18n";
import { usePhone } from "../play/usePhone";
import type { Geometry, Layer } from "./api";
import { LETTER_OF_TERRAIN, TERRAIN_CLASSES, cellsUnder, paint } from "./brush";
import { MILES_TO_KM, fromLatLng, mapCrs, toLatLng, type Point } from "./crs";
import {
  exportUrl,
  getWorldMap,
  ownerPage,
  pictureUrl,
  putWorldMap,
  worldMapKey,
  type GeoDocFeature,
  type GeoDocument,
  type WorldMapDoc,
  type WorldMapOwner,
} from "./editorApi";
import FeatureForm from "./FeatureForm";
import { FOG, TERRAIN_COLOURS, TERRAIN_OF_LETTER, cellPolygon, terrainAreas } from "./fog";
import { History } from "./history";
import { nameTooltip } from "./nameTooltip";
import { useLeaflet } from "./useLeaflet";
import { pictureTileUrl } from "./api";
import styles from "./WorldMapEditor.module.css";

/** What the editor changes, and undoes: the title and the document. */
type Draft = { title: string; geo: GeoDocument };

type DrawTool = "place" | "route" | "river" | "region" | "lake" | "sea";
type Tool = "select" | DrawTool | "edit" | "drag" | "remove" | "brush";

/** What each drawing tool makes: a marker is a place, a line a route or a river, a polygon a region, a lake or a sea. */
const DRAWN: Record<DrawTool, { shape: "Marker" | "Line" | "Polygon"; layer: Layer; kind: string }> = {
  place: { shape: "Marker", layer: "places", kind: "town" },
  route: { shape: "Line", layer: "routes", kind: "road" },
  river: { shape: "Line", layer: "water", kind: "river" },
  region: { shape: "Polygon", layer: "regions", kind: "region" },
  lake: { shape: "Polygon", layer: "water", kind: "lake" },
  sea: { shape: "Polygon", layer: "water", kind: "sea" },
};

const TOOLS: Tool[] = ["select", "place", "route", "river", "region", "lake", "sea", "edit", "drag", "remove", "brush"];
const LAYER_ORDER: Layer[] = ["regions", "water", "routes", "places"];
const ID_PREFIX: Record<Layer, string> = { places: "place", routes: "route", water: "water", regions: "region" };

const draftOf = (doc: WorldMapDoc): Draft => ({ title: doc.title, geo: doc.geo });
const same = (a: Draft, b: Draft) => JSON.stringify(a) === JSON.stringify(b);

/** A map point to the metre, so that a drag doesn't write sixteen decimals. */
const pointOf = (latLng: L.LatLng): Point => fromLatLng(latLng).map((v) => Math.round(v * 1000) / 1000) as Point;

const closed = (ring: Point[]): Point[] =>
  ring.length && (ring[0][0] !== ring[ring.length - 1][0] || ring[0][1] !== ring[ring.length - 1][1])
    ? [...ring, ring[0]]
    : ring;

/** The GeoJSON geometry of a layer Geoman drew or reshaped, in km. */
function geometryOf(layer: L.Layer): Geometry | null {
  if (layer instanceof L.Marker) return { type: "Point", coordinates: pointOf(layer.getLatLng()) };
  if (layer instanceof L.Polygon) {
    const latLngs = layer.getLatLngs() as L.LatLng[][] | L.LatLng[][][];
    const rings = (ring: L.LatLng[]) => closed(ring.map(pointOf));
    if (latLngs.length && Array.isArray(latLngs[0][0]))
      return { type: "MultiPolygon", coordinates: (latLngs as L.LatLng[][][]).map((polygon) => polygon.map(rings)) };
    return { type: "Polygon", coordinates: (latLngs as L.LatLng[][]).map(rings) };
  }
  if (layer instanceof L.Polyline) {
    const latLngs = layer.getLatLngs() as L.LatLng[] | L.LatLng[][];
    if (latLngs.length && Array.isArray(latLngs[0]))
      return { type: "MultiLineString", coordinates: (latLngs as L.LatLng[][]).map((line) => line.map(pointOf)) };
    return { type: "LineString", coordinates: (latLngs as L.LatLng[]).map(pointOf) };
  }
  return null;
}

const lineLatLngs = (geometry: Geometry) =>
  geometry.type === "LineString"
    ? geometry.coordinates.map(toLatLng)
    : geometry.type === "MultiLineString"
      ? geometry.coordinates.map((line) => line.map(toLatLng))
      : [];

const areaLatLngs = (geometry: Geometry) =>
  geometry.type === "Polygon"
    ? geometry.coordinates.map((ring) => ring.map(toLatLng))
    : geometry.type === "MultiPolygon"
      ? geometry.coordinates.map((polygon) => polygon.map((ring) => ring.map(toLatLng)))
      : [];

function placeIcon(feature: GeoDocFeature): L.DivIcon {
  const html = document.createElement("span");
  const dot = document.createElement("span");
  dot.className = "world-place-dot";
  html.append(dot);
  if (feature.properties.name) {
    const label = document.createElement("span");
    label.className = "world-place-label";
    label.textContent = feature.properties.name;
    html.append(label);
  }
  return L.divIcon({
    className: `world-place world-place-${feature.properties.kind}`,
    html,
    iconSize: undefined,
    iconAnchor: [5, 5],
  });
}

/** A feature as the editor draws it, the seat's map's look (`WorldMapView`), with hidden ones faded. */
function featureLayer(feature: GeoDocFeature, selected: boolean): L.Layer | null {
  const { layer, kind, hidden, name } = feature.properties;
  const classes = [`world-${layer}-${kind}`, hidden ? "world-hidden" : "", selected ? "world-selected" : ""].join(" ");
  const weight = (w: number) => (selected ? w + 2 : w);
  const opacity = hidden ? 0.5 : 1;
  const g = feature.geometry;
  if (layer === "places" && g.type === "Point")
    return L.marker(toLatLng(g.coordinates), { icon: placeIcon(feature), title: name, opacity });
  if (layer === "regions")
    return L.polygon(areaLatLngs(g) as L.LatLngExpression[][], {
      className: `world-region ${classes}`,
      color: "#6b4e2e",
      weight: weight(1.5),
      dashArray: "6 4",
      fillOpacity: 0.06,
      opacity,
    });
  if (layer === "water" && (kind === "lake" || kind === "sea"))
    return L.polygon(areaLatLngs(g) as L.LatLngExpression[][], {
      className: `world-water ${classes}`,
      color: TERRAIN_COLOURS[kind],
      weight: weight(1),
      fillColor: TERRAIN_COLOURS[kind],
      fillOpacity: 0.55,
      opacity,
    });
  if (layer === "water")
    return L.polyline(lineLatLngs(g) as L.LatLngExpression[], {
      className: `world-river ${classes}`,
      color: "#2f6fb0",
      weight: weight(2.5),
      opacity,
    });
  if (layer === "routes")
    return L.polyline(lineLatLngs(g) as L.LatLngExpression[], {
      className: `world-route ${classes}`,
      color: "#7a4a1e",
      weight: weight(kind === "road" ? 2.5 : 1.5),
      dashArray: kind === "road" ? undefined : kind === "track" ? "6 3" : "2 4",
      opacity,
    });
  return null;
}

let canDrawOnCanvas: boolean | null = null;

/** The canvas renderer when the browser has one (jsdom hasn't), for the many terrain cells. */
function terrainRenderer(): L.Renderer {
  if (canDrawOnCanvas === null) {
    try {
      canDrawOnCanvas = document.createElement("canvas").getContext("2d") !== null;
    } catch {
      canDrawOnCanvas = false;
    }
  }
  return canDrawOnCanvas ? L.canvas({ padding: 0.2 }) : L.svg();
}

function newId(layer: Layer, features: GeoDocFeature[]): string {
  const ids = new Set(features.map((f) => f.id));
  let n = 1;
  while (ids.has(`${ID_PREFIX[layer]}-${n}`)) n++;
  return `${ID_PREFIX[layer]}-${n}`;
}

const typing = (target: EventTarget | null) =>
  target instanceof HTMLElement &&
  (target.isContentEditable || ["INPUT", "TEXTAREA", "SELECT"].includes(target.tagName));

/**
 * The organiser's world-map editor (design §3.3), on the same Leaflet map as the seat's: places, routes, rivers,
 * coasts and regions drawn and reshaped with Geoman, a terrain brush, each feature's fields, undo and redo, and the
 * dungeon map editor's guard against leaving with unsaved changes. Save sends the document and then holds the
 * server's answer, which has the water cells it derived from a reshaped lake or sea.
 */
const OPACITY_KEY = "delve.worldmap.pictureOpacity";

/** The Picture slider's last setting in this browser, 100 when there is none. */
function storedOpacity(): number {
  try {
    const value = Number(localStorage.getItem(OPACITY_KEY) ?? 100);
    return value >= 0 && value <= 100 ? value : 100;
  } catch {
    return 100;
  }
}

export default function WorldMapEditor({ owner, name }: { owner: WorldMapOwner; name: string }) {
  const t = useT();
  const language = useLanguage();
  const phone = usePhone();
  const qc = useQueryClient();
  const key = worldMapKey(owner, name);
  const { data, error: loadError } = useQuery({ queryKey: key, queryFn: () => getWorldMap(owner, name) });

  const [history, setHistory] = useState<History<Draft> | null>(null);
  const [saved, setSaved] = useState<Draft | null>(null);
  const [tool, setTool] = useState<Tool>("select");
  const [pictureOpacity, setPictureOpacity] = useState(storedOpacity);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [brushClass, setBrushClass] = useState("forest");
  const [brushRadius, setBrushRadius] = useState(0);
  const [problems, setProblems] = useState<string[]>([]);

  // The map held is the one first read; a later read never overwrites unsaved edits.
  useEffect(() => {
    if (!data || history) return;
    setHistory(History.of(draftOf(data)));
    setSaved(draftOf(data));
  }, [data, history]);

  const draft = history?.current ?? null;
  const dirty = useMemo(() => Boolean(draft && saved && !same(draft, saved)), [draft, saved]);
  const draftRef = useRef(draft);
  draftRef.current = draft;

  /** A change to the draft, pushed onto the history unless it changes nothing. */
  const change = useCallback((edit: (d: Draft) => Draft) => {
    setHistory((h) => {
      if (!h) return h;
      const next = edit(h.current);
      return same(next, h.current) ? h : h.push(next);
    });
  }, []);
  const changeGeo = useCallback(
    (edit: (geo: GeoDocument) => GeoDocument) => change((d) => ({ ...d, geo: edit(d.geo) })),
    [change],
  );
  const updateFeature = useCallback(
    (feature: GeoDocFeature) =>
      changeGeo((geo) => ({ ...geo, features: geo.features.map((f) => (f.id === feature.id ? feature : f)) })),
    [changeGeo],
  );
  const removeFeature = useCallback(
    (id: string) => changeGeo((geo) => ({ ...geo, features: geo.features.filter((f) => f.id !== id) })),
    [changeGeo],
  );
  const undo = useCallback(() => setHistory((h) => h?.undo() ?? h), []);
  const redo = useCallback(() => setHistory((h) => h?.redo() ?? h), []);

  const save = useMutation({
    mutationFn: (d: Draft) => putWorldMap(owner, name, d),
    onSuccess: (answer) => {
      const held = draftOf(answer);
      setSaved(held);
      setProblems([]);
      change(() => held);
      qc.setQueryData(key, answer);
    },
    onError: (e) => {
      const listed = e instanceof ApiError && Array.isArray(e.body.problems) ? (e.body.problems as string[]) : [];
      setProblems(listed);
    },
  });
  const onSave = useCallback(() => {
    if (!draftRef.current || !dirty || save.isPending) return;
    save.mutate(draftRef.current);
  }, [dirty, save]);

  // Ctrl+Z undoes and Ctrl+Shift+Z (or Ctrl+Y) redoes, but not inside a field, which has its own; Ctrl+S saves.
  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      if (!(e.ctrlKey || e.metaKey)) return;
      const k = e.key.toLowerCase();
      if (k === "s") {
        e.preventDefault();
        onSave();
      } else if (!typing(e.target) && (k === "z" || k === "y")) {
        e.preventDefault();
        if (k === "y" || e.shiftKey) redo();
        else undo();
      }
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onSave, undo, redo]);

  // The dungeon map editor's guard (MapEditor.tsx): the tab's unload, and the app's own navigation, with Delve's dialog.
  useEffect(() => {
    if (!dirty) return;
    function onBeforeUnload(e: BeforeUnloadEvent) {
      e.preventDefault();
      e.returnValue = "";
    }
    window.addEventListener("beforeunload", onBeforeUnload);
    return () => window.removeEventListener("beforeunload", onBeforeUnload);
  }, [dirty]);
  const shouldBlock = useCallback<BlockerFunction>(
    ({ currentLocation, nextLocation }) => dirty && currentLocation.pathname !== nextLocation.pathname,
    [dirty],
  );
  const blocker = useBlocker(shouldBlock);
  const confirm = useConfirm();
  const asking = useRef(false);
  useEffect(() => {
    if (blocker.state !== "blocked" || asking.current) return;
    asking.current = true;
    void confirm({ title: t("worldMapEditor.leaveUnsaved"), confirm: t("dialog.leave") }).then((leave) => {
      asking.current = false;
      if (leave) blocker.proceed();
      else blocker.reset();
    });
  }, [blocker, confirm, t]);

  if (loadError)
    return (
      <div className={`editor-scope ${styles.page}`}>
        <p role="alert" className={styles.loading}>
          {t("editor.loadFailed", { error: loadError.message })}
        </p>
      </div>
    );
  if (!draft || !data)
    return (
      <div className={`editor-scope ${styles.page}`}>
        <div className={styles.loading}>{t("editor.loading")}</div>
      </div>
    );

  const geo = draft.geo;
  const picture = geo.delve.picture;
  const selected = geo.features.find((f) => f.id === selectedId) ?? null;

  return (
    <div className={`editor-scope ${styles.page}`}>
      <header className={styles.header}>
        <Link to={ownerPage(owner)} className={styles.crumb}>
          {t(`worldMapEditor.back.${owner.kind}`)}
        </Link>
        <input
          className={styles.title}
          aria-label={t("worldMaps.title")}
          value={draft.title}
          onChange={(e) => {
            const title = e.target.value;
            change((d) => ({ ...d, title }));
          }}
        />
        {dirty ? (
          <span className={styles.dirty} title={t("editor.unsaved")}>
            ●
          </span>
        ) : null}
        {save.error ? (
          <span role="alert" className={styles.saveError}>
            {t("editor.saveFailed", { error: save.error.message })}
          </span>
        ) : null}
        <div className={styles.headerActions}>
          <Button variant="ghost" onClick={undo} disabled={!history?.canUndo} title={t("worldMapEditor.undoKeys")}>
            {t("worldMapEditor.undo")}
          </Button>
          <Button variant="ghost" onClick={redo} disabled={!history?.canRedo} title={t("worldMapEditor.redoKeys")}>
            {t("worldMapEditor.redo")}
          </Button>
          <a className="button-like" href={exportUrl(owner, name)} download>
            {t("worldMapEditor.export")}
          </a>
          {picture ? (
            <a className="button-like" href={pictureUrl(owner, name)} download>
              {t("worldMapEditor.downloadPicture")}
            </a>
          ) : null}
          <Button onClick={onSave} disabled={!dirty || save.isPending}>
            {save.isPending ? t("editor.saving") : t("editor.save")}
          </Button>
        </div>
      </header>
      {problems.length ? (
        <ul className={styles.problems} role="alert">
          {problems.map((problem) => (
            <li key={problem}>{problem}</li>
          ))}
        </ul>
      ) : null}
      <div role="toolbar" aria-label={t("worldMapEditor.tools")} className={styles.toolbar}>
        {TOOLS.map((name) => (
          <button
            key={name}
            type="button"
            className={styles.tool}
            aria-pressed={tool === name}
            title={t(`worldMapEditor.toolHint.${name}`)}
            onClick={() => setTool(name)}
          >
            {t(`worldMapEditor.tool.${name}`)}
          </button>
        ))}
        {picture ? (
          <label className={styles.opacity}>
            <span aria-hidden="true">{t("worldMapEditor.pictureOpacity")}</span>
            <input
              type="range"
              aria-label={t("worldMapEditor.pictureOpacity")}
              min={0}
              max={100}
              step={5}
              value={pictureOpacity}
              onChange={(e) => {
                const value = Number(e.target.value);
                setPictureOpacity(value);
                try {
                  localStorage.setItem(OPACITY_KEY, String(value));
                } catch {
                  /* storage unavailable */
                }
              }}
            />
            <span className={styles.opacityValue}>{pictureOpacity}%</span>
          </label>
        ) : null}
      </div>
      <div className={phone ? `${styles.workspace} ${styles.workspacePhone}` : styles.workspace}>
        <div className={tool === "brush" ? `${styles.map} ${styles.brushing}` : styles.map}>
          <EditorMap
            title={draft.title || name}
            geo={geo}
            tool={tool}
            selectedId={selectedId}
            language={language}
            pictureOpacity={pictureOpacity}
            brush={{ terrainClass: brushClass, radiusKm: brushRadius * (geo.delve.frame.units === "miles" ? MILES_TO_KM : 1) }}
            onSelect={setSelectedId}
            onCreate={(drawn, geometry) => {
              const { layer, kind } = DRAWN[drawn];
              const id = newId(layer, draftRef.current?.geo.features ?? []);
              const feature: GeoDocFeature = {
                type: "Feature",
                id,
                geometry,
                properties: { layer, kind, name: "", description: "", dm_notes: "", tags: [], hidden: false },
              };
              changeGeo((g) => ({ ...g, features: [...g.features, feature] }));
              setSelectedId(id);
              setTool("select");
            }}
            onGeometry={(id, geometry) =>
              changeGeo((g) => ({ ...g, features: g.features.map((f) => (f.id === id ? { ...f, geometry } : f)) }))
            }
            onRemove={removeFeature}
            onPaint={(terrain) => changeGeo((g) => ({ ...g, delve: { ...g.delve, terrain } }))}
            t={t}
          />
        </div>
        <aside className={styles.side}>
          {tool === "brush" ? (
            <div className={styles.form}>
              <h2 className={styles.formTitle}>{t("worldMapEditor.tool.brush")}</h2>
              <div className={styles.formField}>
                <label htmlFor="brush-terrain">{t("worldMapEditor.terrain")}</label>
                <select id="brush-terrain" value={brushClass} onChange={(e) => setBrushClass(e.target.value)}>
                  {TERRAIN_CLASSES.map((terrainClass) => (
                    <option key={terrainClass} value={terrainClass}>
                      {t(`worldMapEditor.terrain.${terrainClass}`)}
                    </option>
                  ))}
                </select>
              </div>
              <div className={styles.formField}>
                <label htmlFor="brush-radius">
                  {t("worldMapEditor.radius", { unit: t(`worldMapEditor.units.${geo.delve.frame.units}`) })}
                </label>
                <input
                  id="brush-radius"
                  type="number"
                  min={0}
                  step="any"
                  value={brushRadius}
                  onChange={(e) => setBrushRadius(Math.max(0, Number(e.target.value) || 0))}
                />
                <span className={styles.hint}>{t("worldMapEditor.radiusHint")}</span>
              </div>
            </div>
          ) : selected ? (
            <>
              <FeatureForm
                key={selected.id}
                feature={selected}
                units={geo.delve.frame.units}
                onChange={updateFeature}
                onRemove={() => {
                  removeFeature(selected.id);
                  setSelectedId(null);
                }}
              />
              <p>
                <Button variant="ghost" onClick={() => setSelectedId(null)}>
                  {t("worldMapEditor.done")}
                </Button>
              </p>
            </>
          ) : (
            <FeatureList features={geo.features} onSelect={setSelectedId} />
          )}
        </aside>
      </div>
    </div>
  );
}

/** Every feature by layer, to pick one without finding it on the map (a hidden place, a river under a road). */
function FeatureList({ features, onSelect }: { features: GeoDocFeature[]; onSelect: (id: string) => void }) {
  const t = useT();
  return (
    <section aria-label={t("worldMapEditor.features")}>
      {features.length === 0 ? <p className={styles.hint}>{t("worldMapEditor.noFeatures")}</p> : null}
      {[...LAYER_ORDER].reverse().map((layer) => {
        const of = features.filter((f) => f.properties.layer === layer);
        if (!of.length) return null;
        return (
          <div key={layer}>
            <h3 className={styles.listTitle}>{t(`worldMapEditor.layer.${layer}`)}</h3>
            <ul className={styles.list}>
              {of.map((f) => (
                <li key={f.id}>
                  <button type="button" onClick={() => onSelect(f.id)}>
                    {f.properties.name || t("worldMapEditor.unnamed", { id: f.id })}
                  </button>
                </li>
              ))}
            </ul>
          </div>
        );
      })}
    </section>
  );
}

type Translate = ReturnType<typeof useT>;

/** The Leaflet map of the editor, with Geoman on it. Its callbacks are read through a ref, so that a new closure
 * never remakes the layers under a drag. */
function EditorMap(props: {
  title: string;
  geo: GeoDocument;
  tool: Tool;
  selectedId: string | null;
  language: string;
  brush: { terrainClass: string; radiusKm: number };
  /** How much of the picture shows, 0 to 100. */
  pictureOpacity: number;
  onSelect: (id: string | null) => void;
  onCreate: (tool: DrawTool, geometry: Geometry) => void;
  onGeometry: (id: string, geometry: Geometry) => void;
  onRemove: (id: string) => void;
  onPaint: (terrain: string) => void;
  t: Translate;
}) {
  const { geo, tool, selectedId, language, pictureOpacity, t } = props;
  const pictureLayer = useRef<L.TileLayer | null>(null);
  const latest = useRef(props);
  latest.current = props;
  const { frame, grid, terrain, picture } = geo.delve;
  const { crs, maxZoom, kmPerPx } = useMemo(() => mapCrs(frame, picture), [frame, picture]);
  const { containerRef, map } = useLeaflet(
    { crs, minZoom: maxZoom - 6, maxZoom: maxZoom + 1, zoomSnap: 0.5 },
    `${maxZoom}|${kmPerPx}`,
  );
  const bounds = useMemo(
    () => L.latLngBounds([0, 0], [frame.height_km, frame.width_km]),
    [frame.height_km, frame.width_km],
  );

  // Once per map: the whole frame in sight, the zoom control, and Geoman's words in the reader's language.
  useEffect(() => {
    if (!map) return;
    map.fitBounds(bounds);
    map.setMaxBounds(bounds.pad(0.5));
    const zoom = L.control
      .zoom({ position: "topright", zoomInTitle: t("worldMap.zoomIn"), zoomOutTitle: t("worldMap.zoomOut") })
      .addTo(map);
    map.pm.setLang(
      language === "nl" ? "nl" : "en",
      {
        tooltips: {
          placeMarker: t("worldMapEditor.draw.placeMarker"),
          firstVertex: t("worldMapEditor.draw.firstVertex"),
          continueLine: t("worldMapEditor.draw.continueLine"),
          finishLine: t("worldMapEditor.draw.finishLine"),
          finishPoly: t("worldMapEditor.draw.finishPoly"),
        },
      },
      "en",
    );
    const onCreate = (e: { shape: string; layer: L.Layer }) => {
      e.layer.remove();
      const drawn = latest.current.tool;
      const geometry = geometryOf(e.layer);
      if (geometry && drawn in DRAWN) latest.current.onCreate(drawn as DrawTool, geometry);
    };
    map.on("pm:create", onCreate);
    return () => {
      map.off("pm:create", onCreate);
      zoom.remove();
    };
  }, [map, bounds, language, t]);

  // The picture's own tiles, unfogged: the organiser sees the whole picture.
  useEffect(() => {
    if (!map || !picture) return;
    const layer = L.tileLayer(pictureTileUrl(picture.id), {
      bounds: L.latLngBounds([0, 0], [picture.height_px * picture.km_per_px, picture.width_px * picture.km_per_px]),
      minZoom: maxZoom - 6,
      maxZoom: maxZoom + 1,
      minNativeZoom: 0,
      maxNativeZoom: maxZoom,
      noWrap: true,
      pmIgnore: true,
      opacity: latest.current.pictureOpacity / 100,
    } as L.TileLayerOptions).addTo(map);
    layer.bringToBack();
    pictureLayer.current = layer;
    return () => {
      layer.remove();
      pictureLayer.current = null;
    };
  }, [map, picture, maxZoom]);

  // The Picture slider fades the picture without loading its tiles again.
  useEffect(() => {
    pictureLayer.current?.setOpacity(pictureOpacity / 100);
  }, [pictureOpacity]);

  // The terrain cells, over the picture faintly, or alone in Delve's colours.
  useEffect(() => {
    if (!map) return;
    const group = L.layerGroup([], { pmIgnore: true }).addTo(map);
    const every = new Set(Array.from({ length: grid.cols * grid.rows }, (_, i) => i));
    const renderer = terrainRenderer();
    for (const [terrainClass, rings] of Object.entries(terrainAreas(grid, terrain, every)))
      L.polygon(
        rings.map((ring) => [ring.map(toLatLng)]),
        {
          renderer,
          className: `world-terrain world-terrain-${terrainClass}`,
          stroke: false,
          fillColor: TERRAIN_COLOURS[terrainClass],
          fillOpacity: picture ? 0.35 : 1,
          interactive: false,
          pmIgnore: true,
        },
      ).addTo(group);
    return () => {
      group.remove();
    };
  }, [map, grid, terrain, picture]);

  // The features, each with Geoman's edit, drag and remove on it when those tools are on.
  useEffect(() => {
    if (!map) return;
    const group = L.featureGroup().addTo(map);
    const features = [...geo.features].sort(
      (a, b) => LAYER_ORDER.indexOf(a.properties.layer) - LAYER_ORDER.indexOf(b.properties.layer),
    );
    for (const feature of features) {
      const layer = featureLayer(feature, feature.id === selectedId);
      if (!layer) continue;
      if (feature.properties.name && layer instanceof L.Path) layer.bindTooltip(nameTooltip(feature.properties.name), { sticky: true });
      const reshaped = () => {
        const geometry = geometryOf(layer);
        if (geometry) latest.current.onGeometry(feature.id, geometry);
      };
      layer.on("pm:edit", reshaped);
      layer.on("pm:dragend", reshaped);
      layer.on("pm:remove", () => latest.current.onRemove(feature.id));
      layer.on("click", () => {
        if (latest.current.tool !== "remove") latest.current.onSelect(feature.id);
      });
      layer.addTo(group);
    }
    return () => {
      group.remove();
    };
  }, [map, geo.features, selectedId]);

  // The tool: one of Geoman's modes, the brush, or none.
  useEffect(() => {
    if (!map) return;
    const pm = map.pm;
    if (tool in DRAWN)
      pm.enableDraw(DRAWN[tool as DrawTool].shape, {
        continueDrawing: false,
        markerStyle: { icon: L.divIcon({ className: "world-place world-place-new", iconAnchor: [5, 5] }) },
      });
    else if (tool === "edit") pm.enableGlobalEditMode();
    else if (tool === "drag") pm.enableGlobalDragMode();
    else if (tool === "remove") pm.enableGlobalRemovalMode();
    const cleanup = tool === "brush" ? brushOn(map, latest) : () => {};
    return () => {
      cleanup();
      pm.disableDraw();
      pm.disableGlobalEditMode();
      pm.disableGlobalDragMode();
      pm.disableGlobalRemovalMode();
    };
  }, [map, tool]);

  return (
    <div
      ref={containerRef}
      className="world-leaflet"
      role="region"
      aria-label={t("world.mapAlt", { title: props.title })}
      style={{ background: FOG }}
    />
  );
}

/** The terrain brush on `map`: a press paints the cells under it with the brush's class, and so does each move until
 * it is let go; the whole stroke is one step to undo. A tap (a phone's) paints once. Answers its undoing. */
function brushOn(
  map: L.Map,
  latest: { current: { geo: GeoDocument; brush: { terrainClass: string; radiusKm: number }; onPaint: (t: string) => void } },
): () => void {
  map.dragging.disable();
  const live = L.layerGroup([], { pmIgnore: true }).addTo(map);
  const ring = L.circle([0, 0], {
    radius: 0,
    interactive: false,
    color: "#a3261b",
    weight: 1,
    fill: false,
    pmIgnore: true,
  });
  let stroke: string | null = null;

  const paintAt = (latLng: L.LatLng, terrain: string): string => {
    const { geo, brush } = latest.current;
    const letter = LETTER_OF_TERRAIN[brush.terrainClass];
    const cells = cellsUnder(geo.delve.grid, pointOf(latLng), brush.radiusKm).filter((i) => terrain[i] !== letter);
    for (const i of cells)
      L.polygon(cellPolygon(geo.delve.grid, i).map(toLatLng), {
        stroke: false,
        fillColor: TERRAIN_COLOURS[TERRAIN_OF_LETTER[letter]],
        fillOpacity: 1,
        interactive: false,
        pmIgnore: true,
      }).addTo(live);
    return paint(terrain, cells, letter);
  };
  const end = () => {
    if (stroke === null) return;
    const painted = stroke;
    stroke = null;
    live.clearLayers();
    latest.current.onPaint(painted);
  };
  const down = (e: L.LeafletMouseEvent) => {
    stroke = paintAt(e.latlng, latest.current.geo.delve.terrain);
  };
  const move = (e: L.LeafletMouseEvent) => {
    ring.setLatLng(e.latlng).setRadius(latest.current.brush.radiusKm);
    if (!map.hasLayer(ring)) ring.addTo(map);
    if (stroke !== null) stroke = paintAt(e.latlng, stroke);
  };
  const tap = (e: L.LeafletMouseEvent) => {
    if (stroke !== null) return;
    const painted = paintAt(e.latlng, latest.current.geo.delve.terrain);
    live.clearLayers();
    latest.current.onPaint(painted);
  };
  map.on("mousedown", down);
  map.on("mousemove", move);
  map.on("mouseup", end);
  map.on("mouseout", end);
  map.on("click", tap);
  return () => {
    end();
    map.off("mousedown", down);
    map.off("mousemove", move);
    map.off("mouseup", end);
    map.off("mouseout", end);
    map.off("click", tap);
    ring.remove();
    live.remove();
    map.dragging.enable();
  };
}
