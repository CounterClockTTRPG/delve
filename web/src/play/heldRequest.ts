// A new player's request for a character, held until the table can act (DEL-254): asked before the host started the
// session, it was refused and lost. The picker keeps it here; the play screen puts it back in the player's box under
// the story, to send once the session starts. This browser only, one request a campaign.
import { safeStorage } from "../desktop/storage";

const key = (campaignId: string) => `delve.heldRequest.${campaignId}`;

/** Keep the request for the play screen. */
export function holdRequest(campaignId: string, text: string): void {
  safeStorage.setItem(key(campaignId), text);
}

/** The request held for the campaign, once: it is gone after. Empty when there is none. */
export function takeHeldRequest(campaignId: string): string {
  const text = safeStorage.getItem(key(campaignId)) ?? "";
  if (text) safeStorage.setItem(key(campaignId), "");
  return text;
}
