import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useMemo, useState, type CSSProperties, type FormEvent } from "react";
import { accountKeys } from "../account/api";
import TimeZonePicker, { closestZone, useTimeZones } from "../components/TimeZonePicker";
import { LANGUAGES, isLanguage, useT } from "../i18n";
import { viewerTimeZone } from "../play/NextSession";
import Avatar from "./Avatar";
import {
  AVATAR_LIMIT,
  AVATAR_TYPES,
  COLOUR_NAMES,
  COLOURS,
  getOwnProfile,
  profileKeys,
  putProfile,
  removeAvatar,
  uploadAvatar,
  type ProfileCard,
  type ProfileChanges,
  type ProfileSummary,
} from "./api";
import { EMBLEMS, Emblem } from "./emblems";
import "./profile.css";

const OTHER = "other";
const TEXT_LENGTH = 500;

type Draft = Required<Omit<ProfileChanges, "avatar_emblem" | "time_zone">> & { time_zone: string; avatar_emblem: string | null };

/** The form's fields from the stored profile; `avatar_emblem` is null until the player picks one. */
function draftOf(card: ProfileCard): Draft {
  return {
    display_name: card.display_name,
    pronouns: card.pronouns,
    colour: card.colour,
    language: card.language ?? "en",
    about: card.about,
    host_note: card.host_note ?? "",
    time_zone: card.time_zone ?? "",
    avatar_emblem: null,
  };
}

/**
 * Preferences' Profile section, for an account (players and tavern Task G2): what the other players at its tables see
 * of it. The display name and pronouns, the avatar (one of the twelve emblems, or an uploaded picture, which wins), the
 * colour, the language, about me, a note only the hosts of its tables read, and its time zone, with a preview of the
 * face the table shows. Choosing an emblem takes the picture away when saved; Remove the picture does it at once.
 */
