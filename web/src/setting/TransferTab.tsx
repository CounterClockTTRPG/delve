// A setting's Export and import tab (DEL-366): this install's additions to the setting (its added and overridden
// pages, its facts, its own world maps with their pictures, DM-only content marked so) as a file for another Delve,
// and such a file imported here, keeping or replacing what this install has already. The shipped setting is its pack's,
// downloaded in Preferences' Packs.
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useRef, useState } from "react";
import { Link } from "react-router-dom";
import { useT } from "../i18n";
import { additionsExportUrl, importAdditions, type ImportedAdditions } from "../preferences/packs";

export default function TransferTab({ settingId }: { settingId: string }) {
  const t = useT();
  const client = useQueryClient();
  const file = useRef<HTMLInputElement>(null);
  const [keep, setKeep] = useState(true);
  const [done, setDone] = useState<ImportedAdditions | null>(null);
  const run = useMutation({
    mutationFn: (chosen: File) => importAdditions(settingId, chosen, keep),
    onSuccess: ({ imported }) => {
      setDone(imported);
      // The setting's pages, facts and maps changed: every tab reads them again.
      void client.invalidateQueries();
    },
    onSettled: () => {
      if (file.current) file.current.value = "";
    },
  });

  return (
    <div className="setting-transfer" data-testid="setting-transfer">
      <section aria-labelledby="transfer-export">
        <h2 id="transfer-export">{t("transfer.export")}</h2>
        <p className="lede">{t("transfer.exportAbout")}</p>
        <a className="button-like" href={additionsExportUrl(settingId)} download data-testid="transfer-export-link">
          {t("transfer.download")}
        </a>
        <p className="hint">
          {t("transfer.packHint")} <Link to="/preferences?tab=packs">{t("transfer.packLink")}</Link>
        </p>
      </section>

      <section aria-labelledby="transfer-import">
        <h2 id="transfer-import">{t("transfer.import")}</h2>
        <p className="lede">{t("transfer.importAbout")}</p>
        <fieldset className="transfer-keep">
          <legend>{t("transfer.whenThere")}</legend>
          <label>
            <input type="radio" name="transfer-keep" checked={keep} onChange={() => setKeep(true)} />
            {t("transfer.keepMine")}
          </label>
          <label>
            <input type="radio" name="transfer-keep" checked={!keep} onChange={() => setKeep(false)} />
            {t("transfer.takeTheirs")}
          </label>
        </fieldset>
        <label htmlFor="transfer-file">{t("transfer.file")}</label>
        <input
          id="transfer-file"
          ref={file}
          type="file"
          accept=".zip,application/zip"
          data-testid="transfer-file"
          disabled={run.isPending}
          onChange={(e) => {
            const chosen = e.target.files?.[0];
            if (chosen) {
              setDone(null);
              run.mutate(chosen);
            }
          }}
        />
        {run.isPending && <p className="hint">{t("transfer.importing")}</p>}
        {run.error && (
          <p role="alert" className="notice error">
            {run.error.message}
          </p>
        )}
        {done && (
          <p className="notice" role="status" data-testid="transfer-done">
            {t("transfer.done", {
              pages: String(done.pages_added + done.pages_replaced),
              facts: String(done.facts_added),
              maps: String(done.maps_added + done.maps_replaced),
              kept: String(done.pages_kept + done.facts_kept + done.maps_kept),
            })}
          </p>
        )}
      </section>
    </div>
  );
}
