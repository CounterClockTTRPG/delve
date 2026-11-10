import L from "leaflet";
import "leaflet/dist/leaflet.css";
import { createContext, useContext, useEffect, useRef, useState, type RefObject } from "react";

/** The Leaflet map of the nearest `WorldMapView`, for what its children draw on it; null until it is made. */
export const LeafletContext = createContext<L.Map | null>(null);

export const useLeafletMap = () => useContext(LeafletContext);

/**
 * Makes a Leaflet map in the returned container and disposes of it on unmount, or when `key` changes (a new CRS needs
 * a new map). No react-leaflet: the callers add and remove their layers in their own effects. Leaflet's attribution
 * control stays off (it links out), and so does its default zoom control, whose titles the caller gives in its language.
 */
export function useLeaflet(
  options: L.MapOptions,
  key: string,
): { containerRef: RefObject<HTMLDivElement>; map: L.Map | null } {
  const containerRef = useRef<HTMLDivElement>(null);
  const [map, setMap] = useState<L.Map | null>(null);
  const optionsRef = useRef(options);
  optionsRef.current = options;

  useEffect(() => {
    const container = containerRef.current;
    if (!container) return;
    const made = L.map(container, { attributionControl: false, zoomControl: false, ...optionsRef.current });
    // The container's size follows the layout (a tab shown, a phone turned): Leaflet has to be told.
    const resize = new ResizeObserver(() => made.invalidateSize());
    resize.observe(container);
    setMap(made);
    return () => {
      resize.disconnect();
      made.remove();
      setMap(null);
    };
  }, [key]);

  return { containerRef, map };
}
