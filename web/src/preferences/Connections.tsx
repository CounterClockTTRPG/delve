// Preferences' Connections (portraits plan Task 6): the Replicate token and assetgen, and Google's login client
// (DEL-206), the install's owner's alone.
// A seat, an organiser seat too, is answered 403 and sees nothing of it. A stored token is never shown: a field
// takes a new one and is emptied once it is sent. A change registers its provider on the server at once, so the
// backends are fetched again and the job choices follow without a restart.
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState, type ChangeEvent, type ReactNode } from "react";
import { ApiError, NeedsToken, queryKeys } from "../api";
import { useConfirm } from "../components/dialogs";
import { getLegal, legalKey } from "../account/Legal";
import { useLanguage, useT } from "../i18n";
import {
  DEFAULT_ASSETGEN_URL,
  checkConnection,
  connectionsKey,
  deleteAssetgen,
  deleteEmail,
  deleteGoogle,
  deleteReplicate,
  getConnections,
  putAssetgen,
  putEmail,
  putGoogle,
  putOperator,
  putReplicate,
  type AssetgenConnection,
  type EmailConnection,
  type MailProviderName,
  type GoogleConnection,
  type ConnectionCheck,
  type ConnectionName,
  type ConnectionsState,
  type ReplicateConnection,
} from "./connections";

type Outcome =
  | { kind: "idle" }
  | { kind: "saved" }
  | { kind: "removed" }
  | { kind: "failed"; key: "connections.saveFailed" | "connections.removeFailed" | "connections.testFailed"; error: string }
  | { kind: "checked"; check: ConnectionCheck };

export default function Connections() {
  const t = useT();
  const connections = useQuery({ queryKey: connectionsKey, queryFn: getConnections, retry: false });

  // Not the owner (a seat, an organiser seat too): there is nothing to show.
  const error = connections.error;
  if (error instanceof NeedsToken || (error instanceof ApiError && error.status === 403)) return null;
  if (error) {
    return (
      <section className="connections" aria-labelledby="connections-title">
        <h2 id="connections-title">{t("connections.title")}</h2>
        <p role="alert" className="notice error">
          {t("connections.loadFailed", { error: error.message })}
        </p>
      </section>
    );
  }
  if (!connections.data) return null;

  return (
    <section className="connections" aria-labelledby="connections-title">
      <h2 id="connections-title">{t("connections.title")}</h2>
      <p className="lede">{t("connections.intro")}</p>
      <div className="jobs">
        <Replicate stored={connections.data.replicate} />
        <Assetgen stored={connections.data.assetgen} />
        {connections.data.google && <Google stored={connections.data.google} />}
        {connections.data.email && <Email stored={connections.data.email} />}
        <Operator />
      </div>
    </section>
  );
}

/** After a change: store the new state, and fetch the backends and preferences again (a provider came or went). */
function useChanged() {
  const client = useQueryClient();
  return <K extends ConnectionName>(name: K, state: ConnectionsState[K]) => {
    client.setQueryData<ConnectionsState>(connectionsKey, (old) => (old ? { ...old, [name]: state } : old));
    client.invalidateQueries({ queryKey: queryKeys.backends });
    client.invalidateQueries({ queryKey: queryKeys.preferences });
  };
}

function useCheck(name: ConnectionName, setOutcome: (outcome: Outcome) => void) {
  return useMutation({
    mutationFn: () => checkConnection(name),
    onSuccess: (check) => setOutcome({ kind: "checked", check }),
    onError: (error) => setOutcome({ kind: "failed", key: "connections.testFailed", error: error.message }),
  });
}

