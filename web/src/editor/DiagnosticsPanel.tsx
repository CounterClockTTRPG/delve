import { useT } from "../i18n";
import type { Diagnostic } from "./types";
import styles from "./DiagnosticsPanel.module.css";

export function DiagnosticsPanel({
  diagnostics,
  onJump,
}: {
  diagnostics: Diagnostic[];
  onJump?: (d: Diagnostic) => void;
}) {
  const t = useT();
  const errs = diagnostics.filter((d) => d.severity === "error").length;
  const warns = diagnostics.filter((d) => d.severity === "warning").length;
  const ok = errs === 0 && warns === 0;
  return (
    <div className={styles.panel}>
      <div className={`${styles.status} ${ok ? styles.statusOk : ""}`}>
        {ok ? (
          <span>{t("editor.diagnostics.none")}</span>
        ) : (
          <span>
            {errs > 0 ? (
              <span className={styles.errCount}>
                {t(errs === 1 ? "editor.diagnostics.error" : "editor.diagnostics.errors", { count: String(errs) })}
              </span>
            ) : null}
            {errs > 0 && warns > 0 ? " · " : ""}
            {warns > 0 ? (
              <span className={styles.warnCount}>
                {t(warns === 1 ? "editor.diagnostics.warning" : "editor.diagnostics.warnings", {
                  count: String(warns),
                })}
              </span>
            ) : null}
          </span>
        )}
      </div>
      {diagnostics.length > 0 ? (
        <ul className={styles.list}>
          {diagnostics.map((d, i) => {
            const className = `${styles.item} ${d.severity === "error" ? styles.itemErr : styles.itemWarn}`;
            const body = (
              <>
                <span className={styles.line}>{d.line > 0 ? `${d.line}:${d.column}` : "—"}</span>
                <span className={styles.message}>{d.message}</span>
              </>
            );
            // A button, so the keyboard jumps to the line too.
            return (
              <li key={i}>
                {onJump ? (
                  <button type="button" className={className} onClick={() => onJump(d)}>
                    {body}
                  </button>
                ) : (
                  <div className={className}>{body}</div>
                )}
              </li>
            );
          })}
        </ul>
      ) : null}
    </div>
  );
}
