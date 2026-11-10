import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import {
  NeedsToken,
  createBundle,
  createHouseRule,
  deleteBundle,
  deleteHouseRule,
  importExampleHouseRules,
  listBundles,
  listHouseRules,
  queryKeys,
  updateBundle,
  updateHouseRule,
  type BundleInput,
  type HouseRuleInput,
} from "../api";
import { useConfirm } from "../components/dialogs";
import BundleEditor from "../house-rules/BundleEditor";
import RuleEditor from "../house-rules/RuleEditor";
import RuleList from "../house-rules/RuleList";
import { useT } from "../i18n";
import { usePhone } from "../play/usePhone";

type Selection =
  { type: "rule"; id: string } | { type: "bundle"; id: string } | { type: "new-rule" } | { type: "new-bundle" } | null;

const NEW_RULE: HouseRuleInput = {
  title: "",
  body_md: "",
  kind: "general",
  phases: [],
  ruleset: null,
  setting: null,
  subject: null,
  enabled: true,
};
const NEW_BUNDLE: BundleInput = { title: "", description_md: "", rule_ids: [] };

/**
 * `/house-rules`: the library of rules grouped by kind, the bundles, and an editor for the one picked. On a phone the
 * editor opens as its own view, with a link back to the library.
 */
export default function HouseRules() {
  const t = useT();
  const confirm = useConfirm();
  const client = useQueryClient();
  const rules = useQuery({ queryKey: queryKeys.houseRules, queryFn: listHouseRules });
  const bundles = useQuery({ queryKey: queryKeys.bundles, queryFn: listBundles });
  const [selection, setSelection] = useState<Selection>(null);
  const phone = usePhone();

  const save = useMutation({
    mutationFn: (run: () => Promise<{ id: string } | unknown>) => run(),
    onSuccess: () => client.invalidateQueries({ queryKey: queryKeys.houseRules }),
  });

  const saveRule = (id: string | null, input: HouseRuleInput) =>
    save.mutate(() => (id ? updateHouseRule(id, input) : createHouseRule(input)), {
      onSuccess: (saved) => setSelection({ type: "rule", id: (saved as { id: string }).id }),
    });
  const saveBundle = (id: string | null, input: BundleInput) =>
    save.mutate(() => (id ? updateBundle(id, input) : createBundle(input)), {
      onSuccess: (saved) => setSelection({ type: "bundle", id: (saved as { id: string }).id }),
    });
  const importExample = () =>
    save.mutate(importExampleHouseRules, {
      onSuccess: (imported) => setSelection({ type: "bundle", id: (imported as { id: string }).id }),
    });
  const remove = (run: () => Promise<unknown>) => save.mutate(run, { onSuccess: () => setSelection(null) });

  const loadError = [rules.error, bundles.error].find((e) => e && !(e instanceof NeedsToken));
  const failed = save.error && !(save.error instanceof NeedsToken) ? save.error : null;
  const rule = selection?.type === "rule" ? rules.data?.find((r) => r.id === selection.id) : undefined;
  const bundle = selection?.type === "bundle" ? bundles.data?.find((b) => b.id === selection.id) : undefined;

  function editor() {
    if (!rules.data || !bundles.data) return null;
    if (selection?.type === "new-rule")
      return (
        <RuleEditor key="new-rule" rule={NEW_RULE} busy={save.isPending} onSave={(input) => saveRule(null, input)} />
      );
    if (selection?.type === "new-bundle")
      return (
        <BundleEditor
          key="new-bundle"
          bundle={NEW_BUNDLE}
          rules={rules.data}
          busy={save.isPending}
          onSave={(input) => saveBundle(null, input)}
        />
      );
    if (rule)
      return (
        <RuleEditor
          key={rule.id}
          rule={rule}
          busy={save.isPending}
          onSave={(input) => saveRule(rule.id, input)}
          onDelete={async () =>
            (await confirm({ title: t("houseRules.deleteRuleConfirm", { title: rule.title }), confirm: t("dialog.delete"), danger: true })) &&
            remove(() => deleteHouseRule(rule.id))
          }
        />
      );
    if (bundle)
      return (
        <BundleEditor
          key={bundle.id}
          bundle={bundle}
          rules={rules.data}
          busy={save.isPending}
          onSave={(input) => saveBundle(bundle.id, input)}
          onDelete={async () =>
            (await confirm({ title: t("houseRules.deleteBundleConfirm", { title: bundle.title }), confirm: t("dialog.delete"), danger: true })) &&
            remove(() => deleteBundle(bundle.id))
          }
        />
      );
    return <p className="placeholder">{t("houseRules.pick")}</p>;
  }

  return (
    <section className="page house-rules-page">
      <h1>{t("area.houseRules")}</h1>
      <p className="lede">{t("houseRules.intro")}</p>
      {loadError && (
        <p role="alert" className="notice error">
          {t("houseRules.loadFailed", { error: loadError.message })}
        </p>
      )}
      {failed && (
        <p role="alert" className="notice error">
          {t("houseRules.saveFailed", { error: failed.message })}
        </p>
      )}
      {rules.data?.length === 0 && bundles.data?.length === 0 && (
        <div className="notice house-rules-empty">
          <p>{t("houseRules.emptyLibrary")}</p>
          <button type="button" disabled={save.isPending} onClick={importExample}>
            {t("houseRules.importExample")}
          </button>
        </div>
      )}
      {!rules.data || !bundles.data ? (
        !loadError && <p className="placeholder">{t("houseRules.loading")}</p>
      ) : (
        <div className="house-rules">
          {phone && selection ? null : (
            <aside className="house-rules-library">
              <section>
                <div className="toolbar">
                  <h2>{t("houseRules.bundles")}</h2>
                  <button type="button" onClick={() => setSelection({ type: "new-bundle" })}>
                    {t("houseRules.newBundle")}
                  </button>
                </div>
                {bundles.data.length === 0 ? (
                  <p className="placeholder">{t("houseRules.noBundles")}</p>
                ) : (
                  <ul className="bundle-list">
                    {bundles.data.map((b) => (
                      <li key={b.id}>
                        <button
                          type="button"
                          className="rule-pick"
                          aria-current={bundle?.id === b.id ? "true" : undefined}
                          onClick={() => setSelection({ type: "bundle", id: b.id })}
                        >
                          <span className="rule-pick-title">{b.title}</span>
                          <span className="rule-pick-meta">
                            {t("houseRules.ruleCount", { count: String(b.rule_ids.length) })}
                          </span>
                        </button>
                      </li>
                    ))}
                  </ul>
                )}
              </section>
              <section>
                <div className="toolbar">
                  <h2>{t("houseRules.rules")}</h2>
                  <button type="button" onClick={() => setSelection({ type: "new-rule" })}>
                    {t("houseRules.newRule")}
                  </button>
                </div>
                {rules.data.length === 0 ? (
                  <p className="placeholder">{t("houseRules.noRules")}</p>
                ) : (
                  <RuleList
                    rules={rules.data}
                    selectedId={rule?.id}
                    onSelect={(id) => setSelection({ type: "rule", id })}
                  />
                )}
              </section>
            </aside>
          )}
          {phone && !selection ? null : (
            <div className="house-rules-editor">
              {phone && (
                <button type="button" className="house-rules-back" onClick={() => setSelection(null)}>
                  {t("houseRules.back")}
                </button>
              )}
              {editor()}
            </div>
          )}
        </div>
      )}
    </section>
  );
}
