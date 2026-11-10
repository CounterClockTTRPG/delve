import { useEffect } from "react";
import { X } from "lucide-react";
import CharacterSheet from "../campaign/CharacterSheet";
import type { Character } from "../api";
import Tip from "../components/Tip";
import { useT } from "../i18n";

/** A character's sheet (plateau 2a's CharacterSheet) in a drawer over the play screen; Escape closes it. */
export default function SheetDrawer({
  character,
  onClose,
  mayRepaint = false,
}: {
  character: Character | undefined;
  onClose: () => void;
  /** Whether this seat may repaint the portrait (DEL-135). */
  mayRepaint?: boolean;
}) {
  const t = useT();

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  return (
    <aside className="sheet-drawer" data-testid="sheet-drawer" role="dialog" aria-label={t("play.sheet")}>
      <Tip label={t("play.closeSheet")} side="left">
        <button type="button" className="icon sheet-drawer-close" aria-label={t("play.closeSheet")} onClick={onClose}>
          <X size={18} aria-hidden="true" />
        </button>
      </Tip>
      {character ? <CharacterSheet character={character} mayRepaint={mayRepaint} /> : <p className="placeholder">{t("play.loadingSheet")}</p>}
    </aside>
  );
}
