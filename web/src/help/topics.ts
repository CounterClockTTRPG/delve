import MarkdownIt from "markdown-it";
import { useEffect, useState } from "react";
import { matchPath } from "react-router-dom";
import { useLanguage, type Language } from "../i18n";

// The help topics (DEL-145): Markdown files in ./topics, bundled with the app, each with a header naming its title,
// audience (newcomer, player, organiser or owner), a one-line summary, the screens it is about (router paths, such as
// /play/:campaignId), its order in its audience's list and the topics it leads on to. They are Delve's own text, so
// their Markdown may hold HTML (a figure with its caption); pictures live in /help/*.webp. A topic's translation
// (DEL-284) is ./topics/<language>/<slug>.md, whose header holds only its title and summary: the rest is the English
// topic's. A topic not yet translated is shown in English.

// Newcomers come first: the basics of a roleplaying game (DEL-282), shown to every reader.
export type Audience = "newcomer" | "player" | "organiser" | "owner";
export const AUDIENCES: readonly Audience[] = ["newcomer", "player", "organiser", "owner"];

export interface Topic {
  slug: string;
  title: string;
  audience: Audience;
  summary: string;
  screens: string[];
  order: number;
  related: string[];
  body: string;
}

const files = import.meta.glob("./topics/*.md", {
  query: "?raw",
  import: "default",
  eager: true,
}) as Record<string, string>;

/** A topic file's `---` header (`key: value` lines) and its Markdown. */
function splitTopic(slug: string, text: string): { header: Record<string, string>; body: string } {
  const match = /^---\n([\s\S]*?)\n---\n?([\s\S]*)$/.exec(text.replace(/\r\n/g, "\n"));
  if (!match) throw new Error(`help topic ${slug} has no --- header`);
  const header: Record<string, string> = {};
  for (const line of match[1].split("\n")) {
    const at = line.indexOf(":");
    if (at > 0) header[line.slice(0, at).trim()] = line.slice(at + 1).trim();
  }
  return { header, body: match[2].trim() };
}

/** A topic file: its `---` header (lists are comma-separated), then its Markdown. */
export function parseTopic(slug: string, text: string): Topic {
  const { header, body } = splitTopic(slug, text);
  const list = (value: string | undefined) =>
    value
      ? value
          .split(",")
          .map((item) => item.trim())
          .filter(Boolean)
      : [];
  const audience = header.audience as Audience;
  if (!header.title || !AUDIENCES.includes(audience))
    throw new Error(`help topic ${slug} needs a title and an audience`);
  return {
    slug,
    title: header.title,
    audience,
    summary: header.summary ?? "",
    screens: list(header.screens),
    order: Number(header.order ?? 100),
    related: list(header.related),
    body,
  };
}

/** A topic's words in another language. */
export interface Translation {
  title: string;
  summary: string;
  body: string;
}

/** A translated topic file: a header with its title and summary, then its Markdown. */
export function parseTranslation(slug: string, text: string): Translation {
  const { header, body } = splitTopic(slug, text);
  if (!header.title) throw new Error(`help topic ${slug}'s translation needs a title`);
  return { title: header.title, summary: header.summary ?? "", body };
}

export const TOPICS: Topic[] = Object.entries(files)
  .map(([path, text]) => parseTopic(path.replace(/^.*\/(.+)\.md$/, "$1"), text))
  .sort(
    (a, b) =>
      AUDIENCES.indexOf(a.audience) - AUDIENCES.indexOf(b.audience) ||
      a.order - b.order ||
      a.title.localeCompare(b.title),
  );

export function topic(slug: string | undefined): Topic | undefined {
  return TOPICS.find((t) => t.slug === slug);
}

// Each language's topics are a chunk of their own, fetched when a reader speaks it, as its dictionary is.
const TRANSLATIONS: Record<Exclude<Language, "en">, () => Promise<{ default: Record<string, string> }>> = {
  nl: () => import("./translations/nl"),
  fr: () => import("./translations/fr"),
  de: () => import("./translations/de"),
  lv: () => import("./translations/lv"),
};

const translated: Partial<Record<Language, Map<string, Translation>>> = {
  en: new Map(),
};
const translating: Partial<Record<Language, Promise<void>>> = {};

/** Fetches `language`'s topics, once however often it is asked. */
export function loadTopics(language: Language): Promise<void> {
  if (translated[language]) return Promise.resolve();
  translating[language] ??= TRANSLATIONS[language as Exclude<Language, "en">]()
    .then((module) => {
      translated[language] = new Map(
        Object.entries(module.default).map(([path, text]) => {
          const slug = path.replace(/^.*\/(.+)\.md$/, "$1");
          return [slug, parseTranslation(slug, text)];
        }),
      );
    })
    .finally(() => delete translating[language]);
  return translating[language];
}

/** `shown` in `language` when its translation is here, in English otherwise. */
export function inLanguage(shown: Topic, language: Language): Topic {
  const words = translated[language]?.get(shown.slug);
  return words ? { ...shown, ...words } : shown;
}

/** The reader's language once its topics are here (English until then): what `inLanguage` is given. */
export function useTopicLanguage(): Language {
  const language = useLanguage();
  const [, setLoaded] = useState(0);
  useEffect(() => {
    if (translated[language]) return;
    let current = true;
    loadTopics(language)
      .then(() => current && setLoaded((n) => n + 1))
      // Offline or a stale build: the topics stay in English.
      .catch(() => {});
    return () => {
      current = false;
    };
  }, [language]);
  return translated[language] ? language : "en";
}

/** The audiences a reader is shown in the app's panel: a player's own and the newcomer's; an organiser's and those;
 * all, for the owner. The help pages show every topic to anyone. */
export function audiencesOf(role: Audience): Audience[] {
  return AUDIENCES.slice(0, AUDIENCES.indexOf(role) + 1);
}

/** The topics about the screen at `pathname`, for `role`: the panel's list, the reader's own audience first. */
export function topicsFor(pathname: string, role: Audience, topics: Topic[] = TOPICS): Topic[] {
  const shown = audiencesOf(role);
  return topics
    .filter(
      (t) => shown.includes(t.audience) && t.screens.some((screen) => matchPath({ path: screen, end: true }, pathname)),
    )
    .sort((a, b) => (a.audience === role ? 0 : 1) - (b.audience === role ? 0 : 1) || a.order - b.order);
}

const md = new MarkdownIt({ html: true, linkify: false, typographer: true });

/** A topic's Markdown as HTML: Delve's own text, so its HTML is kept; a link to another topic stays a plain path. */
export function topicHtml(body: string): string {
  return md.render(body);
}
