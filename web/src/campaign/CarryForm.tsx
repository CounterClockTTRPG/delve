import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState, type FormEvent } from "react";
import { useNavigate } from "react-router-dom";
import { toast } from "sonner";
import {
  NeedsToken,
  carryCampaign,
  getCampaignHouseRules,
  getWorlds,
  listModules,
  queryKeys,
  type CampaignDetail,
  type CampaignHouseRules,
  type CampaignWorld,
  type Character,
} from "../api";
import { useT } from "../i18n";
import { sortModules } from "../module/sort";
import HouseRulePicker from "./HouseRulePicker";

/** -10 hit points is dead (`delve.play.characters.DEAD_AT`). */
const DEAD_AT = -10;

export const isDead = (character: Character) => character.state.hp <= DEAD_AT;

/**
 * Carry the party on (carry-the-party-on plan Task 7): a new campaign on a module that isn't a draft, with the PCs
 * ticked here (the living by default; the dead listed, unticked) and all the party owns. The name, the ruleset, the
 * setting and the house rules start as the old campaign's. On success it opens the new campaign's page, where its
 * history is being written; a refusal (a live fight: "End the fight first.") shows as an error.
 */
export default function CarryForm({
  campaign,
  characters,
  onCancel,
}: {
  campaign: CampaignDetail;
  characters: Character[];
  onCancel: () => void;
}) {
  const t = useT();
  const client = useQueryClient();
  const navigate = useNavigate();
  const pcs = characters.filter((c) => c.kind === "pc");
  const modules = useQuery({ queryKey: queryKeys.modules, queryFn: listModules });
  const worlds = useQuery({ queryKey: queryKeys.worlds, queryFn: getWorlds });
  const stored = useQuery({
    queryKey: queryKeys.campaignHouseRules(campaign.id),
    queryFn: () => getCampaignHouseRules(campaign.id),
  });
  const [name, setName] = useState(campaign.name);
  const [moduleId, setModuleId] = useState("");
  const [world, setWorld] = useState<CampaignWorld>({ ruleset: campaign.ruleset, setting: campaign.setting });
  const [houseRules, setHouseRules] = useState<CampaignHouseRules | null>(null);
  const [going, setGoing] = useState(() => new Set(pcs.filter((c) => !isDead(c)).map((c) => c.id)));
  // A draft can't start a campaign until it is marked ready, so it isn't offered; the rest by title (DEL-246), and
  // another module than this one chosen first.
  const playable = modules.data && sortModules(modules.data.filter((m) => !m.draft), "title");
  const chosen = moduleId || (playable?.find((m) => m.id !== campaign.module_id) ?? playable?.[0])?.id || "";
  const rules = houseRules ?? stored.data ?? null;

  const carry = useMutation({
    mutationFn: () =>
      carryCampaign(campaign.id, {
        name: name.trim(),
        module_id: chosen,
        // In the marching order, as the sheets are listed.
        character_ids: pcs.filter((c) => going.has(c.id)).map((c) => c.id),
        ...world,
        ...rules!,
      }),
    onSuccess: (made) => {
      client.invalidateQueries({ queryKey: queryKeys.campaigns });
      client.invalidateQueries({ queryKey: queryKeys.campaign(campaign.id) });
      client.invalidateQueries({ queryKey: queryKeys.conversions });
      toast(t("carry.done", { name: made.name }));
      navigate(`/campaigns/${encodeURIComponent(made.id)}`);
    },
  });

  const submit = (e: FormEvent) => {
    e.preventDefault();
    if (ready) carry.mutate();
  };
  const tick = (id: string, on: boolean) =>
    setGoing((was) => {
      const next = new Set(was);
      if (on) next.add(id);
      else next.delete(id);
      return next;
    });

  const ready = name.trim() !== "" && chosen !== "" && going.size > 0 && rules !== null && !!worlds.data;
  const loadError = [modules.error, worlds.error, stored.error].find((e) => e && !(e instanceof NeedsToken));
  return (
    <section className="carry-form" aria-labelledby="carry-title">
      <h2 id="carry-title">{t("carry.title")}</h2>
      <p className="lede">{t("carry.intro")}</p>
      {loadError && (
        <p role="alert" className="notice error">
          {t("campaign.loadFailed", { error: loadError.message })}
        </p>
      )}
      <form onSubmit={submit}>
        <div className="inline-form">
          <div className="field">
            <label htmlFor="carry-name">{t("carry.name")}</label>
            <input id="carry-name" value={name} onChange={(e) => setName(e.target.value)} />
          </div>
          <div className="field">
            <label htmlFor="carry-module">{t("campaigns.module")}</label>
            <select id="carry-module" value={chosen} onChange={(e) => setModuleId(e.target.value)} disabled={!playable?.length}>
              {playable?.map((m) => (
                <option key={m.id} value={m.id}>
                  {m.title}
                </option>
              ))}
            </select>
          </div>
          {worlds.data && (
            <>
              <div className="field">
                <label htmlFor="carry-ruleset">{t("campaigns.ruleset")}</label>
                <select id="carry-ruleset" value={world.ruleset} onChange={(e) => setWorld({ ...world, ruleset: e.target.value })}>
                  {worlds.data.rulesets.map((r) => (
                    <option key={r.id} value={r.id}>
                      {r.title}
                    </option>
                  ))}
                </select>
              </div>
              <div className="field">
                <label htmlFor="carry-setting">{t("campaigns.setting")}</label>
                <select
                  id="carry-setting"
                  value={world.setting ?? ""}
                  onChange={(e) => setWorld({ ...world, setting: e.target.value || null })}
                >
                  {worlds.data.settings.map((s) => (
                    <option key={s.id} value={s.id}>
                      {s.title}
                    </option>
                  ))}
                  <option value="">{t("campaigns.noSetting")}</option>
                </select>
              </div>
            </>
          )}
        </div>
        {playable?.length === 0 && <p className="hint">{t("carry.noModules")}</p>}

        <fieldset className="carry-party">
          <legend>{t("carry.characters")}</legend>
          {pcs.length === 0 && <p className="placeholder">{t("carry.noPcs")}</p>}
          {pcs.map((c) => (
            <label key={c.id} className={isDead(c) ? "check dead" : "check"}>
              <input type="checkbox" checked={going.has(c.id)} onChange={(e) => tick(c.id, e.target.checked)} />
              {c.name}
              {isDead(c) && <span className="tag">{t("carry.dead")}</span>}
            </label>
          ))}
        </fieldset>

        {rules ? (
          <HouseRulePicker value={rules} onChange={setHouseRules} disabled={carry.isPending} />
        ) : (
          <p className="placeholder">{t("houseRules.loading")}</p>
        )}

        {carry.error && !(carry.error instanceof NeedsToken) && (
          <p role="alert" className="notice error">
            {t("carry.failed", { error: carry.error.message })}
          </p>
        )}
        <div className="actions">
          <button type="submit" className="primary" disabled={!ready || carry.isPending}>
            {t("carry.submit")}
          </button>
          <button type="button" onClick={onCancel}>
            {t("dialog.cancel")}
          </button>
        </div>
      </form>
    </section>
  );
}
