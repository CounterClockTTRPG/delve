import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState, type CSSProperties, type ChangeEvent } from "react";
import {
  NeedsToken,
  attachmentUrl,
  getBannerPaintInfo,
  moduleOwnBannerUrl,
  paintModuleBanner,
  pictureModuleBanner,
  queryKeys,
  removeModuleBanner,
  uploadModuleBanner,
  type Attachment,
  type BannerCrop,
  type ModuleDetail,
} from "../api";
import Banner from "../campaign/Banner";
import { useConfirm } from "../components/dialogs";
import { useT } from "../i18n";

const PICTURES = new Set(["image/png", "image/jpeg", "image/webp"]);

/** The banner's shape, as the server cuts it. */
const BANNER_RATIO = 21 / 9;
const WHOLE: BannerCrop = { x: 0.5, y: 0.5, width: 1 };

/**
 * The box of a picture `width` × `height` that `crop` keeps, as the server's `Crop.box` works it out: its size and
 * place as fractions of the picture, and whether there is room to move it across and down.
 */
export function bannerBox([width, height]: [number, number], crop: BannerCrop) {
  const tall = width / height <= BANNER_RATIO;
  const bandWidth = tall ? width : height * BANNER_RATIO;
  const cutWidth = Math.min(width, bandWidth * crop.width);
  const cutHeight = Math.min(height, (bandWidth / BANNER_RATIO) * crop.width);
  return {
    left: (crop.x * (width - cutWidth)) / width,
    top: (crop.y * (height - cutHeight)) / height,
    width: cutWidth / width,
    height: cutHeight / height,
    across: width - cutWidth >= 1,
    down: height - cutHeight >= 1,
  };
}

/** The preview's picture placed so the 21:9 frame shows the box `crop` keeps; until its size is known, the band. */
function previewStyle(size: [number, number] | null, crop: BannerCrop): CSSProperties {
  if (!size) return { objectPosition: `${crop.x * 100}% ${crop.y * 100}%` };
  const box = bannerBox(size, crop);
  const percent = (v: number) => `${Math.round(v * 1e6) / 1e4}%`;
  return {
    position: "absolute",
    maxWidth: "none",
    width: percent(1 / box.width),
    height: percent(1 / box.height),
    left: percent(-box.left / box.width),
    top: percent(-box.top / box.height),
  };
}

/** A picture to cut: one uploaded (its object address while it is chosen) or one of the module's own. */
type Choice = { kind: "upload"; file: File; src: string } | { kind: "picture"; id: string; src: string };

/**
 * A module's banner on its page (DEL-123): the picture, or that it has none; a painting under way or failed; and the
 * four ways to set it: Paint a banner (with a hint; only the owner with a paid model), Upload a picture, Use one of
 * the module's pictures (its PNG, JPEG and WebP attachments, such as a converted book's cover), or Remove. An upload or
 * a picture is cut to a 21:9 box: Width keeps all of the widest band or part of it (DEL-356), Across and Down say
 * where, and the preview shows exactly that box.
 */
