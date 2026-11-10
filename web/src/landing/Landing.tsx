import { QueryClient, QueryClientProvider, useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { accountKeys, getMe, getSignUp } from "../account/api";
import { I18nProvider, isLanguage, useT } from "../i18n";
import "@fontsource/im-fell-english/400.css";
import "@fontsource/im-fell-english/400-italic.css";
import "./landing.css";

// The public front page (DEL-144), at `/`, outside the app as /login is: what Delve is, for anyone, with the way in.
// A visitor who isn't logged in gets Log in (and Ask for an account while sign-up is open); one who is gets Open
// Delve, the app's own home (`/home`). The hero is a Replicate painting (`/landing/hero-*.webp`), its left third
// left dark for the words.

/** `/` on its own, in the browser's language until someone logs in. */
export function LandingRoot() {
  const [client] = useState(() => new QueryClient({ defaultOptions: { queries: { retry: false, refetchOnWindowFocus: false } } }));
  const code = (typeof navigator !== "undefined" ? navigator.language : "en").slice(0, 2).toLowerCase();
  return (
    <QueryClientProvider client={client}>
      <I18nProvider language={isLanguage(code) ? code : "en"}>
        <Landing />
      </I18nProvider>
    </QueryClientProvider>
  );
}

const STEPS = ["in", "character", "play"] as const;
const FINDS = ["dm", "adventures", "maps", "table", "sheet", "settings"] as const;

export default function Landing() {
  const t = useT();
  // Anyone logged in, a seat at a table too, goes on into the app; a 401 here only says nobody is.
  const me = useQuery({ queryKey: ["landing", "me"], queryFn: () => getMe(), retry: false, staleTime: Infinity });
  const signUp = useQuery({ queryKey: accountKeys.signUp, queryFn: getSignUp, retry: false, staleTime: Infinity });
  const inside = me.isSuccess;
  const name = me.data?.account?.display_name;

  return (
    <div className="landing">
      <header className="landing-hero">
        <img
          className="landing-hero-picture"
          src="/landing/hero-2400.webp"
          srcSet="/landing/hero-1200.webp 1200w, /landing/hero-2400.webp 2400w"
          sizes="100vw"
          alt=""
          {...{ fetchpriority: "high" }}
        />
        <div className="landing-hero-words">
          <h1 className="landing-wordmark">Delve</h1>
          <p className="landing-lede">{t("landing.lede")}</p>
          <div className="landing-actions" data-testid="landing-actions">
            {me.isPending ? null : inside ? (
              <>
                <a className="landing-primary" href="/home">
                  {t("landing.open")}
                </a>
                {name && <span className="landing-who">{t("landing.loggedInAs", { name })}</span>}
              </>
            ) : (
              <>
                <a className="landing-primary" href="/login">
                  {t("landing.logIn")}
                </a>
                {signUp.data?.open ? (
                  <a className="landing-secondary" href="/sign-up">
                    {t("landing.askForAccount")}
                  </a>
                ) : (
                  <span className="landing-who">{t("landing.inviteOnly")}</span>
                )}
              </>
            )}
          </div>
        </div>
      </header>

      <main className="landing-body">
        <section className="landing-steps" aria-labelledby="landing-steps-title">
          <h2 id="landing-steps-title">{t("landing.steps")}</h2>
          <ol>
            {STEPS.map((step) => (
              <li key={step}>
                <h3>{t(`landing.step.${step}`)}</h3>
                <p>{t(`landing.step.${step}.text`)}</p>
              </li>
            ))}
          </ol>
        </section>

        <section className="landing-finds" aria-labelledby="landing-finds-title">
          <h2 id="landing-finds-title">{t("landing.finds")}</h2>
          <dl>
            {FINDS.map((find) => (
              <div key={find}>
                <dt>{t(`landing.find.${find}`)}</dt>
                <dd>{t(`landing.find.${find}.text`)}</dd>
              </div>
            ))}
          </dl>
        </section>
      </main>

      <footer className="landing-foot">
        <p>{t("landing.private")}</p>
        <nav aria-label={t("landing.footLinks")}>
          <a href="/help">{t("landing.help")}</a>
          <a href="/board">{t("board.title")}</a>
          <a href="/privacy">{t("legal.privacy")}</a>
          <a href="/terms">{t("legal.terms")}</a>
          {!inside && <a href="/login">{t("landing.logIn")}</a>}
        </nav>
      </footer>
    </div>
  );
}
