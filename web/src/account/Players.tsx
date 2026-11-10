import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState, type FormEvent } from "react";
import { Link } from "react-router-dom";
import { copyText } from "../components/copyText";
import { LANGUAGES, useLanguage, useT } from "../i18n";
import { useMailEnabled } from "../mail/api";
import { useMe } from "./useMe";
import {
  accountKeys,
  addAccount,
  approveAccount,
  changeAccount,
  dismissResetRequest,
  getSignUp,
  listAccounts,
  rejectAccount,
  resetLink,
  setSignUp,
  type OneTimeLink,
  type PlayerAccount,
} from "./api";
import { useConfirm } from "../components/dialogs";
import "./account.css";

/**
 * `/preferences/players`, the organisers' (players and tavern Task E4): every account, Add a player (which gives a
 * set-password link to hand over), and per account a reset link, Disable or Enable, and for an owner the organiser
 * and owner rights. An account comes from an invite, from here, or from a sign-up (DEL-156): the switch opens or closes
 * sign-up, and the sign-ups waiting for approval come first, each to approve or reject. Then the players who asked for
 * a new password on the login page (DEL-268), each with Make a reset link (which answers the request) or Dismiss.
 */
export default function Players() {
  const t = useT();
  const client = useQueryClient();
  const me = useMe();
  const owner = me.data?.principal.id === "owner" || Boolean(me.data?.account?.owner);
  const accounts = useQuery({ queryKey: accountKeys.accounts, queryFn: listAccounts });
  const [link, setLink] = useState<{ username: string; link: OneTimeLink } | null>(null);
  const [error, setError] = useState<string | null>(null);
  const refresh = () => client.invalidateQueries({ queryKey: accountKeys.accounts });
  const change = useMutation({
    mutationFn: ({ id, ...changes }: { id: string; disabled?: boolean; organiser?: boolean; owner?: boolean }) =>
      changeAccount(id, changes),
    onMutate: () => setError(null),
    onSuccess: refresh,
    onError: (failed) => setError(failed.message),
  });
  const reset = useMutation({
    mutationFn: (account: PlayerAccount) => resetLink(account.id).then((made) => ({ username: account.username, link: made })),
    onMutate: () => setError(null),
    onSuccess: setLink,
    onError: (failed) => setError(failed.message),
  });

  return (
    <section className="page players">
      <p>
        <Link to="/preferences?tab=players">{t("players.back")}</Link>
      </p>
      <h1>{t("players.title")}</h1>
      <p className="lede">{t("players.intro")}</p>
      <AddPlayer
        onAdded={(added) => {
          setLink(added);
          refresh();
        }}
      />
      {link && (
        <div className="notice players-link" data-testid="players-link" role="status">
          <span>{t("players.link", { username: link.username })}</span>
          <input readOnly value={link.link.url} aria-label={t("players.link", { username: link.username })} onFocus={(e) => e.target.select()} />
          <CopyButton text={link.link.url} />
          <span className="hint">{t("players.linkHint")}</span>
        </div>
      )}
      {error && (
        <p className="notice error" role="alert">
          {error}
        </p>
      )}
      {accounts.error && (
        <p className="notice error" role="alert">
          {accounts.error.message}
        </p>
      )}
      <SignUpSwitch />
      {accounts.data && <Waiting accounts={accounts.data.filter((account) => account.pending)} onError={setError} />}
      {accounts.data && (
        <ResetRequests
          accounts={accounts.data.filter((account) => account.reset_asked_at)}
          making={reset.isPending}
          onReset={(account) => reset.mutate(account, { onSuccess: refresh })}
          onError={setError}
        />
      )}
      {accounts.data && (
        <table className="players-table">
          <thead>
            <tr>
              <th>{t("login.username")}</th>
              <th>{t("players.displayName")}</th>
              <th>{t("players.tables")}</th>
              <th>{t("players.rights")}</th>
              <th>
                <span className="visually-hidden">{t("players.actions")}</span>
              </th>
            </tr>
          </thead>
          <tbody>
            {accounts.data.filter((account) => !account.pending).map((account) => (
              <tr key={account.id} data-testid={`players-row-${account.id}`}>
                <td>{account.username}</td>
                <td>{account.display_name}</td>
                <td>{account.tables}</td>
                <td>
                  {[
                    account.owner && t("players.owner"),
                    account.organiser && t("players.organiser"),
                    account.disabled && t("players.disabled"),
                    !account.has_password && t("players.noPassword"),
                    account.has_email && t("players.hasEmail"),
                  ]
                    .filter(Boolean)
                    .join(", ") || t("players.player")}
                </td>
                <td>
                  <div className="players-actions">
                    <button type="button" disabled={reset.isPending} onClick={() => reset.mutate(account)}>
                      {t("players.reset")}
                    </button>
                    <button
                      type="button"
                      disabled={change.isPending}
                      onClick={() => change.mutate({ id: account.id, disabled: !account.disabled })}
                    >
                      {t(account.disabled ? "players.enable" : "players.disable")}
                    </button>
                    {owner && (
                      <button
                        type="button"
                        disabled={change.isPending}
                        onClick={() => change.mutate({ id: account.id, organiser: !account.organiser })}
                      >
                        {t(account.organiser ? "players.withdrawOrganiser" : "players.makeOrganiser")}
                      </button>
                    )}
                    {owner && (
                      <button
                        type="button"
                        disabled={change.isPending}
                        onClick={() => change.mutate({ id: account.id, owner: !account.owner })}
                      >
                        {t(account.owner ? "players.withdrawOwner" : "players.makeOwner")}
                      </button>
                    )}
                  </div>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </section>
  );
}

/** Open or close sign-up: while open, anyone who reaches Delve may ask for a player's account (DEL-156). */
function SignUpSwitch() {
  const t = useT();
  const client = useQueryClient();
  const state = useQuery({ queryKey: accountKeys.signUp, queryFn: getSignUp });
  const flip = useMutation({
    mutationFn: setSignUp,
    onSuccess: (saved) => client.setQueryData(accountKeys.signUp, saved),
  });
  if (!state.data) return null;
  return (
    <section className="players-sign-up" aria-labelledby="players-sign-up-title">
      <h2 id="players-sign-up-title">{t("players.signUp")}</h2>
      <label className="check">
        <input
          type="checkbox"
          data-testid="players-sign-up-open"
          checked={state.data.open}
          disabled={flip.isPending}
          onChange={(e) => flip.mutate(e.target.checked)}
        />
        {t("players.signUpOpen")}
      </label>
      <p className="hint">{t(state.data.open ? "players.signUpOpenHint" : "players.signUpClosedHint")}</p>
      {flip.error && (
        <p className="notice error" role="alert">
          {flip.error.message}
        </p>
      )}
    </section>
  );
}

/** The sign-ups waiting for approval, the oldest first: Let in, or Turn away (which deletes the account). */
/** The players who asked for a new password (DEL-268): no mail, so the link this makes is handed over as any link is. */
function ResetRequests({
  accounts,
  making,
  onReset,
  onError,
}: {
  accounts: PlayerAccount[];
  making: boolean;
  onReset: (account: PlayerAccount) => void;
  onError: (error: string | null) => void;
}) {
  const t = useT();
  const language = useLanguage();
  const client = useQueryClient();
  const mail = useMailEnabled(); // with mail, only accounts without a confirmed address ask the owner
  const dismiss = useMutation({
    mutationFn: (account: PlayerAccount) => dismissResetRequest(account.id),
    onMutate: () => onError(null),
    onSuccess: () => client.invalidateQueries({ queryKey: accountKeys.accounts }),
    onError: (failed) => onError(failed.message),
  });
  if (!accounts.length) return null;
  return (
    <section className="players-waiting" aria-labelledby="players-resets-title" data-testid="players-resets">
      <h2 id="players-resets-title">{t("players.resetAsked", { count: String(accounts.length) })}</h2>
      <p className="hint">{t(mail ? "players.resetAskedHintMail" : "players.resetAskedHint")}</p>
      <ul>
        {accounts.map((account) => (
          <li key={account.id} data-testid={`players-reset-${account.id}`}>
            <div>
              <strong>{account.display_name}</strong> <span className="muted">{account.username}</span>
              <span className="hint">
                {t("players.askedAt", { when: new Date(account.reset_asked_at as string).toLocaleString(language) })}
              </span>
            </div>
            <div className="players-actions">
              <button type="button" className="primary" disabled={making} onClick={() => onReset(account)}>
                {t("players.reset")}
              </button>
              <button type="button" disabled={dismiss.isPending} onClick={() => dismiss.mutate(account)}>
                {t("players.dismiss")}
              </button>
            </div>
          </li>
        ))}
      </ul>
    </section>
  );
}

function Waiting({ accounts, onError }: { accounts: PlayerAccount[]; onError: (error: string | null) => void }) {
  const t = useT();
  const language = useLanguage();
  const client = useQueryClient();
  const confirm = useConfirm();
  const refresh = () => client.invalidateQueries({ queryKey: accountKeys.accounts });
  const approve = useMutation({
    mutationFn: (account: PlayerAccount) => approveAccount(account.id),
    onMutate: () => onError(null),
    onSuccess: refresh,
    onError: (failed) => onError(failed.message),
  });
  const reject = useMutation({
    mutationFn: (account: PlayerAccount) => rejectAccount(account.id),
    onMutate: () => onError(null),
    onSuccess: refresh,
    onError: (failed) => onError(failed.message),
  });
  if (!accounts.length) return null;

  async function turnAway(account: PlayerAccount) {
    const sure = await confirm({
      title: t("players.rejectTitle", { username: account.username }),
      body: t("players.rejectBody"),
      confirm: t("players.reject"),
    });
    if (sure) reject.mutate(account);
  }

  return (
    <section className="players-waiting" aria-labelledby="players-waiting-title" data-testid="players-waiting">
      <h2 id="players-waiting-title">{t("players.waiting", { count: String(accounts.length) })}</h2>
      <ul>
        {accounts.map((account) => (
          <li key={account.id} data-testid={`players-waiting-${account.id}`}>
            <div>
              <strong>{account.display_name}</strong> <span className="muted">{account.username}</span>
              {account.request_note && <p className="players-note">{account.request_note}</p>}
              <span className="hint">{t("players.askedAt", { when: new Date(account.created_at).toLocaleString(language) })}</span>
            </div>
            <div className="players-actions">
              <button type="button" className="primary" disabled={approve.isPending} onClick={() => approve.mutate(account)}>
                {t("players.approve")}
              </button>
              <button type="button" disabled={reject.isPending} onClick={() => void turnAway(account)}>
                {t("players.reject")}
              </button>
            </div>
          </li>
        ))}
      </ul>
    </section>
  );
}

function AddPlayer({ onAdded }: { onAdded: (added: { username: string; link: OneTimeLink }) => void }) {
  const t = useT();
  const [username, setUsername] = useState("");
  const [displayName, setDisplayName] = useState("");
  const [language, setLanguage] = useState("en");
  const add = useMutation({
    mutationFn: () =>
      addAccount({ username: username.trim(), ...(displayName.trim() ? { display_name: displayName.trim() } : {}), language }),
    onSuccess: (added) => {
      setUsername("");
      setDisplayName("");
      onAdded({ username: added.account.username, link: added.link });
    },
  });

  function submit(e: FormEvent) {
    e.preventDefault();
    if (username.trim() && !add.isPending) add.mutate();
  }

  return (
    <form className="inline-form" aria-labelledby="players-add-title" onSubmit={submit}>
      <h2 id="players-add-title" className="visually-hidden">
        {t("players.add")}
      </h2>
      <div className="field">
        <label htmlFor="players-username">{t("login.username")}</label>
        <input
          id="players-username"
          data-testid="players-username"
          value={username}
          autoCapitalize="none"
          spellCheck={false}
          onChange={(e) => setUsername(e.target.value)}
        />
      </div>
      <div className="field">
        <label htmlFor="players-display-name">{t("players.displayName")}</label>
        <input
          id="players-display-name"
          data-testid="players-display-name"
          value={displayName}
          maxLength={40}
          onChange={(e) => setDisplayName(e.target.value)}
        />
      </div>
      <div className="field">
        <label htmlFor="players-language">{t("preferences.language")}</label>
        <select id="players-language" data-testid="players-language" value={language} onChange={(e) => setLanguage(e.target.value)}>
          {LANGUAGES.map((lang) => (
            <option key={lang} value={lang}>
              {t(`language.${lang}`)}
            </option>
          ))}
        </select>
      </div>
      <button type="submit" className="primary" data-testid="players-add" disabled={add.isPending || !username.trim()}>
        {t("players.add")}
      </button>
      {add.error && (
        <p className="notice error" role="alert">
          {add.error.message}
        </p>
      )}
    </form>
  );
}

function CopyButton({ text }: { text: string }) {
  const t = useT();
  const [copied, setCopied] = useState<boolean | null>(null);
  return (
    <>
      <button type="button" onClick={() => void copyText(text).then(setCopied)}>
        {copied ? t("players.copied") : t("players.copy")}
      </button>
      {copied === false && (
        <span className="hint" role="status">
          {t("play.copyFailed")}
        </span>
      )}
    </>
  );
}
