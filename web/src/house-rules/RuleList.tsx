import { useState } from "react";
import { PHASES, RULE_KINDS, type HouseRule } from "../api";
import { useT } from "../i18n";

/** The library of house rules, grouped by kind, with a filter over title, subject and text. */
export default function RuleList({
  rules,
  selectedId,
  onSelect,
}: {
  rules: HouseRule[];
  selectedId?: string;
  onSelect: (id: string) => void;
}) {
  const t = useT();
  const [filter, setFilter] = useState("");
  const wanted = filter.trim().toLowerCase();
  const shown = wanted
    ? rules.filter((r) => [r.title, r.subject ?? "", r.body_md].some((text) => text.toLowerCase().includes(wanted)))
    : rules;

  return (
    <div className="rule-list">
      <div className="field">
        <label htmlFor="rule-filter">{t("ruleList.filter")}</label>
        <input id="rule-filter" type="search" value={filter} onChange={(e) => setFilter(e.target.value)} />
      </div>
      {wanted && shown.length === 0 && (
        <p className="placeholder">{t("ruleList.noMatch", { filter: filter.trim() })}</p>
      )}
      {RULE_KINDS.map((kind) => {
        const group = shown.filter((r) => r.kind === kind);
        if (group.length === 0) return null;
        return (
          <section key={kind} className="rule-group">
            <h3>{t("ruleList.group", { kind: t(`kinds.${kind}`), count: String(group.length) })}</h3>
            <ul>
              {group.map((rule) => (
                <li key={rule.id}>
                  <button
                    type="button"
                    className={rule.enabled ? "rule-pick" : "rule-pick off"}
                    aria-current={rule.id === selectedId ? "true" : undefined}
                    onClick={() => onSelect(rule.id)}
                  >
                    <span className="rule-pick-title">{rule.title}</span>
                    <span className="rule-pick-meta">
                      {PHASES.filter((p) => rule.phases.includes(p))
                        .map((p) => t(`phase.${p}`))
                        .join(", ")}
                      {!rule.enabled && <span className="tag">{t("ruleList.off")}</span>}
                    </span>
                  </button>
                </li>
              ))}
            </ul>
          </section>
        );
      })}
    </div>
  );
}
