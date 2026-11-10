/**
 * Faces on the fight's tokens (DEL-10): a character's token shows its portrait instead of its initial, in a ring of
 * its side's colour, with an arc of the hit points it has left. The map's SVG comes from the server with a disc and
 * an initial per token (`delve.maps.tokens`), its `data-name` the combatant's id, which for a character is its id;
 * `withTokenFaces` puts the face in here, as the party sidebar draws it (`Portrait`), so the server never draws
 * portraits. Only the party's own characters get a face and an arc: an enemy keeps its disc, and the table never
 * sees its hit points (the timeline's fourth wall, `delve.play.timeline`).
 */
import type { Portrait as PortraitRecord } from "../api";
import { portraitSvg } from "../components/Portrait";
import { pictureUrl } from "./api";

const SVG_NS = "http://www.w3.org/2000/svg";

/** What a token shows of a character: its portrait (null for none), and its hit points when the seat knows them. */
export interface TokenFace {
  portrait: PortraitRecord | null;
  hp?: number;
  hpMax?: number;
}

/** The share of its hit points a character has left, from 0 to 1; null when there is nothing to show. */
export function hpLeft(face: Pick<TokenFace, "hp" | "hpMax"> | undefined): number | null {
  if (!face || face.hp === undefined || !face.hpMax || face.hpMax <= 0) return null;
  return Math.min(1, Math.max(0, face.hp / face.hpMax));
}

/** How hurt: what colours the arc. */
export function hpTone(left: number): "healthy" | "wounded" | "critical" {
  return left > 0.5 ? "healthy" : left > 0.25 ? "wounded" : "critical";
}

export const HP_COLOURS = { healthy: "#3fbf5f", wounded: "#e0a92e", critical: "#e0412b" } as const;

/** The pixels a drawn portrait is rendered at before the map scales it: enough for a zoomed-in token. */
const DRAWN_SIZE = 96;

/**
 * The map's SVG with a face on each token of `faces` (by character id). `idPrefix` keeps the ids of this drawing's
 * portraits apart from those of any other drawing on the page. An SVG that doesn't parse is answered as it came.
 */
export function withTokenFaces(
  svg: string,
  faces: Record<string, TokenFace>,
  { campaignId, style, idPrefix }: { campaignId: string; style: string; idPrefix: string },
): string {
  if (!svg.includes('class="marker"') || Object.keys(faces).length === 0) return svg;
  const doc = new DOMParser().parseFromString(svg, "image/svg+xml");
  if (doc.getElementsByTagName("parsererror").length > 0) return svg;
  let changed = false;
  doc.querySelectorAll("g.marker[data-name]").forEach((marker, index) => {
    const face = faces[marker.getAttribute("data-name") ?? ""];
    const disc = marker.querySelector(":scope > circle");
    if (!face || !disc) return;
    const cx = Number(disc.getAttribute("cx"));
    const cy = Number(disc.getAttribute("cy"));
    const r = Number(disc.getAttribute("r"));
    if (![cx, cy, r].every(Number.isFinite) || r <= 0) return;
    const side = disc.getAttribute("fill") ?? "#2c7be5";
    const prefix = `${idPrefix}t${index}`;
    const parts: Element[] = [];
    const picture = facePicture(doc, face.portrait, { cx, cy, r, campaignId, style, prefix });
    if (picture) {
      // The disc and its initial make way for the portrait; the caption under the token stays.
      const initial = marker.querySelector(":scope > text");
      disc.remove();
      initial?.remove();
      parts.push(...picture, element(doc, "circle", { cx, cy, r, fill: "none", stroke: side, "stroke-width": r * 0.22 }));
    }
    const left = hpLeft(face);
    if (left !== null) parts.push(...hpArc(doc, cx, cy, r, left));
    if (parts.length === 0) return;
    marker.setAttribute("data-face", picture ? "portrait" : "initial");
    marker.prepend(...parts);
    changed = true;
  });
  return changed ? new XMLSerializer().serializeToString(doc) : svg;
}

/** The portrait clipped to the token's circle: a drawn one as a nested SVG, a painted one as an image. */
function facePicture(
  doc: Document,
  portrait: PortraitRecord | null,
  { cx, cy, r, campaignId, style, prefix }: { cx: number; cy: number; r: number; campaignId: string; style: string; prefix: string },
): Element[] | null {
  if (!portrait) return null;
  const box = { x: cx - r, y: cy - r, width: r * 2, height: r * 2 };
  let picture: Element;
  if (portrait.kind === "traits") {
    const drawn = new DOMParser().parseFromString(portraitSvg(portrait, DRAWN_SIZE, prefix, { style }), "image/svg+xml");
    if (drawn.getElementsByTagName("parsererror").length > 0) return null;
    picture = doc.importNode(drawn.documentElement, true);
    for (const [name, value] of Object.entries(box)) picture.setAttribute(name, String(value));
    picture.setAttribute("preserveAspectRatio", "xMidYMid slice");
  } else if (portrait.kind === "image") {
    picture = element(doc, "image", { ...box, href: pictureUrl(campaignId, portrait.image_id), preserveAspectRatio: "xMidYMid slice" });
  } else {
    return null;
  }
  const clip = `${prefix}clip`;
  const defs = element(doc, "defs", {});
  const clipPath = element(doc, "clipPath", { id: clip });
  clipPath.append(element(doc, "circle", { cx, cy, r }));
  defs.append(clipPath);
  const held = element(doc, "g", { "clip-path": `url(#${clip})`, class: "token-face" });
  held.append(element(doc, "circle", { cx, cy, r, fill: "#1c1c1c" }), picture);
  return [defs, held];
}

/** A thin arc just outside the ring, from the top clockwise, as long as the share of hit points left. */
function hpArc(doc: Document, cx: number, cy: number, r: number, left: number): Element[] {
  const radius = r * 1.17;
  const width = r * 0.16;
  const turn = `rotate(-90 ${cx} ${cy})`;
  const track = element(doc, "circle", { cx, cy, r: radius, fill: "none", stroke: "#000", "stroke-opacity": 0.35, "stroke-width": width });
  const arc = element(doc, "circle", {
    cx,
    cy,
    r: radius,
    fill: "none",
    stroke: HP_COLOURS[hpTone(left)],
    "stroke-width": width,
    pathLength: 100,
    "stroke-dasharray": `${round(left * 100)} 100`,
    transform: turn,
    class: "token-hp",
    "data-hp-left": round(left),
  });
  return [track, arc];
}

function element(doc: Document, name: string, attributes: Record<string, string | number>): Element {
  const made = doc.createElementNS(SVG_NS, name);
  for (const [key, value] of Object.entries(attributes)) made.setAttribute(key, typeof value === "number" ? String(round(value)) : value);
  return made;
}

const round = (value: number) => Math.round(value * 1000) / 1000;
