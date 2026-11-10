import { QueryClient, QueryClientProvider, useQuery } from "@tanstack/react-query";
import { useState, type FormEvent } from "react";
import { I18nProvider, isLanguage, useT } from "../i18n";
import { useMailEnabled } from "../mail/api";
import { accountKeys, askPasswordHelp, getAuthProviders, getMe, getSignUp, logIn, makeFirstOwner } from "./api";
import { LegalLinks } from "./Legal";
import { OutsideButtons, sayOutside, useOutsideResult } from "./Outside";
import "./account.css";

/** After logging in: the page again, which the new login session now opens (players and tavern Task E1). */
function reload() {
  window.location.reload();
}

/** `/login` on its own, outside the app: where `delve serve` sends the owner to make the owner account, and a way to
 * log in to another account. Once logged in, the app opens. */
export function LoginRoot() {
  const [client] = useState(() => new QueryClient({ defaultOptions: { queries: { retry: false, refetchOnWindowFocus: false } } }));
  const code = (typeof navigator !== "undefined" ? navigator.language : "en").slice(0, 2).toLowerCase();
  return (
    <QueryClientProvider client={client}>
      <I18nProvider language={isLanguage(code) ? code : "en"}>
        <Login onDone={() => window.location.assign("/home")} />
      </I18nProvider>
    </QueryClientProvider>
  );
}

/** The page to come back to after an outside login: this one, unless it is `/login` itself. */
function comeBackTo(): string {
  if (typeof window === "undefined" || window.location.pathname === "/login") return "/";
  return `${window.location.pathname}${window.location.search}`;
}

/**
 * The login page, in place of the app whenever Delve answers 401, and at `/login`: a username and a password, or an
 * outside account (DEL-206: "Continue with Google", back to this page, with what went wrong said here). It never asks
 * for the owner token (the human's ruling of 2026-10-24). On this machine, while there is no owner account yet, it
 * offers to make one.
 */
export default function Login({ onDone = reload }: { onDone?: () => void }) {
  const t = useT();
  // Only this machine is told whether an owner account exists; anyone else gets a 401 here, which says nothing.
  const me = useQuery({ queryKey: ["login", "me"], queryFn: () => getMe(), retry: false, staleTime: Infinity });
  // While sign-up is open, someone without an account may ask for one (DEL-156).
  const signUp = useQuery({ queryKey: accountKeys.signUp, queryFn: getSignUp, retry: false, staleTime: Infinity });
  const outside = useOutsideResult();
  const said = outside.code ? sayOutside(t, outside.code) : null;
  return (
    <main className="gate account-page">
      <div className="gate-card">
        {said && (
          <p className="notice" role="alert" data-testid="outside-result">
            {said}
          </p>
        )}
        <LoginForm onDone={onDone} />
        <OutsideButtons mode="login" params={{ next: comeBackTo() }} />
        <ForgotPassword />
        {signUp.data?.open && (
          <p className="sign-up-entry">
            <a href="/sign-up" data-testid="login-sign-up">
              {t("signUp.askForOne")}
            </a>
          </p>
        )}
        {me.data?.owner_account_exists === false && <FirstOwner onDone={onDone} />}
        <LegalLinks />
      </div>
    </main>
  );
}

function LoginForm({ onDone }: { onDone: () => void }) {
  const t = useT();
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function submit(e: FormEvent) {
    e.preventDefault();
    if (busy || !username.trim() || !password) return;
    setBusy(true);
    setError(null);
    try {
      await logIn(username, password);
      onDone();
    } catch (refused) {
      setError((refused as Error).message);
      setPassword("");
      setBusy(false);
    }
  }

  return (
    <form className="account-form" onSubmit={submit}>
      <h1>{t("login.title")}</h1>
      <label htmlFor="login-username">{t("login.username")}</label>
      <input
        id="login-username"
        data-testid="login-username"
        value={username}
        autoComplete="username"
        autoCapitalize="none"
        spellCheck={false}
        autoFocus
        onChange={(e) => setUsername(e.target.value)}
      />
      <label htmlFor="login-password">{t("login.password")}</label>
      <input
        id="login-password"
        data-testid="login-password"
        type="password"
        value={password}
        autoComplete="current-password"
        onChange={(e) => setPassword(e.target.value)}
      />
      {error && (
        <p className="notice error" role="alert">
          {error}
        </p>
      )}
      <button type="submit" className="primary" data-testid="login-submit" disabled={busy}>
        {t("login.submit")}
      </button>
    </form>
  );
}

