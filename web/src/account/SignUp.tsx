import { QueryClient, QueryClientProvider, useQuery } from "@tanstack/react-query";
import { useState, type FormEvent } from "react";
import { I18nProvider, isLanguage, useT, type Language } from "../i18n";
import { useMailEnabled } from "../mail/api";
import { accountKeys, getSignUp, signUp } from "./api";
import { LegalLinks } from "./Legal";
import { OutsideButtons, sayOutside, useOutsideResult } from "./Outside";
import "./account.css";

const NOTE_MAX = 300;
const NAME_MAX = 40;

/** `/sign-up` on its own, outside the app, as `/login`: nobody is logged in yet. */
export function SignUpRoot() {
  const [client] = useState(() => new QueryClient({ defaultOptions: { queries: { retry: false, refetchOnWindowFocus: false } } }));
  const code = (typeof navigator !== "undefined" ? navigator.language : "en").slice(0, 2).toLowerCase();
  const language: Language = isLanguage(code) ? code : "en";
  return (
    <QueryClientProvider client={client}>
      <I18nProvider language={language}>
        <SignUp language={language} />
      </I18nProvider>
    </QueryClientProvider>
  );
}

/**
 * Asking for an account (DEL-156): a username, a display name, a password and a note for whoever lets people in; or
 * the same with an outside account instead of a password (DEL-206: "Sign up with Google", which comes back here with
 * its answer). The account waits for the owner's or an organiser's approval; until then it can't log in. While
 * sign-up is closed the page says so, and points to an invite.
 */
export default function SignUp({ language = "en" }: { language?: string }) {
  const t = useT();
  const state = useQuery({ queryKey: accountKeys.signUp, queryFn: getSignUp });
  const [username, setUsername] = useState("");
  const [displayName, setDisplayName] = useState("");
  const [password, setPassword] = useState("");
  const [again, setAgain] = useState("");
  const [note, setNote] = useState("");
  const [email, setEmail] = useState("");
  const mailEnabled = useMailEnabled();
  const [busy, setBusy] = useState(false);
  const outside = useOutsideResult();
  const [error, setError] = useState<string | null>(() =>
    outside.code && outside.code !== "waiting" ? sayOutside(t, outside.code) : null,
  );
  const [sentTo, setSentTo] = useState<string | null>(null);
  const [asked, setAsked] = useState<string | null>(() => (outside.code === "waiting" ? outside.username : null));
  const mismatch = again.length > 0 && again !== password;

  async function submit(e: FormEvent) {
    e.preventDefault();
    if (busy || !username.trim() || !password || mismatch || again !== password) return;
    setBusy(true);
    setError(null);
    try {
      const made = await signUp({
        username: username.trim(),
        password,
        language,
        ...(displayName.trim() ? { display_name: displayName.trim() } : {}),
        ...(note.trim() ? { note: note.trim() } : {}),
        ...(mailEnabled && email.trim() ? { email: email.trim() } : {}),
      });
      setSentTo(mailEnabled && email.trim() ? email.trim() : null);
      setAsked(made.username);
    } catch (refused) {
      setError((refused as Error).message);
      setBusy(false);
    }
  }

  return (
    <main className="gate account-page">
      <div className="gate-card">
        <h1>{t("signUp.title")}</h1>
        {asked ? (
          <div className="notice" role="status" data-testid="sign-up-asked">
            <p>{t("signUp.asked", { username: asked })}</p>
            {sentTo && <p>{t("signUp.askedMail", { address: sentTo })}</p>}
            <p>
              <a href="/login">{t("signUp.toLogin")}</a>
            </p>
          </div>
        ) : state.data && !state.data.open ? (
          <p className="notice" data-testid="sign-up-closed">
            {t("signUp.closed")}
          </p>
        ) : state.data ? (
          <form className="account-form" onSubmit={submit}>
            <p className="lede">{t("signUp.intro")}</p>
            <label htmlFor="sign-up-username">{t("login.username")}</label>
            <input
              id="sign-up-username"
              data-testid="sign-up-username"
              value={username}
              autoComplete="username"
              autoCapitalize="none"
              spellCheck={false}
              autoFocus
              onChange={(e) => setUsername(e.target.value)}
            />
            <span className="hint">{t("signUp.usernameHint")}</span>
            <label htmlFor="sign-up-display-name">{t("players.displayName")}</label>
            <input
              id="sign-up-display-name"
              data-testid="sign-up-display-name"
              value={displayName}
              maxLength={NAME_MAX}
              onChange={(e) => setDisplayName(e.target.value)}
            />
            <label htmlFor="sign-up-password">{t("login.password")}</label>
            <input
              id="sign-up-password"
              data-testid="sign-up-password"
              type="password"
              value={password}
              autoComplete="new-password"
              onChange={(e) => setPassword(e.target.value)}
            />
            <label htmlFor="sign-up-again">{t("signUp.again")}</label>
            <input
              id="sign-up-again"
              data-testid="sign-up-again"
              type="password"
              value={again}
              autoComplete="new-password"
              aria-invalid={mismatch}
              onChange={(e) => setAgain(e.target.value)}
            />
            {mismatch && <span className="hint error">{t("signUp.mismatch")}</span>}
            <label htmlFor="sign-up-note">{t("signUp.note")}</label>
            <textarea
              id="sign-up-note"
              data-testid="sign-up-note"
              value={note}
              maxLength={NOTE_MAX}
              rows={3}
              onChange={(e) => setNote(e.target.value)}
            />
            <span className="hint">{t("signUp.noteHint")}</span>
            {mailEnabled && (
              <>
                <label htmlFor="sign-up-email">{t("signUp.email")}</label>
                <input
                  id="sign-up-email"
                  data-testid="sign-up-email"
                  type="email"
                  value={email}
                  autoComplete="email"
                  onChange={(e) => setEmail(e.target.value)}
                />
                <span className="hint">{t("signUp.emailHint")}</span>
              </>
            )}
            {error && (
              <p className="notice error" role="alert">
                {error}
              </p>
            )}
            <button
              type="submit"
              className="primary"
              data-testid="sign-up-submit"
              disabled={busy || !username.trim() || !password || again !== password}
            >
              {t("signUp.submit")}
            </button>
            <OutsideButtons
              mode="signup"
              label="outside.signUp"
              disabled={busy || !username.trim()}
              params={{ username: username.trim(), display_name: displayName.trim(), note: note.trim(), language }}
            />
            <p>
              <a href="/login">{t("signUp.haveAccount")}</a>
            </p>
          </form>
        ) : null}
        <LegalLinks />
      </div>
    </main>
  );
}
