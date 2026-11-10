import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Settings2 } from "lucide-react";
import { useState } from "react";
import type { Effort } from "../api";
import { useT } from "../i18n";
import {
  CUSTOM_TONE_CHARS,
  DETAILS,
  ENEMY_DICE,
  TONES,
  XP_AWARDS,
  getPlaySettings,
  playKeys,
  putPlaySettings,
  type EnemyDice,
  type PlaySettings,
  type XpAward,
} from "./api";

const EFFORTS: Effort[] = ["auto", "low", "medium", "high", "max"];

/** The campaign's table options: tone, detail, effort, whether the other seats read dice in the story at all (DEL-280)
 * and the enemies' among them (DEL-270), and what earns XP. Each change is saved at once and overrides
 * Preferences. A custom tone is the host's own words for the DM, saved when the box is left: what the DM should follow
 * at this table (the table's description is for players, DEL-204). */
export default function TableOptionsPopover({ campaignId }: { campaignId: string }) {
  const t = useT();
  const client = useQueryClient();
  const [open, setOpen] = useState(false);
  const key = playKeys.settings(campaignId);
  const settings = useQuery({ queryKey: key, queryFn: () => getPlaySettings(campaignId) });
  // Each change sends only what changed (DEL-168): a whole object re-armed the beat timer and published `beat`. The
  // changes go one after the other (`scope`), each shown at once; the server's answer stands once the last is in.
  const save = useMutation({
    mutationKey: [...key, "save"],
    scope: { id: `table-options:${campaignId}` },
    mutationFn: (patch: Partial<PlaySettings>) => putPlaySettings(campaignId, patch),
    onSuccess: (saved) => {
      if (client.isMutating({ mutationKey: [...key, "save"] }) <= 1) client.setQueryData(key, saved);
    },
    onError: () => client.invalidateQueries({ queryKey: key }),
  });
  const current = settings.data;
  const [ownTone, setOwnTone] = useState<string | null>(null);

  // No effort (null) is the Preferences choice for the DM job.
  function change(patch: Partial<PlaySettings>) {
    if (!current) return;
    // Shown at once, before its turn to be sent comes.
    client.setQueryData<PlaySettings>(key, (was) => (was ? { ...was, ...patch } : was));
    save.mutate(patch);
  }

  // The box ticked or not, on the awards as last shown, a change still saving included; the server keeps them in its
  // own order.
  function award(name: XpAward, on: boolean) {
    const awards = client.getQueryData<PlaySettings>(key)?.xp_awards ?? [];
    change({ xp_awards: on ? [...awards, name] : awards.filter((a) => a !== name) });
  }

  return (
    <div className="table-options">
      <button
        type="button"
        aria-expanded={open}
        aria-controls="table-options"
        aria-label={t("play.tableOptions")}
        title={t("play.tableOptions")}
        onClick={() => setOpen(!open)}
      >
        <Settings2 size={16} aria-hidden="true" /> <span className="phone-hidden-label">{t("play.tableOptions")}</span>
      </button>
      {open && (
        <div id="table-options" className="popover" role="dialog" aria-label={t("play.tableOptions")}>
          {!current ? (
            <p className="placeholder">{t("play.loading")}</p>
          ) : (
            <>
              <label htmlFor="play-tone">{t("play.tone")}</label>
              <select id="play-tone" value={current.tone} onChange={(e) => change({ tone: e.target.value })}>
                {!(TONES as readonly string[]).includes(current.tone) && current.tone !== "custom" && (
                  <option value={current.tone}>{current.tone}</option>
                )}
                {TONES.map((tone) => (
                  <option key={tone} value={tone}>
                    {t(`play.tone.${tone}`)}
                  </option>
                ))}
                <option value="custom">{t("play.tone.custom")}</option>
              </select>
              {current.tone === "custom" && (
                <>
                  <label htmlFor="play-custom-tone" className="visually-hidden">
                    {t("play.customTone")}
                  </label>
                  <textarea
                    id="play-custom-tone"
                    data-testid="custom-tone"
                    rows={4}
                    maxLength={CUSTOM_TONE_CHARS}
                    value={ownTone ?? current.custom_tone ?? ""}
                    placeholder={t("play.customTonePlaceholder")}
                    onChange={(e) => setOwnTone(e.target.value)}
                    onBlur={() => {
                      if (ownTone !== null && ownTone.trim() !== (current.custom_tone ?? "")) change({ custom_tone: ownTone.trim() });
                      setOwnTone(null);
                    }}
                  />
                  <p className="hint">{t("play.customToneHint")}</p>
                </>
              )}
              <label htmlFor="play-detail">{t("play.detail")}</label>
              <select id="play-detail" value={current.detail} onChange={(e) => change({ detail: Number(e.target.value) })}>
                {DETAILS.map((level) => (
                  <option key={level} value={level}>
                    {t(`play.detail.${level}`)}
                  </option>
                ))}
              </select>
              <label htmlFor="play-effort">{t("play.effort")}</label>
              <select
                id="play-effort"
                value={current.effort ?? ""}
                onChange={(e) => change({ effort: (e.target.value || null) as Effort | null })}
              >
                <option value="">{t("play.effortDefault")}</option>
                {EFFORTS.map((effort) => (
                  <option key={effort} value={effort}>
                    {t(`effort.${effort}`)}
                  </option>
                ))}
              </select>
              <label className="check">
                <input
                  type="checkbox"
                  aria-describedby="play-show-dice-hint"
                  checked={current.show_dice ?? true}
                  onChange={(e) => change({ show_dice: e.target.checked })}
                />
                {t("play.showDice")}
              </label>
              <p className="hint" id="play-show-dice-hint">
                {t("play.showDiceHint")}
              </p>
              <label htmlFor="play-enemy-dice">{t("play.enemyDice")}</label>
              <select
                id="play-enemy-dice"
                aria-describedby="play-enemy-dice-hint"
                disabled={current.show_dice === false}
                value={current.enemy_dice ?? "screen"}
                onChange={(e) => change({ enemy_dice: e.target.value as EnemyDice })}
              >
                {ENEMY_DICE.map((shown) => (
                  <option key={shown} value={shown}>
                    {t(`play.enemyDice.${shown}`)}
                  </option>
                ))}
              </select>
              <p className="hint" id="play-enemy-dice-hint">
                {t("play.enemyDiceHint")}
              </p>
              <label className="check">
                <input
                  type="checkbox"
                  aria-describedby="play-talk-pictures-hint"
                  checked={current.talk_pictures ?? false}
                  onChange={(e) => change({ talk_pictures: e.target.checked })}
                />
                {t("play.talkPictures")}
              </label>
              <p className="hint" id="play-talk-pictures-hint">
                {t("play.talkPicturesHint")}
              </p>
              <fieldset className="xp-awards" data-testid="xp-awards">
                <legend>{t("play.xpAwards")}</legend>
                {XP_AWARDS.map((name) => (
                  <label key={name} className="check">
                    <input
                      type="checkbox"
                      checked={current.xp_awards?.includes(name) ?? false}
                      onChange={(e) => award(name, e.target.checked)}
                    />
                    {t(`play.xpAward.${name}`)}
                  </label>
                ))}
              </fieldset>
              {save.isError && (
                <p className="notice error" role="alert">
                  {save.error.message}
                </p>
              )}
            </>
          )}
        </div>
      )}
    </div>
  );
}
