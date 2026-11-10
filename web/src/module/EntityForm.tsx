import { useMutation } from "@tanstack/react-query";
import { Fragment, useState, type ReactNode } from "react";
import {
  NeedsToken,
  deleteEntity,
  diagnosticsOf,
  putEntity,
  type EntityKind,
  type EntityRecord,
  type ModuleSource,
  type SchemaDiagnostic,
  type SourceWarning,
} from "../api";
import { useConfirm } from "../components/dialogs";
import { useT } from "../i18n";
import { slugify } from "./MarkdownRoundTrip";

/** The ref kind of each entity list: `npc:brother-ansel` is in `npcs`. */
export const REF_KIND: Record<EntityKind, string> = {
  npcs: "npc",
  encounters: "encounter",
  factions: "faction",
  quests: "quest",
  pregens: "pregen",
};
const RELATED: EntityKind[] = ["npcs", "factions", "encounters", "quests"];
const NPC_STATS = ["race", "class", "level", "hd", "ac", "hp"] as const;
/** A pregen's ability scores, as the sheet's `ability_scores` keys them. */
export const ABILITIES = ["str", "dex", "con", "int", "wis", "cha"] as const;
const PREGEN_FIELDS = ["race", "class", "alignment", "background"] as const;

type Values = Record<string, string>;
interface Monster {
  creature: string;
  npc: string;
  count: string;
  notes: string;
  /** The row as it was read, so what the form doesn't show stays. */
  base: Record<string, unknown>;
}

const str = (value: unknown) => (value === undefined || value === null ? "" : String(value));
/** A whole number as a number, anything else as the text it is (`3+1` HD, `1d6` count). */
const numberOr = (value: string) => (/^-?\d+$/.test(value.trim()) ? Number(value.trim()) : value.trim());
const isRecord = (value: unknown): value is Record<string, unknown> =>
  typeof value === "object" && value !== null && !Array.isArray(value);

function adnd2e(record: EntityRecord | null): Record<string, unknown> {
  const stats = record?.stats;
  return isRecord(stats) && isRecord(stats.adnd2e) ? stats.adnd2e : {};
}

/** A pregen's ability scores in `stats.adnd2e`, or none. */
function abilityScores(stats: Record<string, unknown>): Record<string, unknown> {
  return isRecord(stats.ability_scores) ? stats.ability_scores : {};
}

const lines = (text: string) =>
  text
    .split("\n")
    .map((line) => line.trim())
    .filter(Boolean);

function initialValues(kind: EntityKind, record: EntityRecord | null): Values {
  const r = record ?? ({} as Partial<EntityRecord>);
  // A pregen is for the players unless it says otherwise; every other record is the DM's.
  const audience = r.audience ?? (kind === "pregens" ? "player" : "gm");
  const values: Values = {
    name: str(r.name),
    summary: str(r.summary),
    audience: audience === "player" ? "player" : "gm",
    description: str(r.description),
  };
  if (kind === "npcs") {
    const stats = adnd2e(record);
    for (const key of NPC_STATS) values[key] = str(stats[key]);
    values.line = str(stats.line);
    values.disposition = str(r.disposition);
    values.portrait = typeof r.portrait === "string" && r.portrait.startsWith("asset:") ? r.portrait.slice(6) : "";
    values.location = str(r.location);
  }
  if (kind === "encounters") Object.assign(values, { key: str(r.key), kind: str(r.kind), wandering: isWandering(record) ? "yes" : "" });
  if (kind === "factions") {
    const goals = r.goals;
    Object.assign(values, {
      goals: Array.isArray(goals) ? goals.join("\n") : str(goals),
      alignment: str(r.alignment),
      scope: str(r.scope),
    });
  }
  if (kind === "quests") Object.assign(values, { giver: str(r.giver), stakes: str(r.stakes), scope: str(r.scope) });
  if (kind === "pregens") {
    const stats = adnd2e(record);
    const scores = abilityScores(stats);
    for (const key of PREGEN_FIELDS) values[key] = str(r[key]);
    for (const key of ABILITIES) values[key] = str(scores[key]);
    values.level = str(r.level);
    values.hp = str(stats.hp_max);
    values.gear = Array.isArray(r.gear) ? r.gear.map(String).join("\n") : str(r.gear);
  }
  return values;
}

