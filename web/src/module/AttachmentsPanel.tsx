import { useMutation } from "@tanstack/react-query";
import { FileText } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import {
  ApiError,
  NeedsToken,
  attachmentUrl,
  deleteAttachment,
  describeAttachment,
  resetCut,
  uploadAttachment,
  type Attachment,
  type Audience,
  type ModuleTextDoc,
} from "../api";
import { useConfirm } from "../components/dialogs";
import Lightbox from "../components/Lightbox";
import AudienceBar, { ChooseAll, ChooseBox, assetRef, useChosen, type Chosen } from "./AudienceBar";
import { useT, type Translate } from "../i18n";
import CropDialog, { CUTTABLE } from "./CropDialog";
import { headingKey } from "./MarkdownRoundTrip";
import { isBookPicture, startBookMap } from "./mapDrafts";

/** What can be attached (the server refuses anything else with 415). */
export const ATTACHMENT_TYPES = ["image/png", "image/jpeg", "image/webp", "image/gif", "image/svg+xml", "application/pdf"];
const EXTENSIONS: Record<string, string> = {
  "image/png": "png",
  "image/jpeg": "jpg",
  "image/webp": "webp",
  "image/gif": "gif",
  "image/svg+xml": "svg",
  "application/pdf": "pdf",
};

export interface AttachmentsPanelProps {
  moduleId: string;
  attachments: Attachment[];
  /** The module's texts: those with keyed headings are the parts a page of the book can be drawn for. */
  texts?: ModuleTextDoc[];
  /** The module's attachments after an upload, a description, a cut (a split's new pieces after the first) or a delete. */
  onChange: (attachments: Attachment[]) => void;
  /** "Insert in text": the editor places the attachment at its cursor. */
  onInsert: (attachment: Attachment) => void;
  /** Whether a text is open to insert into. */
  canInsert: boolean;
}

function refusal(t: Translate, name: string, error: unknown): string {
  if (error instanceof ApiError && error.status === 415) return t("attachments.wrongType", { name });
  if (error instanceof ApiError && error.status === 413) return t("attachments.tooLarge", { name });
  return t("attachments.refused", { name, error: error instanceof Error ? error.message : String(error) });
}