function Replicate({ stored }: { stored: ReplicateConnection }) {
  const t = useT();
  const confirm = useConfirm();
  const changed = useChanged();
  const [token, setToken] = useState("");
  const [outcome, setOutcome] = useState<Outcome>({ kind: "idle" });

  const save = useMutation({
    mutationFn: putReplicate,
    onSuccess: (state) => {
      changed("replicate", state);
      setOutcome({ kind: "saved" });
    },
    onError: (error) => setOutcome({ kind: "failed", key: "connections.saveFailed", error: error.message }),
    // The typed token goes once, whatever the answer: it isn't kept on the page.
    onSettled: () => setToken(""),
  });
  const remove = useMutation({
    mutationFn: deleteReplicate,
    onSuccess: (state) => {
      changed("replicate", state);
      setOutcome({ kind: "removed" });
    },
    onError: (error) => setOutcome({ kind: "failed", key: "connections.removeFailed", error: error.message }),
  });
  const check = useCheck("replicate", setOutcome);

  return (
    <Row
      name="replicate"
      outcome={outcome}
      busy={save.isPending}
      onSubmit={() => token.trim() && save.mutate(token.trim())}
      canSave={token.trim() !== ""}
      onRemove={
        stored.state === "set"
          ? async () => {
              const sure = await confirm({
                title: t("connections.removeConfirm.replicate"),
                body: t("connections.removeConfirm.body"),
                confirm: t("dialog.remove"),
                danger: true,
              });
              if (sure) remove.mutate();
            }
          : null
      }
      onCheck={() => check.mutate()}
      checking={check.isPending}
    >
      <p className="connection-state">{t("connections.tokenState", { state: t(`connections.state.${stored.state}`) })}</p>
      {stored.state === "environment" && <p className="hint">{t("connections.replicate.environment")}</p>}
      <div className="field">
        <label htmlFor="connection-replicate-token">{t("connections.token")}</label>
        <input
          id="connection-replicate-token"
          type="password"
          autoComplete="off"
          spellCheck={false}
          value={token}
          onChange={(e) => {
            setToken(e.target.value);
            setOutcome({ kind: "idle" });
          }}
        />
      </div>
    </Row>
  );
}

function Assetgen({ stored }: { stored: AssetgenConnection }) {
  const t = useT();
  const confirm = useConfirm();
  const changed = useChanged();
  const [url, setUrl] = useState(stored.url ?? DEFAULT_ASSETGEN_URL);
  const [token, setToken] = useState("");
  const [outcome, setOutcome] = useState<Outcome>({ kind: "idle" });

  const save = useMutation({
    // An empty token field keeps the stored token.
    mutationFn: () => putAssetgen(url.trim(), token.trim() || undefined),
    onSuccess: (state) => {
      changed("assetgen", state);
      if (state.url) setUrl(state.url);
      setOutcome({ kind: "saved" });
    },
    onError: (error) => setOutcome({ kind: "failed", key: "connections.saveFailed", error: error.message }),
    onSettled: () => setToken(""),
  });
  const remove = useMutation({
    mutationFn: deleteAssetgen,
    onSuccess: (state) => {
      changed("assetgen", state);
      setUrl(DEFAULT_ASSETGEN_URL);
      setOutcome({ kind: "removed" });
    },
    onError: (error) => setOutcome({ kind: "failed", key: "connections.removeFailed", error: error.message }),
  });
  const check = useCheck("assetgen", setOutcome);
  const edit = (set: (value: string) => void) => (e: ChangeEvent<HTMLInputElement>) => {
    set(e.target.value);
    setOutcome({ kind: "idle" });
  };

  return (
    <Row
      name="assetgen"
      outcome={outcome}
      busy={save.isPending}
      onSubmit={() => url.trim() && save.mutate()}
      canSave={url.trim() !== ""}
      onRemove={
        stored.url
          ? async () => {
              const sure = await confirm({
                title: t("connections.removeConfirm.assetgen"),
                body: t("connections.removeConfirm.body"),
                confirm: t("dialog.remove"),
                danger: true,
              });
              if (sure) remove.mutate();
            }
          : null
      }
      onCheck={() => check.mutate()}
      checking={check.isPending}
    >
      {stored.url && (
        <p className="connection-state">{t("connections.tokenState", { state: t(`connections.state.${stored.token}`) })}</p>
      )}
      <div className="field">
        <label htmlFor="connection-assetgen-url">{t("connections.url")}</label>
        <input
          id="connection-assetgen-url"
          type="url"
          autoComplete="off"
          spellCheck={false}
          value={url}
          onChange={edit(setUrl)}
        />
      </div>
      <div className="field">
        <label htmlFor="connection-assetgen-token">{t("connections.tokenOptional")}</label>
        <input
          id="connection-assetgen-token"
          type="password"
          autoComplete="off"
          spellCheck={false}
          value={token}
          aria-describedby={stored.token === "set" ? "connection-assetgen-token-hint" : undefined}
          onChange={edit(setToken)}
        />
        {stored.token === "set" && (
          <span id="connection-assetgen-token-hint" className="hint">
            {t("connections.tokenKeep")}
          </span>
        )}
      </div>
    </Row>
  );
}

