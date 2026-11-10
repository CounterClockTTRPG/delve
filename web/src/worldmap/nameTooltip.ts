/**
 * A feature's name for Leaflet's `bindTooltip`, as text: given a string, Leaflet sets it as `innerHTML`, so a name
 * from the editor, a GeoJSON import or a `.dscn` could put markup (a fake login form) on the players' map (DEL-151).
 */
export function nameTooltip(name: string): HTMLElement {
  const span = document.createElement("span");
  span.textContent = name;
  return span;
}
