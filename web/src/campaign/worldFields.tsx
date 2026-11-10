// The fields and row buttons the campaign page's world tables share (plan 6 Task 12): Factions and clocks, Quests
// and Possessions. A DM-only field carries the "DM only" mark beside its label.
import { useId, type ReactNode } from "react";
import { useConfirm } from "../components/dialogs";
import { useT } from "../i18n";

function Label({ id, label, dmOnly }: { id: string; label: string; dmOnly?: boolean }) {
  const t = useT();
  return (
    <label htmlFor={id}>
      {label}
      {dmOnly && <span className="dm-only-mark"> {t("sheet.forTheDm")}</span>}
    </label>
  );
}

export function TextField(props: {
  label: string;
  value: string;
  onChange: (value: string) => void;
  dmOnly?: boolean;
  multiline?: boolean;
}) {
  const id = useId();
  return (
    <div className="field">
      <Label id={id} label={props.label} dmOnly={props.dmOnly} />
      {props.multiline ? (
        <textarea id={id} rows={3} value={props.value} onChange={(e) => props.onChange(e.target.value)} />
      ) : (
        <input id={id} value={props.value} onChange={(e) => props.onChange(e.target.value)} />
      )}
    </div>
  );
}

export function NumberField(props: {
  label: string;
  value: number | null;
  onChange: (value: number | null) => void;
  dmOnly?: boolean;
  min?: number;
  max?: number;
}) {
  const id = useId();
  return (
    <div className="field">
      <Label id={id} label={props.label} dmOnly={props.dmOnly} />
      <input
        id={id}
        type="number"
        min={props.min}
        max={props.max}
        value={props.value ?? ""}
        onChange={(e) => props.onChange(e.target.value === "" ? null : Number(e.target.value))}
      />
    </div>
  );
}

export function SelectField(props: {
  label: string;
  value: string;
  options: { value: string; label: string }[];
  onChange: (value: string) => void;
  dmOnly?: boolean;
}) {
  const id = useId();
  return (
    <div className="field">
      <Label id={id} label={props.label} dmOnly={props.dmOnly} />
      <select id={id} value={props.value} onChange={(e) => props.onChange(e.target.value)}>
        {props.options.map((o) => (
          <option key={o.value} value={o.value}>
            {o.label}
          </option>
        ))}
      </select>
    </div>
  );
}

export function CheckField(props: { label: string; checked: boolean; onChange: (checked: boolean) => void }) {
  return (
    <label className="check-field">
      <input type="checkbox" checked={props.checked} onChange={(e) => props.onChange(e.target.checked)} />
      {props.label}
    </label>
  );
}

/** A record's form under its row: the fields, then Save and Cancel. */
export function RecordForm({
  children,
  busy,
  onSave,
  onCancel,
}: {
  children: ReactNode;
  busy: boolean;
  onSave: () => void;
  onCancel: () => void;
}) {
  const t = useT();
  return (
    <form
      className="world-form"
      onSubmit={(e) => {
        e.preventDefault();
        onSave();
      }}
    >
      <div className="world-form-fields">{children}</div>
      <div className="actions">
        <button type="submit" className="primary" disabled={busy}>
          {t("world.save")}
        </button>
        <button type="button" onClick={onCancel}>
          {t("dialog.cancel")}
        </button>
      </div>
    </form>
  );
}

/** Edit and Delete for a row named `name`; Delete asks first. */
export function RowActions({ name, busy, onEdit, onDelete }: { name: string; busy: boolean; onEdit: () => void; onDelete: () => void }) {
  const t = useT();
  const confirm = useConfirm();
  return (
    <span className="row-actions">
      <button type="button" aria-label={t("world.editNamed", { name })} disabled={busy} onClick={onEdit}>
        {t("world.edit")}
      </button>
      <button
        type="button"
        className="danger"
        aria-label={t("world.deleteNamed", { name })}
        disabled={busy}
        onClick={async () =>
          (await confirm({ title: t("world.deleteConfirm", { name }), confirm: t("dialog.delete"), danger: true })) && onDelete()
        }
      >
        {t("dialog.delete")}
      </button>
    </span>
  );
}

/** A refusal from the server, shown where the table is. */
export function Failed({ error }: { error: Error | null }) {
  if (!error) return null;
  return (
    <p role="alert" className="notice error">
      {error.message}
    </p>
  );
}

/** An id made of a name, as the server makes one: lowercase, its spaces as hyphens. */
export const slug = (name: string) => name.trim().toLowerCase().split(/\s+/).filter(Boolean).join("-");
