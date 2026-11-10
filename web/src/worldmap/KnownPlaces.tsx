import { useT } from "../i18n";
import type { DmView, GeoFeatureView, SeatView } from "./api";

/** The place the party is at: the one named `here`, else the nearest within a cell of the party's point. */
function partyPlace(view: SeatView | DmView, places: GeoFeatureView[], here?: string | null): string | null {
  if (here) {
    const named = places.find((place) => place.name === here);
    if (named) return named.id;
  }
  if (!view.party) return null;
  const [px, py] = view.party;
  let best: { id: string; d: number } | null = null;
  for (const place of places) {
    if (place.geometry.type !== "Point") continue;
    const [x, y] = place.geometry.coordinates;
    const d = Math.hypot(x - px, y - py);
    if (d <= view.grid.size_km && (!best || d < best.d)) best = { id: place.id, d };
  }
  return best?.id ?? null;
}

/**
 * The places the view holds, as a list beside the map: what a screen reader reads of the map, and a way to find a
 * place on a small screen. Only what the server sent is listed, so only what the party knows.
 */
export default function KnownPlaces({
  view,
  here,
  selected,
  onSelect,
}: {
  view: SeatView | DmView;
  here?: string | null;
  /** The place picked on the map or in the list, marked. */
  selected?: string | null;
  onSelect?: (id: string) => void;
}) {
  const t = useT();
  const places = view.features
    .filter((feature) => feature.layer === "places")
    .sort((a, b) => a.name.localeCompare(b.name));
  const at = partyPlace(view, places, here);

  if (places.length === 0) return <p className="placeholder">{t("worldMap.noPlaces")}</p>;
  return (
    <ul className="known-places" aria-label={t("worldMap.knownPlaces")}>
      {places.map((place) => (
        <li
          key={place.id}
          className={["known-place", place.id === at && "here", place.id === selected && "selected"]
            .filter(Boolean)
            .join(" ")}
        >
          <button
            type="button"
            className="known-place-pick"
            aria-pressed={place.id === selected}
            onClick={() => onSelect?.(place.id)}
          >
            <span className="known-place-name">{place.name}</span>{" "}
            <span className="row-meta">{t(`worldMap.kind.${place.kind}`)}</span>
          </button>
          {place.id === at && <span className="known-place-here">{t("worldMap.youAreHere")}</span>}
          {place.description && <p className="known-place-description">{place.description}</p>}
        </li>
      ))}
    </ul>
  );
}
