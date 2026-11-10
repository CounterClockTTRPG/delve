import { useMutation } from "@tanstack/react-query";
import { useId, useState, type FormEvent } from "react";
import { NeedsToken } from "../api";
import { useT } from "../i18n";
import { putPage, type SettingPage } from "./api";
import styles from "./Setting.module.css";

type Row = { key: string; value: string };

/**
 * A setting page to write: a new one (`page` null, the title free) or a change to one (prefilled, its title fixed).
 * Saving an existing shipped page makes an override; the server keeps the book's page to revert to.
 */
export default function PageForm({
  settingId,
  kinds,
  page,
  initialTitle = "",
  onSaved,
  onCancel,
}: {
  settingId: string;
  kinds: string[];
  page: SettingPage | null;
  initialTitle?: string;
  onSaved: (page: SettingPage) => void;
  onCancel?: () => void;
}) {
  const t = useT();
  const id = useId();
  const [title, setTitle] = useState(page?.title ?? initialTitle);
  const [kind, setKind] = useState(page?.kind ?? "");
  const [rows, setRows] = useState<Row[]>(() => Object.entries(page?.fields ?? {}).map(([key, value]) => ({ key, value })));
  const [text, setText] = useState(page?.text ?? "");
  const [dmOnly, setDmOnly] = useState(page?.dm_only ?? false);
  const save = useMutation({
    mutationFn: () =>
      putPage(settingId, title.trim(), {
        kind,
        fields: Object.fromEntries(rows.filter((r) => r.key.trim()).map((r) => [r.key.trim(), r.value])),
        text,
        dm_only: dmOnly,
      }),
    onSuccess: onSaved,
  });
  // A page's kind the setting no longer offers is still shown, so a save keeps it.
  const options = kind && !kinds.includes(kind) ? [...kinds, kind] : kinds;
  const setRow = (i: number, change: Partial<Row>) => setRows((old) => old.map((r, j) => (j === i ? { ...r, ...change } : r)));

  const submit = (e: FormEvent) => {
    e.preventDefault();
    if (title.trim()) save.mutate();
  };

  return (
    <form className={styles.form} onSubmit={submit}>
      <div className="field">
        <label htmlFor={`${id}-title`}>{t("setting.form.title")}</label>
        <input id={`${id}-title`} value={title} readOnly={page !== null} required onChange={(e) => setTitle(e.target.value)} />
      </div>

      <div className="field">
        <label htmlFor={`${id}-kind`}>{t("setting.form.kind")}</label>
        <select id={`${id}-kind`} value={kind} onChange={(e) => setKind(e.target.value)}>
          <option value="">{t("setting.form.noKind")}</option>
          {options.map((k) => (
            <option key={k} value={k}>
              {k}
            </option>
          ))}
        </select>
      </div>

      <fieldset className={`field ${styles.fields}`}>
        <legend>{t("setting.form.fields")}</legend>
        {rows.map((row, i) => (
          <div key={i} className={styles.fieldRow}>
            <input aria-label={t("setting.form.fieldName")} value={row.key} onChange={(e) => setRow(i, { key: e.target.value })} />
            <input aria-label={t("setting.form.fieldValue")} value={row.value} onChange={(e) => setRow(i, { value: e.target.value })} />
            <button type="button" onClick={() => setRows((old) => old.filter((_, j) => j !== i))}>
              {t("setting.form.removeField")}
            </button>
          </div>
        ))}
        <button type="button" onClick={() => setRows((old) => [...old, { key: "", value: "" }])}>
          {t("setting.form.addField")}
        </button>
      </fieldset>

      <div className="field">
        <label htmlFor={`${id}-text`}>{t("setting.form.text")}</label>
        <textarea id={`${id}-text`} rows={14} value={text} onChange={(e) => setText(e.target.value)} />
        <span className="hint">{t("setting.dmSectionHint")}</span>
      </div>

      <label className="check">
        <input type="checkbox" checked={dmOnly} onChange={(e) => setDmOnly(e.target.checked)} />
        {t("setting.form.dmOnly")}
      </label>

      {save.error && !(save.error instanceof NeedsToken) && (
        <p role="alert" className="notice error">
          {t("setting.saveFailed", { error: save.error.message })}
        </p>
      )}

      <div className="actions">
        <button type="submit" className="primary" disabled={save.isPending || !title.trim()}>
          {t("setting.form.save")}
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
