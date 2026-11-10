import { useParams, useSearchParams } from "react-router-dom";
import "@fontsource/im-fell-english/400.css";
import { I18nProvider, isLanguage, useT, type MessageKey } from "../i18n";
import { AUDIENCES, TOPICS, inLanguage, topic, topicHtml, useTopicLanguage, type Audience, type Topic } from "./topics";
import "./help.css";

// The help pages (DEL-145), at /help and /help/:slug, public and outside the app as /privacy is: every topic, for
// newcomers, players, organisers and owners alike. They speak `?lang=` when it names a language (the panel's link to
// a page passes the reader's), the browser's otherwise (DEL-284).

export const AUDIENCE_TITLES: Record<Audience, MessageKey> = {
  newcomer: "help.audience.newcomer",
  player: "help.audience.player",
  organiser: "help.audience.organiser",
  owner: "help.audience.owner",
};

const AUDIENCE_LEDES: Record<Audience, MessageKey> = {
  newcomer: "help.audience.newcomer.lede",
  player: "help.audience.player.lede",
  organiser: "help.audience.organiser.lede",
  owner: "help.audience.owner.lede",
};

function pageLanguage(asked: string | null): string {
  if (isLanguage(asked)) return asked;
  return (typeof navigator !== "undefined" ? navigator.language : "en").slice(0, 2).toLowerCase();
}

function Frame({ children }: { children: React.ReactNode }) {
  const [search] = useSearchParams();
  return (
    <I18nProvider language={pageLanguage(search.get("lang"))}>
      <FrameIn>{children}</FrameIn>
    </I18nProvider>
  );
}

function FrameIn({ children }: { children: React.ReactNode }) {
  const t = useT();
  return (
    <div className="help">
      <header className="help-head">
        <a className="help-home" href="/">
          Delve
        </a>
        <a className="help-index-link" href="/help">
          {t("landing.help")}
        </a>
      </header>
      {children}
      <footer className="help-foot">
        <a href="/">Delve</a>
        <a href="/board">{t("board.title")}</a>
        <a href="/privacy">{t("legal.privacy")}</a>
        <a href="/terms">{t("legal.terms")}</a>
      </footer>
    </div>
  );
}

/** `/help`: every topic, by audience. */
export function HelpIndex() {
  return (
    <Frame>
      <Index />
    </Frame>
  );
}

function Index() {
  const t = useT();
  const language = useTopicLanguage();
  return (
    <main className="help-main">
      <h1>{t("landing.help")}</h1>
      <p className="help-lede">{t("help.lede")}</p>
      {AUDIENCES.map((audience) => (
        <section key={audience} className="help-audience" aria-labelledby={`help-${audience}`}>
          <h2 id={`help-${audience}`}>{t(AUDIENCE_TITLES[audience])}</h2>
          <p className="help-audience-lede">{t(AUDIENCE_LEDES[audience])}</p>
          <ul className="help-topic-list">
            {TOPICS.filter((each) => each.audience === audience)
              .map((each) => inLanguage(each, language))
              .map((each) => (
                <li key={each.slug}>
                  <a href={`/help/${each.slug}`}>{each.title}</a>
                  {each.summary && <span>{each.summary}</span>}
                </li>
              ))}
          </ul>
        </section>
      ))}
    </main>
  );
}

/** `/help/:slug`: one topic, with the topics it leads on to. */
export function HelpTopicPage() {
  return (
    <Frame>
      <TopicPage />
    </Frame>
  );
}

function TopicPage() {
  const t = useT();
  const { slug } = useParams();
  const language = useTopicLanguage();
  const found = topic(slug);
  if (!found) {
    return (
      <main className="help-main">
        <h1>{t("help.noSuchTopic")}</h1>
        <p>
          <a href="/help">{t("help.everyTopic")}</a>
        </p>
      </main>
    );
  }
  return (
    <main className="help-main help-topic">
      <p className="help-audience-name">{t(AUDIENCE_TITLES[found.audience])}</p>
      <TopicBody topic={inLanguage(found, language)} heading={1} />
      <Related topic={found} />
    </main>
  );
}

/** A topic's title and text; `heading` is its title's level (the page's h1, the panel's h2). */
export function TopicBody({ topic: shown, heading }: { topic: Topic; heading: 1 | 2 }) {
  const Title = heading === 1 ? "h1" : "h2";
  return (
    <article className="help-article">
      <Title>{shown.title}</Title>
      {/* The topic files are Delve's own, bundled with the app: their HTML is trusted. */}
      <div className="help-text" dangerouslySetInnerHTML={{ __html: topicHtml(shown.body) }} />
    </article>
  );
}

/** The topics `shown` leads on to: links to their pages, or, given `onOpen` (the panel), buttons reading one there. */
export function Related({ topic: shown, onOpen }: { topic: Topic; onOpen?: (slug: string) => void }) {
  const t = useT();
  const language = useTopicLanguage();
  const related = shown.related
    .map((slug) => topic(slug))
    .filter((each): each is Topic => Boolean(each))
    .map((each) => inLanguage(each, language));
  if (related.length === 0) return null;
  const Heading = onOpen ? "h3" : "h2";
  return (
    <nav className="help-related" aria-label={t("help.readNext")}>
      <Heading>{t("help.readNext")}</Heading>
      <ul>
        {related.map((each) => (
          <li key={each.slug}>
            {onOpen ? (
              <button type="button" onClick={() => onOpen(each.slug)}>
                {each.title}
              </button>
            ) : (
              <a href={`/help/${each.slug}`}>{each.title}</a>
            )}
          </li>
        ))}
      </ul>
    </nav>
  );
}