/**
 * "Forgot your password?" (DEL-268): without mail the player asks the owner, who sees the request on the Players page and
 * hands over a reset link. While Delve sends email (DEL-314) the player may give their address instead, and an account
 * with a confirmed address gets the link by email. The answer is the same for any username or address. With an outside
 * login set up (DEL-206), it also says that an account linked to it logs in that way, password or not.
 */
export function ForgotPassword() {
  const t = useT();
  const providers = useQuery({ queryKey: accountKeys.authProviders, queryFn: getAuthProviders, retry: false, staleTime: 60_000 });
  const mail = useMailEnabled();
  const [open, setOpen] = useState(false);
  const [username, setUsername] = useState("");
  const [busy, setBusy] = useState(false);
  const [asked, setAsked] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const outside = providers.data?.map((provider) => provider.title).join(", ");

  async function submit(e: FormEvent) {
    e.preventDefault();
    if (busy || !username.trim()) return;
    setBusy(true);
    setError(null);
    try {
      await askPasswordHelp(username.trim());
      setAsked(true);
    } catch (refused) {
      setError((refused as Error).message);
    } finally {
      setBusy(false);
    }
  }

  if (!open) {
    return (
      <p className="forgot-entry">
        <button type="button" className="link-button" data-testid="forgot-open" onClick={() => setOpen(true)}>
          {t("forgot.open")}
        </button>
      </p>
    );
  }
  return (
    <section className="forgot" aria-labelledby="forgot-title" data-testid="forgot">
      <h2 id="forgot-title">{t("forgot.title")}</h2>
      {outside && <p className="hint">{t("forgot.outside", { providers: outside })}</p>}
      {asked ? (
        <p className="notice" role="status" data-testid="forgot-asked">
          {t(mail ? "forgot.askedMail" : "forgot.asked")}
        </p>
      ) : (
        <form className="account-form" onSubmit={submit}>
          <p className="hint">{t(mail ? "forgot.explainMail" : "forgot.explain")}</p>
          <label htmlFor="forgot-username">{t(mail ? "forgot.nameOrAddress" : "login.username")}</label>
          <input
            id="forgot-username"
            data-testid="forgot-username"
            value={username}
            autoComplete="username"
            autoCapitalize="none"
            spellCheck={false}
            onChange={(e) => setUsername(e.target.value)}
          />
          {error && (
            <p className="notice error" role="alert">
              {error}
            </p>
          )}
          <button type="submit" data-testid="forgot-submit" disabled={busy || !username.trim()}>
            {t(mail ? "forgot.submitMail" : "forgot.submit")}
          </button>
        </form>
      )}
    </section>
  );
}

/** The install's first owner account, made from this machine (the human's ruling of 2026-10-24). */
function FirstOwner({ onDone }: { onDone: () => void }) {
  const t = useT();
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function submit(e: FormEvent) {
    e.preventDefault();
    if (busy || !username.trim() || !password) return;
    setBusy(true);
    setError(null);
    try {
      await makeFirstOwner(username, password);
      onDone();
    } catch (refused) {
      setError((refused as Error).message);
      setBusy(false);
    }
  }

  return (
    <form className="account-form first-owner" data-testid="login-first-owner" onSubmit={submit}>
      <h2>{t("login.firstOwner")}</h2>
      <p>{t("login.firstOwnerExplain")}</p>
      <label htmlFor="first-owner-username">{t("login.username")}</label>
      <input
        id="first-owner-username"
        data-testid="first-owner-username"
        value={username}
        autoComplete="username"
        autoCapitalize="none"
        spellCheck={false}
        onChange={(e) => setUsername(e.target.value)}
      />
      <label htmlFor="first-owner-password">{t("login.password")}</label>
      <input
        id="first-owner-password"
        data-testid="first-owner-password"
        type="password"
        value={password}
        autoComplete="new-password"
        onChange={(e) => setPassword(e.target.value)}
      />
      <p className="hint">{t("join.passwordHint")}</p>
      {error && (
        <p className="notice error" role="alert">
          {error}
        </p>
      )}
      <button type="submit" data-testid="first-owner-submit" disabled={busy}>
        {t("login.firstOwner")}
      </button>
    </form>
  );
}
