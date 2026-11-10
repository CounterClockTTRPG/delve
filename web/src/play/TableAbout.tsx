import { CalendarPlus } from "lucide-react";
import { useT } from "../i18n";
import { scheduleCalendarUrl, type TableAboutData } from "./api";
import { renderMarkdown } from "./markdown";
import NextSessionLine from "./NextSession";

/**
 * What a table tells its players (DEL-204), on the join page and in the Table tab: when it plays next, in the viewer's
 * own time, with its rule (part C), the host's description, in Markdown
 * (how the table plays together; the DM never reads it), how many places are taken when the table has a limit, and the
 * house rules in effect, folded together under their count and each under its title. Nothing for a table without any.
 * With `calendarFor`, a seat's own table, its schedule downloads as a calendar file (DEL-236).
 */
export default function TableAbout({
  about,
  heading = true,
  places = true,
  calendarFor,
}: {
  about: Partial<TableAboutData>;
  heading?: boolean;
  /** The campaign whose schedule this seat may download: given at the seat's own table only. */
  calendarFor?: string;
  /** False where the table's faces say how many places are taken already (Find a table, DEL-217). */
  places?: boolean;
}) {
  const t = useT();
  const description = about.description?.trim() ?? "";
  const rules = about.house_rules ?? [];
  const slots = places ? (about.slots ?? null) : null;
  const taken = about.taken ?? 0;
  const scheduled = Boolean(about.schedule) || (about.next_sessions ?? []).length > 0;
  if (!description && rules.length === 0 && slots === null && !scheduled) return null;
  return (
    <section className="table-about" data-testid="table-about" aria-label={t("listing.about")}>
      {heading && <h2>{t("listing.about")}</h2>}
      {scheduled && <NextSessionLine sessions={about.next_sessions} schedule={about.schedule} />}
      {calendarFor && about.schedule && (
        <p className="table-calendar">
          <a href={scheduleCalendarUrl(calendarFor)} download data-testid="schedule-calendar">
            <CalendarPlus size={15} aria-hidden="true" /> {t("schedule.calendar")}
          </a>
        </p>
      )}
      {slots !== null && (
        <p className={taken >= slots ? "table-places full" : "table-places"} data-testid="table-places">
          {t(taken >= slots ? "listing.placesFull" : "listing.places", { taken: String(taken), slots: String(slots) })}
        </p>
      )}
      {description && (
        <div className="markdown table-description" dangerouslySetInnerHTML={{ __html: renderMarkdown(description) }} />
      )}
      {rules.length > 0 && (
        <details className="table-rules-all">
          <summary>{t("listing.houseRulesCount", { n: String(rules.length) })}</summary>
          <ul className="table-rules">
            {rules.map((rule) => (
              <li key={rule.id}>
                <details>
                  <summary>{rule.title}</summary>
                  {rule.body_md.trim() && (
                    <div className="markdown" dangerouslySetInnerHTML={{ __html: renderMarkdown(rule.body_md) }} />
                  )}
                </details>
              </li>
            ))}
          </ul>
        </details>
      )}
    </section>
  );
}
