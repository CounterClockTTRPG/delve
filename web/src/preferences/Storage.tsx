// Preferences' Storage (cloud storage plan Task 11): the backup store and the library's store, the backup time, Back up
// now and Restore, the install's owner's alone. A seat, an organiser seat too, is answered 403 and sees nothing of it.
// A stored SAS or secret key is never shown: its field is empty, says it is set, and an empty field keeps it. Back up
// now and Restore show only once a backup store is set, so neither is a button that can only fail.
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { AlertTriangle, XCircle } from "lucide-react";
import { useEffect, useState, type ChangeEvent } from "react";
import { ApiError, NeedsToken } from "../api";
import {
  backupNow,
  backupsKey,
  dayText,
  expiryTone,
  getStorage,
  putSchedule,
  putStore,
  r2Account,
  r2Endpoint,
  removeStore,
  runStatus,
  storageKey,
  testStore,
  whenText,
  type BackupRun,
  type StorageState,
  type StoreCheck,
  type StoreConfig,
  type StoreKind,
  type StoreView,
} from "../cloud/api";
import { useConfirm } from "../components/dialogs";
import { useLanguage, useT } from "../i18n";
import Restore from "./Restore";
import UnusedFiles from "./UnusedFiles";

/** The providers the select offers: R2 is the S3 provider with its endpoint made from an account id. A folder on this
 * machine is offered only when it is the one stored (the server takes it; the owner sets it up by hand). */
type Choice = "azure" | "r2" | "s3" | "local";

type Draft = {
  provider: Choice;
  sasUrl: string;
  account: string;
  endpoint: string;
  bucket: string;
  accessKeyId: string;
  secret: string;
  root: string;
  right: "publish" | "manage";
};

type Outcome =
  | { kind: "idle" }
  | { kind: "saved" }
  | { kind: "removed" }
  | { kind: "failed"; key: "storage.saveFailed" | "storage.removeFailed" | "storage.testFailed"; error: string }
  | { kind: "checked"; check: StoreCheck };

const POLL_MS = 2000;

export default function Storage() {
  const t = useT();
  const storage = useQuery({ queryKey: storageKey, queryFn: getStorage, retry: false });

  // Not the owner (a seat, an organiser seat too): there is nothing to show.
  const error = storage.error;
  if (error instanceof NeedsToken || (error instanceof ApiError && error.status === 403)) return null;
  if (error) {
    return (
      <section className="storage" aria-labelledby="storage-title">
        <h2 id="storage-title">{t("storage.title")}</h2>
        <p role="alert" className="notice error">
          {t("storage.loadFailed", { error: error.message })}
        </p>
      </section>
    );
  }
  if (!storage.data) return null;

  return (
    <section className="storage" aria-labelledby="storage-title">
      <h2 id="storage-title">{t("storage.title")}</h2>
      <p className="lede">{t("storage.intro")}</p>
      <div className="jobs">
        <StoreCard kind="backup" stored={storage.data.backup} />
        <StoreCard kind="library" stored={storage.data.library} />
      </div>
      {storage.data.backup && <Backups state={storage.data} />}
      {storage.data.backup && <Restore installId={storage.data.install_id} />}
      <UnusedFiles />
    </section>
  );
}

function choiceOf(stored: StoreView | null): Choice {
  if (!stored) return "azure";
  if (stored.provider === "s3") return r2Account(endpointOf(stored.label)) ? "r2" : "s3";
  return stored.provider;
}

/** An S3 store's label is `{endpoint}/{bucket}`, the endpoint an address with no path. */
function endpointOf(label: string): string {
  const slash = label.lastIndexOf("/");
  return slash > "https://".length ? label.slice(0, slash) : label;
}

function bucketOf(label: string): string {
  const slash = label.lastIndexOf("/");
  return slash > "https://".length ? label.slice(slash + 1) : "";
}

