import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState, type ReactNode } from "react";
import { Link, useSearchParams } from "react-router-dom";
import AccountSection from "../account/AccountSection";
import { accountKeys, listAccounts, pendingCount, type Me } from "../account/api";
import { useMe } from "../account/useMe";
import {
  ApiError,
  NeedsToken,
  getBackends,
  getPreferences,
  putPreferences,
  queryKeys,
  type AppPreferences,
  type ImageStyle,
  type ImageStylePreset,
  type BackendChoice,
  type Effort,
  type ProviderCapabilities,
  type SettingsWarning,
} from "../api";
import { LANGUAGES, isLanguage, useT } from "../i18n";
import LookPicker from "../looks/LookPicker";
import { useDidYouKnow } from "../play/didYouKnowSetting";
import Connections from "../preferences/Connections";
import Packs from "../preferences/Packs";
import OwnerToken from "../preferences/OwnerToken";
import Storage from "../preferences/Storage";
import ProfileSection from "../profile/ProfileSection";
import EmailSection from "../mail/EmailSection";

type T = ReturnType<typeof useT>;

/** The server's word for a choice it keeps although it can't be used now (`settings.Unusable`). */
const CANT_BE_USED = ": can't be used: ";

/** A server warning: with its code and args from a server that sends `coded_warnings`, else its English text only. */
type Warning = Partial<SettingsWarning> & { text: string };

type Status = { kind: "idle" } | { kind: "saved" } | { kind: "rejected"; warnings: Warning[] } | { kind: "failed"; error: string };

function warningsOf(body: { warnings?: unknown; coded_warnings?: unknown }): Warning[] {
  if (Array.isArray(body.coded_warnings)) return body.coded_warnings as SettingsWarning[];
  return Array.isArray(body.warnings) ? body.warnings.map((text) => ({ text: String(text) })) : [];
}

function jobOf(w: Warning, jobs: string[]): string | undefined {
  return w.args?.job ?? jobs.find((job) => w.text.startsWith(`${job}:`));
}

function isKept(w: Warning): boolean {
  return w.args ? w.args.outcome === "kept" : w.text.includes(CANT_BE_USED);
}

/** What a warning's code says, in the reader's language; null for a code the dictionaries don't have. */
function problemOf(t: T, w: Warning): string | null {
  if (!w.code) return null;
  const key = `settings.warning.${w.code}`;
  const said = t(key, w.args);
  return said === key ? null : said;
}

/** A warning as a sentence: "DM: the provider gone isn't available; its default is used", or its English text. */
function sayWarning(t: T, w: Warning): string {
  const problem = problemOf(t, w);
  const job = w.args?.job;
  const outcome = w.args?.outcome;
  if (problem === null) return w.text;
  if (!job || !outcome) return problem;
  const key = `settings.warning.outcome.${outcome}`;
  const label = t(`job.${job}`);
  const said = t(key, { job: label === `job.${job}` ? job : label, problem });
  return said === key ? w.text : said;
}

/** Why a kept choice can't be used now, without its job. */
function keptReason(t: T, w: Warning, job: string): string {
  return problemOf(t, w) ?? w.text.slice(job.length + CANT_BE_USED.length);
}

/** The effort to keep when the provider changes: the current one if offered, else auto, else the first. */
function effortFor(provider: ProviderCapabilities, current: Effort | null): Effort | null {
  if (current && provider.efforts.includes(current)) return current;
  if (provider.efforts.includes("auto")) return "auto";
  return provider.efforts[0] ?? null;
}

/** A model as the select shows it: "flux-schnell · replicate · ~$0.003 / image", "sdxl-turbo · local · free". A
 * model with no backend of its own (Claude's) shows its label alone, from the dictionary when it has one. */
function modelLabel(t: T, provider: ProviderCapabilities, model: string): string {
  const info = provider.model_info?.[model];
  if (!info) return model;
  if (!info.backend) {
    const key = `preferences.model.${provider.id}.${model}`;
    const named = t(key);
    return named === key ? info.label : named;
  }
  const price = info.paid ? (info.price ?? t("preferences.modelPriceUnknown")) : t("preferences.modelFree");
  return `${info.label} · ${info.backend} · ${price}`;
}

