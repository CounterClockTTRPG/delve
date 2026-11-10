import { useMutation } from "@tanstack/react-query";
import { useState, type ReactNode } from "react";
import { NeedsToken, diagnosticsOf, patchModule, type Attachment, type ModuleDetail } from "../api";
import { useT } from "../i18n";
import { Errors, Field } from "./EntityForm";
import { HOMEBREW, isHomebrewTag } from "./homebrew";

/** The format's author roles (`person.role`). */
const ROLES = ["author", "editor", "cartographer", "artist", "playtester", "translator", "contributor"];

interface Author {
  name: string;
  role: string;
  /** The author as it was read: a name, or an object with an email or a url to keep. */
  base: unknown;
}

interface Range {
  min: string;
  max: string;
  recommended: string;
}

const isRecord = (value: unknown): value is Record<string, unknown> =>
  typeof value === "object" && value !== null && !Array.isArray(value);
const str = (value: unknown) => (value === undefined || value === null ? "" : String(value));

function rangeOf(value: unknown): Range {
  if (typeof value === "number") return { min: String(value), max: "", recommended: "" };
  if (isRecord(value)) return { min: str(value.min), max: str(value.max), recommended: str(value.recommended) };
  return { min: "", max: "", recommended: "" };
}

/** `intRange`: {min, max, recommended?} with both ends, one number with one, nothing with none. */
function rangeValue(range: Range): number | Record<string, number> | undefined {
  const [min, max, recommended] = [range.min, range.max, range.recommended].map((v) => (v.trim() ? Number(v) : undefined));
  if (min !== undefined && max !== undefined) return recommended === undefined ? { min, max } : { min, max, recommended };
  return min ?? max ?? recommended;
}

const listOf = (value: unknown) => (Array.isArray(value) ? value.map(String).join(", ") : str(value));
function listValue(text: string): string[] {
  return [...new Set(text.split(",").map((part) => part.trim()).filter(Boolean))];
}

function authorsOf(value: unknown): Author[] {
  if (!Array.isArray(value)) return [];
  return value.map((a) => (isRecord(a) ? { name: str(a.name), role: str(a.role), base: a } : { name: str(a), role: "", base: a }));
}

function authorValue(author: Author): unknown {
  const name = author.name.trim();
  if (!isRecord(author.base) && !author.role) return name;
  const out: Record<string, unknown> = { ...(isRecord(author.base) ? author.base : {}), name };
  if (author.role) out.role = author.role;
  else delete out.role;
  return out;
}

export interface DetailsFormProps {
  module: ModuleDetail;
  attachments: Attachment[];
  onSaved: (module: ModuleDetail) => void;
}