function draftOf(stored: StoreView | null): Draft {
  const s3 = stored?.provider === "s3";
  const endpoint = s3 ? endpointOf(stored.label) : "";
  return {
    provider: choiceOf(stored),
    sasUrl: "",
    account: (s3 && r2Account(endpoint)) || "",
    endpoint,
    bucket: s3 ? bucketOf(stored.label) : "",
    accessKeyId: "",
    secret: "",
    root: stored?.provider === "local" ? stored.label : "",
    right: stored?.choice ?? "publish",
  };
}

/** The body to save: a secret only when one is typed, so an empty field keeps the stored one. */
function configOf(kind: StoreKind, draft: Draft): StoreConfig {
  if (draft.provider === "azure") return draft.sasUrl.trim() ? { provider: "azure", sas_url: draft.sasUrl.trim() } : { provider: "azure" };
  if (draft.provider === "local") return { provider: "local", root: draft.root.trim() };
  const config: StoreConfig = {
    provider: "s3",
    endpoint: draft.provider === "r2" ? r2Endpoint(draft.account) : draft.endpoint.trim(),
    bucket: draft.bucket.trim(),
    access_key_id: draft.accessKeyId.trim(),
  };
  if (draft.secret.trim()) config.secret_access_key = draft.secret.trim();
  if (kind === "library") config.right = draft.right;
  return config;
}

/** Whether the draft can be saved: every field filled, and a secret typed unless one of this provider is stored. */
function complete(draft: Draft, stored: StoreView | null): boolean {
  const kept = stored !== null && stored.secret === "set" && choiceOf(stored) === draft.provider;
  if (draft.provider === "azure") return kept || draft.sasUrl.trim() !== "";
  if (draft.provider === "local") return draft.root.trim() !== "";
  const where = draft.provider === "r2" ? draft.account.trim() : draft.endpoint.trim();
  return where !== "" && draft.bucket.trim() !== "" && draft.accessKeyId.trim() !== "" && (kept || draft.secret.trim() !== "");
}

