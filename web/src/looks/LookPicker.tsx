import { useId } from "react";
import { useT, type MessageKey } from "../i18n";
import { LOOKS, useLook, type Look } from "./looks";

const NAMES: Record<Look, MessageKey> = {
  delve: "look.delve",
  "gold-wood": "look.goldWood",
  "dark-dungeon": "look.darkDungeon",
};

/** The look picker: in Preferences, and `compact` in the play screen's header. */
export default function LookPicker({ compact = false }: { compact?: boolean }) {
  const t = useT();
  const id = useId();
  const [look, setLook] = useLook();
  return (
    <div className={compact ? "look-picker compact" : "field look-picker"}>
      <label htmlFor={id} className={compact ? "visually-hidden" : undefined}>
        {t("look.title")}
      </label>
      <span className="look-control">
        <span className="look-swatch" data-swatch={look} aria-hidden="true" />
        {/* In the play screen's header, a word beside the swatch where there is room (DEL-259). */}
        {compact && (
          <span className="head-tool-label" aria-hidden="true">
            {t("look.title")}
          </span>
        )}
        <select
          id={id}
          value={look}
          title={compact ? t(NAMES[look]) : undefined}
          onChange={(e) => setLook(e.target.value as Look)}
        >
          {LOOKS.map((option) => (
            <option key={option} value={option}>
              {t(NAMES[option])}
            </option>
          ))}
        </select>
      </span>
      {!compact && <span className="hint">{t("look.hint")}</span>}
    </div>
  );
}
