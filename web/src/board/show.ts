// How the board's pages name what they show (DEL-297): an author, a zone's levels, a post's time. Posts are never
// translated; only these words around them are.
import type { Translate } from "../i18n";
import type { Author, Zone } from "./api";

/** The author's name: "Owner" for the owner by token (no account), "A former member" for an account that is gone. */
export function authorName(t: Translate, author: Author): string {
  if (author.account_id === null) return t("board.owner");
  return author.display_name || t("board.formerMember");
}

/** Who reads and who posts in the zone, said once: "Members only" where they are the same people, else "Anyone can
 * read, accounts post". */
export function levelsLabel(t: Translate, zone: Pick<Zone, "read" | "write">): string {
  if (zone.read === zone.write && zone.read !== "everybody") return t(`board.only.${zone.read}`);
  const said = `${t(`board.read.${zone.read}`)}, ${t(`board.write.${zone.write}`)}`;
  return said.charAt(0).toUpperCase() + said.slice(1);
}

/** A post's time, as a date and the time of day: "28 Oct, 20:14", with the year when it isn't this year's. */
export function postTime(iso: string, language: string, now: Date = new Date()): string {
  const at = new Date(iso);
  const year = at.getFullYear() === now.getFullYear() ? undefined : "numeric";
  return new Intl.DateTimeFormat(language, { day: "numeric", month: "short", year, hour: "2-digit", minute: "2-digit" }).format(at);
}

/** What went wrong, in the server's words. */
export function sayError(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
}
