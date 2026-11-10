import { useT } from "../i18n";
import PersonLink from "./PersonLink";
import type { ProfileSummary } from "./api";
import "./profile.css";

/** Someone at a table, as its card shows them: the host, a co-host or a player. */
export interface TablePerson {
  seat_id: string;
  name: string;
  role: string;
  profile: ProfileSummary | null;
}

/**
 * Who sits at a table, on its card in My tables and Find a table (DEL-217): a face for each of them, the host first,
 * each a button to their profile card; a grey blank for each open place; and "4/6 seats taken", or "4 at the table"
 * when the table has no limit. Nothing for a table of its host alone with no places to fill.
 */
export default function TableFaces({
  people,
  slots,
  taken,
}: {
  people: TablePerson[] | undefined;
  slots: number | null | undefined;
  taken: number | undefined;
}) {
  const t = useT();
  if (!people || (people.length <= 1 && slots == null)) return null;
  const open = slots == null ? 0 : Math.max(0, slots - (taken ?? 0));
  return (
    <div className="table-faces" data-testid="table-faces">
      <ul aria-label={t("faces.label")}>
        {people.map((person) => (
          <li key={person.seat_id}>
            <PersonLink profile={person.profile} name={person.name} size={28} faceOnly />
          </li>
        ))}
        {Array.from({ length: open }, (_, i) => (
          <li key={`open-${i}`} aria-hidden="true">
            <span className="face-open" title={t("faces.open")} />
          </li>
        ))}
      </ul>
      <span className="row-meta">
        {slots == null
          ? t("faces.at", { count: String(people.length) })
          : t("faces.taken", { taken: String(taken ?? 0), slots: String(slots) })}
      </span>
    </div>
  );
}
