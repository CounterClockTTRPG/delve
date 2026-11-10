// The part of the vendored portraitgen (web/vendor/portraitgen) that Delve uses. Its own code is JavaScript and is
// not type-checked here.
declare module "portraitgen" {
  export interface GenerateOptions {
    /** A plain-language request, such as "a stout old male dwarf". */
    describe?: string;
    seed?: string;
  }
  export type Traits = Record<string, unknown>;
  /** Blinking: true, or a timing override in seconds. */
  export type Blink = boolean | { every?: number; delay?: number; double?: boolean };
  export interface RenderOptions {
    size?: number;
    idPrefix?: string;
    /** One of RENDER_STYLES; the traits' own style when absent. */
    style?: string;
    /** Emote ids (keys of EMOTES), animated with CSS inside the SVG. */
    emotes?: string[];
    blink?: Blink;
    /** The line a `talk` emote lip-syncs. */
    say?: string;
    /** Play the emotes one time, ending on the still portrait; idle emotes (blink, breathe) go on. */
    once?: boolean;
  }
  export function generate(options?: GenerateOptions): Traits;
  /** The SVG; every id in it starts with `idPrefix`. */
  export function render(traits: Traits, options?: RenderOptions): string;
  /** How long the emotes take to play once, in ms (0 for none, or for idle emotes alone). */
  export function emoteDuration(traits: Traits, options?: { emotes?: string[]; say?: string }): number;
  /** The render styles by id, each with its label. */
  export const RENDER_STYLES: Record<string, { id: string; label: string }>;
  export const EMOTES: Record<string, unknown>;
}