function initialMonsters(record: EntityRecord | null): Monster[] {
  const fixed = Array.isArray(record?.fixed) ? (record!.fixed as unknown[]) : [];
  return fixed.filter(isRecord).map((row) => {
    const creature = str(row.creature);
    return {
      creature: creature.startsWith("monster:") ? creature.slice(8) : creature.startsWith("npc:") ? "" : creature,
      npc: creature.startsWith("npc:") ? creature.slice(4) : "",
      count: str(row.count),
      notes: str(row.notes),
      base: row,
    };
  });
}

/** What an older module's wandering table is named like, as the server reads it (`delve.domain.wandering`). */
const WANDERING_NAME = /wander|random (?:monster|encounter)|encounters? (?:table|chart)|random-(?:monster|encounter)/i;

/** Whether an encounter's table is rolled on by wandering checks (DEL-321): as it says (an empty table: a place with
 * none), else as its name reads. */
function isWandering(record: EntityRecord | null): boolean {
  if (!record || !Array.isArray(record.table)) return false;
  if (typeof record.wandering === "boolean") return record.wandering;
  return record.table.length > 0 && !record.key && WANDERING_NAME.test(`${record.id} ${str(record.name)}`);
}

const refsOf = (record: EntityRecord | null, key: string) =>
  Array.isArray(record?.[key]) ? (record![key] as unknown[]).map(String) : [];

/** A room as "4. The Destroyed Caravan": its key once, though a sketched map's label already starts with it. */
function roomLabel(key: string, label: string): string {
  const name = label.startsWith(`${key}. `) ? label.slice(key.length + 2).trim() : label.trim();
  return name && name !== key ? `${key}. ${name}` : key;
}

/** Sets a field, or takes it out when it is empty. */
function put(record: Record<string, unknown>, key: string, value: unknown) {
  if (value === "" || value === undefined || (Array.isArray(value) && value.length === 0)) delete record[key];
  else record[key] = value;
}

/** The format's record from the form: the record it was, with the form's fields over it. */
function build(
  kind: EntityKind,
  record: EntityRecord | null,
  id: string,
  values: Values,
  monsters: Monster[],
  members: string[],
  related: string[],
  where: string[] = [],
): EntityRecord {
  const r: Record<string, unknown> = structuredClone(record ?? {});
  r.id = id;
  r.name = values.name.trim();
  put(r, "summary", values.summary.trim());
  if (values.audience === "player" || r.audience !== undefined) r.audience = values.audience;
  put(r, "description", values.description.trim());
  if (kind === "npcs") {
    const stats = isRecord(r.stats) ? r.stats : {};
    const own = { ...adnd2e(record) };
    for (const key of NPC_STATS) put(own, key, numberOr(values[key]));
    put(own, "line", values.line.trim());
    if (Object.keys(own).length) stats.adnd2e = own;
    else delete stats.adnd2e;
    put(r, "stats", Object.keys(stats).length ? stats : "");
    put(r, "disposition", numberOr(values.disposition));
    put(r, "portrait", values.portrait ? `asset:${values.portrait}` : "");
    put(r, "location", values.location);
  }
  if (kind === "encounters") {
    put(r, "key", values.key);
    put(r, "kind", values.kind.trim());
    const fixed = monsters
      .filter((m) => m.npc || m.creature.trim())
      .map((m) => {
        const row: Record<string, unknown> = { ...m.base };
        row.creature = m.npc ? `npc:${m.npc}` : m.creature.includes(":") ? m.creature.trim() : `monster:${slugify(m.creature)}`;
        put(row, "count", m.count.trim() === "" ? "" : numberOr(m.count));
        put(row, "notes", m.notes.trim());
        return row;
      });
    put(r, "fixed", fixed);
    if (Array.isArray(r.table)) {
      r.wandering = values.wandering === "yes";
      put(r, "where", r.wandering ? where : "");
    }
  }
  if (kind === "factions") {
    const lines = values.goals
      .split("\n")
      .map((line) => line.trim())
      .filter(Boolean);
    put(r, "goals", Array.isArray(record?.goals) || lines.length > 1 ? lines : values.goals.trim());
    put(r, "members", members);
    put(r, "alignment", values.alignment.trim());
    put(r, "scope", values.scope.trim());
  }
  if (kind === "quests") {
    put(r, "giver", values.giver);
    put(r, "stakes", values.stakes.trim());
    put(r, "scope", values.scope.trim());
    put(r, "related", related);
  }
  if (kind === "pregens") {
    for (const key of PREGEN_FIELDS) put(r, key, values[key].trim());
    put(r, "level", numberOr(values.level));
    put(r, "gear", lines(values.gear));
    const stats = isRecord(r.stats) ? r.stats : {};
    const own = { ...adnd2e(record) };
    const scores = { ...abilityScores(own) };
    for (const key of ABILITIES) put(scores, key, numberOr(values[key]));
    put(own, "ability_scores", Object.keys(scores).length ? scores : "");
    put(own, "hp_max", numberOr(values.hp));
    if (Object.keys(own).length) stats.adnd2e = own;
    else delete stats.adnd2e;
    put(r, "stats", Object.keys(stats).length ? stats : "");
  }
  return r as EntityRecord;
}

