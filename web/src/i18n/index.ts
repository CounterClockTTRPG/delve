// Interface strings. Every user-visible string comes from these dictionaries;
// every language has every key en has (i18n.test.ts checks). The server's list is delve.domain.settings.LANGUAGES.
import { createContext, createElement, useCallback, useContext, useEffect, useState, type ReactNode } from "react";
import en from "./en.json";

export type MessageKey = keyof typeof en;
export type Translate = (key: MessageKey | string, vars?: Record<string, string>) => string;

/** The interface's languages, in the order the language menus list them (DEL-122). */
export const LANGUAGES = ["en", "nl", "fr", "de", "lv"] as const;
export type Language = (typeof LANGUAGES)[number];

type Dictionary = Record<string, string>;

// English is in the main bundle: it is the fallback for every key. The others are chunks of their own, fetched when a
// reader speaks one, so nobody downloads the four they don't read (DEL-240: about 600 kB of the main chunk).
const LOADERS: Record<Exclude<Language, "en">, () => Promise<{ default: Dictionary }>> = {
  nl: () => import("./nl.json"),
  fr: () => import("./fr.json"),
  de: () => import("./de.json"),
  lv: () => import("./lv.json"),
};

/** The dictionaries loaded so far: English always, another language once `loadLanguage` has fetched it. */
const loaded: Partial<Record<Language, Dictionary>> = { en };
const loading: Partial<Record<Language, Promise<void>>> = {};

export function isLanguage(value: unknown): value is Language {
  return (LANGUAGES as readonly unknown[]).includes(value);
}

/** Whether `language`'s dictionary is here, so `translate` speaks it. */
export function hasLanguage(language: Language): boolean {
  return loaded[language] !== undefined;
}

/** A dictionary given outright: the tests' (vitest.setup.ts), which then need no fetch. */
export function addDictionary(language: Language, dictionary: Dictionary): void {
  loaded[language] = dictionary;
}

/** Fetches `language`'s dictionary, once however often it is asked. A failed fetch is asked again next time. */
export function loadLanguage(language: Language): Promise<void> {
  if (hasLanguage(language)) return Promise.resolve();
  const load = LOADERS[language as Exclude<Language, "en">];
  loading[language] ??= load()
    .then((module) => addDictionary(language, module.default))
    .finally(() => delete loading[language]);
  return loading[language];
}

/** Looks a key up in `language` (when it is loaded), then in English; an unknown key comes back as itself. */
export function translate(language: Language, key: string, vars?: Record<string, string>): string {
  const text = loaded[language]?.[key] ?? en[key as MessageKey] ?? key;
  return vars ? text.replace(/\{(\w+)\}/g, (m, name: string) => vars[name] ?? m) : text;
}

const LanguageContext = createContext<Language>("en");

/** The language its children speak. The page's `<html lang>` follows it (DEL-174), for screen readers, hyphenation
 * and the browser's own translate offer. A language whose dictionary isn't here yet is fetched; until it is, the
 * children keep the language they spoke (English at first), so nothing unmounts and no key shows bare (DEL-240). */
export function I18nProvider({ language, children }: { language: string | undefined; children: ReactNode }) {
  const wanted = isLanguage(language) ? language : "en";
  const [spoken, setSpoken] = useState<Language>(() => (hasLanguage(wanted) ? wanted : "en"));
  const value = hasLanguage(wanted) ? wanted : spoken;
  useEffect(() => {
    if (hasLanguage(wanted)) {
      setSpoken(wanted);
      return;
    }
    let current = true;
    loadLanguage(wanted)
      .then(() => current && setSpoken(wanted))
      // Offline or a stale build: the page stays in the language it speaks; the next change of language tries again.
      .catch(() => {});
    return () => {
      current = false;
    };
  }, [wanted]);
  useEffect(() => {
    document.documentElement.lang = value;
  }, [value]);
  return createElement(LanguageContext.Provider, { value }, children);
}

export function useLanguage(): Language {
  return useContext(LanguageContext);
}

export function useT(): Translate {
  const language = useLanguage();
  return useCallback<Translate>((key, vars) => translate(language, key, vars), [language]);
}
