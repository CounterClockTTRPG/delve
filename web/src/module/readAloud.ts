import { headingKey } from "./MarkdownRoundTrip";

/** A text's top-level block, as the read-aloud rule sees it: a heading (its level and text), a quote, or other. */
export type Block = { heading: { level: number; text: string } } | { quote: true } | { other: true };

/**
 * Which blocks are read-aloud, as the server's `sections_of` reads them (faithful modules Task 11, Delve's reading of
 * R13): under a keyed heading every quote up to the next heading; under another heading only the quotes straight
 * after it. Only the decoration follows this rule; the Markdown is never changed.
 */
export function readAloud(blocks: Block[]): boolean[] {
  let keyed = false;
  let leading = false;
  return blocks.map((block) => {
    if ("heading" in block) {
      keyed = headingKey(block.heading.level, block.heading.text) !== null;
      leading = true;
      return false;
    }
    if ("quote" in block) return keyed || leading;
    leading = false;
    return false;
  });
}
