import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useContext, useEffect } from "react";
import { EventsContext, listConversions, queryKeys, type Conversion, type ConversionEvent } from "../api";
import { safeStorage } from "../desktop/storage";
import type { Translate } from "../i18n";

/**
 * The conversions as the Modules list, the nav and the end notice see them: `GET /api/conversions`, kept up to date
 * by the `conversion` events. An event moves its conversion's step and count in the list; one that says it ended
 * fetches the list again, and the modules with it.
 */
export function useConversions(): Conversion[] {
  const client = useQueryClient();
  const subscribe = useContext(EventsContext);
  const conversions = useQuery({ queryKey: queryKeys.conversions, queryFn: listConversions });

  useEffect(
    () =>
      subscribe({
        conversion: (data) => {
          const event = data as ConversionEvent | null;
          if (!event?.id) return;
          const list = client.getQueryData<Conversion[]>(queryKeys.conversions);
          if (event.status === "running" && list?.some((c) => c.id === event.id)) {
            client.setQueryData<Conversion[]>(queryKeys.conversions, (old) =>
              old?.map((c) => (c.id === event.id ? { ...c, ...event } : c)),
            );
            return;
          }
          client.invalidateQueries({ queryKey: queryKeys.conversions });
          if (event.status !== "running") client.invalidateQueries({ queryKey: queryKeys.modules });
        },
      }),
    [subscribe, client],
  );

  return conversions.data ?? [];
}

/** "Step 2 of 4 · Converting the text", or the step alone before the first. */
export function stepLine(t: Translate, conversion: Pick<Conversion, "step" | "steps">): string {
  const step = t(`conversion.step.${conversion.step}`);
  const steps = conversion.steps;
  return steps && steps.index > 0
    ? t("conversion.stepOf", { index: String(steps.index), count: String(steps.count), step })
    : step;
}

/** The Claude CLI's usage limit, as the server words a pause for it (`pieces.USAGE_LIMIT`). */
export const USAGE_LIMIT = "The Claude usage limit was reached.";
/** A pause for a Delve that stopped while the conversion ran (`workspace.DELVE_STOPPED`). */
export const DELVE_STOPPED = "Delve stopped";
/** A pause by hand (`workspace.PAUSED_BY_ORGANISER`). */
export const PAUSED_BY_ORGANISER = "paused by the organiser";

/**
 * Why a thorough conversion paused, in the reader's words: Delve stopped; the organiser paused it; the usage limit, and
 * when it resets (then it resumes by itself); or the error that paused it.
 */
export function pauseLine(t: Translate, conversion: Pick<Conversion, "paused" | "error">, language?: string): string {
  const reason = conversion.paused?.reason ?? conversion.error ?? "";
  if (reason === DELVE_STOPPED) return t("conversion.pausedStopped");
  if (reason === PAUSED_BY_ORGANISER) return t("conversion.pausedByHand");
  if (reason === USAGE_LIMIT) {
    const at = conversion.paused?.resets_at;
    return at ? t("conversion.pausedLimitAt", { time: resetTime(at, language) }) : t("conversion.pausedLimit");
  }
  return t("conversion.pausedError", { error: reason });
}

/** The usage limit's reset: an ISO time in the reader's own clock and language, else as the notice wrote it ("3am (UTC)"). */
function resetTime(at: string, language?: string): string {
  const time = Date.parse(at);
  return Number.isNaN(time) ? at : new Date(time).toLocaleString(language, { dateStyle: "medium", timeStyle: "short" });
}

/** "12 of 300 pages", or null while there is no count. A history writes texts (the DM's, then the table's), not
 * chapters. */
export function countLine(
  t: Translate,
  conversion: Pick<Conversion, "step" | "done" | "total"> & Partial<Pick<Conversion, "kind">>,
): string | null {
  const key = conversion.kind === "history" && conversion.step === "writing" ? "history.writing" : conversion.step;
  return conversion.total > 0
    ? t(`conversion.count.${key}`, { done: String(conversion.done), total: String(conversion.total) })
    : null;
}

// The finished conversions whose end has been seen: a done one's module opened, or a failed one dismissed. Kept in
// this browser only, the newest last.
const SEEN = "delve.conversions.seen";
const SEEN_KEPT = 50;

function seen(): string[] {
  try {
    const parsed: unknown = JSON.parse(safeStorage.getItem(SEEN) ?? "[]");
    return Array.isArray(parsed) ? parsed.filter((s): s is string => typeof s === "string") : [];
  } catch {
    return [];
  }
}

/** Remember that the end of a conversion was seen: by its id, or by the id of the module it made. Blocked site data
 * keeps nothing, and throws nothing (DEL-174). */
export function markSeen(id: string): void {
  const kept = seen().filter((s) => s !== id);
  safeStorage.setItem(SEEN, JSON.stringify([...kept, id].slice(-SEEN_KEPT)));
}

/** Whether a conversion makes a module: a book's and a request's do; a world map's reading and a map draft don't. */
export function makesModule(conversion: Pick<Conversion, "kind">): boolean {
  return conversion.kind === "pdf" || conversion.kind === "generate";
}

/**
 * Where a finished conversion's result is: a module job's module; a world map's review (a module's, a campaign's or a setting's), from its `target`; the
 * Maps tab of the module a draft was drawn for; a novel's reader; or the History of a history's campaign. Null while
 * there is nothing to open.
 */
export function conversionLink(conversion: Pick<Conversion, "kind" | "module_id" | "target">): string | null {
  const target = conversion.target ?? {};
  const part = encodeURIComponent;
  if (conversion.kind === "novel") return target.novel_id ? `/novels/${part(target.novel_id)}` : null;
  if (conversion.kind === "history") return target.campaign_id ? `/campaigns/${part(target.campaign_id)}#history` : null;
  if (conversion.kind === "worldmap") {
    const [owner, id] = target.module_id
      ? ["module", target.module_id]
      : target.setting_id
        ? ["setting", target.setting_id]
        : ["campaign", target.campaign_id];
    return id && target.name ? `/world-maps/${owner}/${part(id)}/${part(target.name)}/review` : null;
  }
  if (!makesModule(conversion)) return target.module_id ? `/modules/${part(target.module_id)}?tab=maps` : null;
  return conversion.module_id ? `/modules/${part(conversion.module_id)}` : null;
}

/** The conversion that runs, if one does. */
export function runningOf(conversions: Conversion[]): Conversion | null {
  return conversions.find((c) => c.status === "running") ?? null;
}

/** The newest finished conversion that makes a module, while its end hasn't been seen: done with a module, or failed. */
export function unseenEnd(conversions: Conversion[]): Conversion | null {
  const latest = conversions.find((c) => c.status !== "running" && makesModule(c));
  if (!latest || (latest.status !== "done" && latest.status !== "failed")) return null;
  const known = seen();
  if (known.includes(latest.id) || (latest.module_id && known.includes(latest.module_id))) return null;
  return latest;
}
