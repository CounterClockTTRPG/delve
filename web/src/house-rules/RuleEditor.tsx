import { useState, type FormEvent, type ReactNode } from "react";
import { PHASES, RULE_KINDS, type HouseRuleInput, type Phase } from "../api";
import { useT } from "../i18n";

/** Edits one house rule: its title, Markdown text with a preview, kind, phase chips, ruleset, setting, subject. */
export default function RuleEditor({
  rule,
  busy = false,
  onSave,
  onDelete,
}: {
  rule: HouseRuleInput;
  busy?: boolean;
  onSave: (rule: HouseRuleInput) => void;
  /** Absent for a rule that isn't saved yet. */
  onDelete?: () => void;
}) {
  const t = useT();
  const [draft, setDraft] = useState(rule);
  const [tab, setTab] = useState<"write" | "preview">("write");
  const set = <K extends keyof HouseRuleInput>(key: K, value: HouseRuleInput[K]) =>
    setDraft((d) => ({ ...d, [key]: value }));
  const toggle = (phase: Phase) =>
    set("phases", draft.phases.includes(phase) ? draft.phases.filter((p) => p !== phase) : [...draft.phases, phase]);
  const blankIsAny = (value: string | null) => (value ?? "").trim() || null;

  function submit(e: FormEvent) {
    e.preventDefault();
    if (!draft.title.trim()) return;
    onSave({
      title: draft.title.trim(),
      body_md: draft.body_md,
      kind: draft.kind,
      enabled: draft.enabled,
      phases: PHASES.filter((p) => draft.phases.includes(p)),
      ruleset: blankIsAny(draft.ruleset),
      setting: blankIsAny(draft.setting),
      subject: blankIsAny(draft.subject),
    });
  }

  return (
    <form className="editor-form" onSubmit={submit}>
      <div className="field">
        <label htmlFor="rule-title">{t("ruleEditor.title")}</label>
        <input id="rule-title" value={draft.title} onChange={(e) => set("title", e.target.value)} />
      </div>

      <div className="field">
        <div className="text-head">
          <label htmlFor="rule-body">{t("ruleEditor.body")}</label>
          <div className="text-tabs" role="tablist">
            {(["write", "preview"] as const).map((name) => (
              <button
                key={name}
                type="button"
                role="tab"
                className="text-tab"
                aria-selected={tab === name}
                onClick={() => setTab(name)}
              >
                {t(`ruleEditor.${name}`)}
              </button>
            ))}
          </div>
        </div>
        {tab === "write" ? (
          <textarea id="rule-body" rows={14} value={draft.body_md} onChange={(e) => set("body_md", e.target.value)} />
        ) : (
          <div className="markdown-preview" role="tabpanel">
            {draft.body_md.trim() ? (
              <Markdown source={draft.body_md} />
            ) : (
              <p className="placeholder">{t("ruleEditor.emptyPreview")}</p>
            )}
          </div>
        )}
      </div>

      <div className="field">
        <label htmlFor="rule-kind">{t("ruleEditor.kind")}</label>
        <select
          id="rule-kind"
          value={draft.kind}
          onChange={(e) => set("kind", e.target.value as HouseRuleInput["kind"])}
        >
          {RULE_KINDS.map((kind) => (
            <option key={kind} value={kind}>
              {t(`kind.${kind}`)}
            </option>
          ))}
        </select>
      </div>

      <fieldset className="field chips" role="group" aria-labelledby="rule-phases">
        <legend id="rule-phases">{t("ruleEditor.phases")}</legend>
        {PHASES.map((phase) => (
          <button
            key={phase}
            type="button"
            className="chip"
            aria-pressed={draft.phases.includes(phase)}
            onClick={() => toggle(phase)}
          >
            {t(`phase.${phase}`)}
          </button>
        ))}
      </fieldset>

      <div className="field-row">
        {(["ruleset", "setting", "subject"] as const).map((key) => (
          <div className="field" key={key}>
            <label htmlFor={`rule-${key}`}>{t(`ruleEditor.${key}`)}</label>
            <input id={`rule-${key}`} value={draft[key] ?? ""} onChange={(e) => set(key, e.target.value)} />
            <span className="hint">{t(key === "subject" ? "ruleEditor.subjectHint" : "ruleEditor.anyHint")}</span>
          </div>
        ))}
      </div>

      <label className="check">
        <input type="checkbox" checked={draft.enabled} onChange={(e) => set("enabled", e.target.checked)} />
        {t("ruleEditor.enabled")}
      </label>

      <div className="actions">
        <button type="submit" className="primary" disabled={busy || !draft.title.trim()}>
          {t("ruleEditor.save")}
        </button>
        {onDelete && (
          <button type="button" className="danger" disabled={busy} onClick={onDelete}>
            {t("ruleEditor.delete")}
          </button>
        )}
      </div>
    </form>
  );
}