export default function ModuleBannerPanel({ module, attachments }: { module: ModuleDetail; attachments: Attachment[] }) {
  const t = useT();
  const client = useQueryClient();
  const confirm = useConfirm();
  const [hint, setHint] = useState("");
  const [choosing, setChoosing] = useState(false);
  const [choice, setChoice] = useState<Choice | null>(null);
  const [crop, setCrop] = useState<BannerCrop>(WHOLE);
  const [size, setSize] = useState<[number, number] | null>(null);
  const info = useQuery({ queryKey: ["module", module.id, "banner-paint"], queryFn: () => getBannerPaintInfo(module.id) });
  const done = () => {
    setChoice(null);
    setChoosing(false);
    setCrop(WHOLE);
    client.invalidateQueries({ queryKey: queryKeys.module(module.id), exact: true });
    client.invalidateQueries({ queryKey: queryKeys.modules });
  };
  const paint = useMutation({ mutationFn: () => paintModuleBanner(module.id, hint.trim()), onSuccess: () => (setHint(""), done()) });
  const save = useMutation({
    mutationFn: (chosen: Choice) =>
      chosen.kind === "upload"
        ? uploadModuleBanner(module.id, chosen.file, crop)
        : pictureModuleBanner(module.id, chosen.id, crop),
    onSuccess: done,
  });
  const remove = useMutation({ mutationFn: () => removeModuleBanner(module.id), onSuccess: done });
  // An uploaded file's object address is let go once it isn't shown.
  useEffect(() => () => void (choice?.kind === "upload" && URL.revokeObjectURL(choice.src)), [choice]);
  // Another picture: its size is learnt again as it loads.
  useEffect(() => setSize(null), [choice?.src]);

  const banner = module.banner ?? null;
  const pictures = attachments.filter((a) => PICTURES.has(a.type));
  const failed = [paint.error, save.error, remove.error].find((e) => e && !(e instanceof NeedsToken));
  const painting = banner?.status === "painting";

  const room = size ? bannerBox(size, crop) : null;
  const slider = (key: keyof BannerCrop, label: string, min: number, disabled = false) => (
    <label className="banner-crop-slider">
      <span>{t(label)}</span>
      <input
        type="range"
        min={min}
        max={100}
        value={Math.round(crop[key] * 100)}
        disabled={disabled}
        onChange={(e) => setCrop((now) => ({ ...now, [key]: Number(e.target.value) / 100 }))}
      />
    </label>
  );

  function pick(e: ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0];
    e.target.value = "";
    if (file) setChoice({ kind: "upload", file, src: URL.createObjectURL(file) });
  }

  return (
    <section className="module-banner" aria-labelledby="module-banner-title">
      <h2 id="module-banner-title">{t("moduleBanner.title")}</h2>
      {banner?.version ? (
        <Banner src={moduleOwnBannerUrl(module.id, banner.version)} alt={t("moduleBanner.alt", { name: module.title })} variant="campaign" />
      ) : (
        !painting && <p className="placeholder">{t("moduleBanner.none")}</p>
      )}
      {painting && (
        <p className="placeholder" role="status">
          {t("moduleBanner.painting")}
        </p>
      )}
      {banner?.status === "failed" && (
        <p role="alert" className="notice error">
          {t("moduleBanner.failed")} {banner.error}
        </p>
      )}
      {failed && (
        <p role="alert" className="notice error">
          {failed.message}
        </p>
      )}

      {choice ? (
        <div className="banner-crop">
          <div className="banner-crop-frame">
            <img
              src={choice.src}
              alt={t("moduleBanner.preview")}
              style={previewStyle(size, crop)}
              onLoad={(e) => {
                const { naturalWidth, naturalHeight } = e.currentTarget;
                if (naturalWidth && naturalHeight) setSize([naturalWidth, naturalHeight]);
              }}
            />
          </div>
          {slider("width", "moduleBanner.width", 20)}
          {slider("x", "moduleBanner.across", 0, room ? !room.across : false)}
          {slider("y", "moduleBanner.down", 0, room ? !room.down : false)}
          <div className="dialog-actions">
            <button type="button" onClick={() => setChoice(null)}>
              {t("moduleBanner.cancel")}
            </button>
            <button type="button" className="primary" disabled={save.isPending} onClick={() => save.mutate(choice)}>
              {t("moduleBanner.use")}
            </button>
          </div>
        </div>
      ) : choosing ? (
        <div className="banner-pictures">
          <p className="hint">{t("moduleBanner.pickHint")}</p>
          <ul className="banner-picture-grid">
            {pictures.map((a) => (
              <li key={a.id}>
                <button type="button" onClick={() => setChoice({ kind: "picture", id: a.id, src: attachmentUrl(module.id, a.id) })}>
                  <img src={attachmentUrl(module.id, a.id)} alt="" loading="lazy" />
                  <span>{a.description || a.id}</span>
                </button>
              </li>
            ))}
          </ul>
          <button type="button" onClick={() => setChoosing(false)}>
            {t("moduleBanner.cancel")}
          </button>
        </div>
      ) : (
        <div className="banner-actions">
          {info.data?.allowed !== false ? (
            <form
              className="inline-form"
              onSubmit={(e) => {
                e.preventDefault();
                paint.mutate();
              }}
            >
              <input aria-label={t("banner.hint")} placeholder={t("banner.hint")} value={hint} maxLength={300} onChange={(e) => setHint(e.target.value)} />
              <button type="submit" disabled={paint.isPending || painting}>
                {t(banner?.version ? "moduleBanner.paintAgain" : "moduleBanner.paint")}
              </button>
            </form>
          ) : (
            <p className="hint">{t("moduleBanner.paidOwner")}</p>
          )}
          {info.data?.paid && info.data.allowed && <p className="hint">{t("moduleBanner.paid")}</p>}
          <div className="toolbar">
            <label htmlFor="module-banner-upload" className="button-like">
              {t("moduleBanner.upload")}
            </label>
            <input id="module-banner-upload" type="file" accept="image/png,image/jpeg,image/webp" className="visually-hidden" onChange={pick} />
            {pictures.length > 0 && (
              <button type="button" onClick={() => setChoosing(true)}>
                {t("moduleBanner.pick")}
              </button>
            )}
            {banner && (
              <button
                type="button"
                className="danger"
                disabled={remove.isPending}
                onClick={async () => (await confirm({ title: t("moduleBanner.removeConfirm"), confirm: t("moduleBanner.remove"), danger: true })) && remove.mutate()}
              >
                {t("moduleBanner.remove")}
              </button>
            )}
          </div>
        </div>
      )}
    </section>
  );
}