function StoreCard({ kind, stored }: { kind: StoreKind; stored: StoreView | null }) {
  const t = useT();
  const confirm = useConfirm();
  const client = useQueryClient();
  const [draft, setDraft] = useState<Draft>(() => draftOf(stored));
  const [outcome, setOutcome] = useState<Outcome>({ kind: "idle" });
  const id = `store-${kind}`;

  const changed = (view: StoreView | null) =>
    client.setQueryData<StorageState>(storageKey, (old) => (old ? { ...old, [kind]: view } : old));

  const save = useMutation({
    mutationFn: () => putStore(kind, configOf(kind, draft)),
    onSuccess: (view) => {
      changed(view);
      setDraft(draftOf(view));
      setOutcome({ kind: "saved" });
    },
    onError: (error) => setOutcome({ kind: "failed", key: "storage.saveFailed", error: error.message }),
    // A typed secret goes once, whatever the answer: it isn't kept on the page.
    onSettled: () => setDraft((old) => ({ ...old, sasUrl: "", secret: "" })),
  });
  const remove = useMutation({
    mutationFn: () => removeStore(kind),
    onSuccess: () => {
      changed(null);
      setDraft(draftOf(null));
      setOutcome({ kind: "removed" });
    },
    onError: (error) => setOutcome({ kind: "failed", key: "storage.removeFailed", error: error.message }),
  });
  const check = useMutation({
    mutationFn: () => testStore(kind),
    onSuccess: (answer) => {
      setOutcome({ kind: "checked", check: answer });
      // A library's right found by the test becomes its right.
      if (kind === "library") client.setQueryData<StorageState>(storageKey, (old) =>
        old?.library ? { ...old, library: { ...old.library, right: answer.right } } : old);
    },
    onError: (error) => setOutcome({ kind: "failed", key: "storage.testFailed", error: error.message }),
  });

  const edit = (field: keyof Draft) => (e: ChangeEvent<HTMLInputElement | HTMLSelectElement>) => {
    setDraft((old) => ({ ...old, [field]: e.target.value }));
    setOutcome({ kind: "idle" });
  };
  const keeps = stored !== null && stored.secret === "set" && choiceOf(stored) === draft.provider;
  const secretPlaceholder = keeps ? t("storage.secretSet") : undefined;
  const failed = outcome.kind === "failed" || (outcome.kind === "checked" && !outcome.check.ok);
  const choices: Choice[] = stored?.provider === "local" ? ["azure", "r2", "s3", "local"] : ["azure", "r2", "s3"];

  return (
    <form
      className="job connection store"
      role="group"
      aria-labelledby={`${id}-title`}
      onSubmit={(e) => {
        e.preventDefault();
        if (complete(draft, stored)) save.mutate();
      }}
    >
      <div className="job-name">
        <span id={`${id}-title`} className="job-title">
          {t(`storage.${kind}`)}
        </span>
        <span className="job-hint">{t(`storage.${kind}.hint`)}</span>
      </div>
      <div className="connection-body">
        {stored && (
          <div className="store-state">
            <p className="store-label">{stored.label}</p>
            <p>{t("storage.right", { right: t(`storage.right.${stored.right ?? "unknown"}`) })}</p>
            {stored.expires && <Expiry expires={stored.expires} />}
          </div>
        )}

        <div className="field">
          <label htmlFor={`${id}-provider`}>{t("storage.provider")}</label>
          <select id={`${id}-provider`} value={draft.provider} onChange={edit("provider")}>
            {choices.map((choice) => (
              <option key={choice} value={choice}>
                {t(`storage.provider.${choice}`)}
              </option>
            ))}
          </select>
        </div>

        {draft.provider === "azure" && (
          <Field id={`${id}-sas`} label={t("storage.sasUrl")} hint={t("storage.sasUrl.hint")} secret placeholder={secretPlaceholder}
            value={draft.sasUrl} onChange={edit("sasUrl")} />
        )}

        {draft.provider === "local" && <Field id={`${id}-root`} label={t("storage.root")} value={draft.root} onChange={edit("root")} />}

        {(draft.provider === "r2" || draft.provider === "s3") && (
          <>
            {draft.provider === "r2" ? (
              <Field id={`${id}-account`} label={t("storage.account")} hint={t("storage.account.hint")} value={draft.account}
                onChange={edit("account")} />
            ) : (
              <Field id={`${id}-endpoint`} label={t("storage.endpoint")} hint={t("storage.endpoint.hint")} value={draft.endpoint}
                onChange={edit("endpoint")} />
            )}
            <Field id={`${id}-bucket`} label={t("storage.bucket")} value={draft.bucket} onChange={edit("bucket")} />
            <Field id={`${id}-key`} label={t("storage.accessKeyId")} value={draft.accessKeyId} onChange={edit("accessKeyId")}
              hint={keeps ? t("storage.accessKeyId.hint") : undefined} />
            <Field id={`${id}-secret`} label={t("storage.secretAccessKey")} secret placeholder={secretPlaceholder}
              value={draft.secret} onChange={edit("secret")} />
            {kind === "library" && (
              <div className="field">
                <label htmlFor={`${id}-right`}>{t("storage.writeRight")}</label>
                <select id={`${id}-right`} value={draft.right} onChange={edit("right")}>
                  <option value="publish">{t("storage.right.publish")}</option>
                  <option value="manage">{t("storage.right.manage")}</option>
                </select>
                <span className="hint">{t("storage.writeRight.hint")}</span>
              </div>
            )}
          </>
        )}

        <div className="actions">
          <button type="submit" className="primary" disabled={save.isPending || !complete(draft, stored)}>
            {save.isPending ? t("storage.saving") : t("storage.save")}
          </button>
          {stored && (
            <button
              type="button"
              onClick={async () => {
                const sure = await confirm({
                  title: t(`storage.removeConfirm.${kind}`),
                  body: t(`storage.removeConfirm.${kind}.body`),
                  confirm: t("dialog.remove"),
                  danger: true,
                });
                if (sure) remove.mutate();
              }}
            >
              {t("storage.remove")}
            </button>
          )}
          {stored && (
            <button type="button" onClick={() => check.mutate()} disabled={check.isPending}>
              {check.isPending ? t("storage.testing") : t("storage.test")}
            </button>
          )}
        </div>
        <p role="status" className={`connection-outcome${failed ? " failed" : ""}`}>
          {outcome.kind === "saved" && t("storage.saved")}
          {outcome.kind === "removed" && t("storage.removed")}
          {outcome.kind === "failed" && t(outcome.key, { error: outcome.error })}
          {outcome.kind === "checked" && outcome.check.message}
        </p>
      </div>
    </form>
  );
}

