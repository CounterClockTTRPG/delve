import L from "leaflet";
import { useEffect, useMemo, useRef, type ReactNode } from "react";
import { useT } from "../i18n";
import type { DmView, GeoFeatureView, Geometry, JourneyView, SeatView } from "./api";
import { mapCrs, niceScale, toLatLng, type Point } from "./crs";
import { FOG, FOG_TILE, TERRAIN_COLOURS, cellCentre, knownCells, terrainAreas } from "./fog";
import { nameTooltip } from "./nameTooltip";
import { LeafletContext, useLeaflet } from "./useLeaflet";

const SCALE_PX = 120;

let canDrawOnCanvas: boolean | null = null;

/** The canvas renderer when the browser can draw on a canvas; jsdom can't, and gets SVG. Asked once. */
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

const lines = (geometry: Geometry): Point[][] =>
  geometry.type === "LineString"
    ? [geometry.coordinates]
    : geometry.type === "MultiLineString"
      ? geometry.coordinates
      : [];

const areas = (geometry: Geometry): Point[][][] =>
  geometry.type === "Polygon" ? [geometry.coordinates] : geometry.type === "MultiPolygon" ? geometry.coordinates : [];

const latLngs = (points: Point[]) => points.map(toLatLng);

/** The journey's line cut at `done_km` along it: what is behind the party, and what is ahead. */
export function splitJourney(journey: JourneyView): { done: Point[]; ahead: Point[] } {
  const points = journey.points;
  let left = journey.done_km;
  for (let i = 1; i < points.length; i++) {
    const [ax, ay] = points[i - 1];
    const [bx, by] = points[i];
    const step = Math.hypot(bx - ax, by - ay);
    if (left <= step) {
      const k = step === 0 ? 0 : left / step;
      const cut: Point = [ax + (bx - ax) * k, ay + (by - ay) * k];
      return { done: [...points.slice(0, i), cut], ahead: [cut, ...points.slice(i)] };
    }
    left -= step;
  }
  return { done: points, ahead: [] };
}

function placeIcon(feature: GeoFeatureView): L.DivIcon {
  const html = document.createElement("span");
  const dot = document.createElement("span");
  dot.className = "world-place-dot";
  const label = document.createElement("span");
  label.className = "world-place-label";
  label.textContent = feature.name;
  html.append(dot, label);
  return L.divIcon({
    className: `world-place world-place-${feature.kind}`,
    html,
    iconSize: undefined,
    iconAnchor: [5, 5],
  });
}

function partyIcon(title: string): L.DivIcon {
  const html = document.createElement("span");
  html.title = title;
  html.setAttribute("role", "img");
  html.setAttribute("aria-label", title);
  return L.divIcon({ className: "world-party", html, iconSize: [18, 18], iconAnchor: [9, 9] });
}

/** The known cells and the party, a cell around them; null when the party knows the whole map, or nothing of it. */
function knownBounds(view: SeatView | DmView): L.LatLngBounds | null {
  if (view.known.all) return null;
  const points: Point[] = [];
  for (const i of knownCells(view.known.cells)) points.push(cellCentre(view.grid, i));
  if (view.party) points.push(view.party);
  if (points.length === 0) return null;
  const pad = view.grid.size_km;
  const xs = points.map(([x]) => x);
  const ys = points.map(([, y]) => y);
  return L.latLngBounds([Math.min(...ys) - pad, Math.min(...xs) - pad], [Math.max(...ys) + pad, Math.max(...xs) + pad]);
}

/** The features drawn on the map: regions under the water, the water under the routes, the places on top. */
function featureLayer(feature: GeoFeatureView, onSelect?: (id: string) => void): L.Layer | null {
  let layer: L.Layer | null = null;
  const kind = `world-${feature.layer}-${feature.kind}`;
  if (feature.layer === "places" && feature.geometry.type === "Point") {
    layer = L.marker(toLatLng(feature.geometry.coordinates), {
      icon: placeIcon(feature),
      title: feature.name,
      keyboard: true,
    });
  } else if (feature.layer === "regions") {
    layer = L.polygon(
      areas(feature.geometry).map((rings) => rings.map(latLngs)),
      {
        className: `world-region ${kind}`,
        color: "#6b4e2e",
        weight: 1.5,
        dashArray: "6 4",
        fillOpacity: 0.04,
      },
    );
  } else if (feature.layer === "water" && (feature.kind === "lake" || feature.kind === "sea")) {
    layer = L.polygon(
      areas(feature.geometry).map((rings) => rings.map(latLngs)),
      {
        className: `world-water ${kind}`,
        color: TERRAIN_COLOURS[feature.kind],
        weight: 1,
        fillColor: TERRAIN_COLOURS[feature.kind],
        fillOpacity: 0.55,
      },
    );
  } else if (feature.layer === "water") {
    layer = L.polyline(lines(feature.geometry).map(latLngs), {
      className: `world-river ${kind}`,
      color: "#2f6fb0",
      weight: 2.5,
    });
  } else if (feature.layer === "routes") {
    layer = L.polyline(lines(feature.geometry).map(latLngs), {
      className: `world-route ${kind}`,
      color: "#7a4a1e",
      weight: feature.kind === "road" ? 2.5 : 1.5,
      dashArray: feature.kind === "road" ? undefined : feature.kind === "track" ? "6 3" : "2 4",
    });
  }
  if (!layer) return null;
  if (feature.layer !== "places" && feature.name && layer instanceof L.Path)
    layer.bindTooltip(nameTooltip(feature.name), { sticky: true });
  if (onSelect) layer.on("click", () => onSelect(feature.id));
  return layer;
}