/** "Did you know" while the DM thinks, on or off for this browser; it never shows on a phone. */
function DidYouKnowToggle() {
  const t = useT();
  const [on, setOn] = useDidYouKnow();
  return (
    <div className="field">
      <label className="check">
        <input type="checkbox" checked={on} onChange={(e) => setOn(e.target.checked)} />
        {t("preferences.didYouKnow")}
      </label>
      <span className="hint">{t("preferences.didYouKnowHint")}</span>
    </div>
  );
}

/** Who reads Preferences; while `/api/me` doesn't answer, the page shows everything and the server refuses what it
 * must. */
function rightsOf(me: Me | undefined): { organiser: boolean; owner: boolean } {
  if (!me) return { organiser: true, owner: true };
  return {
    organiser: me.principal.roles.includes("organiser"),
    owner: me.principal.id === "owner" || Boolean(me.account?.owner),
  };
}

const TABS = ["profile", "browser", "backends", "connections", "storage", "packs", "players"] as const;
type Tab = (typeof TABS)[number];

/** One tab's sections, rendered only while it is open, so a closed tab asks the server for nothing. */
function TabPanel({ name, active, children }: { name: Tab; active: Tab; children: ReactNode }) {
  if (name !== active) return null;
  return (
    <div role="tabpanel" id={`preferences-panel-${name}`} aria-labelledby={`preferences-tab-${name}`}>
      {children}
    </div>
  );
}

/**
 * Preferences, for everyone (players and tavern Task E4), in tabs kept in `?tab=` (the first one shown when none):
 * Profile, an account's profile (Task G2) and the account; This browser, its look and "Did you know"; then the
 * organiser's: Backends (the backends, the image style and the install's language), Connections and Storage with the
 * owner token (the owner's), and Players, with the sign-ups waiting on its tab. A tab the reader has no right to isn't
 * shown, so a player's account never asks for the organiser's preferences or backends.
 */
export default function Preferences() {
  const t = useT();
  const [params, setParams] = useSearchParams();
  const me = useMe();
  // Sign-ups waiting for approval (DEL-156), beside the way to the Players page.
  const accounts = useQuery({
    queryKey: accountKeys.accounts,
    queryFn: listAccounts,
    enabled: !me.isPending && rightsOf(me.data).organiser,
    retry: false,
  });
  const waiting = pendingCount(accounts.data);
  if (me.isPending) {
    return (
      <section className="page">
        <h1>{t("area.preferences")}</h1>
        <p className="placeholder">{t("preferences.loading")}</p>
      </section>
    );
  }
  const account = me.data?.account ?? null;
  const { organiser, owner } = rightsOf(me.data);
  const shown: Record<Tab, boolean> = {
    profile: Boolean(account),
    browser: true,
    backends: organiser,
    connections: owner,
    storage: owner,
    // The rulesets and settings installed (DEL-366): every organiser downloads; the owner installs and removes.
    packs: organiser,
    players: organiser,
  };
  const tabs = TABS.filter((name) => shown[name]);
  const asked = params.get("tab") ?? "";
  const tab: Tab = (tabs as readonly string[]).includes(asked) ? (asked as Tab) : tabs[0];
  const open = (name: Tab) => setParams(name === tabs[0] ? {} : { tab: name }, { replace: true });
  return (
    <section className="page preferences">
      <h1>{t("area.preferences")}</h1>

      {tabs.length > 1 && (
        <div role="tablist" className="view-tabs preferences-tabs" data-tour="preferences-tabs" aria-label={t("preferences.tabs")}>
          {tabs.map((name) => (
            <button
              key={name}
              type="button"
              role="tab"
              id={`preferences-tab-${name}`}
              aria-selected={tab === name}
              aria-controls={`preferences-panel-${name}`}
              className="view-tab"
              onClick={() => open(name)}
            >
              {t(`preferences.tab.${name}`)}
              {name === "players" && waiting > 0 && <span className="tab-count">{waiting}</span>}
            </button>
          ))}
        </div>
      )}

      <TabPanel name="profile" active={tab}>
        {account && <ProfileSection />}
        {account && <AccountSection account={account} />}
        {account && <EmailSection />}
      </TabPanel>

      <TabPanel name="browser" active={tab}>
        <section className="this-browser" aria-labelledby="this-browser-title">
          <h2 id="this-browser-title">{t("preferences.thisBrowser")}</h2>
          <LookPicker />
          <DidYouKnowToggle />
        </section>
      </TabPanel>

      <TabPanel name="backends" active={tab}>
        <BackendsForm />
      </TabPanel>

      <TabPanel name="connections" active={tab}>
        <Connections />
      </TabPanel>

      <TabPanel name="storage" active={tab}>
        <Storage />
        <OwnerToken />
      </TabPanel>

      <TabPanel name="packs" active={tab}>
        <Packs />
      </TabPanel>

      <TabPanel name="players" active={tab}>
        <section className="players-entry" aria-labelledby="players-entry-title">
          <h2 id="players-entry-title">{t("players.title")}</h2>
          <p className="lede">{t("players.open")}</p>
          <Link className="button-like" to="/preferences/players">
            {t("players.openLink")}
            {waiting > 0 && <span className="nav-count players-entry-count">{waiting}</span>}
          </Link>
          {waiting > 0 && <p className="hint">{t("nav.waiting", { count: String(waiting) })}</p>}
        </section>
      </TabPanel>
    </section>
  );
}

