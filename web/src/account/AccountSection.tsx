import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState, type FormEvent } from "react";
import { useConfirm } from "../components/dialogs";
import { useLanguage, useT } from "../i18n";
import { ago } from "../components/ago";
import {
  accountKeys,
  changePassword,
  endAllSessions,
  endSession,
  getAuthProviders,
  getIdentities,
  getSessions,
  linkTicket,
  logOut,
  unlinkIdentity,
  type Account,
} from "./api";
import { deviceLabel } from "./device";
import { sayOutside, useOutsideResult } from "./Outside";
import "./account.css";

/** Off to the login page: this browser is logged out. */
function toLogin() {
  window.location.assign("/");
}

/**
 * Preferences' Account section, for an account (players and tavern Task E4): its username, a new password (the other
 * devices are logged out), the outside accounts it logs in with (DEL-206), where it is logged in with a Log out for
 * each, Log out everywhere, and Log out.
 */
export default function AccountSection({ account }: { account: Account }) {
  const t = useT();
  const confirm = useConfirm();
  const [leaving, setLeaving] = useState(false);

  async function everywhere() {
    const sure = await confirm({
      title: t("account.endAllConfirm"),
      body: t("account.endAllBody"),
      confirm: t("account.endAll"),
      danger: true,
    });
    if (!sure) return;
    setLeaving(true);
    await endAllSessions().catch(() => undefined);
    toLogin();
  }

  return (
    <section className="account-section" aria-labelledby="account-title">
      <h2 id="account-title">{t("account.title")}</h2>
      <p className="account-username">{account.username}</p>
      <PasswordForm />
      <LinkedAccounts />
      <Sessions />
      <div className="actions">
        <button type="button" className="danger" data-testid="account-end-all" disabled={leaving} onClick={() => void everywhere()}>
          {t("account.endAll")}
        </button>
        <button
          type="button"
          data-testid="account-logout"
          disabled={leaving}
          onClick={() => {
            setLeaving(true);
            void logOut()
              .catch(() => undefined)
              .then(toLogin);
          }}
        >
          {t("account.logout")}
        </button>
      </div>
    </section>
  );
}

function PasswordForm() {
  const t = useT();
  const client = useQueryClient();
  const [old, setOld] = useState("");
  const [next, setNext] = useState("");
  const [again, setAgain] = useState("");
  const [status, setStatus] = useState<{ kind: "idle" } | { kind: "saved" } | { kind: "error"; message: string }>({ kind: "idle" });
  const save = useMutation({
    mutationFn: () => changePassword(old, next),
    onSuccess: () => {
      setOld("");
      setNext("");
      setAgain("");
      setStatus({ kind: "saved" });
      client.invalidateQueries({ queryKey: accountKeys.sessions });
    },
    onError: (error) => setStatus({ kind: "error", message: error.message }),
  });

  function submit(e: FormEvent) {
    e.preventDefault();
    if (save.isPending || !old || !next) return;
    if (next !== again) {
      setStatus({ kind: "error", message: t("link.differ") });
      return;
    }
    setStatus({ kind: "idle" });
    save.mutate();
  }

  return (
    <form className="account-form" aria-labelledby="account-password-title" onSubmit={submit}>
      <h3 id="account-password-title">{t("account.password")}</h3>
      <label htmlFor="account-old">{t("account.oldPassword")}</label>
      <input
        id="account-old"
        data-testid="account-old"
        type="password"
        value={old}
        autoComplete="current-password"
        onChange={(e) => setOld(e.target.value)}
      />
      <label htmlFor="account-new">{t("account.newPassword")}</label>
      <input
        id="account-new"
        data-testid="account-new"
        type="password"
        value={next}
        autoComplete="new-password"
        onChange={(e) => setNext(e.target.value)}
      />
      <p className="hint">{t("join.passwordHint")}</p>
      <label htmlFor="account-new-again">{t("link.again")}</label>
      <input
        id="account-new-again"
        data-testid="account-new-again"
        type="password"
        value={again}
        autoComplete="new-password"
        onChange={(e) => setAgain(e.target.value)}
      />
      {status.kind === "error" && (
        <p className="notice error" role="alert">
          {status.message}
        </p>
      )}
      <button type="submit" data-testid="account-password-save" disabled={save.isPending}>
        {t("account.passwordSave")}
      </button>
      <span role="status" className="status">
        {status.kind === "saved" && t("account.passwordSaved")}
      </span>
    </form>
  );
}

/** The outside accounts the account logs in with (DEL-206): each with its email and Unlink, a "Link …" for each
 * provider this browser may use that isn't linked (asking for the account's password when it has one, so a browser
 * left logged in can't be given another way in), and what a link that just came back said. Nothing at all while no
 * provider is set up and nothing is linked. */
