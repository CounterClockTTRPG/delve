import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useEffect, useId, useState } from "react";
import { NeedsToken, queryKeys, type Campaign, type TableCharacter } from "../api";
import { useT } from "../i18n";
import { usePhone } from "../play/usePhone";
import {
  DEPARTURES,
  INITIATIVE_MODES,
  OBSERVER_RULES,
  VOICE_SETTINGS,
  putDeparture,
  putTableSettings,
  type Departure,
  type TableSettingsChange,
} from "./tableSettings";
import styles from "./TableSettings.module.css";

const VOICE_LABELS = { allowed: "tableSettings.voiceAllowed", off: "tableSettings.voiceOff" } as const;
const INITIATIVE_LABELS = { combatant: "tableSettings.perCombatant", side: "tableSettings.perSide" } as const;
const OBSERVER_LABELS = {
  anyone: "tableSettings.observersAnyone",
  approved: "tableSettings.observersApproved",
  nobody: "tableSettings.observersNobody",
} as const;

/** The host's table settings on the campaign page (table voice and fixes Task S2): Voice allowed or off (off disconnects
 * everyone in voice), Initiative per combatant or per side (from a fight's next round) and who may watch (DEL-215),
 * each saved as it is chosen.
 * Side by side on a desktop, stacked on a phone. A campaign from an older server shows the defaults. */
export default function TableSettings({ campaign }: { campaign: Campaign }) {
  const t = useT();
  const client = useQueryClient();
  const phone = usePhone();
  const voiceId = useId();
  const initiativeId = useId();
  const observersId = useId();
  const save = useMutation({
    mutationFn: (change: TableSettingsChange) => putTableSettings(campaign.id, change),
    onSuccess: () => {
      client.invalidateQueries({ queryKey: queryKeys.campaign(campaign.id) });
      client.invalidateQueries({ queryKey: queryKeys.campaigns });
    },
  });
  // What is being saved shows at once, then the server's answer until the page has read the campaign again; a refusal
  // falls back to what the server has.
  const shown = save.isPending ? save.variables : save.data;
  const voice = shown?.voice ?? campaign.voice ?? "allowed";
  const initiative = shown?.initiative ?? campaign.initiative ?? "combatant";
  const observers = shown?.observers ?? campaign.observers ?? "anyone";
  const { reset } = save;
  useEffect(() => reset(), [reset, campaign.voice, campaign.initiative, campaign.observers]);
  return (
    <div className={styles.settings} data-testid="table-settings" data-layout={phone ? "stacked" : "row"}>
      <fieldset className={`field ${styles.setting}`} role="radiogroup" aria-labelledby={voiceId}>
        <legend id={voiceId}>{t("tableSettings.voice")}</legend>
        <div className={styles.options}>
          {VOICE_SETTINGS.map((value) => (
            <label key={value} className="check">
              <input
                type="radio"
                name={`${voiceId}-voice`}
                value={value}
                checked={voice === value}
                disabled={save.isPending}
                onChange={() => save.mutate({ voice: value })}
              />
              {t(VOICE_LABELS[value])}
            </label>
          ))}
        </div>
        <p className="hint">{t("tableSettings.voiceOffHint")}</p>
      </fieldset>
      <fieldset className={`field ${styles.setting}`} role="radiogroup" aria-labelledby={initiativeId}>
        <legend id={initiativeId}>{t("tableSettings.initiative")}</legend>
        <div className={styles.options}>
          {INITIATIVE_MODES.map((value) => (
            <label key={value} className="check">
              <input
                type="radio"
                name={`${initiativeId}-initiative`}
                value={value}
                checked={initiative === value}
                disabled={save.isPending}
                onChange={() => save.mutate({ initiative: value })}
              />
              {t(INITIATIVE_LABELS[value])}
            </label>
          ))}
        </div>
        <p className="hint">{t("tableSettings.nextRound")}</p>
      </fieldset>
      <fieldset className={`field ${styles.setting}`} role="radiogroup" aria-labelledby={observersId}>
        <legend id={observersId}>{t("tableSettings.observers")}</legend>
        <div className={styles.options}>
          {OBSERVER_RULES.map((value) => (
            <label key={value} className="check">
              <input
                type="radio"
                name={`${observersId}-observers`}
                value={value}
                checked={observers === value}
                disabled={save.isPending}
                onChange={() => save.mutate({ observers: value })}
              />
              {t(OBSERVER_LABELS[value])}
            </label>
          ))}
        </div>
        <p className="hint">{t("tableSettings.observersHint")}</p>
      </fieldset>
      {save.error && !(save.error instanceof NeedsToken) && (
        <p role="alert" className="notice error">
          {t("tableSettings.saveFailed", { error: save.error.message })}
        </p>
      )}
    </div>
  );
}

/** A PC's Leave the party in the campaign page's character list, beside Rename and Remove (which stays for mistakes):
 * Leave the party asks why (died, retired, left), and a PC that left shows why, with Return. An NPC has neither. The
 * change runs through the page's own `onChange`, which refreshes the campaign and shows a refusal. */
export function DepartureButtons({
  campaignId,
  character,
  busy,
  onChange,
}: {
  campaignId: string;
  character: TableCharacter;
  busy: boolean;
  onChange: (run: () => Promise<unknown>) => void;
}) {
  const t = useT();
  const reasonId = useId();
  const [asking, setAsking] = useState(false);
  const [reason, setReason] = useState<Departure>("died");
  if (character.kind !== "pc") return null;
  const departure = "departure" in character ? character.departure : null;
  const send = (next: Departure | null) => onChange(() => putDeparture(campaignId, character.id, next));
  if (departure) {
    return (
      <span className={styles.departure}>
        <span className={`row-meta ${styles.reason}`}>{t(`tableSettings.reason.${departure}`)}</span>
        <button type="button" disabled={busy} onClick={() => send(null)}>
          {t("tableSettings.return")}
        </button>
      </span>
    );
  }
  if (!asking) {
    return (
      <button type="button" disabled={busy} onClick={() => setAsking(true)}>
        {t("tableSettings.leave")}
      </button>
    );
  }
  return (
    <form
      className={styles.departure}
      onSubmit={(e) => {
        e.preventDefault();
        setAsking(false);
        send(reason);
      }}
    >
      <label htmlFor={reasonId} className="visually-hidden">
        {t("tableSettings.why", { name: character.name })}
      </label>
      <select id={reasonId} value={reason} onChange={(e) => setReason(e.target.value as Departure)}>
        {DEPARTURES.map((value) => (
          <option key={value} value={value}>
            {t(`tableSettings.reason.${value}`)}
          </option>
        ))}
      </select>
      <button type="submit" className="danger" disabled={busy}>
        {t("tableSettings.leaveConfirm")}
      </button>
      <button type="button" onClick={() => setAsking(false)}>
        {t("dialog.cancel")}
      </button>
    </form>
  );
}
