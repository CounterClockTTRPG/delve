import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState, type ChangeEvent } from "react";
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
  type ModuleDetail,
} from "../api";
import Banner from "../campaign/Banner";
import { useConfirm } from "../components/dialogs";
import { useT } from "../i18n";

const PICTURES = new Set(["image/png", "image/jpeg", "image/webp"]);

/** A picture to cut: one uploaded (its object address while it is chosen) or one of the module's own. */
type Choice = { kind: "upload"; file: File; src: string } | { kind: "picture"; id: string; src: string };

/**
 * A module's banner on its page (DEL-123): the picture, or that it has none; a painting under way or failed; and the
 * four ways to set it: Paint a banner (with a hint; only the owner with a paid model), Upload a picture, Use one of
 * the module's pictures (its PNG, JPEG and WebP attachments, such as a converted book's cover), or Remove. An upload or
 * a picture is cut to the banner's 21:9 band: the slider chooses which, and the preview shows exactly that band.
 */
export default function ModuleBannerPanel({ module, attachments }: { module: ModuleDetail; attachments: Attachment[] }) {
  const t = useT();
  const client = useQueryClient();
  const confirm = useConfirm();
  const [hint, setHint] = useState("");
  const [choosing, setChoosing] = useState(false);
  const [choice, setChoice] = useState<Choice | null>(null);
  const [position, setPosition] = useState(50);
  const info = useQuery({ queryKey: ["module", module.id, "banner-paint"], queryFn: () => getBannerPaintInfo(module.id) });
  const done = () => {
    setChoice(null);
    setChoosing(false);
    setPosition(50);
    client.invalidateQueries({ queryKey: queryKeys.module(module.id), exact: true });
    client.invalidateQueries({ queryKey: queryKeys.modules });
  };
  const paint = useMutation({ mutationFn: () => paintModuleBanner(module.id, hint.trim()), onSuccess: () => (setHint(""), done()) });
  const save = useMutation({
    mutationFn: (chosen: Choice) =>
      chosen.kind === "upload"
        ? uploadModuleBanner(module.id, chosen.file, position / 100)
        : pictureModuleBanner(module.id, chosen.id, position / 100),
    onSuccess: done,
  });
  const remove = useMutation({ mutationFn: () => removeModuleBanner(module.id), onSuccess: done });
  // An uploaded file's object address is let go once it isn't shown.
  useEffect(() => () => void (choice?.kind === "upload" && URL.revokeObjectURL(choice.src)), [choice]);

  const banner = module.banner ?? null;
  const pictures = attachments.filter((a) => PICTURES.has(a.type));
  const failed = [paint.error, save.error, remove.error].find((e) => e && !(e instanceof NeedsToken));
  const painting = banner?.status === "painting";

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
            <img src={choice.src} alt={t("moduleBanner.preview")} style={{ objectPosition: `${position}% ${position}%` }} />
          </div>
          <label className="banner-crop-slider">
            <span>{t("moduleBanner.position")}</span>
            <input type="range" min={0} max={100} value={position} onChange={(e) => setPosition(Number(e.target.value))} />
          </label>
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
