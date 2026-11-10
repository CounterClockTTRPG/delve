import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState, type FormEvent } from "react";
import { NeedsToken, apiFetch, attachmentUrl, postJson, putJson, queryKeys } from "../api";
import { useT } from "../i18n";

// What Claude asked while making a module (plan 7 Task 20), with the assumption it made for each.
export interface MakingQuestion {
  id: string;
  text: string;
  default: string;
  answer: string | null;
}

/** One guess a thorough conversion made (thorough conversion Task 6): its part, its pages in the PDF, its kind. */
export interface ConversionDoubt {
  piece: string;
  part: string;
  pages: number[];
  kind: "missing-text" | "missing-room" | "checker-flag" | "left-out" | "guessed-landing" | "picture-unsure" | "crop-refused" | "sketched-map" | "other";
  text: string;
}

/**
 * One job's questions and the organiser's remarks, as `GET /api/modules/{id}/questions` answers them; a thorough
 * job's also its doubts, whether they were told to the DM, and what it cost.
 */
export interface MakingQuestionsEntry {
  conversion_id: string;
  questions: MakingQuestion[];
  remarks: string[];
  doubts?: ConversionDoubt[];
  told?: boolean;
  cost_usd?: number | null;
  /** The keys of the closed questions and doubts, `question:<id>` and `doubt:<index>`; left out by an older server. */
  closed?: string[];
}

/** The original PDF a converted module keeps (`runner.SOURCE_PDF`), which a doubt's pages open at. */
const SOURCE_PDF = "source-pdf";

/** Under the module's key, so a `modules` event's refresh of the module refreshes its questions too. */
const questionsKey = (moduleId: string) => ["module", moduleId, "questions"] as const;

const listQuestions = (moduleId: string) =>
  apiFetch<MakingQuestionsEntry[]>(`/api/modules/${encodeURIComponent(moduleId)}/questions`);

const answerQuestions = (conversionId: string, answers: Record<string, string>, remarks: string[]) =>
  putJson<MakingQuestionsEntry>(`/api/conversions/${encodeURIComponent(conversionId)}/questions`, { answers, remarks });

const tellTheDm = (conversionId: string) =>
  postJson<MakingQuestionsEntry>(`/api/conversions/${encodeURIComponent(conversionId)}/tell-dm`);

const setClosed = (conversionId: string, closed: string[]) =>
  putJson<MakingQuestionsEntry>(`/api/conversions/${encodeURIComponent(conversionId)}/closed`, { closed });

const questionKey = (question: MakingQuestion) => `question:${question.id}`;
const doubtKey = (n: number) => `doubt:${n}`;

/** Closing or reopening some items (`keys`) of each entry: its closed keys sent whole, one PUT per entry changed. */
function useClosing(moduleId: string) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (changes: { entry: MakingQuestionsEntry; keys: string[]; close: boolean }[]) =>
      Promise.all(
        changes.map(({ entry, keys, close }) => {
          const closed = entry.closed ?? [];
          const next = close ? [...closed, ...keys.filter((k) => !closed.includes(k))] : closed.filter((k) => !keys.includes(k));
          return setClosed(entry.conversion_id, next);
        }),
      ),
    onSuccess: () => client.invalidateQueries({ queryKey: questionsKey(moduleId) }),
  });
}

/** "All 12 dealt with · Show": a box whose every item is closed, folded to one line; Show opens it, Hide folds it. */
function Folded({ count, open, onToggle }: { count: number; open: boolean; onToggle: () => void }) {
  const t = useT();
  return (
    <p className="row-meta folded">
      <span>{t("conversionNotes.allDealtWith", { count: String(count) })}</span> ·{" "}
      <button type="button" className="link-button" onClick={onToggle}>
        {open ? t("conversionNotes.hide") : t("conversionNotes.show")}
      </button>
    </p>
  );
}

/** A closed item: what it was about, "Dealt with" and Reopen. */
function ClosedItem({ label, onReopen, disabled }: { label: string; onReopen: () => void; disabled: boolean }) {
  const t = useT();
  return (
    <>
      <span className="closed-item">{label}</span> <span className="tag">{t("conversionNotes.closed")}</span>{" "}
      <button type="button" disabled={disabled} onClick={onReopen}>
        {t("conversionNotes.reopen")}
      </button>
    </>
  );
}

function ClosingFailed({ error }: { error: Error | null }) {
  const t = useT();
  return error && !(error instanceof NeedsToken) ? (
    <p role="alert" className="notice error">
      {t("conversionNotes.closeFailed", { error: error.message })}
    </p>
  ) : null;
}

