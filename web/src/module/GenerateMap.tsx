import * as Dialog from "@radix-ui/react-dialog";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { NeedsToken, queryKeys, runningConversionOf, type Conversion } from "../api";
import { useT } from "../i18n";
import ConversionProgress from "./ConversionProgress";
import MapDrafts from "./MapDrafts";
import { startMapDraft } from "./mapDrafts";
import styles from "./MapDrafts.module.css";

/**
 * "Generate a map": a dialog with a description (and a name, if wanted), then the drawing's progress, then the drafts
 * side by side, with Keep and Discard. Each Draw it starts another draft, so several can be compared before one is
 * kept. Nothing is saved in the module until then.
 */
export default function GenerateMap({ moduleId }: { moduleId: string }) {
  const t = useT();
  const [open, setOpen] = useState(false);
  return (
    <Dialog.Root open={open} onOpenChange={setOpen}>
      <Dialog.Trigger asChild>
        <button type="button">{t("mapDrafts.generate")}</button>
      </Dialog.Trigger>
      <Dialog.Portal>
        <Dialog.Overlay className="dialog-overlay" />
        <Dialog.Content className={`dialog ${styles.dialog}`}>
          <Dialog.Title className="dialog-title">{t("mapDrafts.title")}</Dialog.Title>
          <Dialog.Description className="dialog-body">{t("mapDrafts.lede")}</Dialog.Description>
          <DescribeForm moduleId={moduleId} />
          <MapDrafts moduleId={moduleId} empty />
          <div className="dialog-actions">
            <Dialog.Close asChild>
              <button type="button">{t("mapDrafts.close")}</button>
            </Dialog.Close>
          </div>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}

function DescribeForm({ moduleId }: { moduleId: string }) {
  const t = useT();
  const client = useQueryClient();
  const [description, setDescription] = useState("");
  const [name, setName] = useState("");
  const [started, setStarted] = useState<Conversion | null>(null);
  const start = useMutation({
    mutationFn: () => startMapDraft(moduleId, description.trim(), name.trim() || undefined),
    onSuccess: (conversion) => {
      setStarted(conversion);
      client.invalidateQueries({ queryKey: queryKeys.conversions });
    },
    onError: (error) => {
      const running = runningConversionOf(error);
      if (running) setStarted(running);
    },
  });

  return (
    <>
      <form
        onSubmit={(e) => {
          e.preventDefault();
          start.mutate();
        }}
      >
        <div className="field">
          <label htmlFor="map-draft-description">{t("mapDrafts.description")}</label>
          <textarea
            id="map-draft-description"
            value={description}
            placeholder={t("mapDrafts.descriptionHint")}
            onChange={(e) => setDescription(e.target.value)}
          />
        </div>
        <div className="field">
          <label htmlFor="map-draft-name">{t("mapDrafts.name")}</label>
          <input id="map-draft-name" value={name} onChange={(e) => setName(e.target.value)} />
        </div>
        <div className="actions">
          <button type="submit" className="primary" disabled={start.isPending || !description.trim()}>
            {t("mapDrafts.start")}
          </button>
        </div>
      </form>
      {start.error && !(start.error instanceof NeedsToken) && !runningConversionOf(start.error) && (
        <p role="alert" className="notice error">
          {t("mapDrafts.startFailed", { error: start.error.message })}
        </p>
      )}
      {started && <ConversionProgress key={started.id} conversion={started} />}
    </>
  );
}
