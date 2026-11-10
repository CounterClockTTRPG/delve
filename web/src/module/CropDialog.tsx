import * as Dialog from "@radix-ui/react-dialog";
import { useMutation } from "@tanstack/react-query";
import { RotateCcw, RotateCw } from "lucide-react";
import { useRef, useState, type PointerEvent as ReactPointerEvent } from "react";
import { NeedsToken, cutAttachment, originalUrl, type Attachment, type Audience, type CutBox } from "../api";
import { useT } from "../i18n";

/** The pictures that can be cut (the server refuses an SVG or a PDF with 422). */
export const CUTTABLE = ["image/png", "image/jpeg", "image/webp", "image/gif"];

/** The most pieces a picture is split into, as the server takes. */
const MOST_PIECES = 12;

interface Piece {
  box: CutBox | null;
  description: string;
  audience: Audience;
}

/** A box turned a quarter with its picture: clockwise (`1`) or anticlockwise (`-1`), so it keeps on the same part. */
export function turnBox(box: CutBox, way: 1 | -1): CutBox {
  const [x, y, w, h] = box;
  return way === 1 ? [1 - (y + h), x, h, w] : [y, 1 - (x + w), h, w];
}

const clamp = (v: number) => Math.min(1, Math.max(0, v));
const round = (v: number) => Math.round(v * 10000) / 10000;

type Drag =
  | { kind: "draw"; from: [number, number]; before: CutBox | null }
  | { kind: "move"; from: [number, number]; box: CutBox }
  | { kind: "resize"; anchor: [number, number] };

/**
 * Crop, turn or split a picture (DEL-40): its original, turned as chosen, with a box per piece over it. Drag on the
 * picture to draw the chosen piece's box, drag a box to move it, a corner to resize it. The first piece is the
 * picture itself; each other becomes a picture of its own. It opens on the picture's cut (a conversion's proposed one
 * too); Save cuts it again from the original.
 */
