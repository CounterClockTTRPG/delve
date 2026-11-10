/**
 * A kind of monster's picture (DEL-275): its face, which enlarges on a click like a character's portrait, and Paint,
 * the organisers' way to have a missing one painted, or a poor one painted again, once for every table.
 */
import * as Dialog from "@radix-ui/react-dialog";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Paintbrush } from "lucide-react";
import { useState, type ReactNode } from "react";
import { ApiError } from "../api";
import Lightbox from "../components/Lightbox";
import { useT } from "../i18n";
import { getMonsterPicture, monsterKeys, monsterPictureUrl, paintMonster } from "./api";

/** The kind's picture at `size` px (the CSS may scale it), a button that shows it large. */
export function MonsterFace({ name, slug, version, size }: { name: string; slug: string; version?: string | null; size: number }) {
  const t = useT();
  const src = monsterPictureUrl(slug, version);
  return (
    <Lightbox
      label={t("monsters.enlarge", { name })}
      title={name}
      big={<img className="portrait painted big" src={src} alt={name} />}
      className="portrait-zoom"
    >
      <img className="portrait painted" src={src} alt={name} style={{ width: size, height: size }} loading="lazy" />
    </Lightbox>
  );
}

/** What the server says of a refusal, or nothing for any other failure. */
function refusedWith(error: unknown): string | null {
  if (!(error instanceof ApiError)) return null;
  const body = error.body as { error?: unknown; detail?: unknown } | undefined;
  const said = body?.error ?? body?.detail;
  return typeof said === "string" ? said : null;
}

/**
 * Paint `name` for every table: `trigger` is the button (it gets the click), and a dialog says what painting it
 * means before it starts. `again` is Paint again, for a kind that has a picture. `campaignId` is the table that
 * asked; `onAsked` runs once the painting has started.
 */
export function PaintMonster({
  name,
  again = false,
  campaignId,
  onAsked,
  trigger,
}: {
  name: string;
  again?: boolean;
  campaignId?: string;
  onAsked?: () => void;
  trigger: (open: () => void) => ReactNode;
}) {
  const t = useT();
  const client = useQueryClient();
  const [open, setOpen] = useState(false);
  const state = useQuery({ queryKey: monsterKeys.state(name), queryFn: () => getMonsterPicture(name), enabled: open });
  const paint = useMutation({
    mutationFn: () => paintMonster(name, campaignId),
    onSuccess: () => {
      client.invalidateQueries({ queryKey: monsterKeys.all });
      onAsked?.();
      setOpen(false);
    },
  });
  const failed = paint.error ? (refusedWith(paint.error) ?? t("monsters.paintFailed")) : null;
  return (
    <>
      {trigger(() => {
        paint.reset();
        setOpen(true);
      })}
      {open && (
        <Dialog.Root open onOpenChange={(isOpen) => isOpen || setOpen(false)}>
          <Dialog.Portal>
            <Dialog.Overlay className="dialog-overlay" />
            <Dialog.Content
              className="dialog paint-monster"
              data-testid="paint-monster"
              aria-describedby="paint-monster-about"
              onClick={(e) => e.stopPropagation()}
            >
              <Dialog.Title className="dialog-title">
                {t(again ? "monsters.againTitle" : "monsters.noneTitle", { name })}
              </Dialog.Title>
              <div id="paint-monster-about" className="dialog-body">
                <p>{t(again ? "monsters.againWhy" : "monsters.noneWhy", { name })}</p>
                {state.data?.paid && <p className="hint">{t("monsters.paid")}</p>}
                <p className="hint">{t(again ? "monsters.againMeanwhile" : "monsters.noneMeanwhile")}</p>
                {state.data?.error && <p className="hint">{t("monsters.lastFailed", { error: state.data.error })}</p>}
                {failed && (
                  <p className="error" role="alert">
                    {failed}
                  </p>
                )}
              </div>
              <div className="dialog-actions">
                <Dialog.Close asChild>
                  <button type="button">{t("monsters.notNow")}</button>
                </Dialog.Close>
                <button
                  type="button"
                  className="primary"
                  data-testid="paint-monster-go"
                  disabled={paint.isPending || state.data?.painting}
                  onClick={() => paint.mutate()}
                >
                  <Paintbrush size={16} aria-hidden="true" />{" "}
                  {t(state.data?.painting ? "monsters.painting" : again ? "monsters.paintAgain" : "monsters.paint", { name })}
                </button>
              </div>
            </Dialog.Content>
          </Dialog.Portal>
        </Dialog.Root>
      )}
    </>
  );
}