/** Google's login client (DEL-206): its client id and secret from Google Cloud's console, and the redirect URIs to
 * register there. An empty secret field keeps the stored secret. */
function Google({ stored }: { stored: GoogleConnection }) {
  const t = useT();
  const confirm = useConfirm();
  const client = useQueryClient();
  const [clientId, setClientId] = useState(stored.client_id ?? "");
  const [secret, setSecret] = useState("");
  const [outcome, setOutcome] = useState<Outcome>({ kind: "idle" });
  const changed = (state: GoogleConnection) => {
    client.setQueryData<ConnectionsState>(connectionsKey, (old) => (old ? { ...old, google: state } : old));
    client.invalidateQueries({ queryKey: ["auth", "providers"] });
  };
  const save = useMutation({
    mutationFn: () => putGoogle(clientId.trim(), secret.trim() || undefined),
    onSuccess: (state) => {
      changed(state);
      setOutcome({ kind: "saved" });
    },
    onError: (error) => setOutcome({ kind: "failed", key: "connections.saveFailed", error: error.message }),
    onSettled: () => setSecret(""),
  });
  const remove = useMutation({
    mutationFn: deleteGoogle,
    onSuccess: (state) => {
      changed(state);
      setClientId("");
      setOutcome({ kind: "removed" });
    },
    onError: (error) => setOutcome({ kind: "failed", key: "connections.removeFailed", error: error.message }),
  });
  const canSave = clientId.trim() !== "" && (stored.secret === "set" || secret.trim() !== "");
  return (
    <Row
      name="google"
      outcome={outcome}
      busy={save.isPending}
      onSubmit={() => canSave && save.mutate()}
      canSave={canSave}
      onRemove={
        stored.secret === "set"
          ? async () => {
              const sure = await confirm({
                title: t("connections.removeConfirm.google"),
                body: t("connections.removeConfirm.googleBody"),
                confirm: t("dialog.remove"),
                danger: true,
              });
              if (sure) remove.mutate();
            }
          : null
      }
    >
      <div className="field">
        <label htmlFor="connection-google-client-id">{t("connections.google.clientId")}</label>
        <input
          id="connection-google-client-id"
          autoComplete="off"
          spellCheck={false}
          value={clientId}
          onChange={(e) => {
            setClientId(e.target.value);
            setOutcome({ kind: "idle" });
          }}
        />
      </div>
      <div className="field">
        <label htmlFor="connection-google-secret">{t("connections.google.secret")}</label>
        <input
          id="connection-google-secret"
          type="password"
          autoComplete="off"
          spellCheck={false}
          value={secret}
          onChange={(e) => {
            setSecret(e.target.value);
            setOutcome({ kind: "idle" });
          }}
        />
        {stored.secret === "set" && <span className="hint">{t("connections.tokenKeep")}</span>}
      </div>
      <div className="field">
        <span className="label">{t("connections.google.redirects")}</span>
        <ul className="connection-redirects" data-testid="google-redirects">
          {stored.redirect_uris.map((uri) => (
            <li key={uri}>
              <code>{uri}</code>
            </li>
          ))}
        </ul>
        <span className="hint">{t("connections.google.redirectsHint")}</span>
      </div>
    </Row>
  );
}

/** Email (DEL-314): Emailit's key, the sender and the public address links start with, and a test email to the
 * owner's own confirmed address. An empty key field keeps the stored key. */