function Field({
  id,
  label,
  value,
  onChange,
  hint,
  secret = false,
  placeholder,
}: {
  id: string;
  label: string;
  value: string;
  onChange: (e: ChangeEvent<HTMLInputElement>) => void;
  hint?: string;
  secret?: boolean;
  placeholder?: string;
}) {
  return (
    <div className="field">
      <label htmlFor={id}>{label}</label>
      <input
        id={id}
        type={secret ? "password" : "text"}
        autoComplete="off"
        spellCheck={false}
        value={value}
        placeholder={placeholder}
        aria-describedby={hint ? `${id}-hint` : undefined}
        onChange={onChange}
      />
      {hint && (
        <span id={`${id}-hint`} className="hint">
          {hint}
        </span>
      )}
    </div>
  );
}

/** An Azure SAS's expiry: amber within 14 days, red once past, and the words say it too. */
function Expiry({ expires }: { expires: string }) {
  const t = useT();
  const language = useLanguage();
  const tone = expiryTone(expires);
  const date = dayText(language, expires);
  const days = Math.floor((new Date(expires).getTime() - Date.now()) / (24 * 60 * 60 * 1000));
  return (
    <p className={`store-expiry expiry-${tone}`}>
      {tone === "soon" && <AlertTriangle aria-hidden="true" size={16} />}
      {tone === "past" && <XCircle aria-hidden="true" size={16} />}
      <span>
        {tone === "ok" && t("storage.expires", { date })}
        {tone === "soon" && (days >= 2 ? t("storage.expiresSoon", { date, days: String(days) }) : t("storage.expiresDay", { date }))}
        {tone === "past" && t("storage.expired", { date })}
      </span>
    </p>
  );
}

