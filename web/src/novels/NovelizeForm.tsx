import { useMutation } from "@tanstack/react-query";
import { useState, type FormEvent } from "react";
import { ApiError, NeedsToken, type Conversion } from "../api";
import { LANGUAGES, useT } from "../i18n";
import { TONES } from "../play/api";
import { NOVEL_LENGTHS, createNovel, type Novel, type NovelRequest, type NovelSource } from "./api";

/** What the form asks for; the source comes with it. */
export type NovelChoices = Omit<NovelRequest, "source" | "id">;

const NOVEL_TONES = [...TONES, "custom"];

/** A new novel's choices: a recap, in `tone` (the campaign's, or classic for a module), in the UI's language, of all
 * the sessions or the latest revision. */
export function defaultChoices(language: string, tone: { tone: string; custom_tone?: string }): NovelChoices {
  return {
    length: "recap",
    tone: NOVEL_TONES.includes(tone.tone) ? tone.tone : "classic",
    custom_tone: tone.custom_tone ?? "",
    language: (LANGUAGES as readonly string[]).includes(language) ? language : "en",
    instructions: "",
    sessions: null,
    revision: null,
  };
}

/** A novel's own choices, for Write again. */
export function choicesOf(novel: Novel | Omit<Novel, "chapters">): NovelChoices {
  const { length, tone, custom_tone, language, instructions, sessions, revision } = novel;
  return { length, tone, custom_tone, language, instructions, sessions, revision };
}

/**
 * Novelize: the length, the tone (a play tone or the owner's own), the language, the instructions, and which part of
 * the source: a campaign's sessions (all of them, or a range) or a module's revision (the latest, or an older one).
 * While a job runs it says so and waits: one job runs at a time.
 */
export default function NovelizeForm({
  source,
  initial,
  running,
  latestRevision,
  onStarted,
}: {
  source: NovelSource;
  initial: NovelChoices;
  running: Conversion | null;
  /** A module's newest revision, for the older ones to choose from. */
  latestRevision?: number | null;
  onStarted: (novel: Novel) => void;
}) {
  const t = useT();
  const [choices, setChoices] = useState<NovelChoices>(initial);
  const [range, setRange] = useState<[string, string]>(() =>
    initial.sessions ? [String(initial.sessions[0]), String(initial.sessions[1])] : ["1", "1"],
  );
  const [someSessions, setSomeSessions] = useState(initial.sessions !== null);
  const start = useMutation({ mutationFn: createNovel, onSuccess: onStarted });
  const set = (change: Partial<NovelChoices>) => setChoices((old) => ({ ...old, ...change }));
  const campaign = source.kind === "campaign";

  function submit(e: FormEvent) {
    e.preventDefault();
    const sessions: [number, number] | null = campaign && someSessions ? [Number(range[0]), Number(range[1])] : null;
    start.mutate({
      source: source.kind,
      id: source.id,
      ...choices,
      custom_tone: choices.tone === "custom" ? choices.custom_tone : "",
      sessions,
      revision: campaign ? null : choices.revision,
    });
  }

  const refused = start.error && !(start.error instanceof NeedsToken) ? start.error : null;
  const hint = refused instanceof ApiError && typeof refused.body.hint === "string" ? refused.body.hint : null;
  const older = latestRevision ? Array.from({ length: latestRevision - 1 }, (_, i) => latestRevision - 1 - i) : [];

  return (
    <form className="choice novelize" onSubmit={submit}>
      <h3>{t("novelize.heading")}</h3>
      <fieldset className="field">
        <legend>{t("novelize.length")}</legend>
        {NOVEL_LENGTHS.map((length) => (
          <label key={length} className="check">
            <input
              type="radio"
              name="novel-length"
              value={length}
              checked={choices.length === length}
              onChange={() => set({ length })}
            />{" "}
            {t(`novel.length.${length}`)}
          </label>
        ))}
      </fieldset>
      <div className="field">
        <label htmlFor="novel-tone">{t("novelize.tone")}</label>
        <select id="novel-tone" value={choices.tone} onChange={(e) => set({ tone: e.target.value })}>
          {NOVEL_TONES.map((tone) => (
            <option key={tone} value={tone}>
              {tone === "custom" ? t("novelize.tone.custom") : t(`play.tone.${tone}`)}
            </option>
          ))}
        </select>
      </div>
      {choices.tone === "custom" && (
        <div className="field">
          <label htmlFor="novel-custom-tone">{t("novelize.customTone")}</label>
          <input
            id="novel-custom-tone"
            value={choices.custom_tone}
            required
            onChange={(e) => set({ custom_tone: e.target.value })}
          />
        </div>
      )}
      <div className="field">
        <label htmlFor="novel-language">{t("novelize.language")}</label>
        <select id="novel-language" value={choices.language} onChange={(e) => set({ language: e.target.value })}>
          {LANGUAGES.map((language) => (
            <option key={language} value={language}>
              {t(`language.${language}`)}
            </option>
          ))}
        </select>
      </div>
      <div className="field">
        <label htmlFor="novel-instructions">{t("novelize.instructions")}</label>
        <textarea
          id="novel-instructions"
          rows={3}
          value={choices.instructions}
          placeholder={t("novelize.instructionsHint")}
          onChange={(e) => set({ instructions: e.target.value })}
        />
      </div>
      {campaign ? (
        <fieldset className="field">
          <legend>{t("novelize.sessions")}</legend>
          <label className="check">
            <input type="radio" name="novel-sessions" checked={!someSessions} onChange={() => setSomeSessions(false)} />{" "}
            {t("novelize.allSessions")}
          </label>
          <label className="check">
            <input type="radio" name="novel-sessions" checked={someSessions} onChange={() => setSomeSessions(true)} />{" "}
            {t("novelize.someSessions")}
          </label>{" "}
          <input
            type="number"
            min={1}
            aria-label={t("novelize.first")}
            value={range[0]}
            disabled={!someSessions}
            onChange={(e) => setRange([e.target.value, range[1]])}
          />{" "}
          {t("novelize.to")}{" "}
          <input
            type="number"
            min={1}
            aria-label={t("novelize.last")}
            value={range[1]}
            disabled={!someSessions}
            onChange={(e) => setRange([range[0], e.target.value])}
          />
        </fieldset>
      ) : (
        <div className="field">
          <label htmlFor="novel-revision">{t("novelize.revision")}</label>
          <select
            id="novel-revision"
            value={choices.revision === null ? "" : String(choices.revision)}
            onChange={(e) => set({ revision: e.target.value ? Number(e.target.value) : null })}
          >
            <option value="">{t("novelize.latest")}</option>
            {older.map((n) => (
              <option key={n} value={String(n)}>
                {t("novelize.revisionN", { n: String(n) })}
              </option>
            ))}
          </select>
        </div>
      )}
      {running && (
        <p className="notice" role="note">
          {t("novelize.running", { title: running.title })}
        </p>
      )}
      {refused && (
        <p role="alert" className="notice error">
          {t("novelize.failed", { error: refused.message })}
          {hint && <> {hint}</>}
        </p>
      )}
      <div className="actions">
        <button type="submit" className="primary" disabled={running !== null || start.isPending}>
          {t("novelize.submit")}
        </button>
      </div>
    </form>
  );
}