const TONE_STYLE: ImageStyle = { preset: "tone", custom: "" };

/** The install's image style (DEL-202): the campaign's tone, a preset (with its sample picture and its words), or the
 * owner's own words. Any but the tone's replaces the tone's painter in every picture. */
function ImageStyleField({
  presets,
  style,
  onChange,
}: {
  presets: ImageStylePreset[];
  style: ImageStyle;
  onChange: (style: ImageStyle) => void;
}) {
  const t = useT();
  const preset = presets.find((p) => p.id === style.preset);
  return (
    <div className="field image-style">
      <label htmlFor="image-style">{t("preferences.imageStyle")}</label>
      <select id="image-style" value={style.preset} onChange={(e) => onChange({ ...style, preset: e.target.value })}>
        <option value="tone">{t("preferences.imageStyle.tone")}</option>
        {presets.map((p) => (
          <option key={p.id} value={p.id}>
            {p.name}
          </option>
        ))}
        <option value="custom">{t("preferences.imageStyle.custom")}</option>
      </select>
      <span className="hint">{t("preferences.imageStyleHint")}</span>
      {preset && (
        <div className="image-style-preview">
          {preset.sample && (
            <img src={`/image-styles/${preset.id}.webp`} alt={t("preferences.imageStyle.sample", { name: preset.name })} />
          )}
          <p className="hint">{preset.prompt}</p>
        </div>
      )}
      {style.preset === "custom" && (
        <textarea
          id="image-style-custom"
          aria-label={t("preferences.imageStyle.customLabel")}
          rows={3}
          maxLength={1000}
          value={style.custom}
          placeholder={t("preferences.imageStyle.customPlaceholder")}
          onChange={(e) => onChange({ ...style, custom: e.target.value })}
        />
      )}
    </div>
  );
}

