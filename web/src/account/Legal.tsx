import { QueryClient, QueryClientProvider, useQuery } from "@tanstack/react-query";
import { useState, type ReactNode } from "react";
import { apiFetch } from "../api";
import { I18nProvider, isLanguage, useT } from "../i18n";
import "./account.css";

// The public privacy policy and terms of service (DEL-208), at /privacy and /terms, outside the app as /login is: read
// before anyone logs in, and linked from the login and sign-up pages, as Google asks of an app it publishes. The text
// is English; it says what this install does, the outside services named as `GET /api/legal` says they are set up.

export interface Legal {
  operator: { name: string; email: string };
  services: { google: boolean; replicate: boolean; backups: boolean };
}

export const getLegal = () => apiFetch<Legal>("/api/legal");
export const legalKey = ["legal"] as const;

const UPDATED = "27 October 2026";

function Root({ children }: { children: ReactNode }) {
  const [client] = useState(() => new QueryClient({ defaultOptions: { queries: { retry: false, refetchOnWindowFocus: false } } }));
  const code = (typeof navigator !== "undefined" ? navigator.language : "en").slice(0, 2).toLowerCase();
  return (
    <QueryClientProvider client={client}>
      <I18nProvider language={isLanguage(code) ? code : "en"}>{children}</I18nProvider>
    </QueryClientProvider>
  );
}

export function PrivacyRoot() {
  return (
    <Root>
      <Privacy />
    </Root>
  );
}

export function TermsRoot() {
  return (
    <Root>
      <Terms />
    </Root>
  );
}

/** Who runs this Delve, as the owner set it in Connections: "Raf (raf@example.org)", or a plain stand-in. */
function Operator({ legal }: { legal: Legal | undefined }) {
  const name = legal?.operator.name || "the owner of this Delve";
  const email = legal?.operator.email;
  return (
    <>
      {name}
      {email && (
        <>
          {" "}
          (<a href={`mailto:${email}`}>{email}</a>)
        </>
      )}
    </>
  );
}

function Page({ title, children }: { title: string; children: ReactNode }) {
  const t = useT();
  return (
    <main className="legal-page" lang="en">
      <article>
        <h1>{title}</h1>
        <p className="row-meta">Last updated {UPDATED}.</p>
        {children}
      </article>
      <LegalLinks />
      <p>
        <a href="/">{t("legal.back")}</a>
      </p>
    </main>
  );
}

/** "Privacy · Terms", at the foot of the login and sign-up pages. */
export function LegalLinks() {
  const t = useT();
  return (
    <p className="legal-links" data-testid="legal-links">
      <a href="/privacy">{t("legal.privacy")}</a> · <a href="/terms">{t("legal.terms")}</a>
    </p>
  );
}

