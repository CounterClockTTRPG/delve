import { useState } from "react";
import { useT } from "../i18n";

export type Layout = "table" | "cards";

function stored(key: string): Layout {
  try {
    return localStorage.getItem(key) === "cards" ? "cards" : "table";
  } catch {
    return "table";
  }
}

/** A list's layout, Table or Cards, this browser's choice kept under `key` (DEL-123, DEL-207). */
export function useLayout(key: string): [Layout, (next: Layout) => void] {
  const [layout, setLayout] = useState<Layout>(() => stored(key));
  const choose = (next: Layout) => {
    setLayout(next);
    try {
      localStorage.setItem(key, next);
    } catch {
      // A private window: the choice holds for this visit.
    }
  };
  return [layout, choose];
}

/** The Table | Cards switch. */
export function LayoutSwitch({ value, onChange }: { value: Layout; onChange: (next: Layout) => void }) {
  const t = useT();
  return (
    <div className="segmented" role="group" aria-label={t("modules.layout")}>
      {(["table", "cards"] as const).map((name) => (
        <button key={name} type="button" aria-pressed={value === name} onClick={() => onChange(name)}>
          {t(`modules.layout.${name}`)}
        </button>
      ))}
    </div>
  );
}

/** A card's banner across its top, or, without one, `title`'s first letter on the sunken surface. */
export function CardBanner({ src, title }: { src: string | null; title: string }) {
  return src ? (
    <img className="module-card-banner" src={src} alt="" loading="lazy" />
  ) : (
    <span className="module-card-banner module-card-blank" aria-hidden="true">
      {Array.from(title.trim())[0]?.toUpperCase() ?? ""}
    </span>
  );
}
