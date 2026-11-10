// Storage's Restore (cloud storage plan Task 11): what an install backed up, from this install's backups or another's
// in the same backup store (a new machine has a new install id). Items restore under their own ids, so one that is on
// this install is replaced only after the owner says so. A campaign whose module or setting isn't here brings it along
// from the same backups: ticked with it, and locked while the campaign is.
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { queryKeys } from "../api";
import {
  backupIndexKey,
  backupsKey,
  getBackupIndex,
  getBackups,
  restore,
  sizeText,
  whenText,
  type BackupItem,
  type ItemKind,
  type RestoreResult,
} from "../cloud/api";
import { useConfirm } from "../components/dialogs";
import { settingKeys } from "../setting/api";
import { useLanguage, useT } from "../i18n";

/** Modules first, then settings, then campaigns: what a campaign needs is restored ahead of it. */
const ORDER: ItemKind[] = ["module", "setting", "campaign"];

const keyOf = (item: { kind: ItemKind; item_id: string }) => `${item.kind}/${item.item_id}`;

/** What a ticked campaign brings along: its module and setting, when they are in these backups and not here. */
function broughtAlong(items: BackupItem[], ticked: Set<string>): Map<string, BackupItem> {
  const byKey = new Map(items.map((item) => [keyOf(item), item]));
  const along = new Map<string, BackupItem>();
  for (const key of ticked) {
    const campaign = byKey.get(key);
    if (campaign?.kind !== "campaign") continue;
    const needs = [
      campaign.module_id ? `module/${campaign.module_id}` : null,
      campaign.setting_id ? `setting/${campaign.setting_id}` : null,
    ];
    for (const need of needs) {
      const item = need ? byKey.get(need) : undefined;
      if (item && !item.exists_here && !ticked.has(need!) && !along.has(need!)) along.set(need!, campaign);
    }
  }
  return along;
}

export default function Restore({ installId }: { installId: string }) {
  const t = useT();
  const installs = useQuery({ queryKey: backupsKey, queryFn: getBackups, retry: false });
  const [chosen, setChosen] = useState<string | null>(null);

  // This install first, then the others as the store lists them.
  const listed = installs.data ?? [];
  const ordered = [...listed.filter((i) => i.install_id === installId), ...listed.filter((i) => i.install_id !== installId)];
  const shown = chosen ?? ordered[0]?.install_id ?? null;

  return (
    <section className="restore" aria-labelledby="restore-title">
      <h3 id="restore-title">{t("restore.title")}</h3>
      {installs.error && (
        <p role="alert" className="notice error">
          {t("restore.loadFailed", { error: installs.error.message })}
        </p>
      )}
      {installs.data && ordered.length === 0 && <p className="placeholder">{t("restore.nothing")}</p>}
      {ordered.length > 0 && (
        <div className="field">
          <label htmlFor="restore-install">{t("restore.install")}</label>
          <select id="restore-install" value={shown ?? ""} onChange={(e) => setChosen(e.target.value)}>
            {ordered.map((install) => (
              <option key={install.install_id} value={install.install_id}>
                {install.install_id === installId ? t("restore.thisInstall", { name: install.name }) : install.name}
              </option>
            ))}
          </select>
        </div>
      )}
      {shown && <Items key={shown} installId={shown} />}
    </section>
  );
}

