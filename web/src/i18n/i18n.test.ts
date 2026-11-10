import { describe, expect, it } from "vitest";
import { LANGUAGES } from "./index";
import de from "./de.json";
import en from "./en.json";
import fr from "./fr.json";
import lv from "./lv.json";
import nl from "./nl.json";

// Each language's file as it is, whether or not the app has fetched it (DEL-240).
const dictionaries: Record<string, Record<string, string>> = { en, nl, fr, de, lv };

const placeholders = (text: string) => [...text.matchAll(/\{(\w+)\}/g)].map((m) => m[1]).sort();

describe("dictionaries", () => {
  it("has a dictionary per language, each with every key en has (DEL-122)", () => {
    for (const language of LANGUAGES) expect(Object.keys(dictionaries[language]).sort(), language).toEqual(Object.keys(en).sort());
  });

  it("keeps each string's placeholders in every language", () => {
    for (const language of LANGUAGES)
      for (const [key, text] of Object.entries(en))
        expect(placeholders(dictionaries[language][key] ?? ""), `${language} ${key}`).toEqual(placeholders(text));
  });

  it("has no empty strings", () => {
    for (const dict of Object.values(dictionaries)) {
      for (const [key, value] of Object.entries(dict)) {
        expect(value, key).not.toBe("");
      }
    }
  });

  it("uses the glossary's words", () => {
    // DM, never GM (nor MD or MJ in French); beat, never round or turn for a go of the table.
    for (const dict of Object.values(dictionaries)) {
      for (const value of Object.values(dict)) {
        expect(value).not.toMatch(/\bGM\b|\bSL\b|\bMD\b|\bMJ\b/);
      }
    }
  });
});
