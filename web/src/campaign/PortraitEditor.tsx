import * as Dialog from "@radix-ui/react-dialog";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useRef, useState } from "react";
import { generate } from "portraitgen";
import { ApiError, editPortrait, queryKeys, type Character } from "../api";
import { DEFAULT_PORTRAIT_STYLE, usePortraitStyle } from "../components/portraitStyle";
import { useT } from "../i18n";

/** portraitgen's own editor, vendored unchanged (web/vendor/portraitgen/README.md) and built as a page of its own. */
export const EDITOR_URL = "/vendor/portraitgen/web/index.html";

type Traits = Record<string, unknown>;
export type Editable = Pick<Character, "id" | "campaign_id" | "name" | "sheet" | "portrait_painting">;

/** The editor's link for a portrait (its `encodeTraits`): the traits' JSON, UTF-8, in base64. */
export function encodeTraits(traits: Traits): string {
  const bytes = new TextEncoder().encode(JSON.stringify(traits));
  return btoa(Array.from(bytes, (b) => String.fromCharCode(b)).join(""));
}

/** The traits a link of the editor's holds, or null for anything else. */
export function decodeTraits(hash: string): Traits | null {
  try {
    const bytes = Uint8Array.from(atob(hash.replace(/^#/, "")), (c) => c.charCodeAt(0));
    const traits: unknown = JSON.parse(new TextDecoder().decode(bytes));
    return traits && typeof traits === "object" && !Array.isArray(traits) ? (traits as Traits) : null;
  } catch {
    return null;
  }
}

/**
 * What the editor opens on: an edited portrait's own traits, else the face Delve draws now, from the portrait's
 * description and seed (or the sheet's race and class, seeded by the character's id, for a painted one), in the
 * campaign's style, so the editor starts on the face the sheet shows.
 */
export function startingTraits(character: Editable, style: string): Traits {
  const portrait = character.sheet.portrait;
  if (portrait?.kind === "traits" && portrait.traits) return portrait.traits;
  const { gender, race, cls } = character.sheet;
  const words = [gender, race, cls].map((w) => w.trim().toLowerCase()).filter(Boolean).join(" ");
  const describe = portrait?.kind === "traits" ? portrait.describe : words ? `a ${words}` : "an adventurer";
  const seed = portrait?.kind === "traits" ? portrait.seed : character.id;
  const traits = generate({ describe, seed });
  return style === DEFAULT_PORTRAIT_STYLE ? traits : { ...traits, style };
}

/**
 * The sheet's Edit portrait (DEL-238), in place of Repaint portrait while Preferences draw PCs' portraits with
 * portraitgen: portraitgen's own editor in a dialog, opened on the portrait the sheet shows. The editor keeps the
 * portrait it shows in its address, so Save reads it from there and saves it; Cancel, Escape or a click outside
 * leaves the portrait as it was. A refusal is the server's own words.
 */
export function EditPortraitLink({ character }: { character: Editable }) {
  const t = useT();
  const [open, setOpen] = useState(false);
  if (character.portrait_painting) return null;
  return (
    <div className="portrait-repaint">
      <button
        type="button"
        className="link-button"
        aria-label={t("portraits.editOf", { name: character.name })}
        onClick={() => setOpen(true)}
      >
        {t("portraits.edit")}
      </button>
      {open && <PortraitEditor character={character} onClose={() => setOpen(false)} />}
    </div>
  );
}

function PortraitEditor({ character, onClose }: { character: Editable; onClose: () => void }) {
  const t = useT();
  const client = useQueryClient();
  const style = usePortraitStyle(false);
  // The editor opens once, on the portrait as it was when the dialog opened.
  const [src] = useState(() => `${EDITOR_URL}#${encodeTraits(startingTraits(character, style))}`);
  const frame = useRef<HTMLIFrameElement>(null);
  const [loaded, setLoaded] = useState(false);
  const save = useMutation({
    mutationFn: () => {
      const traits = decodeTraits(frame.current?.contentWindow?.location.hash ?? "");
      if (!traits) throw new Error(t("portraits.editRefused"));
      return editPortrait(character.campaign_id, character.id, traits);
    },
    onSuccess: () => {
      client.invalidateQueries({ queryKey: queryKeys.characters(character.campaign_id) });
      onClose();
    },
  });
  const refused =
    save.error instanceof ApiError
      ? [save.error.body.error, save.error.body.hint].filter((s) => typeof s === "string" && s).join(" ")
      : save.error?.message;
  return (
    <Dialog.Root open onOpenChange={(isOpen) => isOpen || onClose()}>
      <Dialog.Portal>
        <Dialog.Overlay className="dialog-overlay" />
        <Dialog.Content className="dialog portrait-editor" aria-describedby={undefined}>
          <Dialog.Title className="dialog-title">{t("portraits.editorTitle", { name: character.name })}</Dialog.Title>
          <iframe
            ref={frame}
            className="portrait-editor-frame"
            src={src}
            title={t("portraits.editorTitle", { name: character.name })}
            onLoad={() => setLoaded(true)}
          />
          {save.isError && (
            <p className="notice error" role="alert">
              {refused || t("portraits.editRefused")}
            </p>
          )}
          <div className="dialog-actions">
            <Dialog.Close asChild>
              <button type="button">{t("dialog.cancel")}</button>
            </Dialog.Close>
            <button type="button" className="primary" disabled={!loaded || save.isPending} onClick={() => save.mutate()}>
              {t("portraits.save")}
            </button>
          </div>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}
