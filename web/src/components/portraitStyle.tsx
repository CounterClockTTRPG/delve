import { useQuery } from "@tanstack/react-query";
import { createContext, useContext, useMemo, type ReactNode } from "react";
import { getPlayState, playKeys } from "../play/api";

/** portraitgen's render styles (`delve.play.portraits.PORTRAIT_STYLES`), in the order the campaign page offers them.
 * `illustrated`, the first, is the look every portrait had before styles. */
export const PORTRAIT_STYLES = ["illustrated", "realistic", "painterly", "inkwash", "engraving", "anime", "pixel"] as const;
export const DEFAULT_PORTRAIT_STYLE = PORTRAIT_STYLES[0];

/** The campaign page's sample: one face, drawn in each style. */
export const SAMPLE_PORTRAIT = { kind: "traits", describe: "a weathered human ranger", seed: "delve-sample" } as const;

const PortraitStyle = createContext<{ pc: string; npc: string }>({ pc: DEFAULT_PORTRAIT_STYLE, npc: DEFAULT_PORTRAIT_STYLE });

/**
 * The campaign's portrait styles, a PC's and an NPC's, for every `Portrait` inside: read from the play state, which
 * every seat at the table reads. Each is the campaign's own style, else the one Preferences pick for PCs or NPCs as
 * portraitgen's model (DEL-252). Until it has loaded, and without a campaign's answer, `illustrated`.
 */
export function PortraitStyleProvider({ campaignId, children }: { campaignId: string; children: ReactNode }) {
  const state = useQuery({ queryKey: playKeys.state(campaignId), queryFn: () => getPlayState(campaignId) });
  const pc = state.data?.portrait_style ?? DEFAULT_PORTRAIT_STYLE;
  const npc = state.data?.npc_portrait_style ?? pc;
  const value = useMemo(() => ({ pc, npc }), [pc, npc]);
  return <PortraitStyle.Provider value={value}>{children}</PortraitStyle.Provider>;
}

/** The style the portraits here are drawn in: an NPC's with `npc`. */
export function usePortraitStyle(npc = false): string {
  const styles = useContext(PortraitStyle);
  return npc ? styles.npc : styles.pc;
}
