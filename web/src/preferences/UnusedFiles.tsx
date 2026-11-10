// Storage's Files nothing uses (DEL-36): the blob store's files that no module, picture, map or account names any
// more, such as the pictures a QA pass replaced. Look says what would go and how much space it frees; Delete them
// asks first, and the server looks again before it deletes. Files put in the last day, or since a job still running
// started, stay.
import { useMutation } from "@tanstack/react-query";
import { useState } from "react";
import {
  deleteUnused,
  getUnused,
  sizeText,
  type UnusedFiles as Found,
} from "../cloud/api";
import { useConfirm } from "../components/dialogs";
import { useLanguage, useT } from "../i18n";

type Shown =
  | { kind: "found"; found: Found }
  | { kind: "deleted"; found: Found }
  | { kind: "failed"; error: string };

export default function UnusedFiles() {
  const t = useT();
  const language = useLanguage();
  const confirm = useConfirm();
  const [shown, setShown] = useState<Shown | null>(null);
  const look = useMutation({
    mutationFn: getUnused,
    onSuccess: (found) => setShown({ kind: "found", found }),
    onError: (error) =>
      setShown({
        kind: "failed",
        error: t("storage.unused.lookFailed", { error: error.message }),
      }),
  });
  const remove = useMutation({
    mutationFn: deleteUnused,
    onSuccess: (found) => setShown({ kind: "deleted", found }),
    onError: (error) =>
      setShown({
        kind: "failed",
        error: t("storage.unused.deleteFailed", { error: error.message }),
      }),
  });
  const busy = look.isPending || remove.isPending;
  const found = shown?.kind === "found" ? shown.found : null;
  const totals = (of: Found) => ({
    count: String(of.count),
    size: sizeText(language, of.size),
  });

  return (
    <section className="unused-files" aria-labelledby="unused-files-title">
      <h3 id="unused-files-title">{t("storage.unused.title")}</h3>
      <p className="hint">{t("storage.unused.intro")}</p>
      {found && found.count > 0 && (
        <>
          <p>{t("storage.unused.found", totals(found))}</p>
          <ul className="unused-kinds">
            {found.kinds.map((kind) => (
              <li key={kind.mime ?? ""}>
                {t("storage.unused.kind", {
                  kind: kind.mime ?? t("storage.unused.noRecord"),
                  count: String(kind.count),
                  size: sizeText(language, kind.size),
                })}
              </li>
            ))}
          </ul>
        </>
      )}
      {found && found.count === 0 && <p>{t("storage.unused.none")}</p>}
      {shown?.kind === "deleted" && (
        <p role="status">{t("storage.unused.deleted", totals(shown.found))}</p>
      )}
      {shown && shown.kind !== "failed" && shown.found.kept > 0 && (
        <p className="hint">
          {t("storage.unused.kept", { count: String(shown.found.kept) })}
        </p>
      )}
      {shown?.kind === "failed" && (
        <p role="alert" className="notice error">
          {shown.error}
        </p>
      )}
      <div className="actions">
        <button type="button" disabled={busy} onClick={() => look.mutate()}>
          {look.isPending
            ? t("storage.unused.looking")
            : t("storage.unused.look")}
        </button>
        {found && found.count > 0 && (
          <button
            type="button"
            className="danger"
            disabled={busy}
            onClick={async () => {
              const sure = await confirm({
                title: t("storage.unused.confirm", totals(found)),
                body: t("storage.unused.confirm.body"),
                confirm: t("storage.unused.delete"),
                danger: true,
              });
              if (sure) remove.mutate();
            }}
          >
            {remove.isPending
              ? t("storage.unused.deleting")
              : t("storage.unused.delete")}
          </button>
        )}
      </div>
    </section>
  );
}