/** The checks the schema can't make. */
function check(kind: EntityKind, values: Values, outOfRange: string): SchemaDiagnostic[] {
  const disposition = kind === "npcs" ? numberOr(values.disposition) : "";
  if (typeof disposition === "number" && (disposition < -100 || disposition > 100))
    return [{ severity: "error", code: "range", message: outOfRange, path: "disposition" }];
  return [];
}

export interface EntityFormProps {
  moduleId: string;
  kind: EntityKind;
  /** The record to edit, or null for a new one. */
  record: EntityRecord | null;
  source: ModuleSource;
  /** The module's played maps, by name: where a wandering table may be rolled. */
  maps?: string[];
  onSaved: (record: EntityRecord, warnings: SourceWarning[]) => void;
  onDeleted?: (id: string) => void;
}

/**
 * The form of an NPC, an encounter, a faction, a quest or a pregen, saved as the format's record (spec §8.2). The id is the
 * name's slug when the entity is made, and never changes. The server's schema check shows beside its field.
 */
export default function EntityForm({ moduleId, kind, record, source, maps = [], onSaved, onDeleted }: EntityFormProps) {
  const t = useT();
  const confirm = useConfirm();
  const [values, setValues] = useState(() => initialValues(kind, record));
  const [monsters, setMonsters] = useState(() => initialMonsters(record));
  const [members, setMembers] = useState(() => refsOf(record, "members"));
  const [related, setRelated] = useState(() => refsOf(record, "related"));
  const [where, setWhere] = useState(() => refsOf(record, "where"));
  // What the form checks itself: the schema allows any disposition, the spec says −100 to 100.
  const [local, setLocal] = useState<SchemaDiagnostic[]>([]);
  const entities = source.entities;
  const prefix = `entity-${kind}`;

  const save = useMutation({
    mutationFn: () => {
      const taken = new Set((entities[kind] ?? []).map((e) => e.id));
      const base = slugify(values.name);
      let id = record?.id ?? base;
      for (let n = 2; !record && taken.has(id); n++) id = `${base}-${n}`;
      return putEntity(moduleId, kind, build(kind, record, id, values, monsters, members, related, where));
    },
    onSuccess: ({ record: saved, warnings }) => onSaved(saved, warnings),
  });
  const remove = useMutation({
    mutationFn: () => deleteEntity(moduleId, kind, record!.id),
    onSuccess: () => onDeleted?.(record!.id),
  });

  const diagnostics = [...local, ...diagnosticsOf(save.error)];
  const fieldPaths: string[] = [];
  /** The diagnostics at a field: its path, or anything under it. */
  const at = (path: string) => {
    fieldPaths.push(path);
    return diagnostics.filter((d) => d.path === path || d.path.startsWith(`${path}/`));
  };
  const set = (key: string) => (value: string) => setValues((v) => ({ ...v, [key]: value }));

  const text = (key: string, label: string, path = key, hint?: string) => (
    <Field id={`${prefix}-${key}`} label={label} errors={at(path)} hint={hint}>
      <input id={`${prefix}-${key}`} value={values[key]} onChange={(e) => set(key)(e.target.value)} />
    </Field>
  );
  const area = (key: string, label: string, path = key, rows = 4, hint?: string) => (
    <Field id={`${prefix}-${key}`} label={label} errors={at(path)} hint={hint}>
      <textarea id={`${prefix}-${key}`} rows={rows} value={values[key]} onChange={(e) => set(key)(e.target.value)} />
    </Field>
  );
  const choose = (key: string, label: string, options: [string, string][], path = key) => {
    const known = options.some(([value]) => value === values[key]);
    return (
      <Field id={`${prefix}-${key}`} label={label} errors={at(path)}>
        <select id={`${prefix}-${key}`} value={values[key]} onChange={(e) => set(key)(e.target.value)}>
          <option value="">{t("entity.none")}</option>
          {!known && values[key] && <option value={values[key]}>{values[key]}</option>}
          {options.map(([value, name]) => (
            <option key={value} value={value}>
              {name}
            </option>
          ))}
        </select>
      </Field>
    );
  };

  const npcs = entities.npcs ?? [];
  // The module's keyed rooms, by key: their name and their heading (`text:<id>#<anchor>`).
  const rooms = new Map<string, { label: string; text: string }>();
  for (const link of source.links)
    if (!rooms.has(link.key)) rooms.set(link.key, { label: roomLabel(link.key, link.label), text: `text:${link.text_id}#${link.anchor}` });
  for (const raw of source.keys) {
    const key = str(raw.key);
    if (key && !rooms.has(key)) rooms.set(key, { label: roomLabel(key, str(raw.title)), text: str(raw.text) });
  }
  // Then every other keyed heading, linked to a room or not.
  for (const heading of source.headings ?? [])
    if (!rooms.has(heading.key))
      rooms.set(heading.key, { label: roomLabel(heading.key, heading.title), text: `text:${heading.text_id}#${heading.anchor}` });

  const body: ReactNode = (() => {
    switch (kind) {
      case "npcs":
        return (
          <>
            <div className="field-grid">
              {text("race", t("entity.race"), "stats/adnd2e/race")}
              {text("class", t("entity.class"), "stats/adnd2e/class")}
              {text("level", t("entity.level"), "stats/adnd2e/level")}
              {text("hd", t("entity.hd"), "stats/adnd2e/hd")}
              {text("ac", t("entity.ac"), "stats/adnd2e/ac")}
              {text("hp", t("entity.hp"), "stats/adnd2e/hp")}
            </div>
            <Field id={`${prefix}-line`} label={t("entity.statLine")} errors={at("stats/adnd2e/line")} hint={t("entity.statLineHint")}>
              <textarea id={`${prefix}-line`} rows={2} value={values.line} onChange={(e) => set("line")(e.target.value)} />
            </Field>
            {choose(
              "location",
              t("entity.where"),
              [...rooms.values()].filter((room) => room.text).map((room) => [room.text, room.label]),
            )}
            {text("disposition", t("entity.disposition"), "disposition", t("entity.dispositionHint"))}
            {area("description", t("entity.notes"))}
            {choose(
              "portrait",
              t("entity.portrait"),
              source.attachments.filter((a) => a.type.startsWith("image/")).map((a) => [a.id, a.description || a.id]),
            )}
          </>
        );
      case "encounters":
        return (
          <>
            {choose("key", t("entity.where"), [...rooms].map(([key, room]) => [`key:${key}`, room.label]))}
            {text("kind", t("entity.kind"))}
            <fieldset className="monsters">
              <legend>{t("entity.monsters")}</legend>
              {Array.isArray(record?.table) && <p className="hint">{t("entity.tableKept", { rows: String(record!.table.length) })}</p>}
              {Array.isArray(record?.table) && (
                <label className="check">
                  <input
                    type="checkbox"
                    checked={values.wandering === "yes"}
                    onChange={(e) => set("wandering")(e.target.checked ? "yes" : "")}
                  />
                  {t("entity.wandering")}
                </label>
              )}
              {Array.isArray(record?.table) && values.wandering === "yes" && (
                <RefChecks
                  legend={t("entity.rolledWhere")}
                  options={[
                    ...maps.map((name): [string, string] => [`map:${name}`, t("entity.onMap", { map: name })]),
                    ...source.texts.map((doc): [string, string] => [`text:${doc.id}`, doc.title || doc.id]),
                  ]}
                  value={where}
                  onChange={setWhere}
                  errors={at("where")}
                />
              )}
              {Array.isArray(record?.table) && values.wandering === "yes" && <p className="hint">{t("entity.rolledWhereHint")}</p>}
              {monsters.map((m, i) => (
                <MonsterRow
                  key={i}
                  n={i + 1}
                  monster={m}
                  npcs={npcs}
                  errors={at(`fixed/${i}`)}
                  onChange={(next) => setMonsters((all) => all.map((row, j) => (j === i ? next : row)))}
                  onRemove={() => setMonsters((all) => all.filter((_, j) => j !== i))}
                />
              ))}
              <button
                type="button"
                onClick={() => setMonsters((all) => [...all, { creature: "", npc: "", count: "", notes: "", base: {} }])}
              >
                {t("entity.addMonster")}
              </button>
            </fieldset>
            {area("description", t("entity.conditions"))}
          </>
        );
      case "factions":
        return (
          <>
            {area("goals", t("entity.goals"))}
            <RefChecks
              legend={t("entity.members")}
              options={npcs.map((npc) => [`npc:${npc.id}`, npc.name])}
              value={members}
              onChange={setMembers}
              errors={at("members")}
            />
            {text("alignment", t("entity.alignment"))}
            {text("scope", t("entity.scope"))}
            {area("description", t("entity.notes"))}
          </>
        );
      case "quests":
        return (
          <>
            {choose("giver", t("entity.giver"), npcs.map((npc) => [`npc:${npc.id}`, npc.name]))}
            {area("stakes", t("entity.stakes"), "stakes", 3)}
            {text("scope", t("entity.scope"))}
            <RefChecks
              legend={t("entity.related")}
              options={RELATED.flatMap((k) =>
                (entities[k] ?? [])
                  .filter((e) => !(k === kind && e.id === record?.id))
                  .map((e): [string, string] => [`${REF_KIND[k]}:${e.id}`, e.name]),
              )}
              value={related}
              onChange={setRelated}
              errors={at("related")}
            />
            {area("description", t("entity.notes"))}
          </>
        );
      case "pregens":
        return (
          <>
            <div className="field-grid">
              {text("race", t("entity.race"))}
              {text("class", t("entity.class"))}
              {text("level", t("entity.level"))}
              {text("alignment", t("entity.alignment"))}
            </div>
            <fieldset className="abilities">
              <legend>{t("entity.abilities")}</legend>
              <div className="field-grid">
                {ABILITIES.map((key) => (
                  <Fragment key={key}>{text(key, t(`entity.ability.${key}`), `stats/adnd2e/ability_scores/${key}`)}</Fragment>
                ))}
                {text("hp", t("entity.hp"), "stats/adnd2e/hp_max")}
              </div>
            </fieldset>
            {area("gear", t("entity.gear"), "gear", 4, t("entity.gearHint"))}
            {area("background", t("entity.background"))}
          </>
        );
    }
  })();

  const common = (
    <>
      {text("name", t("entity.name"))}
      {area("summary", t("entity.summary"), "summary", 3)}
      <Field id={`${prefix}-audience`} label={t("audience.label")} errors={at("audience")}>
        <select id={`${prefix}-audience`} value={values.audience} onChange={(e) => set("audience")(e.target.value)}>
          <option value="gm">{t("audience.dm")}</option>
          <option value="player">{t("audience.player")}</option>
        </select>
      </Field>
    </>
  );
  // Diagnostics at no field of the form are shown above it.
  const loose = diagnostics.filter((d) => !fieldPaths.some((p) => d.path === p || d.path.startsWith(`${p}/`)));
  const failed = save.error ?? remove.error;

  return (
    <form
      className="entity-form"
      onSubmit={(e) => {
        e.preventDefault();
        const found = check(kind, values, t("entity.dispositionRange"));
        setLocal(found);
        if (values.name.trim() && found.length === 0) save.mutate();
      }}
    >
      {record && <p className="hint">{t("entity.id", { id: record.id })}</p>}
      {failed && !(failed instanceof NeedsToken) && (
        <div role="alert" className="notice error">
          <p>{t("entity.notSaved", { error: failed.message })}</p>
          {loose.length > 0 && (
            <ul>
              {loose.map((d, i) => (
                <li key={i}>{d.path ? `${d.path}: ${d.message}` : d.message}</li>
              ))}
            </ul>
          )}
        </div>
      )}
      {common}
      {body}
      <div className="actions">
        <button type="submit" className="primary" disabled={!values.name.trim() || save.isPending}>
          {t("entity.save")}
        </button>
        {record && onDeleted && (
          <button
            type="button"
            className="danger"
            disabled={remove.isPending}
            onClick={async () =>
              (await confirm({ title: t("entity.deleteConfirm", { name: record.name }), confirm: t("dialog.delete"), danger: true })) &&
              remove.mutate()
            }
          >
            {t("entity.delete")}
          </button>
        )}
      </div>
    </form>
  );
}