/** The module's descriptive metadata (spec §8.2): what the format's manifest says about it, beside its parts. */
export default function DetailsForm({ module, attachments, onSaved }: DetailsFormProps) {
  const t = useT();
  const meta = module.metadata;
  const party = isRecord(meta.party) ? meta.party : {};
  const [title, setTitle] = useState(module.title);
  const [summary, setSummary] = useState(str(meta.summary));
  const [description, setDescription] = useState(str(meta.description));
  const [authors, setAuthors] = useState(() => authorsOf(meta.authors));
  const [levels, setLevels] = useState(() => rangeOf(party.levels));
  const [size, setSize] = useState(() => rangeOf(party.size));
  const [partyNotes, setPartyNotes] = useState(str(party.notes));
  const [setting, setSetting] = useState(str(meta.setting));
  const [system, setSystem] = useState(str(meta.system));
  const [tags, setTags] = useState(listOf(meta.tags));
  const [warnings, setWarnings] = useState(listOf(meta.content_warnings));
  // Homebrew is a tag (DEL-226): the box adds it to the tags or takes it out.
  const homebrew = listValue(tags).some(isHomebrewTag);
  const setHomebrew = (on: boolean) => {
    const rest = listValue(tags).filter((tag) => !isHomebrewTag(tag));
    setTags((on ? [...rest, HOMEBREW] : rest).join(", "));
  };
  const [cover, setCover] = useState(typeof meta.cover === "string" ? meta.cover.replace(/^asset:/, "") : "");

  const save = useMutation({
    mutationFn: () => {
      const metadata: Record<string, unknown> = structuredClone(meta);
      const nextParty: Record<string, unknown> = structuredClone(party);
      const set = (target: Record<string, unknown>, key: string, value: unknown) => {
        if (value === undefined || value === "" || (Array.isArray(value) && value.length === 0)) delete target[key];
        else target[key] = value;
      };
      set(metadata, "summary", summary.trim());
      set(metadata, "description", description.trim());
      set(metadata, "authors", authors.filter((a) => a.name.trim()).map(authorValue));
      set(nextParty, "levels", rangeValue(levels));
      set(nextParty, "size", rangeValue(size));
      set(nextParty, "notes", partyNotes.trim());
      set(metadata, "party", Object.keys(nextParty).length ? nextParty : undefined);
      set(metadata, "setting", setting.trim());
      set(metadata, "system", system.trim());
      set(metadata, "tags", listValue(tags));
      set(metadata, "content_warnings", listValue(warnings));
      set(metadata, "cover", cover ? `asset:${cover}` : "");
      return patchModule(module.id, { title: title.trim() || module.title, metadata });
    },
    onSuccess: onSaved,
  });

  const diagnostics = diagnosticsOf(save.error);
  const shown: string[] = [];
  const at = (path: string) => {
    shown.push(path);
    return diagnostics.filter((d) => d.path === path || d.path.startsWith(`${path}/`));
  };
  const images = attachments.filter((a) => a.type.startsWith("image/"));

  const field = (id: string, label: string, path: string, control: ReactNode, hint?: string) => (
    <Field id={id} label={label} errors={at(path)} hint={hint}>
      {control}
    </Field>
  );
  const range = (legend: string, path: string, value: Range, onChange: (r: Range) => void, labels: [string, string, string]) => {
    const errors = at(path);
    return (
      <fieldset className={`range${errors.length ? " invalid" : ""}`}>
        <legend>{legend}</legend>
        {(["min", "max", "recommended"] as const).map((end, i) => (
          <div key={end} className="field">
            <label htmlFor={`${path}-${end}`}>{labels[i]}</label>
            <input
              id={`${path}-${end}`}
              type="number"
              min={1}
              value={value[end]}
              onChange={(e) => onChange({ ...value, [end]: e.target.value })}
            />
          </div>
        ))}
        <Errors errors={errors} />
      </fieldset>
    );
  };

  const authorFields = (
    <fieldset className="authors">
      <legend>{t("details.authors")}</legend>
      {authors.map((author, i) => {
        const n = String(i + 1);
        const change = (patch: Partial<Author>) => setAuthors((all) => all.map((a, j) => (j === i ? { ...a, ...patch } : a)));
        return (
          <div key={i} className="author-row">
            <div className="field">
              <label htmlFor={`author-${n}`}>{t("details.author", { n })}</label>
              <input id={`author-${n}`} value={author.name} onChange={(e) => change({ name: e.target.value })} />
            </div>
            <div className="field">
              <label htmlFor={`author-${n}-role`}>{t("details.authorRole", { n })}</label>
              <select id={`author-${n}-role`} value={author.role} onChange={(e) => change({ role: e.target.value })}>
                <option value="">{t("details.noRole")}</option>
                {ROLES.map((role) => (
                  <option key={role} value={role}>
                    {t(`details.role.${role}`)}
                  </option>
                ))}
              </select>
            </div>
            <button type="button" className="danger" onClick={() => setAuthors((all) => all.filter((_, j) => j !== i))}>
              {t("details.removeAuthor", { n })}
            </button>
          </div>
        );
      })}
      <button type="button" onClick={() => setAuthors((all) => [...all, { name: "", role: "", base: undefined }])}>
        {t("details.addAuthor")}
      </button>
      <Errors errors={at("authors")} />
    </fieldset>
  );

  const body = (
    <>
      {field("details-title", t("details.title"), "title", <input id="details-title" value={title} onChange={(e) => setTitle(e.target.value)} />)}
      {field(
        "details-summary",
        t("details.summary"),
        "summary",
        <input id="details-summary" maxLength={300} value={summary} onChange={(e) => setSummary(e.target.value)} />,
        t("details.summaryHint"),
      )}
      {field(
        "details-description",
        t("details.description"),
        "description",
        <textarea id="details-description" rows={5} value={description} onChange={(e) => setDescription(e.target.value)} />,
        t("details.descriptionHint"),
      )}
      {authorFields}
      {range(t("details.levels"), "party/levels", levels, setLevels, [t("details.levelMin"), t("details.levelMax"), t("details.levelRecommended")])}
      {range(t("details.size"), "party/size", size, setSize, [t("details.sizeMin"), t("details.sizeMax"), t("details.sizeRecommended")])}
      {field(
        "details-party-notes",
        t("details.partyNotes"),
        "party/notes",
        <textarea id="details-party-notes" rows={3} value={partyNotes} onChange={(e) => setPartyNotes(e.target.value)} />,
        t("details.partyNotesHint"),
      )}
      <div className="field-grid">
        {field("details-setting", t("details.setting"), "setting", <input id="details-setting" value={setting} onChange={(e) => setSetting(e.target.value)} />)}
        {field(
          "details-system",
          t("details.system"),
          "system",
          <input id="details-system" value={system} onChange={(e) => setSystem(e.target.value)} />,
          t("details.systemHint"),
        )}
      </div>
      {field(
        "details-tags",
        t("details.tags"),
        "tags",
        <input id="details-tags" value={tags} onChange={(e) => setTags(e.target.value)} />,
        t("details.listHint"),
      )}
      <label className="check">
        <input type="checkbox" checked={homebrew} onChange={(e) => setHomebrew(e.target.checked)} />
        {t("details.homebrew")}
      </label>
      {field(
        "details-warnings",
        t("details.contentWarnings"),
        "content_warnings",
        <input id="details-warnings" value={warnings} onChange={(e) => setWarnings(e.target.value)} />,
        t("details.listHint"),
      )}
      {field(
        "details-cover",
        t("details.cover"),
        "cover",
        <select id="details-cover" value={cover} onChange={(e) => setCover(e.target.value)}>
          <option value="">{t("details.noCover")}</option>
          {images.map((a) => (
            <option key={a.id} value={a.id}>
              {a.description || a.id}
            </option>
          ))}
        </select>,
      )}
    </>
  );
  const loose = diagnostics.filter((d) => !shown.some((p) => d.path === p || d.path.startsWith(`${p}/`)));

  return (
    <form
      className="details-form"
      onSubmit={(e) => {
        e.preventDefault();
        save.mutate();
      }}
    >
      {save.error && !(save.error instanceof NeedsToken) && (
        <div role="alert" className="notice error">
          <p>{t("details.notSaved", { error: save.error.message })}</p>
          {loose.length > 0 && (
            <ul>
              {loose.map((d, i) => (
                <li key={i}>{d.path ? `${d.path}: ${d.message}` : d.message}</li>
              ))}
            </ul>
          )}
        </div>
      )}
      {body}
      <div className="actions">
        <button type="submit" className="primary" disabled={save.isPending}>
          {t("details.save")}
        </button>
        {save.isSuccess && <span className="status">{t("details.saved")}</span>}
      </div>
    </form>
  );
}