export default function CropDialog({
  moduleId,
  attachment,
  onClose,
  onSaved,
}: {
  moduleId: string;
  attachment: Attachment;
  onClose: () => void;
  /** The pieces, the first being the attachment itself. */
  onSaved: (pieces: Attachment[]) => void;
}) {
  const t = useT();
  const [rotate, setRotate] = useState(attachment.cut?.rotate ?? 0);
  const [pieces, setPieces] = useState<Piece[]>([
    { box: attachment.cut?.box ?? null, description: attachment.description, audience: attachment.audience },
  ]);
  const [chosen, setChosen] = useState(0);
  const [size, setSize] = useState<[number, number] | null>(null);
  const stage = useRef<HTMLDivElement>(null);
  const drag = useRef<Drag | null>(null);

  const save = useMutation({
    mutationFn: () =>
      cutAttachment(moduleId, attachment.id, {
        rotate,
        pieces: pieces.map((piece, n) =>
          n === 0 ? { box: piece.box } : { box: piece.box, description: piece.description, audience: piece.audience },
        ),
      }),
    onSuccess: ({ attachments }) => onSaved(attachments),
  });

  const setBox = (n: number, box: CutBox | null) =>
    setPieces((all) => all.map((piece, i) => (i === n ? { ...piece, box } : piece)));
  const turn = (way: 1 | -1) => {
    setRotate((r) => (r + way * 90 + 360) % 360);
    setPieces((all) => all.map((piece) => ({ ...piece, box: piece.box && turnBox(piece.box, way) })));
  };

  const at = (e: ReactPointerEvent): [number, number] => {
    const rect = stage.current!.getBoundingClientRect();
    return [clamp((e.clientX - rect.left) / rect.width), clamp((e.clientY - rect.top) / rect.height)];
  };
  const down = (e: ReactPointerEvent, start: Drag) => {
    e.preventDefault();
    e.stopPropagation();
    stage.current?.setPointerCapture?.(e.pointerId);
    drag.current = start;
  };
  const move = (e: ReactPointerEvent) => {
    const now = drag.current;
    if (!now) return;
    const [px, py] = at(e);
    if (now.kind === "move") {
      const [x, y, w, h] = now.box;
      const nx = Math.min(1 - w, Math.max(0, x + px - now.from[0]));
      const ny = Math.min(1 - h, Math.max(0, y + py - now.from[1]));
      setBox(chosen, [round(nx), round(ny), w, h]);
      return;
    }
    const [ax, ay] = now.kind === "draw" ? now.from : now.anchor;
    setBox(chosen, [round(Math.min(ax, px)), round(Math.min(ay, py)), round(Math.abs(px - ax)), round(Math.abs(py - ay))]);
  };
  const up = () => {
    const ended = drag.current;
    drag.current = null;
    // A box drawn by a slip of the pointer is no box: the piece keeps the one it had (never "the whole picture").
    if (ended?.kind !== "draw") return;
    setPieces((all) =>
      all.map((piece, n) =>
        n === chosen && piece.box && (piece.box[2] < 0.01 || piece.box[3] < 0.01) ? { ...piece, box: ended.before } : piece,
      ),
    );
  };

  // The stage is the turned picture: its boxes are fractions of it, as the server's are.
  const sideways = rotate % 180 !== 0;
  const [width, height] = size ?? [4, 3];
  const ratio = sideways ? height / width : width / height;
  const imageStyle = sideways
    ? { width: `${(1 / ratio) * 100}%`, height: `${ratio * 100}%` }
    : { width: "100%", height: "100%" };
  const failed = save.error;

  return (
    <Dialog.Root open onOpenChange={(open) => !open && onClose()}>
      <Dialog.Portal>
        <Dialog.Overlay className="dialog-overlay" />
        <Dialog.Content className="dialog crop-dialog" aria-describedby={undefined}>
          <Dialog.Title className="dialog-title">{t("crop.title", { id: attachment.id })}</Dialog.Title>
          <p className="hint">{t("crop.hint")}</p>
          <div className="crop-tools">
            <button type="button" onClick={() => turn(-1)}>
              <RotateCcw aria-hidden size={16} /> {t("crop.turnLeft")}
            </button>
            <button type="button" onClick={() => turn(1)}>
              <RotateCw aria-hidden size={16} /> {t("crop.turnRight")}
            </button>
            <button type="button" disabled={pieces[chosen].box === null} onClick={() => setBox(chosen, null)}>
              {t("crop.whole")}
            </button>
          </div>
          <div
            ref={stage}
            className="crop-stage"
            style={{ aspectRatio: `${ratio}`, width: `min(100%, calc(50vh * ${ratio}))` }}
            data-testid="crop-stage"
            onPointerDown={(e) => down(e, { kind: "draw", from: at(e), before: pieces[chosen].box })}
            onPointerMove={move}
            onPointerUp={up}
            onPointerCancel={up}
          >
            <img
              src={originalUrl(moduleId, attachment.id)}
              alt={attachment.description || attachment.id}
              draggable={false}
              style={{ ...imageStyle, transform: `translate(-50%, -50%) rotate(${rotate}deg)` }}
              onLoad={(e) => setSize([e.currentTarget.naturalWidth || 4, e.currentTarget.naturalHeight || 3])}
            />
            {pieces.map(
              (piece, n) =>
                piece.box && (
                  <div
                    key={n}
                    className="crop-box"
                    data-chosen={n === chosen || undefined}
                    data-testid={`crop-box-${n + 1}`}
                    style={{
                      left: `${piece.box[0] * 100}%`,
                      top: `${piece.box[1] * 100}%`,
                      width: `${piece.box[2] * 100}%`,
                      height: `${piece.box[3] * 100}%`,
                    }}
                    onPointerDown={(e) => {
                      setChosen(n);
                      down(e, { kind: "move", from: at(e), box: piece.box! });
                    }}
                  >
                    <span className="crop-label">{n + 1}</span>
                    {n === chosen &&
                      ([0, 1] as const).flatMap((cx) =>
                        ([0, 1] as const).map((cy) => (
                          <span
                            key={`${cx}${cy}`}
                            className="crop-corner"
                            data-x={cx}
                            data-y={cy}
                            onPointerDown={(e) => {
                              const [x, y, w, h] = piece.box!;
                              down(e, { kind: "resize", anchor: [cx ? x : x + w, cy ? y : y + h] });
                            }}
                          />
                        )),
                      )}
                  </div>
                ),
            )}
          </div>
          <ol className="crop-pieces">
            {pieces.map((piece, n) => (
              <li key={n} data-chosen={n === chosen || undefined}>
                <button type="button" aria-pressed={n === chosen} onClick={() => setChosen(n)}>
                  {t("crop.piece", { n: String(n + 1) })}
                  {piece.box === null && ` · ${t("crop.wholeShort")}`}
                </button>
                {n > 0 && (
                  <>
                    <span className="field">
                      <label htmlFor={`crop-piece-${n + 1}-description`}>{t("crop.pieceDescription", { n: String(n + 1) })}</label>
                      <textarea
                        id={`crop-piece-${n + 1}-description`}
                        rows={2}
                        value={piece.description}
                        onChange={(e) =>
                          setPieces((all) => all.map((p, i) => (i === n ? { ...p, description: e.target.value } : p)))
                        }
                      />
                    </span>
                    <span className="field">
                      <label htmlFor={`crop-piece-${n + 1}-audience`}>{t("crop.pieceAudience", { n: String(n + 1) })}</label>
                      <select
                        id={`crop-piece-${n + 1}-audience`}
                        value={piece.audience}
                        onChange={(e) =>
                          setPieces((all) => all.map((p, i) => (i === n ? { ...p, audience: e.target.value as Audience } : p)))
                        }
                      >
                        <option value="gm">{t("audience.dm")}</option>
                        <option value="player">{t("audience.player")}</option>
                      </select>
                    </span>
                    <button
                      type="button"
                      className="danger"
                      onClick={() => {
                        setPieces((all) => all.filter((_, i) => i !== n));
                        setChosen(0);
                      }}
                    >
                      {t("crop.removePiece", { n: String(n + 1) })}
                    </button>
                  </>
                )}
              </li>
            ))}
          </ol>
          <div className="crop-tools">
            <button
              type="button"
              disabled={pieces.length >= MOST_PIECES}
              onClick={() => {
                setPieces((all) => [...all, { box: null, description: attachment.description, audience: attachment.audience }]);
                setChosen(pieces.length);
              }}
            >
              {t("crop.addPiece")}
            </button>
            {pieces.length > 1 && <span className="hint">{t("crop.splitHint")}</span>}
          </div>
          {failed && !(failed instanceof NeedsToken) && (
            <p role="alert" className="notice error">
              {t("crop.failed", { error: failed.message })}
            </p>
          )}
          <div className="dialog-actions">
            <button type="button" className="primary" disabled={save.isPending} onClick={() => save.mutate()}>
              {t("crop.save")}
            </button>
            <Dialog.Close asChild>
              <button type="button">{t("dialog.cancel")}</button>
            </Dialog.Close>
          </div>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}
