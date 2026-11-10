import { useMutation, useQueryClient } from "@tanstack/react-query";
import { ApiError, queryKeys, repaintPortrait, type Character } from "../api";
import { useT } from "../i18n";

/** What the repaint needs of a character: who it is, and whether its portrait is painting or failed. */
export type Repaintable = Pick<Character, "id" | "campaign_id" | "name" | "portrait_painting" | "portrait_failed">;

/**
 * The Repaint portrait request (DEL-135): it paints the portrait again with the painter Preferences choose now, and
 * the characters are read again, so the sheet shows the painting, then the new portrait. A refusal's reason is the
 * server's own words (paid images off, the day's pictures used up, NPC portraits off).
 */
export function useRepaint(character: Repaintable) {
  const client = useQueryClient();
  const repaint = useMutation({
    mutationFn: () => repaintPortrait(character.campaign_id, character.id),
    onSettled: () => client.invalidateQueries({ queryKey: queryKeys.characters(character.campaign_id) }),
  });
  const refused =
    repaint.error instanceof ApiError
      ? [repaint.error.body.error, repaint.error.body.hint].filter((s) => typeof s === "string" && s).join(" ")
      : null;
  return { repaint, refused };
}

/** The refusal line, the server's reason, or a line of our own when it gave none. */
function Refused({ refused }: { refused: string | null }) {
  const t = useT();
  return (
    <p className="notice error portrait-refused" role="alert">
      {refused || t("portraits.repaintRefused")}
    </p>
  );
}

/**
 * The sheet's: a small link under the portrait, Repaint portrait, or Try again with a line saying it failed while
 * the free portrait stands in for a failed one. Nothing while a portrait is being painted: the sheet says so.
 */
export function RepaintLink({ character }: { character: Repaintable }) {
  const t = useT();
  const { repaint, refused } = useRepaint(character);
  if (character.portrait_painting) return null;
  const failed = Boolean(character.portrait_failed);
  return (
    <div className="portrait-repaint">
      {failed && <p className="notice error">{t("portraits.failed")}</p>}
      <button
        type="button"
        className="link-button"
        disabled={repaint.isPending}
        aria-label={t(failed ? "portraits.tryAgainOf" : "portraits.repaintOf", { name: character.name })}
        onClick={() => repaint.mutate()}
      >
        {t(failed ? "portraits.tryAgain" : "portraits.repaint")}
      </button>
      {repaint.isError && <Refused refused={refused} />}
    </div>
  );
}
