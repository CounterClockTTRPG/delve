// The module library (cloud storage plan Task 12): the Modules page's Library tab, the first publish's dialog, and the
// module page's library bar (Publish to library or New version, Update, Delete from library). Each right shows only
// its own buttons: Publish and New version from publish up, Delete for manage, none for read.
import * as Dialog from "@radix-ui/react-dialog";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { Link } from "react-router-dom";
import { useMe } from "../account/useMe";
import { ApiError, NeedsToken, listModules, queryKeys, type ModuleDetail, type ModuleSummary } from "../api";
import {
  dayText,
  deleteEntry,
  downloadEntry,
  getLibrary,
  libraryKey,
  mayAddVersion,
  publishModule,
  sizeText,
  updateModule,
  type LibraryEntry,
} from "../cloud/api";
import { useConfirm } from "../components/dialogs";
import { useLanguage, useT } from "../i18n";

/** The library, read when a page that needs it opens and on Refresh, not polled. */
export function useLibrary() {
  return useQuery({ queryKey: libraryKey, queryFn: getLibrary, staleTime: 5 * 60 * 1000, retry: false });
}

/** Whether the install has a library store: it answered, or it is set but failed (a 502 shows its error). No library
 * (409), a seat that isn't an organiser (403) or nobody logged in hide it. */
export function hasLibrary(library: ReturnType<typeof useLibrary>): boolean {
  if (library.data) return true;
  return library.error instanceof ApiError && library.error.status >= 500;
}

/** A refusal's message, for the line under the buttons. */
const failureOf = (error: unknown) => (error instanceof Error && !(error instanceof NeedsToken) ? error.message : null);

