import L from "leaflet";

// Geoman's build reads Leaflet from the global `L`. Imported before Geoman, this module sets it first.
(window as unknown as { L: typeof L }).L = L;