function LinkedAccounts() {
  const t = useT();
  const client = useQueryClient();
  const outside = useOutsideResult();
  const linked = useQuery({ queryKey: accountKeys.identities, queryFn: getIdentities });
  const providers = useQuery({ queryKey: accountKeys.authProviders, queryFn: getAuthProviders, retry: false });
  const [error, setError] = useState<string | null>(null);
  const unlink = useMutation({
    mutationFn: unlinkIdentity,
    onSuccess: () => {
      setError(null);
      client.invalidateQueries({ queryKey: accountKeys.identities });
    },
    onError: (refused) => setError(refused.message),
  });
  const identities = linked.data?.identities ?? [];
  const unlinked = (providers.data ?? []).filter((p) => !identities.some((i) => i.provider === p.id));
  const said = outside.code ? sayOutside(t, outside.code) : null;
  if (identities.length === 0 && unlinked.length === 0 && !said) return null;
  return (
    <div className="account-linked" data-testid="account-linked">
      <h3>{t("outside.linkedTitle")}</h3>
      {said && (
        <p className={outside.code === "linked" ? "notice" : "notice error"} role="status" data-testid="outside-result">
          {said}
        </p>
      )}
      {identities.length > 0 && (
        <ul className="account-identities">
          {identities.map((identity) => (
            <li key={identity.provider} data-testid={`account-identity-${identity.provider}`}>
              <span>
                {identity.title}
                {identity.email && <span className="row-meta"> · {identity.email}</span>}
              </span>
              <button type="button" disabled={unlink.isPending} onClick={() => unlink.mutate(identity.provider)}>
                {t("outside.unlink")}
              </button>
            </li>
          ))}
        </ul>
      )}
      {error && (
        <p className="notice error" role="alert">
          {error}
        </p>
      )}
      {identities.length === 0 && unlinked.length > 0 && (
        // Delve sends no mail, so a linked outside account is the player's own way back in (DEL-268).
        <p className="hint" data-testid="outside-why">
          {t("outside.linkWhy", { providers: unlinked.map((provider) => provider.title).join(", ") })}
        </p>
      )}
      {unlinked.map((provider) => (
        <LinkForm key={provider.id} provider={provider} askPassword={linked.data?.has_password ?? true} />
      ))}
    </div>
  );
}

function LinkForm({ provider, askPassword }: { provider: { id: string; title: string }; askPassword: boolean }) {
  const t = useT();
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const start = useMutation({
    mutationFn: () => linkTicket(provider.id, askPassword ? password : undefined),
    onSuccess: ({ url }) => window.location.assign(url),
    onError: (refused) => {
      setPassword("");
      setError(refused.message);
    },
  });
  return (
    <form
      className="account-form account-link-form"
      onSubmit={(e) => {
        e.preventDefault();
        if (!start.isPending && (!askPassword || password)) start.mutate();
      }}
    >
      {askPassword && (
        <>
          <label htmlFor={`link-${provider.id}-password`}>{t("outside.linkPassword")}</label>
          <input
            id={`link-${provider.id}-password`}
            type="password"
            value={password}
            autoComplete="current-password"
            onChange={(e) => setPassword(e.target.value)}
          />
          <span className="hint">{t("outside.linkPasswordHint")}</span>
        </>
      )}
      {error && (
        <p className="notice error" role="alert">
          {error}
        </p>
      )}
      <button type="submit" disabled={start.isPending || (askPassword && !password)}>
        {t("outside.link", { provider: provider.title })}
      </button>
    </form>
  );
}

/** Where the account is logged in: each browser, when it was last used, and a Log out. */
function Sessions() {
  const t = useT();
  const language = useLanguage();
  const client = useQueryClient();
  const sessions = useQuery({ queryKey: accountKeys.sessions, queryFn: getSessions });
  const end = useMutation({
    mutationFn: (id: string) => endSession(id),
    onSuccess: (_, id) => {
      if (sessions.data?.find((s) => s.id === id)?.current) toLogin();
      else client.invalidateQueries({ queryKey: accountKeys.sessions });
    },
  });
  return (
    <div className="account-sessions-block">
      <h3>{t("account.sessions")}</h3>
      {sessions.error && (
        <p className="notice error" role="alert">
          {sessions.error.message}
        </p>
      )}
      {sessions.data && (
        <table className="account-sessions">
          <tbody>
            {sessions.data.map((session) => (
              <tr key={session.id} data-testid={`account-session-${session.id}`}>
                <td>
                  {deviceLabel(session.device, t)}
                  {session.current && <span className="account-session-current"> · {t("account.thisDevice")}</span>}
                </td>
                <td className="row-meta">{t("account.lastUsed", { ago: ago(session.last_used_at, language) })}</td>
                <td>
                  <button type="button" disabled={end.isPending} onClick={() => end.mutate(session.id)}>
                    {t("account.logout")}
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}
