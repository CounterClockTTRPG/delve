import { useId, useLayoutEffect, useMemo, useRef, type ReactNode } from "react";
import { generate, render, type RenderOptions } from "portraitgen";
import type { Portrait as PortraitRecord } from "../api";
import { useT } from "../i18n";
import Lightbox from "./Lightbox";
import { pictureUrl } from "../play/api";
import { DEFAULT_PORTRAIT_STYLE, usePortraitStyle } from "./portraitStyle";

type Traits = Extract<PortraitRecord, { kind: "traits" }>;
type Look = Pick<RenderOptions, "style" | "emotes" | "say" | "once">;

/**
 * portraitgen's SVG for a description and a seed: the same pair always draws the same face. `illustrated`, like no
 * style, draws the portrait in its own look, as before styles: a description may ask for a realistic one. An edited
 * portrait (DEL-238) is drawn from its own traits, or from its description and seed when this portraitgen can't draw
 * them.
 */
export function portraitSvg(portrait: Traits, size: number, idPrefix: string, look: Look = {}): string {
  const style = look.style === DEFAULT_PORTRAIT_STYLE ? undefined : look.style;
  const options = { size, idPrefix, ...look, style };
  if (portrait.traits) {
    try {
      return render(portrait.traits, options);
    } catch {
      // drawn from the description below
    }
  }
  return render(generate({ describe: portrait.describe, seed: portrait.seed }), options);
}

/**
 * A character's portrait (plan 6): drawn by portraitgen from its description and seed, a painted picture from the
 * pictures route, or, without one, the initial. A drawn one is in the campaign's portrait style (`usePortraitStyle`)
 * or its own `style`, and plays its `emotes` (a `talk` lip-syncs `say`; `once` plays them one time); a painted one is
 * as it was painted. Each drawing gets ids of its own, so two of the same character on one page don't share their
 * gradients. Never import `portraitgen/node`: it pulls in resvg. `rate` plays the emotes faster (2: twice as fast),
 * as a spoken line does to keep up with its words.
 *
 * A drawn or painted portrait enlarges on a click, in a dialog (`ENLARGED` px, drawn again at that size), which a
 * click or Escape closes; the click stops at the portrait, so a party card around it doesn't open the sheet. With
 * `enlarge` false it is only the picture, such as a token's face on the initiative timeline (DEL-10).
 */
export default function Portrait({
  campaignId,
  portrait,
  name,
  size,
  style,
  emotes,
  say,
  once,
  rate = 1,
  enlarge = true,
  npc = false,
}: {
  campaignId: string;
  portrait: PortraitRecord | null;
  name: string;
  size: number;
  /** One of PORTRAIT_STYLES, over the campaign's. */
  style?: string;
  emotes?: string[];
  say?: string;
  once?: boolean;
  rate?: number;
  enlarge?: boolean;
  /** An NPC's portrait: drawn in the NPCs' style (DEL-252). */
  npc?: boolean;
}) {
  // useId gives ":r0:", and an SVG id that url(#…) refers to wants no colons.
  const idPrefix = `pg${useId().replace(/[^A-Za-z0-9_-]/g, "")}`;
  const campaignStyle = usePortraitStyle(npc);
  const drawnStyle = style ?? campaignStyle;
  const traits = portrait?.kind === "traits" ? portrait : null;
  const emoteKey = emotes?.join(" ");
  const svg = useMemo(
    () => (traits ? portraitSvg(traits, size, idPrefix, { style: drawnStyle, emotes, say, once }) : ""),
    // The emotes by their ids: a new array of the same ones draws nothing new.
    [traits?.describe, traits?.seed, traitsKey(traits), size, idPrefix, drawnStyle, emoteKey, say, once],
  );
  const drawn = useRef<HTMLSpanElement>(null);
  // portraitgen times its emotes in CSS; the browser's own animations of the drawing set their pace.
  useLayoutEffect(() => {
    for (const animation of drawn.current?.getAnimations?.({ subtree: true }) ?? []) animation.playbackRate = rate;
  }, [svg, rate]);
  const box = { width: size, height: size };
  if (traits) {
    const face = (
      <span ref={drawn} className="portrait drawn" role="img" aria-label={name} style={box} dangerouslySetInnerHTML={{ __html: svg }} />
    );
    if (!enlarge) return face;
    return (
      <Enlargeable name={name} big={<Drawn traits={traits} name={name} style={drawnStyle} idPrefix={`${idPrefix}big`} />}>
        {face}
      </Enlargeable>
    );
  }
  if (portrait?.kind === "image") {
    const src = pictureUrl(campaignId, portrait.image_id);
    const face = <img className="portrait painted" src={src} alt={name} style={box} loading="lazy" />;
    if (!enlarge) return face;
    return (
      <Enlargeable name={name} big={<img className="portrait painted big" src={src} alt={name} />}>
        {face}
      </Enlargeable>
    );
  }
  return (
    <span className="portrait" aria-hidden="true" style={box}>
      {name.slice(0, 1)}
    </span>
  );
}

/** An edited portrait's traits as one string, so that the same ones draw nothing new. */
function traitsKey(traits: Traits | null): string | undefined {
  return traits?.traits ? JSON.stringify(traits.traits) : undefined;
}

/** How big an enlarged portrait is drawn, in px (the page shows it at up to 80% of the screen's shorter side). */
export const ENLARGED = 480;

function Drawn({ traits, name, style, idPrefix }: { traits: Traits; name: string; style: string; idPrefix: string }) {
  const svg = useMemo(() => portraitSvg(traits, ENLARGED, idPrefix, { style }), [traits, idPrefix, style]);
  return <span className="portrait drawn big" role="img" aria-label={name} dangerouslySetInnerHTML={{ __html: svg }} />;
}

/** The portrait as a `Lightbox`: a click shows `big`. */
function Enlargeable({ name, big, children }: { name: string; big: ReactNode; children: ReactNode }) {
  const t = useT();
  return (
    <Lightbox label={t("portraits.enlarge", { name })} title={name} big={big} className="portrait-zoom">
      {children}
    </Lightbox>
  );
}