/**
 * The Markdown of house rules, as React elements: headings, paragraphs, bullet lists, tables, **bold**, *italic* and
 * `code`. Anything else stays text; nothing is ever set as HTML.
 */
export function Markdown({ source }: { source: string }) {
  const blocks: ReactNode[] = [];
  const lines = source.replace(/\r\n?/g, "\n").split("\n");
  let i = 0;
  while (i < lines.length) {
    const line = lines[i];
    const heading = /^(#{1,6})\s+(.*)$/.exec(line);
    if (!line.trim()) {
      i++;
    } else if (heading) {
      // A rule's own headings sit below the page's h1-h3.
      const Tag = `h${Math.min(heading[1].length + 2, 6)}` as "h3";
      blocks.push(<Tag key={i}>{inline(heading[2])}</Tag>);
      i++;
    } else if (/^\s*[-*+]\s+/.test(line)) {
      const items: string[] = [];
      while (i < lines.length && lines[i].trim()) {
        const bullet = /^\s*[-*+]\s+(.*)$/.exec(lines[i]);
        if (bullet) items.push(bullet[1]);
        else if (items.length) items[items.length - 1] += ` ${lines[i].trim()}`;
        i++;
      }
      blocks.push(
        <ul key={i}>
          {items.map((item, n) => (
            <li key={n}>{inline(item)}</li>
          ))}
        </ul>,
      );
    } else if (line.trim().startsWith("|")) {
      const rows: string[][] = [];
      while (i < lines.length && lines[i].trim().startsWith("|")) {
        const cells = lines[i]
          .trim()
          .replace(/^\||\|$/g, "")
          .split("|")
          .map((c) => c.trim());
        if (!cells.every((c) => /^:?-+:?$/.test(c))) rows.push(cells);
        i++;
      }
      const [head, ...body] = rows;
      blocks.push(
        <table key={i}>
          <thead>
            <tr>
              {head.map((cell, n) => (
                <th key={n}>{inline(cell)}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {body.map((row, r) => (
              <tr key={r}>
                {row.map((cell, n) => (
                  <td key={n}>{inline(cell)}</td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>,
      );
    } else {
      const para: string[] = [];
      while (i < lines.length && lines[i].trim() && !/^(#{1,6}\s|\s*[-*+]\s|\s*\|)/.test(lines[i]))
        para.push(lines[i++].trim());
      blocks.push(<p key={i}>{inline(para.join(" "))}</p>);
    }
  }
  return <div className="markdown">{blocks}</div>;
}

function inline(text: string): ReactNode[] {
  const out: ReactNode[] = [];
  const pattern = /\*\*(.+?)\*\*|`([^`]+)`|\*([^*\s][^*]*?)\*|_([^_\s][^_]*?)_/g;
  let last = 0;
  for (let match = pattern.exec(text); match; match = pattern.exec(text)) {
    if (match.index > last) out.push(text.slice(last, match.index));
    const key = match.index;
    if (match[1] !== undefined) out.push(<strong key={key}>{inline(match[1])}</strong>);
    else if (match[2] !== undefined) out.push(<code key={key}>{match[2]}</code>);
    else out.push(<em key={key}>{inline(match[3] ?? match[4])}</em>);
    last = pattern.lastIndex;
  }
  if (last < text.length) out.push(text.slice(last));
  return out;
}
