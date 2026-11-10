import type { ReactNode } from "react";
import type { SeatRole } from "../api";
import { VoiceContext, useVoice } from "./useVoice";

/**
 * Voice at the table (table voice and fixes Task V2.2): holds the play screen's one voice connection, so it outlives
 * the phone's screens and ends with the play screen. `allowed` is false when the campaign's voice is off; an observer
 * (`role`) only listens. `VoiceControls` and `SeatIndicators` read it through `useVoiceState()`.
 */
export default function VoiceProvider({
  campaignId,
  allowed,
  role,
  children,
}: {
  campaignId: string;
  allowed: boolean;
  role: SeatRole;
  children: ReactNode;
}) {
  const voice = useVoice({ campaignId, allowed, role });
  return <VoiceContext.Provider value={voice}>{children}</VoiceContext.Provider>;
}
