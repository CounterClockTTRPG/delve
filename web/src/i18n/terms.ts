// The rules' words a sheet stores in English (races, classes, genders and alignments), in the reader's language
// (open fixes Task 6). Item, weapon and spell names stay as the DM or the book wrote them.
import type { Translate } from "./index";

export type TermKind = "race" | "class" | "gender" | "alignment";

/** `value` in the reader's language: "Half-Elf" is `race.halfelf`, "Lawful Good" `alignment.lawfulgood`. A term
 * the dictionaries don't have comes back as written. */
export function term(t: Translate, kind: TermKind, value: string): string {
  if (typeof value !== "string") return String(value ?? ""); // an older sheet without the field
  const key = `${kind}.${value.toLowerCase().replace(/[\s-]+/g, "")}`;
  const name = t(key);
  return name === key ? value : name;
}

/** A sheet's classes, each in the reader's language: "Fighter/Thief" is "Krijger/Dief" in Dutch. */
export function classTerms(t: Translate, cls: string): string {
  if (typeof cls !== "string") return String(cls ?? "");
  return cls
    .split("/")
    .map((c) => c.trim())
    .filter(Boolean)
    .map((c) => term(t, "class", c))
    .join("/");
}