function Email({ stored }: { stored: EmailConnection }) {
  const t = useT();
  const language = useLanguage();
  const confirm = useConfirm();
  const client = useQueryClient();
  const [provider, setProvider] = useState<MailProviderName>(stored.provider);
  const [sender, setSender] = useState(stored.sender);
  const [publicUrl, setPublicUrl] = useState(stored.public_url);
  const [key, setKey] = useState("");
  const [outcome, setOutcome] = useState<Outcome>({ kind: "idle" });
  const changed = (state: EmailConnection) => {
    client.setQueryData<ConnectionsState>(connectionsKey, (old) => (old ? { ...old, email: state } : old));
    client.invalidateQueries({ queryKey: ["mail", "status"] });
  };
  const save = useMutation({
    mutationFn: () =>
      putEmail({
        provider,
        sender: sender.trim(),
        public_url: publicUrl.trim(),
        ...(key.trim() ? { key: key.trim() } : {}),
      }),
    onSuccess: (state) => {
      changed(state);
      setPublicUrl(state.public_url);
      setOutcome({ kind: "saved" });
    },
    onError: (error) => setOutcome({ kind: "failed", key: "connections.saveFailed", error: error.message }),
    onSettled: () => setKey(""),
  });
  const remove = useMutation({
    mutationFn: deleteEmail,
    onSuccess: (state) => {
      changed(state);
      setProvider(state.provider);
      setOutcome({ kind: "removed" });
    },
    onError: (error) => setOutcome({ kind: "failed", key: "connections.removeFailed", error: error.message }),
  });
  const check = useCheck("email", setOutcome);
  const edit = (set: (value: string) => void) => (e: ChangeEvent<HTMLInputElement>) => {
    set(e.target.value);
    setOutcome({ kind: "idle" });
  };
  return (
    <Row
      name="email"
      outcome={outcome}
      busy={save.isPending}
      onSubmit={() => save.mutate()}
      canSave
      onRemove={
        stored.provider === "emailit" || stored.key === "set"
          ? async () => {
              const sure = await confirm({
                title: t("connections.removeConfirm.email"),
                body: t("connections.removeConfirm.emailBody"),
                confirm: t("dialog.remove"),
                danger: true,
              });
              if (sure) remove.mutate();
            }
          : null
      }
      onCheck={() => check.mutate()}
      checking={check.isPending}
    >
      <div className="field">
        <label htmlFor="connection-email-provider">{t("connections.email.provider")}</label>
        <select
          id="connection-email-provider"
          value={provider}
          onChange={(e) => {
            setProvider(e.target.value as MailProviderName);
            setOutcome({ kind: "idle" });
          }}
        >
          <option value="log">{t("connections.email.provider.log")}</option>
          <option value="emailit">{t("connections.email.provider.emailit")}</option>
        </select>
      </div>
      <p className="connection-state">{t("connections.tokenState", { state: t(`connections.state.${stored.key}`) })}</p>
      {stored.key === "environment" && <p className="hint">{t("connections.email.environment")}</p>}
      <div className="field">
        <label htmlFor="connection-email-key">{t("connections.email.key")}</label>
        <input
          id="connection-email-key"
          type="password"
          autoComplete="off"
          spellCheck={false}
          value={key}
          onChange={edit(setKey)}
        />
        {stored.key === "set" && <span className="hint">{t("connections.tokenKeep")}</span>}
      </div>
      <div className="field">
        <label htmlFor="connection-email-sender">{t("connections.email.sender")}</label>
        <input
          id="connection-email-sender"
          autoComplete="off"
          spellCheck={false}
          placeholder="Delve <delve@example.org>"
          value={sender}
          onChange={edit(setSender)}
        />
        <span className="hint">{t("connections.email.senderHint")}</span>
      </div>
      <div className="field">
        <label htmlFor="connection-email-url">{t("connections.email.publicUrl")}</label>
        <input
          id="connection-email-url"
          type="url"
          autoComplete="off"
          spellCheck={false}
          placeholder={stored.public_url_default ?? "https://delve.example"}
          value={publicUrl}
          onChange={edit(setPublicUrl)}
        />
        <span className="hint">
          {stored.public_url_default
            ? t("connections.email.publicUrlDefault", { url: stored.public_url_default })
            : t("connections.email.publicUrlHint")}
        </span>
      </div>
      <p className="hint">{t("connections.email.sentToday", { count: String(stored.sent_today) })}</p>
      <p className="hint">{t("connections.email.waiting", { count: String(stored.waiting) })}</p>
      {stored.failures.length > 0 && (
        <div className="field">
          <span className="label">{t("connections.email.failures")}</span>
          <ul className="connection-failures">
            {stored.failures.map((failure, index) => (
              <li key={index}>
                <time dateTime={failure.at}>{new Date(failure.at).toLocaleString(language)}</time> · {failure.kind} ·{" "}
                {failure.failure}
              </li>
            ))}
          </ul>
        </div>
      )}
      <p className="hint">
        <a href="/help/email-setup" target="_blank" rel="noreferrer">
          {t("connections.email.help")}
        </a>
      </p>
    </Row>
  );
}