const HEADING = /^(#{1,6})\s+(.*)$/;

/** Whether the text has a keyed heading ("## 7. Dining Room"). */
function hasKeys(text: ModuleTextDoc): boolean {
  return text.markdown.split("\n").some((line) => {
    const heading = HEADING.exec(line);
    return heading !== null && headingKey(heading[1].length, heading[2]) !== null;
  });
}

/**
 * The module's attachments: a grid with each one's description and audience, and uploads of several files. A map page
 * or full-page picture of the book can be drawn as a new map, for the part chosen; the draft shows with the maps.
 */
export default function AttachmentsPanel({ moduleId, attachments, texts = [], onChange, onInsert, canInsert }: AttachmentsPanelProps) {
  const t = useT();
  const [refused, setRefused] = useState<string[]>([]);
  const parts = useMemo(() => texts.filter(hasKeys), [texts]);
  const chosen = useChosen(attachments.map((attachment) => assetRef(attachment.id)));

  const upload = useMutation({
    mutationFn: async (files: File[]) => {
      const added: Attachment[] = [];
      const failed: string[] = [];
      for (const file of files) {
        try {
          added.push(await uploadAttachment(moduleId, file));
        } catch (error) {
          if (error instanceof NeedsToken) throw error;
          failed.push(refusal(t, file.name, error));
        }
      }
      return { added, failed };
    },
    onSuccess: ({ added, failed }) => {
      setRefused(failed);
      if (added.length) onChange([...attachments, ...added]);
    },
  });

  return (
    <div className="attachments">
      <div className="upload">
        <label className="button-like" htmlFor="attachment-upload">
          {t("attachments.upload")}
        </label>
        <input
          id="attachment-upload"
          className="visually-hidden"
          type="file"
          multiple
          accept={ATTACHMENT_TYPES.join(",")}
          disabled={upload.isPending}
          onChange={(e) => {
            const files = [...(e.target.files ?? [])];
            e.target.value = "";
            if (files.length) upload.mutate(files);
          }}
        />
        <span className="hint">{t("attachments.uploadHint")}</span>
      </div>
      {refused.length > 0 && (
        <ul role="alert" className="notice error">
          {refused.map((line) => (
            <li key={line}>{line}</li>
          ))}
        </ul>
      )}
      <ChooseAll chosen={chosen} count={attachments.length} />
      <AudienceBar selected={chosen.refs} onDone={chosen.clear} moduleId={moduleId} />
      {attachments.length === 0 ? (
        <p className="placeholder">{t("attachments.none")}</p>
      ) : (
        <ul className="attachment-grid">
          {attachments.map((attachment) => (
            <AttachmentCard
              key={attachment.id}
              moduleId={moduleId}
              attachment={attachment}
              chosen={chosen}
              canInsert={canInsert}
              parts={parts}
              onInsert={() => onInsert(attachment)}
              onChanged={(next) => onChange(attachments.map((a) => (a.id === next.id ? next : a)))}
              onCut={(pieces) => onChange(attachments.flatMap((a) => (a.id === attachment.id ? pieces : [a])))}
              onDeleted={() => onChange(attachments.filter((a) => a.id !== attachment.id))}
            />
          ))}
        </ul>
      )}
    </div>
  );
}

function AttachmentCard({
  moduleId,
  attachment,
  chosen,
  canInsert,
  parts,
  onInsert,
  onChanged,
  onCut,
  onDeleted,
}: {
  moduleId: string;
  attachment: Attachment;
  chosen: Chosen;
  canInsert: boolean;
  parts: ModuleTextDoc[];
  onInsert: () => void;
  onChanged: (attachment: Attachment) => void;
  /** After a cut: the pieces, the first being this attachment. */
  onCut: (pieces: Attachment[]) => void;
  onDeleted: () => void;
}) {
  const t = useT();
  const confirm = useConfirm();
  const { id } = attachment;
  const [description, setDescription] = useState(attachment.description);
  useEffect(() => setDescription(attachment.description), [attachment.description]);
  const describe = useMutation({
    mutationFn: (patch: { description?: string; audience?: Audience; reviewed?: boolean }) =>
      describeAttachment(moduleId, id, patch),
    onSuccess: onChanged,
  });
  const reset = useMutation({ mutationFn: () => resetCut(moduleId, id), onSuccess: onChanged });
  const [cropping, setCropping] = useState(false);
  const remove = useMutation({ mutationFn: () => deleteAttachment(moduleId, id), onSuccess: onDeleted });
  const [part, setPart] = useState("");
  const draw = useMutation({ mutationFn: () => startBookMap(moduleId, null, id, part || parts[0]?.id) });
  const failed = describe.error ?? remove.error ?? reset.error;
  const drawFailed = draw.error;
  const image = attachment.type.startsWith("image/");
  const url = attachmentUrl(moduleId, id, attachment.sha256);
  const cuttable = CUTTABLE.includes(attachment.cut?.original_type ?? attachment.type);

  return (
    <li className="attachment-card">
      <ChooseBox chosen={chosen} itemRef={assetRef(id)} name={id} />
      <div className="attachment-thumb">
        {image ? (
          <Lightbox
            label={t("play.enlarge", { name: id })}
            title={id}
            className="image-zoom"
            big={<img className="lightbox-image" src={url} alt={attachment.description || id} />}
          >
            <img src={url} alt={attachment.description || id} loading="lazy" />
          </Lightbox>
        ) : (
          <span className="attachment-file">
            <FileText aria-hidden size={28} />
            {`${id}.${EXTENSIONS[attachment.type] ?? "bin"}`}
          </span>
        )}
      </div>
      {attachment.cut?.proposed && (
        <p className="crop-proposed">
          <span className="badge">{t("attachments.proposedCrop")}</span>
          <button
            type="button"
            aria-label={t("attachments.looksRightOf", { id })}
            disabled={describe.isPending}
            onClick={() => describe.mutate({ reviewed: true })}
          >
            {t("attachments.looksRight")}
          </button>
        </p>
      )}
      <div className="field">
        <label htmlFor={`attachment-${id}-description`}>{t("attachments.description", { id })}</label>
        <textarea
          id={`attachment-${id}-description`}
          rows={3}
          value={description}
          placeholder={t("attachments.descriptionHint")}
          onChange={(e) => setDescription(e.target.value)}
          onBlur={() => description !== attachment.description && describe.mutate({ description })}
        />
      </div>
      <div className="field">
        <label htmlFor={`attachment-${id}-audience`}>{t("attachments.audience", { id })}</label>
        <select
          id={`attachment-${id}-audience`}
          value={attachment.audience}
          onChange={(e) => describe.mutate({ audience: e.target.value as Audience })}
        >
          <option value="gm">{t("audience.dm")}</option>
          <option value="player">{t("audience.player")}</option>
        </select>
      </div>
      {isBookPicture(attachment) && (
        <div className="actions">
          {parts.length > 0 && (
            <span className="field">
              <label htmlFor={`attachment-${id}-part`}>{t("mapDrafts.part")}</label>
              <select id={`attachment-${id}-part`} value={part || parts[0].id} onChange={(e) => setPart(e.target.value)}>
                {parts.map((text) => (
                  <option key={text.id} value={text.id}>
                    {text.title}
                  </option>
                ))}
              </select>
            </span>
          )}
          <button type="button" disabled={draw.isPending} onClick={() => draw.mutate()}>
            {t("mapDrafts.fromPage")}
          </button>
          {draw.isSuccess && <span className="row-meta">{t("mapDrafts.drawing")}</span>}
        </div>
      )}
      {drawFailed && !(drawFailed instanceof NeedsToken) && (
        <p role="alert" className="notice error">
          {t("mapDrafts.startFailed", { error: drawFailed.message })}
        </p>
      )}
      <div className="actions">
        <button type="button" disabled={!canInsert} aria-label={t("attachments.insertOf", { id })} onClick={onInsert}>
          {t("attachments.insert")}
        </button>
        {cuttable && (
          <button type="button" aria-label={t("attachments.cropOf", { id })} onClick={() => setCropping(true)}>
            {t("attachments.crop")}
          </button>
        )}
        {attachment.cut && (
          <button
            type="button"
            aria-label={t("attachments.resetCutOf", { id })}
            disabled={reset.isPending}
            onClick={() => reset.mutate()}
          >
            {t("attachments.resetCut")}
          </button>
        )}
        <button
          type="button"
          className="danger"
          aria-label={t("attachments.deleteOf", { id })}
          disabled={remove.isPending}
          onClick={async () =>
            (await confirm({ title: t("attachments.deleteConfirm", { id }), confirm: t("dialog.delete"), danger: true })) &&
            remove.mutate()
          }
        >
          {t("attachments.delete")}
        </button>
      </div>
      {failed && !(failed instanceof NeedsToken) && (
        <p role="alert" className="notice error">
          {t("attachments.changeFailed", { error: failed.message })}
        </p>
      )}
      {cropping && (
        <CropDialog
          moduleId={moduleId}
          attachment={attachment}
          onClose={() => setCropping(false)}
          onSaved={(pieces) => {
            setCropping(false);
            onCut(pieces);
          }}
        />
      )}
    </li>
  );
}
