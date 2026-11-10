/**
 * The twelve heraldic emblems a player's avatar may be (players and tavern Task G1), in the server's order
 * (`delve.domain.accounts.EMBLEMS`). Each is a heater shield with one charge, cut like a woodcut: flat shapes in one
 * ink (`currentColor`), holes by winding (solids clockwise, holes counter-clockwise, `fill-rule` nonzero), and no
 * reference to anything outside the drawing, so it needs no id and draws the same wherever it is.
 */

export const EMBLEMS = ["lion", "eagle", "stag", "boar", "wolf", "dragon", "tower", "key", "sword", "crown", "moon", "oak"] as const;
export type EmblemName = (typeof EMBLEMS)[number];

export function isEmblem(name: unknown): name is EmblemName {
  return typeof name === "string" && (EMBLEMS as readonly string[]).includes(name);
}

/** A clockwise circle: a solid. */
const disc = (x: number, y: number, r: number) => `M${x - r} ${y}a${r} ${r} 0 1 1 ${2 * r} 0a${r} ${r} 0 1 1 ${-2 * r} 0Z`;
/** A counter-clockwise circle: a hole in the solid under it. */
const hole = (x: number, y: number, r: number) => `M${x - r} ${y}a${r} ${r} 0 1 0 ${2 * r} 0a${r} ${r} 0 1 0 ${-2 * r} 0Z`;

/** The shield's edge: the outline, less the field inside it. */
const SHIELD =
  "M8 5H56V28C56 44 46 53 32 59C18 53 8 44 8 28Z" + "M11.5 8.5V28C11.5 41.5 20 49.5 32 55.2C44 49.5 52.5 41.5 52.5 28V8.5Z";

