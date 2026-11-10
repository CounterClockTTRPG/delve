import { useId, useLayoutEffect, useRef, useState } from "react";
import { useT } from "../i18n";

/**
 * A module card's one-line summary (DEL-360), kept to two lines so the cards in a row stay alike. Only when it is cut
 * off does a More open the rest, in place, and Less close it again; a click on the text does the same. Whether it is
 * cut off is measured, not guessed from its length: the card's width (and so the line breaks) changes with the window.
 */
export default function CardSummary({ text }: { text: string }) {
  const t = useT();
  const id = useId();
  const ref = useRef<HTMLParagraphElement>(null);
  const [open, setOpen] = useState(false);
  const [cut, setCut] = useState(false);

  useLayoutEffect(() => {
    const element = ref.current;
    if (!element || open) return;
    const measure = () => setCut(element.scrollHeight > element.clientHeight + 1);
    measure();
    const observer = new ResizeObserver(measure);
    observer.observe(element);
    return () => observer.disconnect();
  }, [text, open]);

  const toggle = () => setOpen((was) => !was);
  return (
    <div className="module-card-summary-box">
      <p
        id={id}
        ref={ref}
        className={["module-card-summary", (cut || open) && "is-cut", open && "is-open"].filter(Boolean).join(" ")}
        onClick={cut || open ? toggle : undefined}
      >
        {text}
      </p>
      {(cut || open) && (
        <button type="button" className="module-card-summary-more" aria-expanded={open} aria-controls={id} onClick={toggle}>
          {open ? t("modules.summaryLess") : t("modules.summaryMore")}
        </button>
      )}
    </div>
  );
}