/** The server's diagnostics for one field. */
export function Errors({ errors }: { errors: SchemaDiagnostic[] }) {
  return (
    <>
      {errors.map((d, i) => (
        <span key={i} className="field-error" role="alert">
          {d.message}
        </span>
      ))}
    </>
  );
}

/** A labelled control with the server's diagnostics for it. */
export function Field({
  id,
  label,
  errors,
  hint,
  children,
}: {
  id: string;
  label: string;
  errors: SchemaDiagnostic[];
  hint?: string;
  children: ReactNode;
}) {
  return (
    <div className={`field${errors.length ? " invalid" : ""}`}>
      <label htmlFor={id}>{label}</label>
      {children}
      {hint && <span className="hint">{hint}</span>}
      <Errors errors={errors} />
    </div>
  );
}

function MonsterRow({
  n,
  monster,
  npcs,
  errors,
  onChange,
  onRemove,
}: {
  n: number;
  monster: Monster;
  npcs: EntityRecord[];
  errors: SchemaDiagnostic[];
  onChange: (next: Monster) => void;
  onRemove: () => void;
}) {
  const t = useT();
  const id = (part: string) => `monster-${n}-${part}`;
  const vars = { n: String(n) };
  return (
    <div className="monster-row">
      <div className="field">
        <label htmlFor={id("creature")}>{t("entity.creature", vars)}</label>
        <input
          id={id("creature")}
          value={monster.creature}
          disabled={!!monster.npc}
          onChange={(e) => onChange({ ...monster, creature: e.target.value })}
        />
      </div>
      <div className="field">
        <label htmlFor={id("npc")}>{t("entity.creatureNpc", vars)}</label>
        <select id={id("npc")} value={monster.npc} onChange={(e) => onChange({ ...monster, npc: e.target.value })}>
          <option value="">{t("entity.none")}</option>
          {npcs.map((npc) => (
            <option key={npc.id} value={npc.id}>
              {npc.name}
            </option>
          ))}
        </select>
      </div>
      <div className="field">
        <label htmlFor={id("count")}>{t("entity.count", vars)}</label>
        <input id={id("count")} value={monster.count} placeholder="1d6" onChange={(e) => onChange({ ...monster, count: e.target.value })} />
      </div>
      <div className="field">
        <label htmlFor={id("notes")}>{t("entity.monsterNotes", vars)}</label>
        <textarea id={id("notes")} rows={2} value={monster.notes} onChange={(e) => onChange({ ...monster, notes: e.target.value })} />
      </div>
      <button type="button" className="danger" onClick={onRemove}>
        {t("entity.removeMonster", vars)}
      </button>
      <Errors errors={errors} />
    </div>
  );
}

/** Checkboxes for refs (`npc:…`); refs the form doesn't offer stay as they are. */
function RefChecks({
  legend,
  options,
  value,
  onChange,
  errors,
}: {
  legend: string;
  options: [string, string][];
  value: string[];
  onChange: (next: string[]) => void;
  errors: SchemaDiagnostic[];
}) {
  const t = useT();
  const offered = options.map(([ref]) => ref);
  const toggle = (ref: string, on: boolean) => {
    const kept = value.filter((r) => !offered.includes(r));
    const picked = offered.filter((r) => (r === ref ? on : value.includes(r)));
    onChange([...kept, ...picked]);
  };
  return (
    <fieldset className="ref-checks">
      <legend>{legend}</legend>
      {options.length === 0 && <p className="hint">{t("entity.noneToChoose")}</p>}
      {options.map(([ref, name]) => (
        <label key={ref} className="check">
          <input type="checkbox" checked={value.includes(ref)} onChange={(e) => toggle(ref, e.target.checked)} />
          {name}
        </label>
      ))}
      <Errors errors={errors} />
    </fieldset>
  );
}