const CHARGES: Record<EmblemName, string> = {
  // A lion rampant, facing the viewer's left: a shaggy mane, raised forepaws, a tufted tail.
  lion:
    "M23.5 10.5L26 12.5L28.5 11.5L29 14L31.5 13.5L31 16.5L33.5 17L32.5 19.5L35 21L36.5 26L39 31.5L42 27L41.5 21" +
    "L43 16.5L45.5 13L46 16L48.5 15.5L46.5 18.5L44.5 21L45 26L42.5 33L42 36L43 41L46.5 45L48 48.5H40L38.5 45.5" +
    "L36.5 42.5L33.5 42L30.5 44.5L31.5 47L33 48.5H25.5L25 45L26.5 40.5L27 36.5L25.5 33L22.5 31.5L18.5 31.5L16 32.5" +
    "L15.5 30L18 27.5L22.5 27L23 25L19.5 23.5L16.5 22.5L16.5 20L19 19.5L22.5 20.5L21 19.5L18 19L16.5 17L19 14.5L21.5 13Z" +
    hole(23.5, 15.8, 0.9),
  // An eagle displayed: wings spread and raised, head turned to the viewer's right.
  eagle:
    disc(32, 17, 3.6) +
    "M35 15.8L39 17.6L35 19.4Z" +
    "M32 20L35 21L37 26L40.5 22L43.5 17L47.5 13L50 12L49 16.5L51 18L49 21.5L51 24L49 27L50.5 30L46.5 31L41 31L36 32" +
    "L36 38L39.5 45.5L35.5 44.5L34 49L32 46.5L30 49L28.5 44.5L24.5 45.5L28 38L28 32L23 31L17.5 31L13.5 30L15 27" +
    "L13 24L15 21.5L13 18L15 16.5L14 12L16.5 13L20.5 17L23.5 22L27 26L29 21Z",
  // A stag's head caboshed: the head seen from the front, without its neck, under branching antlers.
  stag:
    "M26 27L20.5 23.5L16.5 17.5L15.5 11L18 11.5L19.5 16.5L21 10L23 10.5L22.5 17L24.5 20.5L25.5 15L27.5 15.5L27 21.5L29.5 25.5" +
    "L32 26.5L34.5 25.5L37 21.5L36.5 15.5L38.5 15L39.5 20.5L41.5 17L41 10.5L43 10L44.5 16.5L46 11.5L48.5 11L47.5 17.5" +
    "L43.5 23.5L38 27L38.5 29L43.5 28L40.5 32.5L37 33.5L35.5 42L34.5 46.5H29.5L28.5 42L27 33.5L23.5 32.5L20.5 28L25.5 29Z" +
    hole(29, 32, 1.1) +
    hole(35, 32, 1.1),
  // A boar's head couped, facing the viewer's left: a flat snout, a tall ear, a bristled back, a white tusk.
  boar:
    "M14 28.5L21 25L25 23L26 14L30.5 21L33 19.5L34.5 23L37.5 20L38.5 24L41.5 21.5L42.5 25.5L45 25L46.5 44H33.5L29 41" +
    "L24 38.5L19.5 37L14 35Z" +
    "M22 35.5L23.8 34.8L19.5 30.8L17.5 30.5Z" +
    hole(27.5, 27.5, 1.4),
  // A wolf's head couped, facing the viewer's left: pricked ears, a long snout, the jaws open.
  wolf:
    "M14 29.5L24 25L28 22L28.5 13L32.5 20.5L36.5 14L38 22L42 26.5L44 33L46 44H33.5L31 38.5L23.5 36.5L16.5 34L22.5 33" +
    "L15 31Z" +
    hole(29, 26.5, 1.3),
  // A dragon's head couped, facing the viewer's left: two horns, a spined crest, the jaws open.
  dragon:
    "M14 27L20 23L25 22L29.5 12.5L30.5 20.5L37 14L35.5 21.5L40 24L44 22.5L43.5 27.5L47.5 29L45.5 33L48.5 36.5L45.5 38" +
    "L46.5 46H34.5L31.5 38.5L23 35L16 34.5L22.5 31L15 29.5Z" +
    hole(27, 25.5, 1.4),
  // A tower: battlements, a window, an arched door.
  tower:
    "M20 14H25V18H29.5V14H34.5V18H39V14H44V22.5H42V48H22V22.5H20Z" + "M36 48V40.5A4 4 0 0 0 28 40.5V48Z" + "M30.5 26V32.5H33.5V26Z",
  // A key, its bow at the top and its bit to the viewer's right.
  key: disc(32, 18.5, 7) + hole(32, 18.5, 3.4) + "M30 24H34V38H41V42H37.5V44H41V48H30Z",
  // A sword, its point down: pommel, grip, cross-guard, blade.
  sword:
    disc(32, 13.5, 2.6) + "M30.5 15H33.5V22H30.5Z" + "M20.5 23.5L23 21.5H41L43.5 23.5L41 25.5H23Z" + "M28.8 25.5H35.2V44L32 51L28.8 44Z",
  // A crown of three points, each with its pearl, over a band of three jewels.
  crown:
    "M19 37.5L16.5 22.5L25 30L32 18.5L39 30L47.5 22.5L45 37.5Z" +
    disc(16.5, 20.5, 2.6) +
    disc(32, 16, 2.8) +
    disc(47.5, 20.5, 2.6) +
    "M18 39.5H46V46H18Z" +
    hole(25, 42.75, 1.6) +
    hole(32, 42.75, 1.6) +
    hole(39, 42.75, 1.6),
  // A crescent, its horns up.
  moon: "M19.67 25.46A15 15 0 1 0 44.33 25.46A12.5 12.5 0 1 1 19.67 25.46Z",
  // An oak: a round crown of leaves on a trunk that spreads at its foot.
  oak:
    disc(32, 21, 9) +
    disc(23, 26.5, 7) +
    disc(41, 26.5, 7) +
    disc(25.5, 33, 6) +
    disc(38.5, 33, 6) +
    disc(32, 30.5, 7) +
    "M29.5 34H34.5V43.5L39.5 48H24.5L29.5 43.5Z",
};

/** An emblem; `title` names it for a screen reader, and without it the drawing is decoration. */
export function Emblem({ name, title, size }: { name: EmblemName | string; title?: string; size?: number }) {
  const charge = CHARGES[isEmblem(name) ? name : "tower"];
  return (
    <svg
      className="emblem"
      viewBox="0 0 64 64"
      fill="currentColor"
      width={size}
      height={size}
      role={title ? "img" : undefined}
      aria-hidden={title ? undefined : true}
      data-emblem={name}
    >
      {title && <title>{title}</title>}
      <g>
        <path className="emblem-shield" d={SHIELD} fillRule="evenodd" />
        <path className="emblem-charge" d={charge} />
      </g>
    </svg>
  );
}
