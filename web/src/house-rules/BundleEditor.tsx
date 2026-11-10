import { ArrowDown, ArrowUp, X } from "lucide-react";
import { useState, type FormEvent } from "react";
import type { BundleInput, HouseRule } from "../api";
import Tip from "../components/Tip";
import { useT } from "../i18n";

/** Edits one bundle: its title, description, and the ordered list of its rules, with add, remove and arrows. */
export default function BundleEditor({
  bundle,
  rules,
  busy = false,
  onSave,
  onDelete,
}: {
  bundle: BundleInput;
  /** The whole library, to name the bundle's rules and offer the others. */
  rules: HouseRule[];
  busy?: boolean;
  onSave: (bundle: BundleInput) => void;
  onDelete?: () => void;
}) {
  const t = useT();
  const [title, setTitle] = useState(bundle.title);
  const [description, setDescription] = useState(bundle.description_md);
  const [ruleIds, setRuleIds] = useState(bundle.rule_ids);
  const [adding, setAdding] = useState("");
  const byId = new Map(rules.map((r) => [r.id, r]));
  const others = rules.filter((r) => !ruleIds.includes(r.id));
  const toAdd = others.some((r) => r.id === adding) ? adding : (others[0]?.id ?? "");

  function move(index: number, by: -1 | 1) {
    const next = [...ruleIds];
    [next[index], next[index + by]] = [next[index + by], next[index]];
    setRuleIds(next);
  }

  function submit(e: FormEvent) {
    e.preventDefault();
    if (title.trim()) onSave({ title: title.trim(), description_md: description, rule_ids: ruleIds });
  }

  return (
    <form className="editor-form" onSubmit={submit}>
      <div className="field">
        <label htmlFor="bundle-title">{t("bundleEditor.title")}</label>
        <input id="bundle-title" value={title} onChange={(e) => setTitle(e.target.value)} />
      </div>
      <div className="field">
        <label htmlFor="bundle-description">{t("bundleEditor.description")}</label>
        <textarea
          id="bundle-description"
          rows={3}
          value={description}
          onChange={(e) => setDescription(e.target.value)}
        />
      </div>

      <h3 id="bundle-rules">{t("bundleEditor.rules")}</h3>
      {ruleIds.length === 0 ? (
        <p className="placeholder">{t("bundleEditor.empty")}</p>
      ) : (
        <ol className="bundle-rules" aria-labelledby="bundle-rules">
          {ruleIds.map((id, index) => {
            const name = byId.get(id)?.title ?? t("bundleEditor.missing");
            return (
              <li key={id} className="bundle-rule">
                <span className="bundle-rule-title">{name}</span>
                <span className="bundle-rule-kind">{byId.has(id) ? t(`kind.${byId.get(id)!.kind}`) : ""}</span>
                <Tip label={t("bundleEditor.up", { title: name })}>
                  <button
                    type="button"
                    className="icon"
                    aria-label={t("bundleEditor.up", { title: name })}
                    disabled={index === 0}
                    onClick={() => move(index, -1)}
                  >
                    <ArrowUp size={16} aria-hidden />
                  </button>
                </Tip>
                <Tip label={t("bundleEditor.down", { title: name })}>
                  <button
                    type="button"
                    className="icon"
                    aria-label={t("bundleEditor.down", { title: name })}
                    disabled={index === ruleIds.length - 1}
                    onClick={() => move(index, 1)}
                  >
                    <ArrowDown size={16} aria-hidden />
                  </button>
                </Tip>
                <Tip label={t("bundleEditor.remove", { title: name })}>
                  <button
                    type="button"
                    className="icon"
                    aria-label={t("bundleEditor.remove", { title: name })}
                    onClick={() => setRuleIds(ruleIds.filter((r) => r !== id))}
                  >
                    <X size={16} aria-hidden />
                  </button>
                </Tip>
              </li>
            );
          })}
        </ol>
      )}

      {others.length > 0 && (
        <div className="inline-form">
          <div className="field">
            <label htmlFor="bundle-add">{t("bundleEditor.add")}</label>
            <select id="bundle-add" value={toAdd} onChange={(e) => setAdding(e.target.value)}>
              {others.map((r) => (
                <option key={r.id} value={r.id}>
                  {r.title}
                </option>
              ))}
            </select>
          </div>
          <button type="button" disabled={!toAdd} onClick={() => setRuleIds([...ruleIds, toAdd])}>
            {t("bundleEditor.addButton")}
          </button>
        </div>
      )}

      <div className="actions">
        <button type="submit" className="primary" disabled={busy || !title.trim()}>
          {t("bundleEditor.save")}
        </button>
        {onDelete && (
          <button type="button" className="danger" disabled={busy} onClick={onDelete}>
            {t("bundleEditor.delete")}
          </button>
        )}
      </div>
    </form>
  );
}
