import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useId, useState, type FormEvent } from "react";
import { NeedsToken } from "../api";
import { useConfirm } from "../components/dialogs";
import { useT } from "../i18n";
import { addFact, deleteFact, getFacts, putFact, settingKeys, type FactInput, type SettingFact, type ShippedFact } from "./api";
import styles from "./Setting.module.css";

/**
 * A setting's facts: the install's own, each to edit or delete, with a form to add one; below them the book's,
 * read-only, by category.
 */
export default function FactsTab({ settingId }: { settingId: string }) {
  const t = useT();
  const id = useId();
  const client = useQueryClient();
  const confirm = useConfirm();
  const [editing, setEditing] = useState<number | null>(null);
  const facts = useQuery({ queryKey: settingKeys.facts(settingId), queryFn: () => getFacts(settingId) });
  // The setting's counts change with its facts, so its whole cache goes.
  const changed = () => client.invalidateQueries({ queryKey: settingKeys.one(settingId) });
  const add = useMutation({ mutationFn: (body: FactInput) => addFact(settingId, body), onSuccess: changed });
  const save = useMutation({
    mutationFn: ({ factId, body }: { factId: number; body: FactInput }) => putFact(settingId, factId, body),
    onSuccess: () => {
      setEditing(null);
      return changed();
    },
  });
  const remove = useMutation({ mutationFn: (factId: number) => deleteFact(settingId, factId), onSuccess: changed });
  const loadFailed = facts.error && !(facts.error instanceof NeedsToken) ? facts.error : null;
  const saveFailed = [add.error, save.error, remove.error].find((e) => e && !(e instanceof NeedsToken));

  const askDelete = async (fact: SettingFact) => {
    const sure = await confirm({ title: t("setting.facts.deleteConfirm", { text: fact.text }), confirm: t("setting.delete"), danger: true });
    if (sure) remove.mutate(fact.id);
  };

  return (
    <div className={styles.facts}>
      {loadFailed && (
        <p role="alert" className="notice error">
          {t("setting.loadFailed", { error: loadFailed.message })}
        </p>
      )}
      {saveFailed && (
        <p role="alert" className="notice error">
          {t("setting.saveFailed", { error: saveFailed.message })}
        </p>
      )}

      <section aria-labelledby={`${id}-own`}>
        <h2 id={`${id}-own`}>{t("setting.facts.own")}</h2>
        {facts.data &&
          (facts.data.own.length === 0 ? (
            <p className="placeholder">{t("setting.facts.empty")}</p>
          ) : (
            <ul className="rows">
              {facts.data.own.map((fact) => (
                <li key={fact.id} className="row">
                  {editing === fact.id ? (
                    <FactForm
                      fact={fact}
                      submit={t("setting.form.save")}
                      busy={save.isPending}
                      onSubmit={(body) => save.mutate({ factId: fact.id, body })}
                      onCancel={() => setEditing(null)}
                    />
                  ) : (
                    <>
                      <span className="row-title">{fact.text}</span>
                      {fact.category && <span className="row-meta">{fact.category}</span>}
                      {fact.dm_only && <span className="dm-only-mark">{t("setting.dmOnly")}</span>}
                      <span className="actions">
                        <button type="button" onClick={() => setEditing(fact.id)}>
                          {t("setting.edit")}
                        </button>
                        <button type="button" className="danger" disabled={remove.isPending} onClick={() => askDelete(fact)}>
                          {t("setting.delete")}
                        </button>
                      </span>
                    </>
                  )}
                </li>
              ))}
            </ul>
          ))}
        <FactForm submit={t("setting.facts.add")} busy={add.isPending} onSubmit={(body) => add.mutate(body)} clearOnSubmit />
      </section>

      {facts.data && facts.data.shipped.length > 0 && (
        <section aria-labelledby={`${id}-shipped`}>
          <h2 id={`${id}-shipped`}>{t("setting.facts.shipped")}</h2>
          {byCategory(facts.data.shipped).map(([category, rows]) => (
            <div key={category}>
              {category && <h3>{category}</h3>}
              <ul className="rows">
                {rows.map((fact) => (
                  <li key={fact.id} className="row">
                    {fact.text}
                  </li>
                ))}
              </ul>
            </div>
          ))}
        </section>
      )}
    </div>
  );
}

/** The book's facts grouped by category, in the order the categories first come. */
function byCategory(facts: ShippedFact[]): [string, ShippedFact[]][] {
  const groups = new Map<string, ShippedFact[]>();
  for (const fact of facts) groups.set(fact.category, [...(groups.get(fact.category) ?? []), fact]);
  return [...groups];
}

/** A fact to add (empty, cleared once sent) or to change (prefilled): its text, its category and DM only. */
function FactForm({
  fact,
  submit,
  busy,
  onSubmit,
  onCancel,
  clearOnSubmit = false,
}: {
  fact?: SettingFact;
  submit: string;
  busy: boolean;
  onSubmit: (body: FactInput) => void;
  onCancel?: () => void;
  clearOnSubmit?: boolean;
}) {
  const t = useT();
  const id = useId();
  const [text, setText] = useState(fact?.text ?? "");
  const [category, setCategory] = useState(fact?.category ?? "");
  const [dmOnly, setDmOnly] = useState(fact?.dm_only ?? false);
  const send = (e: FormEvent) => {
    e.preventDefault();
    if (!text.trim()) return;
    onSubmit({ text: text.trim(), category: category.trim(), dm_only: dmOnly });
    if (clearOnSubmit) {
      setText("");
      setCategory("");
      setDmOnly(false);
    }
  };
  return (
    <form className={styles.factForm} onSubmit={send}>
      <div className="field">
        <label htmlFor={`${id}-text`}>{t("setting.facts.text")}</label>
        <textarea id={`${id}-text`} rows={2} required value={text} onChange={(e) => setText(e.target.value)} />
      </div>
      <div className="field">
        <label htmlFor={`${id}-category`}>{t("setting.facts.category")}</label>
        <input id={`${id}-category`} value={category} onChange={(e) => setCategory(e.target.value)} />
      </div>
      <label className="check">
        <input type="checkbox" checked={dmOnly} onChange={(e) => setDmOnly(e.target.checked)} />
        {t("setting.form.dmOnly")}
      </label>
      <div className="actions">
        <button type="submit" className="primary" disabled={busy}>
          {submit}
        </button>
        {onCancel && (
          <button type="button" onClick={onCancel}>
            {t("dialog.cancel")}
          </button>
        )}
      </div>
    </form>
  );
}