/** The backup time, Back up now, and what the last run did. */
function Backups({ state }: { state: StorageState }) {
  const t = useT();
  const client = useQueryClient();
  const [time, setTime] = useState(state.schedule.time);
  const [timeOutcome, setTimeOutcome] = useState<"idle" | "saved" | { error: string }>("idle");
  // After Back up now, the run's start before it and when the storage was last fetched: the storage is fetched again
  // until a newer answer says no run is going, or a newer run shows.
  const [waitingAfter, setWaitingAfter] = useState<{ started_at: string | null; fetched: number } | undefined>(undefined);
  const [nowError, setNowError] = useState<string | null>(null);
  const waiting = waitingAfter !== undefined;
  const run = state.schedule.last_run;

  const { dataUpdatedAt } = useQuery({
    queryKey: storageKey,
    queryFn: getStorage,
    retry: false,
    refetchInterval: waiting ? POLL_MS : false,
  });
  useEffect(() => {
    if (!waitingAfter) return;
    const newerRun = run && run.started_at !== waitingAfter.started_at;
    const stopped = dataUpdatedAt > waitingAfter.fetched && state.schedule.running === false;
    if (!newerRun && !stopped) return;
    setWaitingAfter(undefined);
    // The run wrote the backups' list: the Restore list reads it again.
    void client.invalidateQueries({ queryKey: backupsKey });
  }, [waitingAfter, run, dataUpdatedAt, state.schedule.running, client]);
  const waitForRun = () => setWaitingAfter({ started_at: run?.started_at ?? null, fetched: dataUpdatedAt });
  useEffect(() => setTime(state.schedule.time), [state.schedule.time]);

  const saveTime = useMutation({
    mutationFn: () => putSchedule(time),
    onSuccess: (schedule) => {
      client.setQueryData<StorageState>(storageKey, (old) => (old ? { ...old, schedule } : old));
      setTimeOutcome("saved");
    },
    onError: (error) => setTimeOutcome({ error: error.message }),
  });
  const now = useMutation({
    mutationFn: backupNow,
    onMutate: () => setNowError(null),
    onSuccess: () => {
      waitForRun();
      void client.invalidateQueries({ queryKey: storageKey });
    },
    onError: (error) => {
      if (error instanceof ApiError && error.status === 409) {
        setNowError(t("storage.alreadyRunning"));
        waitForRun();
      } else {
        setNowError(t("storage.backupNowFailed", { error: error.message }));
      }
    },
  });

  return (
    <div className="storage-backups">
      <form
        className="storage-schedule"
        onSubmit={(e) => {
          e.preventDefault();
          saveTime.mutate();
        }}
      >
        <div className="field">
          <label htmlFor="backup-time">{t("storage.time")}</label>
          <input
            id="backup-time"
            type="time"
            required
            value={time}
            aria-describedby="backup-time-hint"
            onChange={(e) => {
              setTime(e.target.value);
              setTimeOutcome("idle");
            }}
          />
          <span id="backup-time-hint" className="hint">
            {t("storage.time.hint")}
          </span>
        </div>
        <div className="actions">
          <button type="submit" disabled={saveTime.isPending || time === state.schedule.time}>
            {t("storage.saveTime")}
          </button>
          <button type="button" className="primary" disabled={now.isPending || waiting} onClick={() => now.mutate()}>
            {waiting ? t("storage.backingUp") : t("storage.backupNow")}
          </button>
        </div>
        <p role="status" className={`connection-outcome${nowError || typeof timeOutcome === "object" ? " failed" : ""}`}>
          {timeOutcome === "saved" && t("storage.timeSaved")}
          {typeof timeOutcome === "object" && t("storage.saveFailed", { error: timeOutcome.error })}
          {nowError}
        </p>
      </form>
      <LastRun run={run} />
    </div>
  );
}

function LastRun({ run }: { run: BackupRun | null }) {
  const t = useT();
  const language = useLanguage();
  if (!run) {
    return (
      <section className="last-run" aria-labelledby="last-run-title">
        <h3 id="last-run-title">{t("storage.lastRun")}</h3>
        <p className="placeholder">{t("storage.noRunYet")}</p>
      </section>
    );
  }
  const status = runStatus(run);
  const when = whenText(language, run.started_at);
  return (
    <section className={`last-run run-${status}`} aria-labelledby="last-run-title">
      <h3 id="last-run-title">{t("storage.lastRun")}</h3>
      <p className="run-status">
        {status === "partial" && <AlertTriangle aria-hidden="true" size={16} />}
        {status === "failed" && <XCircle aria-hidden="true" size={16} />}
        <span>{t(`storage.run.${status}`, { when })}</span>
      </p>
      <p>
        {t("storage.runCounts", {
          uploaded: String(run.uploaded.length),
          unchanged: String(run.unchanged),
          failed: String(run.failed.length),
        })}
      </p>
      {run.failed.length > 0 && (
        <ul className="run-failures">
          {run.failed.map((failure) => (
            <li key={`${failure.kind}/${failure.item_id}`}>
              {failure.kind === "index" || !failure.title
                ? t("storage.runFailure.untitled", { kind: t(`storage.kind.${failure.kind}`), error: failure.error })
                : t("storage.runFailure", { title: failure.title, kind: t(`storage.kind.${failure.kind}`), error: failure.error })}
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