/**
 * The questions asked while making the module, each with its answer, else its default filled in, and a field for
 * remarks. Saving writes them into the module's DM-only text "Notes from making this module", which the DM reads with
 * the module; the conversion isn't run again. Nothing shows for a module made without questions.
 *
 * Under them, a thorough conversion's doubts (thorough conversion Task 8): every guess it made, each with its part, its
 * pages (links into the original PDF at that page), its kind and what is uncertain, and the job's cost beside the
 * heading. They are the organiser's alone until "Tell the DM" writes them into the same DM-only text.
 *
 * Each question and doubt can be closed once dealt with, and reopened (table voice and fixes F3); Close all closes a
 * box's every item. A box whose items are all closed folds to one line, "All 12 dealt with · Show". Closing is stored
 * on the job, so every organiser sees the same, and only hides: the notes and what the DM is told stay as they are.
 */
export default function MakingQuestions({ moduleId }: { moduleId: string }) {
  const t = useT();
  const asked = useQuery({ queryKey: questionsKey(moduleId), queryFn: () => listQuestions(moduleId) });
  const closing = useClosing(moduleId);
  const [open, setOpen] = useState(false);
  if (asked.error && !(asked.error instanceof NeedsToken)) {
    return (
      <p role="alert" className="notice error">
        {t("making.failed", { error: asked.error.message })}
      </p>
    );
  }
  const entries = asked.data ?? [];
  // A thorough job that asked nothing has only its doubts to show.
  const questioned = entries.filter((entry) => entry.questions.length > 0 || entry.doubts === undefined);
  const doubted = entries.filter((entry) => entry.doubts !== undefined);
  if (entries.length === 0) return null;
  const count = questioned.reduce((n, entry) => n + entry.questions.length, 0);
  const allClosed = count > 0 && questioned.every((e) => e.questions.every((q) => (e.closed ?? []).includes(questionKey(q))));
  const closeAll = () =>
    closing.mutate(questioned.filter((e) => e.questions.length > 0).map((entry) => ({ entry, keys: entry.questions.map(questionKey), close: true })));
  return (
    <>
      {questioned.length > 0 && (
        <section className="notice" aria-label={t("making.title")}>
          <h2>{t("making.title")}</h2>
          {allClosed && <Folded count={count} open={open} onToggle={() => setOpen(!open)} />}
          {(!allClosed || open) && (
            <>
              <p className="hint">{t("making.hint")}</p>
              {!allClosed && count > 0 && (
                <div className="actions">
                  <button type="button" disabled={closing.isPending} onClick={closeAll}>
                    {t("conversionNotes.closeAll")}
                  </button>
                </div>
              )}
              {questioned.map((entry) => (
                <EntryForm key={entry.conversion_id} moduleId={moduleId} entry={entry} />
              ))}
            </>
          )}
          <ClosingFailed error={closing.error} />
        </section>
      )}
      {doubted.map((entry) => (
        <Doubts key={entry.conversion_id} moduleId={moduleId} entry={entry} />
      ))}
    </>
  );
}

function Doubts({ moduleId, entry }: { moduleId: string; entry: MakingQuestionsEntry }) {
  const t = useT();
  const client = useQueryClient();
  const tell = useMutation({
    mutationFn: () => tellTheDm(entry.conversion_id),
    onSuccess: () => {
      client.invalidateQueries({ queryKey: questionsKey(moduleId) });
      client.invalidateQueries({ queryKey: queryKeys.moduleSource(moduleId), exact: true });
    },
  });
  const closing = useClosing(moduleId);
  const [open, setOpen] = useState(false);
  const doubts = entry.doubts ?? [];
  const heading = `doubts-${entry.conversion_id}`;
  const pdf = attachmentUrl(moduleId, SOURCE_PDF);
  const closed = entry.closed ?? [];
  const allClosed = doubts.length > 0 && doubts.every((_, n) => closed.includes(doubtKey(n)));
  const shown = !allClosed || open;
  const change = (keys: string[], close: boolean) => closing.mutate([{ entry, keys, close }]);
  return (
    <section className="notice doubts" aria-labelledby={heading} data-testid="conversion-doubts">
      <h2 id={heading}>
        {t("doubts.title", { count: String(doubts.length) })}
        {typeof entry.cost_usd === "number" && (
          <span className="tag doubts-cost">{t("conversion.cost", { amount: entry.cost_usd.toFixed(2) })}</span>
        )}
      </h2>
      {allClosed && <Folded count={doubts.length} open={open} onToggle={() => setOpen(!open)} />}
      {shown && <p className="hint">{doubts.length === 0 ? t("doubts.none") : t("doubts.hint")}</p>}
      {shown && doubts.length > 0 && (
        <ul className="doubts-list">
          {doubts.map((doubt, n) =>
            closed.includes(doubtKey(n)) ? (
              <li key={n} className="closed">
                <ClosedItem label={doubt.part} disabled={closing.isPending} onReopen={() => change([doubtKey(n)], false)} />
              </li>
            ) : (
              <li key={n}>
                <strong>{doubt.part}</strong>
                {doubt.pages.length > 0 && (
                  <span className="doubt-pages">
                    {" "}
                    {t(doubt.pages.length === 1 ? "doubts.page" : "doubts.pages")}{" "}
                    {doubt.pages.map((page, i) => (
                      <span key={page}>
                        {i > 0 && ", "}
                        <a href={`${pdf}#page=${page}`} target="_blank" rel="noreferrer">
                          {page}
                        </a>
                      </span>
                    ))}
                  </span>
                )}{" "}
                <span className="tag">{t(`doubts.kind.${doubt.kind}`)}</span>{" "}
                <button type="button" disabled={closing.isPending} onClick={() => change([doubtKey(n)], true)}>
                  {t("conversionNotes.close")}
                </button>
                <p>{doubt.text}</p>
              </li>
            ),
          )}
        </ul>
      )}
      {shown && doubts.length > 0 && (
        <div className="actions">
          {!allClosed && (
            <button type="button" disabled={closing.isPending} onClick={() => change(doubts.map((_, n) => doubtKey(n)), true)}>
              {t("conversionNotes.closeAll")}
            </button>
          )}
          {entry.told ? (
            <p role="status">{t("doubts.told")}</p>
          ) : (
            <button type="button" disabled={tell.isPending} onClick={() => tell.mutate()}>
              {t("doubts.tell")}
            </button>
          )}
        </div>
      )}
      {tell.error && !(tell.error instanceof NeedsToken) && (
        <p role="alert" className="notice error">
          {t("doubts.tellFailed", { error: tell.error.message })}
        </p>
      )}
      <ClosingFailed error={closing.error} />
    </section>
  );
}