function Items({ installId }: { installId: string }) {
  const t = useT();
  const language = useLanguage();
  const confirm = useConfirm();
  const client = useQueryClient();
  const index = useQuery({ queryKey: backupIndexKey(installId), queryFn: () => getBackupIndex(installId), retry: false });
  const [ticked, setTicked] = useState<Set<string>>(new Set());
  const [results, setResults] = useState<RestoreResult[] | null>(null);
  const [failed, setFailed] = useState<string | null>(null);
  useEffect(() => setResults(null), [ticked]);

  const items = index.data ?? [];
  const along = broughtAlong(items, ticked);
  const titles = new Map(items.map((item) => [keyOf(item), item.title]));
  const picked = items
    .filter((item) => ticked.has(keyOf(item)) || along.has(keyOf(item)))
    .sort((a, b) => ORDER.indexOf(a.kind) - ORDER.indexOf(b.kind));

  const run = useMutation({
    mutationFn: (replace: boolean) =>
      restore(installId, picked.map(({ kind, item_id }) => ({ kind, item_id })), replace),
    onMutate: () => setFailed(null),
    onSuccess: (answer) => {
      setResults(answer);
      void client.invalidateQueries({ queryKey: backupIndexKey(installId) });
      void client.invalidateQueries({ queryKey: queryKeys.modules });
      void client.invalidateQueries({ queryKey: queryKeys.campaigns });
      void client.invalidateQueries({ queryKey: settingKeys.list });
      void client.invalidateQueries({ queryKey: queryKeys.worlds });
    },
    onError: (error) => setFailed(error.message),
  });

  async function start() {
    const here = picked.filter((item) => item.exists_here);
    if (here.length > 0) {
      const sure = await confirm({
        title: t("restore.replaceConfirm"),
        body: t("restore.replaceConfirm.body", { titles: here.map((item) => item.title).join(", ") }),
        confirm: t("restore.replace"),
        danger: true,
      });
      if (!sure) return;
    }
    run.mutate(here.length > 0);
  }

  function toggle(key: string) {
    setTicked((old) => {
      const next = new Set(old);
      if (next.has(key)) next.delete(key);
      else next.add(key);
      return next;
    });
  }

  if (index.error) {
    return (
      <p role="alert" className="notice error">
        {t("restore.loadFailed", { error: index.error.message })}
      </p>
    );
  }
  if (!index.data) return <p className="placeholder">{t("restore.loading")}</p>;
  if (items.length === 0) return <p className="placeholder">{t("restore.nothing")}</p>;

  return (
    <>
      <div className="restore-scroll">
        <table className="sheet-table restore-items">
          <thead>
            <tr>
              <th scope="col">{t("restore.item")}</th>
              <th scope="col">{t("restore.kind")}</th>
              <th scope="col">{t("restore.backedUp")}</th>
              <th scope="col">{t("restore.size")}</th>
              <th scope="col">{t("restore.where")}</th>
            </tr>
          </thead>
          <tbody>
            {items.map((item) => {
              const key = keyOf(item);
              const id = `restore-${key.replace(/\W/g, "-")}`;
              const bringer = along.get(key);
              return (
                <tr key={key}>
                  <td>
                    <label className="check" htmlFor={id}>
                      <input
                        id={id}
                        type="checkbox"
                        checked={ticked.has(key) || Boolean(bringer)}
                        disabled={Boolean(bringer) || run.isPending}
                        onChange={() => toggle(key)}
                      />
                      {item.title}
                    </label>
                    {bringer && <span className="hint">{t("restore.comesWith", { title: bringer.title })}</span>}
                  </td>
                  <td>{t(`storage.kind.${item.kind}`)}</td>
                  <td>
                    <time dateTime={item.backed_up_at}>{whenText(language, item.backed_up_at)}</time>
                  </td>
                  <td className="num">{sizeText(language, item.size)}</td>
                  <td>
                    {item.exists_here
                      ? t("restore.here")
                      : item.on_install
                        ? t("restore.notHere")
                        : t("restore.gone")}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
      <div className="actions">
        <button type="button" className="primary" disabled={picked.length === 0 || run.isPending} onClick={() => void start()}>
          {run.isPending ? t("restore.restoring") : t("restore.selected")}
        </button>
      </div>
      {failed && (
        <p role="alert" className="notice error">
          {t("restore.failed", { error: failed })}
        </p>
      )}
      {results && (
        <ul className="restore-results" role="status">
          {results.map((result) => {
            const title = titles.get(keyOf(result)) ?? result.item_id;
            const error = result.error === "exists" ? t("restore.exists") : (result.error ?? "");
            return (
              <li key={keyOf(result)} className={result.ok ? undefined : "failed"}>
                {result.ok
                  ? t(result.added ? "restore.restoredAlong" : "restore.restored", { title })
                  : t("restore.notRestored", { title, error })}
                {result.warnings.length > 0 && (
                  <ul>
                    {result.warnings.map((warning) => (
                      <li key={warning}>{warning}</li>
                    ))}
                  </ul>
                )}
              </li>
            );
          })}
        </ul>
      )}
    </>
  );
}
