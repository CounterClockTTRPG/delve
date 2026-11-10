import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useEffect, useId, useState } from "react";
import { NeedsToken, queryKeys, type Campaign, type Visibility } from "../api";
import { useT } from "../i18n";
import { renderMarkdown } from "../play/markdown";
import { DESCRIPTION_CHARS, MAX_SLOTS, putListing } from "./tableSettings";
import styles from "./TableSettings.module.css";

const VISIBILITIES: Visibility[] = ["private", "public"];

/**
 * The table's listing on the campaign page (DEL-204): who can find the table (only through the invite link, or listed
 * for the accounts on this Delve), how many places it has for players (the host and observers take none; empty for no
 * limit), and a description for players, in Markdown with a preview: how they play together, what they expect of each
 * other, whether newcomers are welcome. The DM never reads it; what the DM should follow goes in the custom tone. Saved
 * with Save; a campaign from an older server shows the defaults.
 */
export default function TableListing({ campaign }: { campaign: Campaign }) {
  const t = useT();
  const client = useQueryClient();
  const visibilityId = useId();
  const slotsId = useId();
  const descriptionId = useId();
  const [visibility, setVisibility] = useState<Visibility>(campaign.visibility ?? "private");
  const [slots, setSlots] = useState(campaign.slots == null ? "" : String(campaign.slots));
  const [description, setDescription] = useState(campaign.description ?? "");
  const [preview, setPreview] = useState(false);
  // The campaign as read again (another tab saved it): the form follows it.
  useEffect(() => {
    setVisibility(campaign.visibility ?? "private");
    setSlots(campaign.slots == null ? "" : String(campaign.slots));
    setDescription(campaign.description ?? "");
  }, [campaign.visibility, campaign.slots, campaign.description]);

  const places = slots.trim() === "" ? null : Number(slots);
  const placesOk = places === null || (Number.isInteger(places) && places >= 1 && places <= MAX_SLOTS);
  const changed =
    visibility !== (campaign.visibility ?? "private") ||
    places !== (campaign.slots ?? null) ||
    description !== (campaign.description ?? "");
  const save = useMutation({
    mutationFn: () => putListing(campaign.id, { visibility, description: description.trim(), slots: places }),
    onSuccess: () => {
      client.invalidateQueries({ queryKey: queryKeys.campaign(campaign.id) });
      client.invalidateQueries({ queryKey: queryKeys.campaigns });
    },
  });

  return (
    <form
      className={styles.listing}
      data-testid="table-listing"
      onSubmit={(e) => {
        e.preventDefault();
        if (placesOk && changed) save.mutate();
      }}
    >
      <div className={styles.settings}>
        <fieldset className={`field ${styles.setting}`} role="radiogroup" aria-labelledby={visibilityId}>
          <legend id={visibilityId}>{t("listing.visibility")}</legend>
          <div className={styles.options}>
            {VISIBILITIES.map((value) => (
              <label key={value} className="check">
                <input
                  type="radio"
                  name={`${visibilityId}-visibility`}
                  value={value}
                  checked={visibility === value}
                  onChange={() => setVisibility(value)}
                />
                {t(`listing.${value}`)}
              </label>
            ))}
          </div>
          <p className="hint">{t(visibility === "public" ? "listing.publicHint" : "listing.privateHint")}</p>
        </fieldset>
        <div className={`field ${styles.setting}`}>
          <label htmlFor={slotsId}>{t("listing.slots")}</label>
          <input
            id={slotsId}
            type="number"
            inputMode="numeric"
            min={1}
            max={MAX_SLOTS}
            value={slots}
            placeholder={t("listing.noLimit")}
            aria-invalid={!placesOk}
            className={styles.slots}
            onChange={(e) => setSlots(e.target.value)}
          />
          <p className="hint">{t(placesOk ? "listing.slotsHint" : "listing.slotsRange", { max: String(MAX_SLOTS) })}</p>
        </div>
      </div>

      <div className="field">
        <div className={styles.descriptionHead}>
          <label htmlFor={descriptionId}>{t("listing.description")}</label>
          <button type="button" className="link-button" aria-pressed={preview} onClick={() => setPreview(!preview)}>
            {t(preview ? "listing.edit" : "listing.preview")}
          </button>
        </div>
        {preview ? (
          <div
            className={`markdown ${styles.preview}`}
            data-testid="listing-preview"
            dangerouslySetInnerHTML={{ __html: renderMarkdown(description.trim() || t("listing.noDescription")) }}
          />
        ) : (
          <textarea
            id={descriptionId}
            rows={6}
            maxLength={DESCRIPTION_CHARS}
            value={description}
            placeholder={t("listing.descriptionPlaceholder")}
            onChange={(e) => setDescription(e.target.value)}
          />
        )}
        <p className="hint">{t("listing.descriptionHint")}</p>
      </div>

      <div className={styles.actions}>
        <button type="submit" className="primary" data-testid="listing-save" disabled={!changed || !placesOk || save.isPending}>
          {t("listing.save")}
        </button>
        {save.isSuccess && !changed && (
          <span className="hint" role="status">
            {t("listing.saved")}
          </span>
        )}
      </div>
      {save.error && !(save.error instanceof NeedsToken) && (
        <p role="alert" className="notice error">
          {t("listing.saveFailed", { error: save.error.message })}
        </p>
      )}
    </form>
  );
}
