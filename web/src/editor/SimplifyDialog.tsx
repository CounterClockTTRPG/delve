// Review dialog for "Simplify": lists what the backend would drop (redundant
// corridor nodes, covered stubs, room points on a straight wall) per
// corridor/room, plus suggestions it deliberately left alone, before the
// editor applies the rewritten source to its buffer. Applying goes through
// the editor's value, so Ctrl+Z undoes it and nothing is saved until Save.
import { useEffect } from "react";
import { useT } from "../i18n";
import type { SimplifyResponse } from "./types";
import { Button } from "./Primitives";
import styles from "./SimplifyDialog.module.css";

// The change kinds with a label (editor.simplify.kind.<kind>); others show as they are.
const KINDS = new Set([
  "collinear-node",
  "covered-spur",
  "duplicate-node",
  "duplicate-run",
  "zero-run",
  "unused-node",
  "collinear-segment",
  "collinear-point",
  "duplicate-point",
  "collinear-edge",
]);

function counts(stats: SimplifyResponse["stats"][string]): string {
  return Object.entries(stats)
    .filter(([, v]) => v.before !== v.after)
    .map(([k, v]) => `${k} ${v.before} → ${v.after}`)
    .join(", ");
}

export function SimplifyDialog({
  result,
  doorSpurs,
  loading,
  error,
  onDoorSpurs,
  onApply,
  onClose,
  onJump,
}: {
  result: SimplifyResponse | null;
  doorSpurs: boolean;
  loading: boolean;
  error: string | null;
  onDoorSpurs: (v: boolean) => void;
  onApply: () => void;
  onClose: () => void;
  onJump?: (line: number) => void;
}) {
  const t = useT();
  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      if (e.key === "Escape") onClose();
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  const applied = result?.changes.filter((c) => c.applied) ?? [];
  const kept = result?.changes.filter((c) => !c.applied) ?? [];
  const targets = [...new Set(applied.map((c) => c.target))];

  return (
    <div className={styles.backdrop} onMouseDown={onClose}>
      <div
        className={styles.dialog}
        role="dialog"
        aria-modal="true"
        aria-labelledby="simplify-title"
        onMouseDown={(e) => e.stopPropagation()}
      >
        <h2 id="simplify-title" className={styles.title}>
          {t("editor.simplify.title")}
        </h2>
        <p className={styles.lede}>
          {t("editor.simplify.lede")}
        </p>

        {loading ? <p className={styles.muted}>{t("editor.simplify.analysing")}</p> : null}
        {error ? <p className={styles.error}>{error}</p> : null}

        {result && !loading ? (
          applied.length === 0 ? (
            <p className={styles.muted} data-testid="simplify-nothing">
              {t("editor.simplify.nothing")}
            </p>
          ) : (
            <ul className={styles.targets} data-testid="simplify-changes">
              {targets.map((target) => (
                <li key={target}>
                  <div className={styles.target}>
                    <code>{target}</code>
                    {result.stats[target] ? (
                      <span className={styles.counts}>{counts(result.stats[target])}</span>
                    ) : null}
                  </div>
                  <ul className={styles.changes}>
                    {applied
                      .filter((c) => c.target === target)
                      .map((c, i) => (
                        <li key={i}>
                          <button
                            type="button"
                            className={styles.line}
                            onClick={() => onJump?.(c.line)}
                            title={t("editor.simplify.showInEditor")}
                          >
                            L{c.line}
                          </button>{" "}
                          <span className={styles.kind}>
                            {KINDS.has(c.kind) ? t(`editor.simplify.kind.${c.kind}`) : c.kind}
                          </span>{" "}
                          — {c.message}
                        </li>
                      ))}
                  </ul>
                </li>
              ))}
            </ul>
          )
        ) : null}

        {kept.length > 0 && !loading ? (
          <div className={styles.kept} data-testid="simplify-kept">
            <strong>{t("editor.simplify.leftAlone", { count: String(kept.length) })}</strong>
            <ul className={styles.changes}>
              {kept.map((c, i) => (
                <li key={i}>
                  <code>{c.target}</code> L{c.line} — {c.message}
                </li>
              ))}
            </ul>
          </div>
        ) : null}

        <label className={styles.option}>
          <input
            type="checkbox"
            checked={doorSpurs}
            onChange={(e) => onDoorSpurs(e.target.checked)}
          />{" "}
          {t("editor.simplify.doorSpurs")}{" "}
          <span className={styles.muted}>{t("editor.simplify.doorSpursHint")}</span>
        </label>

        <div className={styles.actions}>
          <Button variant="ghost" onClick={onClose}>
            {t("editor.simplify.cancel")}
          </Button>
          <Button
            onClick={onApply}
            disabled={loading || !result || applied.length === 0}
          >
            {applied.length > 0
              ? t("editor.simplify.applyCount", { count: String(applied.length) })
              : t("editor.simplify.apply")}
          </Button>
        </div>
      </div>
    </div>
  );
}