/** The Library tab: the entries, newest updated first, with what this install has of each and the right's buttons. */
export default function Library() {
  const t = useT();
  const language = useLanguage();
  const client = useQueryClient();
  const confirm = useConfirm();
  const library = useLibrary();
  const [publishing, setPublishing] = useState(false);
  const changed = () => {
    client.invalidateQueries({ queryKey: libraryKey });
    client.invalidateQueries({ queryKey: queryKeys.modules });
  };
  const download = useMutation({ mutationFn: downloadEntry, onSuccess: changed });
  const addVersion = useMutation({ mutationFn: (moduleId: string) => publishModule(moduleId), onSuccess: changed });
  const remove = useMutation({
    mutationFn: ({ key, version }: { key: string; version?: number }) => deleteEntry(key, version),
    onSuccess: changed,
  });
  const failed = failureOf(download.error ?? addVersion.error ?? remove.error);
  const right = library.data?.right ?? null;
  const writes = right === "publish" || right === "manage";

  async function removeEntry(entry: LibraryEntry, version?: number) {
    const ok = await confirm({
      title:
        version === undefined
          ? t("library.deleteConfirm", { title: entry.title })
          : t("library.deleteVersionConfirm", { title: entry.title, version: String(version) }),
      body: t("library.deleteConfirm.body"),
      confirm: t("dialog.delete"),
      danger: true,
    });
    if (ok) remove.mutate({ key: entry.key, version });
  }

  return (
    <div className="library">
      <div className="toolbar">
        <button type="button" disabled={library.isFetching} onClick={() => library.refetch()}>
          {library.isFetching ? t("library.loading") : t("library.refresh")}
        </button>
        {writes && (
          <button type="button" className="primary" onClick={() => setPublishing(true)}>
            {t("library.publishModule")}
          </button>
        )}
      </div>

      {library.error && !(library.error instanceof NeedsToken) && (
        <p role="alert" className="notice error">
          {t("library.loadFailed", { error: library.error.message })}
        </p>
      )}
      {library.data && library.data.warnings.length > 0 && (
        <div className="notice" role="note">
          <p>{t("library.warnings")}</p>
          <ul>
            {library.data.warnings.map((w) => (
              <li key={w}>{w}</li>
            ))}
          </ul>
        </div>
      )}
      {right === "read" && <p className="row-meta">{t("library.readOnly")}</p>}
      {failed && (
        <p role="alert" className="notice error">
          {t("library.failed", { error: failed })}
        </p>
      )}

      {library.data ? (
        library.data.entries.length === 0 ? (
          <p className="placeholder">{t("library.empty")}</p>
        ) : (
          <table className="sheet-table library-entries">
            <thead>
              <tr>
                <th scope="col">{t("library.col.title")}</th>
                <th scope="col">{t("library.col.author")}</th>
                <th scope="col">{t("library.col.created")}</th>
                <th scope="col">{t("library.col.updated")}</th>
                <th scope="col">{t("library.col.version")}</th>
                <th scope="col">{t("library.col.size")}</th>
                <th scope="col">{t("library.col.here")}</th>
              </tr>
            </thead>
            <tbody>
              {library.data.entries.map((entry) => (
                <tr key={entry.key}>
                  <td>
                    <span className="row-title">{entry.title}</span>
                    {entry.summary && <p className="row-meta">{entry.summary}</p>}
                  </td>
                  <td>{entry.author}</td>
                  <td>{dayText(language, entry.created_at)}</td>
                  <td>{dayText(language, entry.updated_at)}</td>
                  <td>{entry.version}</td>
                  <td>{sizeText(language, entry.size)}</td>
                  <td>
                    <div className="actions">
                      {entry.local ? (
                        <Link to={`/modules/${encodeURIComponent(entry.local.module_id)}`}>
                          {t(entry.local.origin === "published" ? "library.publishedHere" : "library.downloaded")}
                        </Link>
                      ) : (
                        <button
                          type="button"
                          disabled={download.isPending}
                          aria-label={t("library.downloadOf", { title: entry.title })}
                          onClick={() => download.mutate(entry.key)}
                        >
                          {download.isPending && download.variables === entry.key ? t("library.downloading") : t("library.download")}
                        </button>
                      )}
                      {mayAddVersion(right, entry) && (
                        <button
                          type="button"
                          disabled={addVersion.isPending}
                          aria-label={t("library.newVersionOf", { title: entry.title })}
                          onClick={() => addVersion.mutate(entry.local!.module_id)}
                        >
                          {t("library.newVersion")}
                        </button>
                      )}
                      {right === "manage" && (
                        <>
                          {entry.version > 1 && (
                            <button
                              type="button"
                              className="danger"
                              disabled={remove.isPending}
                              onClick={() => removeEntry(entry, entry.version)}
                            >
                              {t("library.deleteVersion", { version: String(entry.version) })}
                            </button>
                          )}
                          <button
                            type="button"
                            className="danger"
                            disabled={remove.isPending}
                            aria-label={t("library.deleteOf", { title: entry.title })}
                            onClick={() => removeEntry(entry)}
                          >
                            {t("library.delete")}
                          </button>
                        </>
                      )}
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )
      ) : library.isPending ? (
        <p className="placeholder">{t("library.loading")}</p>
      ) : null}

      {publishing && <PublishDialog onClose={() => setPublishing(false)} />}
    </div>
  );
}

/**
 * The first publish: the entry it will make (title, summary, author, created today, version 1) before it is made,
 * the author editable. Without a `module`, it first asks which of this install's modules to publish.
 */
export function PublishDialog({ module, onClose }: { module?: ModuleDetail; onClose: () => void }) {
  const t = useT();
  const language = useLanguage();
  const client = useQueryClient();
  const me = useMe();
  const modules = useQuery({ queryKey: queryKeys.modules, queryFn: listModules, enabled: !module });
  const [picked, setPicked] = useState("");
  const [author, setAuthor] = useState<string | null>(null);
  const known = me.data?.account?.display_name ?? me.data?.seat?.name ?? "";
  const chosen: ModuleSummary | ModuleDetail | undefined = module ?? modules.data?.find((m) => m.id === picked);
  const summary = module && typeof module.metadata.summary === "string" ? module.metadata.summary.trim() : "";
  const publish = useMutation({
    mutationFn: () => publishModule(chosen!.id, (author ?? known).trim() || undefined),
    onSuccess: () => {
      client.invalidateQueries({ queryKey: libraryKey });
      client.invalidateQueries({ queryKey: queryKeys.modules });
      if (chosen) client.invalidateQueries({ queryKey: queryKeys.module(chosen.id) });
      onClose();
    },
  });
  const failed = failureOf(publish.error);

  return (
    <Dialog.Root open onOpenChange={(isOpen) => isOpen || onClose()}>
      <Dialog.Portal>
        <Dialog.Overlay className="dialog-overlay" />
        <Dialog.Content className="dialog" aria-describedby={undefined}>
          <Dialog.Title className="dialog-title">{t("library.publish.title")}</Dialog.Title>
          <form
            onSubmit={(e) => {
              e.preventDefault();
              if (chosen) publish.mutate();
            }}
          >
            {!module && (
              <div className="field">
                <label htmlFor="publish-module">{t("library.publish.module")}</label>
                <select id="publish-module" value={picked} onChange={(e) => setPicked(e.target.value)}>
                  <option value="">{t("library.publish.pick")}</option>
                  {(modules.data ?? []).map((m) => (
                    <option key={m.id} value={m.id}>
                      {m.title}
                    </option>
                  ))}
                </select>
              </div>
            )}
            <p className="dialog-body">{t("library.publish.hint")}</p>
            <dl className="library-entry">
              <dt>{t("library.col.title")}</dt>
              <dd>{chosen?.title ?? "—"}</dd>
              {module && (
                <>
                  <dt>{t("library.publish.summary")}</dt>
                  <dd>{summary || t("library.publish.noSummary")}</dd>
                </>
              )}
              <dt>{t("library.col.created")}</dt>
              <dd>{dayText(language, new Date().toISOString())}</dd>
              <dt>{t("library.col.version")}</dt>
              <dd>1</dd>
            </dl>
            <div className="field">
              <label htmlFor="publish-author">{t("library.col.author")}</label>
              <input
                id="publish-author"
                value={author ?? known}
                maxLength={100}
                placeholder={t("library.publish.authorHint")}
                onChange={(e) => setAuthor(e.target.value)}
              />
            </div>
            {failed && (
              <p role="alert" className="notice error">
                {t("library.failed", { error: failed })}
              </p>
            )}
            <div className="dialog-actions">
              <button type="button" onClick={onClose}>
                {t("dialog.cancel")}
              </button>
              <button type="submit" className="primary" disabled={!chosen || publish.isPending}>
                {publish.isPending ? t("library.publishing") : t("library.publish.confirm")}
              </button>
            </div>
          </form>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}

/** Update on a module edited here: its edits will be replaced, and keeping them as a module of its own is offered,
 * checked. */
function UpdateDialog({
  module,
  busy,
  onUpdate,
  onClose,
}: {
  module: ModuleDetail;
  busy: boolean;
  onUpdate: (keepCopy: boolean) => void;
  onClose: () => void;
}) {
  const t = useT();
  const [keep, setKeep] = useState(true);
  return (
    <Dialog.Root open onOpenChange={(isOpen) => isOpen || onClose()}>
      <Dialog.Portal>
        <Dialog.Overlay className="dialog-overlay" />
        <Dialog.Content className="dialog">
          <Dialog.Title className="dialog-title">
            {t("library.update.title", { title: module.title, version: String(module.library?.newer ?? "") })}
          </Dialog.Title>
          <Dialog.Description className="dialog-body">{t("library.update.edited")}</Dialog.Description>
          <label className="check">
            <input type="checkbox" checked={keep} onChange={(e) => setKeep(e.target.checked)} />{" "}
            {t("library.update.keep")}
          </label>
          <div className="dialog-actions">
            <button type="button" onClick={onClose}>
              {t("dialog.cancel")}
            </button>
            <button type="button" className="primary" disabled={busy} onClick={() => onUpdate(keep)}>
              {busy ? t("library.updating") : t("library.update")}
            </button>
          </div>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}

/**
 * A module's place in the library, on its page, when the install has a library: Update available (with Update), the
 * version it is at, Publish to library or New version (publish and up), and Delete from library (manage).
 */
export function ModuleLibraryBar({ module }: { module: ModuleDetail }) {
  const t = useT();
  const client = useQueryClient();
  const confirm = useConfirm();
  const library = useLibrary();
  const [dialog, setDialog] = useState<"publish" | "update" | null>(null);
  const [done, setDone] = useState<string | null>(null);
  const changed = () => {
    client.invalidateQueries({ queryKey: libraryKey });
    client.invalidateQueries({ queryKey: queryKeys.modules });
    client.invalidateQueries({ queryKey: queryKeys.module(module.id) });
  };
  const update = useMutation({
    mutationFn: (keepCopy: boolean) => updateModule(module.id, keepCopy),
    onSuccess: (saved) => {
      client.setQueryData(queryKeys.module(module.id), saved);
      changed();
      setDialog(null);
      setDone(t("library.updated", { version: String(saved.library?.version ?? "") }));
    },
    onError: () => setDialog(null),
  });
  const addVersion = useMutation({
    mutationFn: () => publishModule(module.id),
    onSuccess: (entry) => {
      changed();
      setDone(t("library.publishedAs", { version: String(entry.version) }));
    },
  });
  const remove = useMutation({ mutationFn: () => deleteEntry(module.library!.key), onSuccess: changed });
  if (!library.data) return null;

  const right = library.data.right;
  const own = module.library;
  const entry = own ? library.data.entries.find((e) => e.key === own.key) : undefined;
  const writes = right === "publish" || right === "manage";
  // A downloaded module published again becomes an entry of this install's own (the server's rule); a version on top
  // of another install's newer one needs manage (`mayAddVersion`).
  const firstPublish = !own || own.origin === "downloaded";
  const failed = failureOf(update.error ?? addVersion.error ?? remove.error);
  if (!own && !writes) return null;

  return (
    <div className="notice library-bar" role="note">
      <p>
        {own && <span className="row-meta">{t("library.at", { version: String(own.version) })}</span>}{" "}
        {own?.newer != null && (
          <>
            <span className="tag">{t("library.updateAvailable")}</span>{" "}
            <span className="row-meta">{t("library.newer", { version: String(own.newer) })}</span>
          </>
        )}
      </p>
      <div className="actions">
        {own?.newer != null && (
          <button
            type="button"
            className="primary"
            disabled={update.isPending}
            onClick={() => (own.edited ? setDialog("update") : update.mutate(false))}
          >
            {update.isPending ? t("library.updating") : t("library.update")}
          </button>
        )}
        {writes && firstPublish && (
          <button type="button" onClick={() => setDialog("publish")}>
            {t("library.publish")}
          </button>
        )}
        {writes && !firstPublish && (right === "manage" || !entry || entry.version === own.version) && (
          <button type="button" disabled={addVersion.isPending || !own.edited} onClick={() => addVersion.mutate()}>
            {own.edited ? t("library.newVersion") : t("library.upToDate")}
          </button>
        )}
        {right === "manage" && own && entry && (
          <button
            type="button"
            className="danger"
            disabled={remove.isPending}
            onClick={async () =>
              (await confirm({
                title: t("library.deleteConfirm", { title: entry.title }),
                body: t("library.deleteConfirm.body"),
                confirm: t("dialog.delete"),
                danger: true,
              })) && remove.mutate()
            }
          >
            {t("library.delete")}
          </button>
        )}
      </div>
      {right === "read" && !own?.newer && <p className="row-meta">{t("library.readOnly")}</p>}
      {done && <p className="row-meta">{done}</p>}
      {failed && (
        <p role="alert" className="notice error">
          {t("library.failed", { error: failed })}
        </p>
      )}
      {dialog === "publish" && <PublishDialog module={module} onClose={() => setDialog(null)} />}
      {dialog === "update" && (
        <UpdateDialog
          module={module}
          busy={update.isPending}
          onUpdate={(keep) => update.mutate(keep)}
          onClose={() => setDialog(null)}
        />
      )}
    </div>
  );
}
