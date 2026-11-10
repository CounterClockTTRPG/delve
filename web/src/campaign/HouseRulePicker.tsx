import { useQuery } from "@tanstack/react-query";
import { RULE_KINDS, listBundles, listHouseRules, queryKeys, type CampaignHouseRules, type HouseRule } from "../api";
import { useT } from "../i18n";

/** The ruleset and setting a rule is tied to, as written; the server leaves it out of campaigns on another. */
const tags = (rule: HouseRule) => [rule.ruleset, rule.setting].filter(Boolean).join(", ");

/** Chooses a campaign's house rules: whole bundles, and single rules besides. Used by New campaign and the campaign page. */
export default function HouseRulePicker({
  value,
  onChange,
  disabled = false,
}: {
  value: CampaignHouseRules;
  onChange: (value: CampaignHouseRules) => void;
  disabled?: boolean;
}) {
  const t = useT();
  const rules = useQuery({ queryKey: queryKeys.houseRules, queryFn: listHouseRules });
  const bundles = useQuery({ queryKey: queryKeys.bundles, queryFn: listBundles });
  const toggled = (ids: string[], id: string, on: boolean) => (on ? [...ids, id] : ids.filter((i) => i !== id));

  if (!rules.data || !bundles.data) {
    return <p className="placeholder">{t("picker.loading")}</p>;
  }
  if (rules.data.length === 0 && bundles.data.length === 0) {
    return <p className="hint">{t("picker.none")}</p>;
  }

  return (
    <fieldset className="picker" disabled={disabled}>
      <legend>{t("picker.legend")}</legend>
      {bundles.data.length > 0 && (
        <div className="picker-group">
          <h3>{t("picker.bundles")}</h3>
          {bundles.data.map((bundle) => (
            <label key={bundle.id} className="check">
              <input
                type="checkbox"
                checked={value.bundle_ids.includes(bundle.id)}
                onChange={(e) =>
                  onChange({ ...value, bundle_ids: toggled(value.bundle_ids, bundle.id, e.target.checked) })
                }
              />
              {bundle.title}
              <span className="row-meta">{t("houseRules.ruleCount", { count: String(bundle.rule_ids.length) })}</span>
            </label>
          ))}
        </div>
      )}
      {rules.data.length > 0 && (
        <details className="picker-group">
          <summary>{t("picker.rules")}</summary>
          {RULE_KINDS.map((kind) => {
            const group = rules.data.filter((r) => r.kind === kind);
            if (group.length === 0) return null;
            return (
              <div key={kind}>
                <h4>{t(`kinds.${kind}`)}</h4>
                {group.map((rule) => (
                  <label key={rule.id} className="check">
                    <input
                      type="checkbox"
                      checked={value.rule_ids.includes(rule.id)}
                      onChange={(e) =>
                        onChange({ ...value, rule_ids: toggled(value.rule_ids, rule.id, e.target.checked) })
                      }
                    />
                    {rule.title}
                    {tags(rule) && <span className="row-meta">{tags(rule)}</span>}
                  </label>
                ))}
              </div>
            );
          })}
        </details>
      )}
    </fieldset>
  );
}
