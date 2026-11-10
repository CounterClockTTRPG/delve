import { QueryClient, QueryClientProvider, useQuery } from "@tanstack/react-query";
import { useState, type FormEvent } from "react";
import { useParams } from "react-router-dom";
import { ApiError } from "../api";
import { I18nProvider, isLanguage, useT } from "../i18n";
import { accountKeys, getLink, useLink } from "./api";
import "./account.css";

/** The interface language before the account is known: the browser's, when Delve speaks it. */
export function browserLanguage(): string {
  const code = (typeof navigator !== "undefined" ? navigator.language : "en").slice(0, 2).toLowerCase();
  return isLanguage(code) ? code : "en";
}

/** `/account/link/:token` on its own, outside the app, as `/join/:token`: the link is all it needs. */
export function SetPasswordRoot() {
  const [client] = useState(() => new QueryClient({ defaultOptions: { queries: { retry: false, refetchOnWindowFocus: false } } }));
  return (
    <QueryClientProvider client={client}>
      <I18nProvider language={browserLanguage()}>
        <SetPassword />
      </I18nProvider>
    </QueryClientProvider>
  );
}

/**
 * A one-time link an organiser handed out (players and tavern Task E1): the account's username, then the password
 * twice. Using the link logs this browser in, and the app opens.
 */
export default function SetPassword() {
  const t = useT();
  const { token = "" } = useParams();
  const link = useQuery({ queryKey: accountKeys.link(token), queryFn: () => getLink(token) });
  const [password, setPassword] = useState("");
  const [again, setAgain] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function submit(e: FormEvent) {
    e.preventDefault();
    if (busy || !password) return;
    if (password !== again) {
      setError(t("link.differ"));
      return;
    }
    setBusy(true);
    setError(null);
    try {
      await useLink(token, password);
      window.location.assign("/home");
    } catch (refused) {
      setError(refused instanceof ApiError && refused.status === 404 ? t("link.gone") : (refused as Error).message);
      setBusy(false);
    }
  }

  return (
    <main className="gate account-page">
      <form className="gate-card account-form" onSubmit={submit}>
        <h1>{t("link.title")}</h1>
        {link.isPending && <p className="placeholder">{t("preferences.loading")}</p>}
        {link.error && (
          <p className="notice error" role="alert">
            {link.error instanceof ApiError && link.error.status === 404 ? t("link.gone") : link.error.message}
          </p>
        )}
        {link.data && (
          <>
            <p className="account-username">{link.data.username}</p>
            <label htmlFor="link-password">{t("login.password")}</label>
            <input
              id="link-password"
              data-testid="link-password"
              type="password"
              value={password}
              autoComplete="new-password"
              autoFocus
              onChange={(e) => setPassword(e.target.value)}
            />
            <p className="hint">{t("join.passwordHint")}</p>
            <label htmlFor="link-password-again">{t("link.again")}</label>
            <input
              id="link-password-again"
              data-testid="link-password-again"
              type="password"
              value={again}
              autoComplete="new-password"
              onChange={(e) => setAgain(e.target.value)}
            />
            {error && (
              <p className="notice error" role="alert">
                {error}
              </p>
            )}
            <button type="submit" className="primary" data-testid="link-submit" disabled={busy}>
              {t("link.submit")}
            </button>
          </>
        )}
      </form>
    </main>
  );
}
