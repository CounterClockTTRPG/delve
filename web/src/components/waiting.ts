import type { Translate } from "../i18n";
import type { Waiting } from "../play/api";

/**
 * "Waiting in assetgen's queue: number 3." while a painting waits its turn at its painter (DEL-138), so a slow queue
 * doesn't look stuck; null once it runs, or when the painter doesn't say.
 */
export function queuedLine(t: Translate, waiting: Waiting | null | undefined): string | null {
  if (!waiting?.queue) return null;
  return t("painting.queued", { provider: waiting.provider || "?", queue: String(waiting.queue) });
}