export default function ProfileSection() {
  const t = useT();
  const client = useQueryClient();
  const profile = useQuery({ queryKey: profileKeys.own, queryFn: getOwnProfile });
  const [draft, setDraft] = useState<Draft | null>(null);
  const [other, setOther] = useState("");
  const [status, setStatus] = useState<{ kind: "idle" | "saved" } | { kind: "error"; message: string }>({ kind: "idle" });

  useEffect(() => {
    if (!profile.data) return;
    const next = draftOf(profile.data);
    if (!isLanguage(next.language)) {
      setOther(next.language);
      next.language = OTHER;
    }
    setDraft(next);
  }, [profile.data]);

  function stored(card: ProfileCard) {
    client.setQueryData(profileKeys.own, card);
    void client.invalidateQueries({ queryKey: accountKeys.me() });
  }

  function refused(error: Error) {
    setStatus({ kind: "error", message: error.message });
  }

  const save = useMutation({
    mutationFn: (changes: ProfileChanges) => putProfile(changes),
    onSuccess: (card) => {
      stored(card);
      setStatus({ kind: "saved" });
    },
    onError: refused,
  });
  const upload = useMutation({
    mutationFn: uploadAvatar,
    onSuccess: (card) => {
      stored(card);
      setDraft((d) => d && { ...d, avatar_emblem: null });
      setStatus({ kind: "idle" });
    },
    onError: refused,
  });
  const remove = useMutation({ mutationFn: removeAvatar, onSuccess: stored, onError: refused });

  const zones = useTimeZones(profile.data?.time_zone ?? "");
  const own = useMemo(() => closestZone(viewerTimeZone(), zones), [zones]);

  if (!profile.data || !draft) {
    return (
      <section id="profile" className="profile-section" aria-labelledby="profile-title">
        <h2 id="profile-title">{t("profile.title")}</h2>
        <p className="placeholder">{profile.error ? profile.error.message : t("preferences.loading")}</p>
      </section>
    );
  }
  const card = profile.data;
  const set = (change: Partial<Draft>) => {
    setDraft({ ...draft, ...change });
    setStatus({ kind: "idle" });
  };
  const language = draft.language === OTHER ? other.trim().toLowerCase() : draft.language;
  const hasPicture = "picture" in card.avatar;
  const preview: ProfileSummary = {
    ...card,
    display_name: draft.display_name || card.display_name,
    colour: draft.colour,
    avatar: draft.avatar_emblem ? { emblem: draft.avatar_emblem } : card.avatar,
  };
  const shownEmblem = draft.avatar_emblem ?? ("emblem" in card.avatar ? card.avatar.emblem : null);

  function submit(event: FormEvent) {
    event.preventDefault();
    if (!draft) return;
    const { avatar_emblem, time_zone, ...fields } = draft;
    const changes: ProfileChanges = { ...fields, language, time_zone: time_zone || null };
    if (avatar_emblem) changes.avatar_emblem = avatar_emblem;
    save.mutate(changes, { onSuccess: () => setDraft((d) => d && { ...d, avatar_emblem: null }) });
  }

  function pick(file: File | undefined) {
    if (!file) return;
    if (file.size > AVATAR_LIMIT) {
      setStatus({ kind: "error", message: t("profile.tooLarge") });
      return;
    }
    upload.mutate(file);
  }

  const busy = save.isPending || upload.isPending || remove.isPending;
  return (
    <section id="profile" className="profile-section" aria-labelledby="profile-title">
      <h2 id="profile-title">{t("profile.title")}</h2>
      <div className="profile-layout">
        <figure className="profile-preview" aria-hidden="true">
          <Avatar profile={preview} size={112} />
          <figcaption>
            <span className="profile-preview-name">{preview.display_name}</span>
            {draft.pronouns && <span className="profile-preview-pronouns">{draft.pronouns}</span>}
          </figcaption>
        </figure>

        <form className="profile-form" onSubmit={submit} aria-labelledby="profile-title">
          <div className="profile-names">
            <div className="field">
              <label htmlFor="profile-name">{t("profile.displayName")}</label>
              <input
                id="profile-name"
                data-testid="profile-name"
                value={draft.display_name}
                maxLength={40}
                autoComplete="nickname"
                onChange={(e) => set({ display_name: e.target.value })}
              />
            </div>
            <div className="field">
              <label htmlFor="profile-pronouns">{t("profile.pronouns")}</label>
              <input
                id="profile-pronouns"
                data-testid="profile-pronouns"
                value={draft.pronouns}
                maxLength={40}
                onChange={(e) => set({ pronouns: e.target.value })}
              />
            </div>
          </div>

          <fieldset className="profile-emblems">
            <legend>{t("profile.avatar")}</legend>
            <div
              className="profile-emblem-grid"
              style={{ "--pick-colour": COLOURS[draft.colour as keyof typeof COLOURS] } as CSSProperties}
            >
              {EMBLEMS.map((name) => (
                <label key={name} className="profile-emblem" data-colour={draft.colour} title={t(`emblem.${name}`)}>
                  <input
                    type="radio"
                    name="profile-emblem"
                    value={name}
                    data-testid={`profile-emblem-${name}`}
                    checked={!(hasPicture && !draft.avatar_emblem) && shownEmblem === name}
                    onChange={() => set({ avatar_emblem: name })}
                  />
                  <span className="profile-emblem-face">
                    <Emblem name={name} />
                  </span>
                  <span className="visually-hidden">{t(`emblem.${name}`)}</span>
                </label>
              ))}
            </div>
            <div className="profile-picture">
              <label className="button-like profile-upload">
                {t("profile.upload")}
                <input
                  type="file"
                  className="visually-hidden"
                  data-testid="profile-upload"
                  accept={AVATAR_TYPES.join(",")}
                  disabled={busy}
                  onChange={(e) => {
                    pick(e.target.files?.[0]);
                    e.target.value = "";
                  }}
                />
              </label>
              {hasPicture && (
                <button type="button" disabled={busy} onClick={() => remove.mutate()}>
                  {t("profile.removePicture")}
                </button>
              )}
              <span className="hint">{t("profile.uploadHint")}</span>
            </div>
          </fieldset>

          <fieldset className="profile-colours">
            <legend>{t("profile.colour")}</legend>
            {COLOUR_NAMES.map((name) => (
              <label key={name} className="profile-colour" data-colour={name}>
                <input
                  type="radio"
                  name="profile-colour"
                  value={name}
                  data-testid={`profile-colour-${name}`}
                  checked={draft.colour === name}
                  onChange={() => set({ colour: name })}
                />
                <span className="profile-swatch" style={{ background: COLOURS[name] }} aria-hidden="true" />
                {t(`profile.colour.${name}`)}
              </label>
            ))}
          </fieldset>

          <div className="field">
            <label htmlFor="profile-language">{t("profile.language")}</label>
            <select
              id="profile-language"
              data-testid="profile-language"
              value={draft.language}
              onChange={(e) => set({ language: e.target.value })}
            >
              {LANGUAGES.map((lang) => (
                <option key={lang} value={lang}>
                  {t(`language.${lang}`)}
                </option>
              ))}
              <option value={OTHER}>{t("join.lang.other")}</option>
            </select>
            {draft.language === OTHER && (
              <>
                <label htmlFor="profile-other-language">{t("join.otherCode")}</label>
                <input
                  id="profile-other-language"
                  value={other}
                  maxLength={3}
                  autoComplete="off"
                  onChange={(e) => setOther(e.target.value)}
                />
                <span className="hint">{t("join.otherHint")}</span>
              </>
            )}
          </div>

          <div className="field">
            <label htmlFor="profile-about">{t("profile.about")}</label>
            <textarea
              id="profile-about"
              data-testid="profile-about"
              rows={3}
              maxLength={TEXT_LENGTH}
              value={draft.about}
              onChange={(e) => set({ about: e.target.value })}
            />
            <span className="hint profile-count">
              {t("profile.count", { count: String(draft.about.length), max: String(TEXT_LENGTH) })}
            </span>
          </div>

          <div className="field">
            <label htmlFor="profile-note">{t("profile.note")}</label>
            <textarea
              id="profile-note"
              data-testid="profile-note"
              rows={2}
              maxLength={TEXT_LENGTH}
              value={draft.host_note}
              onChange={(e) => set({ host_note: e.target.value })}
            />
            <span className="hint">{t("profile.noteHint")}</span>
          </div>

          <div className="field">
            <label htmlFor="profile-time-zone">{t("profile.timeZone")}</label>
            <TimeZonePicker
              id="profile-time-zone"
              testId="profile-time-zone"
              zones={zones}
              value={draft.time_zone}
              onChange={(time_zone) => set({ time_zone })}
              preferred={own}
              none={t("profile.noTimeZone")}
            />
            <span className="hint">{t("profile.timeZoneHint")}</span>
          </div>

          {status.kind === "error" && (
            <p role="alert" className="notice error">
              {status.message}
            </p>
          )}
          <div className="actions">
            <button type="submit" className="primary" data-testid="profile-save" disabled={busy}>
              {t("profile.save")}
            </button>
            {status.kind === "saved" && <span role="status">{t("profile.saved")}</span>}
          </div>
        </form>
      </div>
    </section>
  );
}
