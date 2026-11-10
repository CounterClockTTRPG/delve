import { MapPin, TriangleAlert } from "lucide-react";
import { useT } from "../i18n";

/**
 * The small map chip beside a keyed heading: the room it links to, or a warning that no room has its key.
 * It isn't part of the text, so the editor can't put the cursor in it.
 */
export default function KeyChip({ label, map, warning }: { label: string; map?: string; warning?: string }) {
  const t = useT();
  if (warning !== undefined) {
    return (
      <span className="key-chip warning" contentEditable={false} title={warning} aria-label={t("text.keyWithoutRoom", { key: label })}>
        <TriangleAlert aria-hidden size={13} />
        {t("text.noRoom")}
      </span>
    );
  }
  return (
    <span className="key-chip" contentEditable={false} aria-label={t("text.linkedRoom", { label, map: map ?? "" })}>
      <MapPin aria-hidden size={13} />
      {label}
    </span>
  );
}