/** A scale bar in the map's units, which follows the zoom. */
function scaleControl(kmPerPxAt: (zoom: number) => number, units: "km" | "miles", unitLabel: string): L.Control {
  const control = new L.Control({ position: "topleft" });
  control.onAdd = (map: L.Map) => {
    const bar = L.DomUtil.create("div", "world-scale");
    const update = () => {
      const { length, px } = niceScale(kmPerPxAt(map.getZoom()), units, SCALE_PX);
      bar.style.width = `${Math.round(px)}px`;
      bar.textContent = `${length} ${unitLabel}`;
    };
    map.on("zoomend", update);
    control.onRemove = () => map.off("zoomend", update);
    update();
    return bar;
  };
  return control;
}

/**
 * A world map in Leaflet, in km (`crs.ts`): the picture's tiles under the server's fog, or for a map without a picture
 * the known cells in Delve's terrain colours; the features the view holds; the party's marker; its journey, done solid
 * and ahead dashed; and a scale bar in the map's units. Everything comes from the view, which the server cut to what
 * this seat may see: a tile it doesn't send is drawn as fog.
 */
export default function WorldMapView({
  view,
  tileUrl,
  onSelect,
  children,
}: {
  view: SeatView | DmView;
  tileUrl: string | null;
  onSelect?: (id: string) => void;
  children?: ReactNode;
}) {
  const t = useT();
  const { crs, maxZoom, kmPerPx } = useMemo(() => mapCrs(view.frame, view.picture), [view.frame, view.picture]);
  // Far enough out for the whole Flanaess on a phone; the tiles below zoom 0 are zoom 0's, scaled.
  const minZoom = maxZoom - 6;
  const { containerRef, map } = useLeaflet(
    { crs, minZoom, maxZoom: maxZoom + 1, zoomSnap: 0.5 },
    `${view.name}|${maxZoom}|${kmPerPx}`,
  );
  const bounds = useMemo(
    () => L.latLngBounds([0, 0], [view.frame.height_km, view.frame.width_km]),
    [view.frame.height_km, view.frame.width_km],
  );
  const fitted = useRef<L.Map | null>(null);

  // What the party knows in sight once per map; a new view of the same map keeps where the reader looked.
  useEffect(() => {
    if (!map || fitted.current === map) return;
    fitted.current = map;
    map.fitBounds(knownBounds(view) ?? bounds);
    map.setMaxBounds(bounds.pad(0.5));
    L.control
      .zoom({ position: "topright", zoomInTitle: t("worldMap.zoomIn"), zoomOutTitle: t("worldMap.zoomOut") })
      .addTo(map);
  }, [map, bounds, t]);

  useEffect(() => {
    if (!map) return;
    const unit = view.units;
    const control = scaleControl((zoom) => kmPerPx * 2 ** (maxZoom - zoom), unit, t(`worldMap.unit.${unit}`)).addTo(
      map,
    );
    return () => {
      control.remove();
    };
  }, [map, kmPerPx, maxZoom, view.units, t]);

  useEffect(() => {
    if (!map) return;
    const group = L.layerGroup().addTo(map);
    const picture = view.picture;
    if (picture && tileUrl) {
      L.tileLayer(tileUrl, {
        bounds: L.latLngBounds([0, 0], [picture.height_px * picture.km_per_px, picture.width_px * picture.km_per_px]),
        minZoom,
        maxZoom: maxZoom + 1,
        minNativeZoom: 0,
        maxNativeZoom: maxZoom,
        noWrap: true,
        errorTileUrl: FOG_TILE,
      }).addTo(group);
    } else {
      const known = view.known.all
        ? new Set(Array.from({ length: view.grid.cols * view.grid.rows }, (_, i) => i))
        : knownCells(view.known.cells);
      const renderer = terrainRenderer();
      for (const [terrainClass, rings] of Object.entries(terrainAreas(view.grid, view.terrain, known))) {
        L.polygon(
          rings.map((ring) => [latLngs(ring)]),
          {
            renderer,
            className: `world-terrain world-terrain-${terrainClass}`,
            stroke: false,
            fillColor: TERRAIN_COLOURS[terrainClass],
            fillOpacity: 1,
            interactive: false,
          },
        ).addTo(group);
      }
    }
    const order = ["regions", "water", "routes", "places"];
    const features = [...view.features].sort((a, b) => order.indexOf(a.layer) - order.indexOf(b.layer));
    for (const feature of features) featureLayer(feature, onSelect)?.addTo(group);

    if (view.journey && view.journey.points.length > 1) {
      const { done, ahead } = splitJourney(view.journey);
      if (done.length > 1)
        L.polyline(latLngs(done), {
          className: "world-journey world-journey-done",
          color: "#a3261b",
          weight: 3,
          interactive: false,
        }).addTo(group);
      if (ahead.length > 1)
        L.polyline(latLngs(ahead), {
          className: "world-journey world-journey-ahead",
          color: "#a3261b",
          weight: 3,
          dashArray: "8 6",
          interactive: false,
        }).addTo(group);
    }
    if (view.party)
      L.marker(toLatLng(view.party), {
        icon: partyIcon(t("worldMap.party")),
        zIndexOffset: 1000,
        keyboard: false,
      }).addTo(group);
    return () => {
      group.remove();
    };
  }, [map, view, tileUrl, onSelect, minZoom, maxZoom, t]);

  return (
    <div
      ref={containerRef}
      className="world-leaflet"
      role="region"
      aria-label={t("world.mapAlt", { title: view.title || view.name })}
      style={{ background: FOG }}
    >
      {map && <LeafletContext.Provider value={map}>{children}</LeafletContext.Provider>}
    </div>
  );
}