/** Who runs this Delve, for the public privacy policy and terms (DEL-208): a name and a contact email, both shown
 * there to anyone. */
function Operator() {
  const t = useT();
  const client = useQueryClient();
  const legal = useQuery({ queryKey: legalKey, queryFn: getLegal });
  const [name, setName] = useState<string | null>(null);
  const [email, setEmail] = useState<string | null>(null);
  const [outcome, setOutcome] = useState<Outcome>({ kind: "idle" });
  const shownName = name ?? legal.data?.operator.name ?? "";
  const shownEmail = email ?? legal.data?.operator.email ?? "";
  const save = useMutation({
    mutationFn: () => putOperator({ name: shownName.trim(), email: shownEmail.trim() }),
    onSuccess: (saved) => {
      client.setQueryData(legalKey, saved);
      setOutcome({ kind: "saved" });
    },
    onError: (error) => setOutcome({ kind: "failed", key: "connections.saveFailed", error: error.message }),
  });
  if (!legal.data) return null;
  return (
    <Row name="legal" outcome={outcome} busy={save.isPending} canSave onSubmit={() => save.mutate()} onRemove={null}>
      <div className="field">
        <label htmlFor="connection-legal-name">{t("connections.legal.name")}</label>
        <input
          id="connection-legal-name"
          value={shownName}
          onChange={(e) => {
            setName(e.target.value);
            setOutcome({ kind: "idle" });
          }}
        />
      </div>
      <div className="field">
        <label htmlFor="connection-legal-email">{t("connections.legal.email")}</label>
        <input
          id="connection-legal-email"
          type="email"
          value={shownEmail}
          onChange={(e) => {
            setEmail(e.target.value);
            setOutcome({ kind: "idle" });
          }}
        />
        <span className="hint">{t("connections.legal.emailHint")}</span>
      </div>
      <p className="legal-links">
        <a href="/privacy" target="_blank" rel="noreferrer">
          {t("legal.privacy")}
        </a>{" "}
        ·{" "}
        <a href="/terms" target="_blank" rel="noreferrer">
          {t("legal.terms")}
        </a>
      </p>
    </Row>
  );
}

/** One connection: its name, its fields, and Save, Remove and Test (if it has one), with what the last of them
 * answered. */
function Row({
  name,
  outcome,
  busy,
  canSave,
  onSubmit,
  onRemove,
  onCheck,
  checking,
  children,
}: {
  /** A connection, or the operator's row (`legal`), which isn't one but looks like one. */
  name: ConnectionName | "legal";
  outcome: Outcome;
  busy: boolean;
  canSave: boolean;
  onSubmit: () => void;
  onRemove: (() => void) | null;
  onCheck?: () => void;
  checking?: boolean;
  children: ReactNode;
}) {
  const t = useT();
  const id = `connection-${name}`;
  return (
    <form
      className="job connection"
      role="group"
      aria-labelledby={`${id}-title`}
      onSubmit={(e) => {
        e.preventDefault();
        onSubmit();
      }}
    >
      <div className="job-name">
        <span id={`${id}-title`} className="job-title">
          {t(`connections.${name}`)}
        </span>
        <span className="job-hint">{t(`connections.${name}.hint`)}</span>
      </div>
      <div className="connection-body">
        {children}
        <div className="actions">
          <button type="submit" className="primary" disabled={busy || !canSave}>
            {busy ? t("connections.saving") : t("connections.save")}
          </button>
          {onRemove && (
            <button type="button" onClick={onRemove}>
              {t("connections.remove")}
            </button>
          )}
          {onCheck && (
            <button type="button" onClick={onCheck} disabled={checking}>
              {checking ? t("connections.testing") : t("connections.test")}
            </button>
          )}
        </div>
        <p role="status" className={`connection-outcome${outcomeFailed(outcome) ? " failed" : ""}`}>
          {outcome.kind === "saved" && t("connections.saved")}
          {outcome.kind === "removed" && t("connections.removed")}
          {outcome.kind === "failed" && t(outcome.key, { error: outcome.error })}
          {outcome.kind === "checked" && outcome.check.message}
        </p>
      </div>
    </form>
  );
}

function outcomeFailed(outcome: Outcome): boolean {
  return outcome.kind === "failed" || (outcome.kind === "checked" && !outcome.check.ok);
}