/** The install's backends and models, its image style and its interface language: an organiser's. */
function BackendsForm() {
  const t = useT();
  const client = useQueryClient();
  const backends = useQuery({ queryKey: queryKeys.backends, queryFn: getBackends });
  const stored = useQuery({ queryKey: queryKeys.preferences, queryFn: getPreferences });
  const [draft, setDraft] = useState<AppPreferences | null>(null);
  const [status, setStatus] = useState<Status>({ kind: "idle" });

  // Start from the server's preferences, and again whenever they change (also from another device, via SSE).
  useEffect(() => {
    if (stored.data) {
      const { choices, language, image_style } = stored.data;
      setDraft({ choices, language, image_style: image_style ?? TONE_STYLE });
    }
  }, [stored.data]);

  const save = useMutation({
    mutationFn: putPreferences,
    onSuccess: (saved) => {
      client.setQueryData(queryKeys.preferences, saved);
      // The owner's seats follow the language (see the side bar's menu).
      void client.invalidateQueries({ queryKey: accountKeys.me() });
      setStatus({ kind: "saved" });
    },
    onError: (error) => {
      if (error instanceof NeedsToken) return; // the token gate takes over
      if (error instanceof ApiError && error.status === 422) {
        const warnings = warningsOf(error.body);
        setStatus({ kind: "rejected", warnings: warnings.length > 0 ? warnings : [{ text: error.message }] });
      } else {
        setStatus({ kind: "failed", error: error.message });
      }
    },
  });

  const loadError = backends.error ?? stored.error;
  if (loadError && !(loadError instanceof NeedsToken)) {
    return (
      <p role="alert" className="notice error">
        {t("preferences.loadFailed", { error: loadError.message })}
      </p>
    );
  }
  if (!backends.data || !draft) return <p className="placeholder">{t("preferences.loading")}</p>;

  const providers = backends.data.providers;
  const jobs = backends.data.jobs;
  const rejected = status.kind === "rejected" ? status.warnings : [];
  const jobWarnings = (job: string) => rejected.filter((w) => jobOf(w, jobs) === job);
  const otherWarnings = rejected.filter((w) => !jobs.includes(jobOf(w, jobs) ?? ""));
  // A stored choice the server keeps although it can't be used now is shown in its job, not as a fallback.
  const storedWarnings = stored.data ? warningsOf(stored.data) : [];
  const fellBack = storedWarnings.filter((w) => !isKept(w));
  function cantBeUsed(job: string, provider: ProviderCapabilities | undefined): string[] {
    if (!provider) return [];
    const reasons = provider.problem ? [provider.problem] : [];
    // The server's reasons hold for the stored choice only, while the draft still names its provider.
    if (stored.data?.choices[job]?.provider === provider.id) {
      for (const w of storedWarnings) {
        if (isKept(w) && jobOf(w, jobs) === job) reasons.push(keptReason(t, w, job));
      }
    }
    return [...new Set(reasons)];
  }

  function change(next: AppPreferences) {
    setDraft(next);
    setStatus({ kind: "idle" });
  }

  function setChoice(job: string, choice: BackendChoice) {
    change({ ...draft!, choices: { ...draft!.choices, [job]: choice } });
  }

  return (
    <>
      {fellBack.length > 0 && (
        <div className="notice" role="note">
          <p>{t("preferences.fellBack")}</p>
          <ul>
            {fellBack.map((w) => (
              <li key={w.text}>{sayWarning(t, w)}</li>
            ))}
          </ul>
        </div>
      )}

      <form
        aria-labelledby="backends-title"
        onSubmit={(e) => {
          e.preventDefault();
          save.mutate(draft);
        }}
      >
        <h2 id="backends-title">{t("preferences.backends")}</h2>
        <p className="lede">{t("preferences.intro")}</p>

        <div className="jobs">
          {backends.data.jobs.map((job) => {
            const offered = providers.filter((p) => p.jobs.includes(job));
            const choice = draft.choices[job];
            const provider = offered.find((p) => p.id === choice?.provider);
            const id = `job-${job.replace(/\W/g, "-")}`;
            const warnings = jobWarnings(job);
            const unusable = cantBeUsed(job, provider);
            // A model the provider no longer offers stays chosen, and shown, until the owner picks another.
            const models = provider?.models ?? [];
            const gone = choice?.model && provider && !models.includes(choice.model) ? choice.model : null;
            const fakePictures = job.startsWith("image.") && Boolean(provider?.development);
            return (
              <fieldset key={job} className="job" aria-labelledby={`${id}-title`}>
                <div className="job-name">
                  <span id={`${id}-title`} className="job-title">
                    {t(`job.${job}`)}
                  </span>
                  <span className="job-hint">{t(`job.${job}.hint`)}</span>
                </div>

                <div className="field provider">
                  <label htmlFor={`${id}-provider`}>{t("preferences.provider")}</label>
                  <select
                    id={`${id}-provider`}
                    value={provider?.id ?? ""}
                    disabled={offered.length === 0}
                    onChange={(e) => {
                      const next = offered.find((p) => p.id === e.target.value)!;
                      setChoice(job, { provider: next.id, model: null, effort: effortFor(next, choice?.effort ?? null) });
                    }}
                  >
                    {!provider && <option value="">{t("preferences.notOffered")}</option>}
                    {offered.map((p) => (
                      <option key={p.id} value={p.id}>
                        {p.title}
                      </option>
                    ))}
                  </select>
                </div>

                <div className="field">
                  <label htmlFor={`${id}-model`}>{t("preferences.model")}</label>
                  <select
                    id={`${id}-model`}
                    value={choice?.model ?? ""}
                    disabled={!provider || (models.length === 0 && !gone)}
                    onChange={(e) => setChoice(job, { ...choice!, model: e.target.value || null })}
                  >
                    <option value="">{t("preferences.providerDefault")}</option>
                    {provider &&
                      models.map((m) => (
                        <option key={m} value={m}>
                          {modelLabel(t, provider, m)}
                        </option>
                      ))}
                    {gone && <option value={gone}>{gone}</option>}
                  </select>
                </div>

                <div className="field">
                  <label htmlFor={`${id}-effort`}>{t("preferences.effort")}</label>
                  <select
                    id={`${id}-effort`}
                    value={choice?.effort ?? ""}
                    disabled={!provider || provider.efforts.length === 0}
                    onChange={(e) => setChoice(job, { ...choice!, effort: (e.target.value || null) as Effort | null })}
                  >
                    {(!provider || provider.efforts.length === 0) && (
                      <option value="">{t("preferences.notOffered")}</option>
                    )}
                    {provider && provider.efforts.length > 0 && !choice?.effort && (
                      <option value="">{t("preferences.providerDefault")}</option>
                    )}
                    {provider?.efforts.map((effort) => (
                      <option key={effort} value={effort}>
                        {t(`effort.${effort}`)}
                      </option>
                    ))}
                  </select>
                </div>

                {fakePictures && (
                  <ul className="job-warnings" role="note">
                    <li>{t("preferences.developmentWarning")}</li>
                  </ul>
                )}

                {unusable.length > 0 && (
                  <ul className="job-warnings" role="note">
                    {unusable.map((reason) => (
                      <li key={reason}>{t("preferences.cantBeUsed", { reason })}</li>
                    ))}
                  </ul>
                )}

                {warnings.length > 0 && (
                  <ul className="job-warnings" role="alert">
                    {warnings.map((w) => (
                      <li key={w.text}>{sayWarning(t, w)}</li>
                    ))}
                  </ul>
                )}
              </fieldset>
            );
          })}
        </div>

        <ImageStyleField
          presets={backends.data.image_styles ?? []}
          style={draft.image_style}
          onChange={(image_style) => change({ ...draft, image_style })}
        />

        <div className="field language">
          <label htmlFor="language">{t("preferences.language")}</label>
          <select
            id="language"
            value={draft.language}
            onChange={(e) => isLanguage(e.target.value) && change({ ...draft, language: e.target.value })}
          >
            {LANGUAGES.map((lang) => (
              <option key={lang} value={lang}>
                {t(`language.${lang}`)}
              </option>
            ))}
          </select>
          <span className="hint">{t("preferences.languageHint")}</span>
        </div>

        <div className="actions">
          <button type="submit" className="primary" disabled={save.isPending}>
            {save.isPending ? t("preferences.saving") : t("preferences.save")}
          </button>
          <span role="status" className="status">
            {status.kind === "saved" && t("preferences.saved")}
            {status.kind === "failed" && t("preferences.saveFailed", { error: status.error })}
          </span>
        </div>

        {status.kind === "rejected" && (
          <div className="notice error" role="alert">
            <p>{t("preferences.rejected")}</p>
            {otherWarnings.length > 0 && (
              <ul>
                {otherWarnings.map((w) => (
                  <li key={w.text}>{sayWarning(t, w)}</li>
                ))}
              </ul>
            )}
          </div>
        )}
      </form>
    </>
  );
}
