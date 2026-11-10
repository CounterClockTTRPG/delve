// Preferences' Packs (DEL-366): the rulesets and settings installed on this Delve, each to download as its .delvepack.
// The owner alone installs, updates and removes one, as a pack runs code on the server; Delve uses what changed once
// it restarts, which the owner can ask for here when Delve runs under systemd, after being told what it breaks off.
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useRef, useState } from "react";
import { useConfirm } from "../components/dialogs";
import { useT } from "../i18n";
import { getPacks, packDownloadUrl, packKeys, removePack, restartDelve, uploadPack, type PackRow, type RestartState } from "./packs";

/** How long after asking for a restart the page reads the packs again: Delve is back by then. */
export const RESTART_WAIT_MS = 4000;

export default function Packs() {
  const t = useT();
  const confirm = useConfirm();
  const client = useQueryClient();
  const packs = useQuery({ queryKey: packKeys.all, queryFn: getPacks });
  const file = useRef<HTMLInputElement>(null);
  const [installed, setInstalled] = useState<PackRow | null>(null);
  const [restarting, setRestarting] = useState(false);
  const [restarted, setRestarted] = useState(false);
  const refresh = () => client.invalidateQueries({ queryKey: packKeys.all });

  const upload = useMutation({
    mutationFn: uploadPack,
    onSuccess: ({ pack }) => {
      setInstalled(pack);
      setRestarted(false);
      void refresh();
    },
    onSettled: () => {
      if (file.current) file.current.value = "";
    },
  });
  const remove = useMutation({
    mutationFn: ({ id, force }: { id: string; force: boolean }) => removePack(id, force),
    onSuccess: () => {
      setRestarted(false);
      void refresh();
    },
  });
  const restart = useMutation({
    mutationFn: restartDelve,
    onSuccess: () => {
      setRestarting(true);
      setTimeout(() => {
        setRestarting(false);
        setRestarted(true);
        void refresh();
      }, RESTART_WAIT_MS);
    },
  });

  async function install(chosen: File | undefined) {
    if (!chosen) return;
    const sure = await confirm({
      title: t("packs.installTitle", { name: chosen.name }),
      body: t("packs.installBody"),
      confirm: t("packs.install"),
      danger: true,
    });
    if (sure) upload.mutate(chosen);
    else if (file.current) file.current.value = "";
  }

  async function removeOne(pack: PackRow) {
    const sure = await confirm({
      title: t("packs.removeTitle", { name: pack.title }),
      body:
        pack.campaigns.length > 0
          ? t("packs.removeInUse", { campaigns: pack.campaigns.join(", ") })
          : t("packs.removeBody"),
      confirm: t("packs.remove"),
      danger: true,
    });
    if (sure) remove.mutate({ id: pack.id, force: pack.campaigns.length > 0 });
  }

  async function restartNow(state: RestartState) {
    const busy = [
      ...(state.beats.length > 0 ? [t("packs.restartBeats", { campaigns: state.beats.join(", ") })] : []),
      ...(state.conversion ? [t("packs.restartConversion", { title: state.conversion })] : []),
    ];
    const sure = await confirm({
      title: t("packs.restartTitle"),
      body: [t("packs.restartBody"), ...busy].join(" "),
      confirm: t("packs.restart"),
      danger: busy.length > 0,
    });
    if (sure) restart.mutate();
  }

  const view = packs.data;
  const error = upload.error ?? remove.error ?? restart.error;
  return (
    <section className="packs" aria-labelledby="packs-title" data-testid="packs">
      <h2 id="packs-title">{t("packs.title")}</h2>
      <p className="lede">{t("packs.intro")}</p>

      {packs.error && (
        <p role="alert" className="notice error">
          {t("packs.loadFailed", { error: packs.error.message })}
        </p>
      )}

      {view && (view.restart.needed || restarting) && (
        <div className="notice packs-restart" role="status" data-testid="packs-restart">
          {restarting ? (
            <p>{t("packs.restarting")}</p>
          ) : (
            <>
              <p>{t("packs.restartNeeded")}</p>
              {view.can_install && view.restart.possible && (
                <button type="button" className="primary" disabled={restart.isPending} onClick={() => void restartNow(view.restart)}>
                  {t("packs.restart")}
                </button>
              )}
              {view.can_install && !view.restart.possible && <p className="hint">{t("packs.restartByHand")}</p>}
            </>
          )}
        </div>
      )}
      {restarted && view && !view.restart.needed && (
        <p className="notice" role="status" data-testid="packs-restarted">
          {t("packs.restarted")}
        </p>
      )}
      {installed && (
        <p className="notice" role="status">
          {t("packs.installed", { title: installed.title, version: installed.version })}
        </p>
      )}

      {view && (
        <table className="packs-table">
          <thead>
            <tr>
              <th scope="col">{t("packs.pack")}</th>
              <th scope="col">{t("packs.kind")}</th>
              <th scope="col">{t("packs.version")}</th>
              <th scope="col">{t("packs.campaigns")}</th>
              <th scope="col">
                <span className="visually-hidden">{t("packs.actions")}</span>
              </th>
            </tr>
          </thead>
          <tbody>
            {view.packs.map((pack) => (
              <tr key={pack.id} data-testid={`pack-${pack.id}`}>
                <td>
                  <strong>{pack.title}</strong> <code>{pack.id}</code>
                  {!pack.active && <span className="tag">{t("packs.waits")}</span>}
                </td>
                <td>{t(pack.kind === "ruleset" ? "packs.ruleset" : "packs.setting")}</td>
                <td>{pack.version}</td>
                <td>{pack.campaigns.length}</td>
                <td className="packs-actions">
                  <a href={packDownloadUrl(pack.id)} download>
                    {t("packs.download")}
                  </a>
                  {view.can_install && (
                    <button type="button" className="link-button danger" disabled={remove.isPending} onClick={() => void removeOne(pack)}>
                      {t("packs.remove")}
                    </button>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      {view && view.packs.length === 0 && <p className="placeholder">{t("packs.none")}</p>}
      {view && view.removed.length > 0 && (
        <p className="hint">{t("packs.removedStill", { ids: view.removed.join(", ") })}</p>
      )}

      {view?.can_install && (
        <div className="packs-upload">
          <label htmlFor="pack-file">{t("packs.upload")}</label>
          <input
            id="pack-file"
            ref={file}
            type="file"
            accept=".delvepack,application/zip"
            data-testid="pack-file"
            disabled={upload.isPending}
            onChange={(e) => void install(e.target.files?.[0])}
          />
          <p className="hint">{upload.isPending ? t("packs.installing") : t("packs.uploadHint")}</p>
        </div>
      )}

      {error && (
        <p role="alert" className="notice error">
          {error.message}
        </p>
      )}
    </section>
  );
}