export function Privacy() {
  const legal = useQuery({ queryKey: legalKey, queryFn: getLegal });
  const services = legal.data?.services;
  return (
    <Page title="Privacy policy">
      <p>
        Delve is a tabletop role-playing game played in the browser, with an AI game master. This Delve is a private
        installation run by <Operator legal={legal.data} />, on their own computer. This page says what it keeps about
        you, why, and who else sees it.
      </p>

      <h2>What Delve keeps</h2>
      <ul>
        <li>
          <strong>Your account:</strong> your username, the display name, pronouns, picture, colour, time zone,
          language and the text you put in your profile, and your password, which is kept only as a one-way hash.
        </li>
        {services?.google && (
          <li>
            <strong>Signing in with Google:</strong> if you sign in or sign up with Google, Delve keeps the id Google
            gives your Google account, and the email address and name Google sends with it. It uses them only to log you
            in and to show which Google account is linked. Delve asks Google for nothing else: not your contacts, files
            or mail.
          </li>
        )}
        <li>
          <strong>Where you are logged in:</strong> for each browser you log in on, a description of the browser, the
          IP address it came from, and when it was last used, so you can see your logins and end them.
        </li>
        <li>
          <strong>What you play:</strong> your characters, what you write at a table, table talk, the story the game
          master tells, and the pictures painted for a campaign. The people at the same table see what is shared there.
        </li>
        <li>
          <strong>Voice:</strong> voice chat at a table goes live between the people at that table. It is never
          recorded or stored.
        </li>
        <li>
          <strong>The server's log:</strong> the computer Delve runs on logs the requests it answers, with their IP
          address, as servers do, to keep Delve working and safe.
        </li>
      </ul>

      <h2>Who else sees it</h2>
      <ul>
        <li>
          <strong>Anthropic (Claude):</strong> the game master is Claude, an AI by Anthropic. What is written in play,
          the adventure's text and the campaign's story are sent to Anthropic for the game master to answer, to
          translate what you write, and to read the books turned into adventures.
        </li>
        {services?.replicate && (
          <li>
            <strong>Replicate:</strong> paid pictures (portraits, scenes, banners) are painted by Replicate from a
            description of what to paint.
          </li>
        )}
        {services?.google && (
          <li>
            <strong>Google:</strong> when you sign in with Google, Google sees that you signed in to Delve.
          </li>
        )}
        {services?.backups && (
          <li>
            <strong>Backups:</strong> copies of Delve's data are kept in the operator's own cloud storage account, to
            restore Delve if its computer fails.
          </li>
        )}
        <li>
          <strong>The connection:</strong> over the internet, the connection to Delve passes through a tunnel service
          (Cloudflare) that forwards it to the operator's computer.
        </li>
      </ul>
      <p>Nothing is sold, and nothing is used for advertising.</p>

      <h2>Cookies and your browser</h2>
      <p>
        Delve uses only the cookies it needs: one that keeps you logged in, one that recognises your browser so a
        wrong password elsewhere can't lock you out, one that lasts ten minutes while you sign in with Google, and one
        for a seat at a table you joined by its link. Your browser also remembers settings such as the look you chose.
        There is no tracking and no analytics.
      </p>

      <h2>How long</h2>
      <p>
        Your account and what you played stay until you ask for them to be deleted, or the operator deletes them. A
        login ends 30 days after it was last used. Backup copies, if any, are replaced over time.
      </p>

      <h2>Your rights</h2>
      <p>
        You may ask the operator to see what Delve keeps about you, to correct it, or to delete your account and what
        you wrote. Write to <Operator legal={legal.data} />. If you think your data is mishandled, you may also turn to
        the data protection authority where you live.
      </p>

      <h2>Children</h2>
      <p>Delve isn't meant for children under 16 without a parent's or guardian's permission.</p>

      <h2>Changes</h2>
      <p>When this policy changes, this page changes, with its date.</p>
    </Page>
  );
}

export function Terms() {
  const legal = useQuery({ queryKey: legalKey, queryFn: getLegal });
  return (
    <Page title="Terms of service">
      <p>
        This Delve is a private installation of Delve, a tabletop role-playing game played in the browser with an AI
        game master, run by <Operator legal={legal.data} />. By using it you agree to these terms.
      </p>

      <h2>Your account</h2>
      <ul>
        <li>An account is for one person. Keep your password to yourself; you answer for what is done with it.</li>
        <li>
          Accounts are let in by the operator or an organiser, who may turn a request away, and may disable an account
          that breaks these terms.
        </li>
      </ul>

      <h2>At the table</h2>
      <ul>
        <li>Be decent to the people you play with. No harassment, threats or hateful content.</li>
        <li>Don't post anything unlawful, or anything you have no right to share.</li>
        <li>Don't try to get into what isn't yours, or to overload or break Delve.</li>
      </ul>

      <h2>What you write</h2>
      <p>
        What you write stays yours. You let the operator keep it and process it to run your games, which includes
        sending it to the services named in the <a href="/privacy">privacy policy</a>.
      </p>

      <h2>The game master is an AI</h2>
      <p>
        The story, the rules calls and the pictures are made by AI. They can be wrong, odd or not to your taste, and
        they are no advice of any kind.
      </p>

      <h2>Adventures and books</h2>
      <p>
        Published adventures and settings belong to their authors and publishers. Books turned into adventures are for
        the games played here; don't copy them out of Delve.
      </p>

      <h2>No guarantees</h2>
      <p>
        Delve is offered free and as it is, by a private person. It may change, be down, or stop, and data may be lost.
        As far as the law allows, the operator isn't liable for any damage from using it.
      </p>

      <h2>Ending</h2>
      <p>
        You may stop at any time and ask for your account to be deleted. The operator may end an account, or Delve
        itself.
      </p>

      <h2>Changes and contact</h2>
      <p>
        When these terms change, this page changes, with its date. Questions go to <Operator legal={legal.data} />.
      </p>
    </Page>
  );
}