function EntryForm({ moduleId, entry }: { moduleId: string; entry: MakingQuestionsEntry }) {
  const t = useT();
  const client = useQueryClient();
  const [answers, setAnswers] = useState<Record<string, string>>(() =>
    Object.fromEntries(entry.questions.map((q) => [q.id, q.answer ?? q.default])),
  );
  const [remark, setRemark] = useState(entry.remarks.join("\n\n"));
  const closing = useClosing(moduleId);
  const closed = entry.closed ?? [];
  // An answer left at its default isn't sent, so the notes say it was assumed.
  const given = () =>
    Object.fromEntries(
      entry.questions.filter((q) => answers[q.id].trim() !== q.default).map((q) => [q.id, answers[q.id].trim()]),
    );
  const save = useMutation({
    mutationFn: () => answerQuestions(entry.conversion_id, given(), remark.trim() ? [remark.trim()] : []),
    onSuccess: () => {
      client.invalidateQueries({ queryKey: questionsKey(moduleId) });
      client.invalidateQueries({ queryKey: queryKeys.moduleSource(moduleId), exact: true });
    },
  });

  function submit(event: FormEvent) {
    event.preventDefault();
    save.mutate();
  }

  return (
    <form onSubmit={submit}>
      {entry.questions.map((question) => {
        const field = `making-${entry.conversion_id}-${question.id}`;
        const key = questionKey(question);
        // A closed question's answer is still sent: closing only hides it.
        if (closed.includes(key)) {
          return (
            <div className="field closed" key={question.id}>
              <ClosedItem
                label={question.text}
                disabled={closing.isPending}
                onReopen={() => closing.mutate([{ entry, keys: [key], close: false }])}
              />
            </div>
          );
        }
        return (
          <div className="field" key={question.id}>
            <label htmlFor={field}>{question.text}</label>
            <div className="inline-form">
              <input
                id={field}
                value={answers[question.id] ?? ""}
                onChange={(e) => setAnswers({ ...answers, [question.id]: e.target.value })}
              />
              <button type="button" disabled={closing.isPending} onClick={() => closing.mutate([{ entry, keys: [key], close: true }])}>
                {t("conversionNotes.close")}
              </button>
            </div>
          </div>
        );
      })}
      <div className="field">
        <label htmlFor={`making-${entry.conversion_id}-remarks`}>{t("making.remarks")}</label>
        <textarea
          id={`making-${entry.conversion_id}-remarks`}
          rows={3}
          value={remark}
          onChange={(e) => setRemark(e.target.value)}
        />
      </div>
      <div className="actions">
        <button type="submit" className="primary" disabled={save.isPending}>
          {t("making.save")}
        </button>
      </div>
      {save.isSuccess && <p role="status">{t("making.saved")}</p>}
      {save.error && !(save.error instanceof NeedsToken) && (
        <p role="alert" className="notice error">
          {t("making.saveFailed", { error: save.error.message })}
        </p>
      )}
      <ClosingFailed error={closing.error} />
    </form>
  );
}
