import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useContext, useEffect, useState, type ChangeEvent, type FormEvent, type ReactNode } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
import {
  EventsContext,
  NeedsToken,
  conversionOptions,
  convertPdf,
  createModule,
  generateModule,
  importModule,
  listConversions,
  queryKeys,
  runningConversionOf,
  scopeRequest,
  type Conversion,
  type ConversionEvent,
  type ConversionMode,
  type GenerateScope,
  type ModuleDetail,
} from "../api";
import { useFileDrop } from "../desktop/useFileDrop";
import { useT } from "../i18n";
import ConversionProgress from "../module/ConversionProgress";
import ConversionsPanel from "../module/ConversionsPanel";
import { makesModule } from "../module/conversions";

const MODES: ConversionMode[] = ["ready", "draft"];
/** How a PDF is converted: thoroughly (the default) or quickly, today's conversion (thorough conversion Task 8). */
type Depth = "thorough" | "quick";

const WAYS = ["empty", "pdf", "describe", "dscn"] as const;
type Way = (typeof WAYS)[number];
const isWay = (value: string | null): value is Way => WAYS.includes(value as Way);
/** The most characters the PDF form's comments may have (`runner.COMMENTS_MAX`). */
const COMMENTS_MAX = 2000;
/** A request that names a file, or asks to import or convert, is likely a book for the PDF form (Features 17). */
const LOOKS_LIKE_IMPORT = /\.\w{2,4}\b|\b(import|importeer|convert|omzetten)/i;

/** A generated module's pictures (DEL-347): where the form starts, and the server's `MAX_PICTURES`. */
const PICTURES_DEFAULT = 6;
const PICTURES_MAX = 12;

/**
 * `/modules/new`: the four ways to get a module (spec §8.3). The screen first offers the four, and `?way=` shows only
 * the picked one's form, so two ways' fields can't be mixed. An empty module and a `.dscn` open the module at once; a
 * PDF and a request start a conversion, whose progress shows above the form until it ends. A reload finds the running
 * conversion through `GET /api/conversions`. One conversion runs at a time: a PDF uploaded or a request sent while one
 * runs waits in the queue (DEL-141), which the Conversions panel lists, with Pause, Resume, Cancel and the queue's switch (thorough conversion,
 * owner addition 2026-10-23). Once a PDF's module is made, the drafts
 * of the book's map pages that follow are shown as they are drawn, then linked (`BookMaps`).
 *
 * A PDF is converted thoroughly by default: every page checked and every map traced from the book, by agents on the
 * Claude CLI. When `GET /api/conversions/options` says it can't run, Thorough is disabled with the reason and Quick is
 * chosen. The book-maps checkbox is Quick's only. A paused thorough conversion is shown as the running one is, with
 * Resume.
 *
 * The PDF form's "Comments for Claude" go with the book to every prompt of the conversion (table voice and fixes F1).
 * A request in the generate box that reads like an import (a file name, "import", "convert") points to the PDF form.
 * Its "Paint pictures" asks for handouts within a limit, disabled with the reason when only the owner may (DEL-347).
 *
 * Generate first sizes the request up (`POST /api/conversions/generate/scope`, DEL-134): a module or a campaign, and
 * what Claude asks before writing. With questions, they show under the request, each with an answer box whose
 * placeholder is what Claude assumes; Generate then sends the answers with the scale. Without questions the job starts
 * at once; when the scope call fails, it starts without a scale, and the job sizes the request up itself. Changing the
 * request drops the questions.
 */
const SCOPE_HINTS = {
  module: "newModule.scopeModule",
  campaign: "newModule.scopeCampaign",
  sandbox: "newModule.scopeSandbox",
} as const;

export default function NewModule() {
  const t = useT();
  const client = useQueryClient();
  const navigate = useNavigate();
  const [params, setParams] = useSearchParams();
  const way = params.get("way");
  const conversions = useQuery({ queryKey: queryKeys.conversions, queryFn: listConversions });
  // The conversion this screen started or was refused for: it stays in view after it ends.
  const [followed, setFollowed] = useState<Conversion | null>(null);
  const [title, setTitle] = useState("");
  const [book, setBook] = useState<File | null>(null);
  // The name of a PDF dropped on the page (its file field can't show it), or of a file a drop couldn't use.
  const [dropped, setDropped] = useState<string | null>(null);
  const [refusedDrop, setRefusedDrop] = useState<string | null>(null);
  const [bookTitle, setBookTitle] = useState("");
  const [mode, setMode] = useState<ConversionMode>("ready");
  const [bookMaps, setBookMaps] = useState(true);
  const options = useQuery({ queryKey: queryKeys.conversionOptions, queryFn: conversionOptions });
  const thoroughOk = options.data?.thorough.available ?? false;
  const [picked, setPicked] = useState<Depth | null>(null);
  const depth: Depth = thoroughOk ? (picked ?? "thorough") : "quick";
  const [request, setRequest] = useState("");
  // The request's scope once it was sized up with questions to answer, and the answers, by question id.
  const [scope, setScope] = useState<GenerateScope | null>(null);
  const [answers, setAnswers] = useState<Record<string, string>>({});
  const [comments, setComments] = useState("");
  const [paintPictures, setPaintPictures] = useState(false);
  const [pictureLimit, setPictureLimit] = useState(PICTURES_DEFAULT);
  const picturesAllowed = options.data?.pictures?.allowed !== false;

  // An import's warnings travel along to the module's page, which shows them.
  const opened = (module: ModuleDetail & { warnings?: string[] }) => {
    client.invalidateQueries({ queryKey: queryKeys.modules });
    navigate(`/modules/${encodeURIComponent(module.id)}`, { state: { warnings: module.warnings ?? [] } });
  };
  const create = useMutation({ mutationFn: createModule, onSuccess: opened });
  const upload = useMutation({ mutationFn: importModule, onSuccess: opened });

  const follow = (conversion: Conversion) => {
    setFollowed(conversion);
    client.invalidateQueries({ queryKey: queryKeys.conversions });
  };
  const refused = (error: Error) => {
    const running = runningConversionOf(error);
    if (running) follow(running);
  };
  const convert = useMutation({
    mutationFn: ({ file, name }: { file: File; name: string }) => convertPdf(file, name, mode, bookMaps, depth === "thorough", comments),
    onSuccess: follow,
    onError: refused,
  });
  const generate = useMutation({
    mutationFn: ({ text, sized, given = {} }: { text: string; sized?: GenerateScope; given?: Record<string, string> }) =>
      generateModule(
        text,
        "ready",
        sized && {
          scale: sized.scale,
          answers: sized.questions.map((q) => ({ text: q.text, default: q.default, answer: (given[q.id] ?? "").trim() })),
        },
        paintPictures && picturesAllowed ? pictureLimit : 0,
      ),
    onSuccess: (conversion: Conversion) => {
      setScope(null);
      setAnswers({});
      follow(conversion);
    },
    onError: refused,
  });
  const sizeUp = useMutation({
    mutationFn: scopeRequest,
    onSuccess: (sized: GenerateScope, text: string) => {
      if (sized.questions.length) setScope(sized);
      else generate.mutate({ text, sized });
    },
    onError: (_error: Error, text: string) => generate.mutate({ text }),
  });

  // A world map's reading and a map draft are followed where they were started, never here.
  const listed = (conversions.data ?? []).filter(makesModule);
  // A paused thorough conversion is shown as a running one is, to be resumed; it holds no slot.
  const running =
    listed.find((c) => c.status === "running") ??
    listed.find((c) => c.status === "paused") ??
    listed.find((c) => c.status === "queued") ??
    null;
  // A running conversion found after a reload is followed too, so its end stays in view when it is no longer running.
  useEffect(() => {
    if (running && !followed) setFollowed(running);
  }, [running, followed]);
  const shown = (followed && (listed.find((c) => c.id === followed.id) ?? followed)) ?? running;
  // A book or a request sent while a conversion runs waits in the queue.
  const uploading = convert.isPending || generate.isPending || sizeUp.isPending;

  function submit(e: FormEvent) {
    e.preventDefault();
    const value = title.trim();
    if (value) create.mutate(value);
  }

  function pick(e: ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0];
    e.target.value = ""; // the same file can be picked again after a refusal
    if (file) upload.mutate(file);
  }

  function pickBook(e: ChangeEvent<HTMLInputElement>) {
    takeBook(e.target.files?.[0] ?? null);
    setDropped(null);
  }

  function takeBook(file: File | null) {
    setBook(file);
    if (file && !bookTitle.trim()) setBookTitle(file.name.replace(/\.pdf$/i, ""));
  }

  // A file dropped on the page: a PDF opens the PDF form with it, a .dscn is imported at once.
  const dragging = useFileDrop(
    (file) => {
      if (/\.pdf$/i.test(file.name) || file.type === "application/pdf") {
        takeBook(file);
        setDropped(file.name);
        setRefusedDrop(null);
        setParams({ way: "pdf" });
      } else if (/\.dscn$/i.test(file.name)) {
        setRefusedDrop(null);
        upload.mutate(file);
      } else {
        setDropped(null);
        setRefusedDrop(file.name);
      }
    },
    !uploading && !upload.isPending,
  );

  function submitBook(e: FormEvent) {
    e.preventDefault();
    const name = bookTitle.trim();
    if (book && name) convert.mutate({ file: book, name });
  }

  function submitRequest(e: FormEvent) {
    e.preventDefault();
    const text = request.trim();
    if (!text) return;
    if (scope) generate.mutate({ text, sized: scope, given: answers });
    else sizeUp.mutate(text);
  }

  const failure = (error: Error | null, key: string, file?: string) =>
    error && !(error instanceof NeedsToken) ? (
      <p role="alert" className="notice error">
        {t(key, { error: error.message, file: file ?? "" })}
      </p>
    ) : null;
  // A refused import names its file, picked or dropped, whichever way it came.
  const importFailure = failure(upload.error, "modules.importFailed", upload.variables instanceof File ? upload.variables.name : undefined);

  return (
    <section className="page new-module">
      <p>
        <Link to="/modules">{t("module.back")}</Link>
      </p>
      <h1>{t("modules.new")}</h1>
      <p className="hint">{t("newModule.dropHint")}</p>
      {dragging && (
        <div className="drop-overlay" aria-hidden="true">
          <p>{t("newModule.dropHere")}</p>
        </div>
      )}
      {refusedDrop && (
        <p role="alert" className="notice error">
          {t("newModule.dropRefused", { name: refusedDrop })}
        </p>
      )}
      {way !== "dscn" && importFailure}

      {shown && (
        <>
          <ConversionProgress key={shown.id} conversion={shown} />
          {shown.status === "running" && <p className="hint">{t("newModule.oneAtATime")}</p>}
          {shown.status !== "running" && shown.status !== "paused" && typeof shown.cost_usd === "number" && (
            <p className="hint">{t("conversion.cost", { amount: shown.cost_usd.toFixed(2) })}</p>
          )}
          {shown.status === "done" && shown.module_id && (
            <BookMaps moduleId={shown.module_id} conversions={conversions.data ?? []} warnings={shown.warnings} />
          )}
        </>
      )}

      {isWay(way) ? (
        <>
          <p>
            <Link to="/modules/new">{t("newModule.otherWays")}</Link>
          </p>
          {way === "empty" && (
            <Choice id="empty" title={t("newModule.empty")} hint={t("newModule.emptyHint")}>
              <form className="inline-form" onSubmit={submit}>
                <div className="field">
                  <label htmlFor="module-title">{t("modules.title")}</label>
                  <input id="module-title" value={title} onChange={(e) => setTitle(e.target.value)} />
                </div>
                <button type="submit" className="primary" disabled={create.isPending || !title.trim()}>
                  {t("newModule.create")}
                </button>
              </form>
              {failure(create.error, "modules.createFailed")}
            </Choice>
          )}

          {way === "dscn" && (
            <Choice id="dscn" title={t("newModule.dscn")} hint={t("modules.importHint")}>
              <div className="upload">
                <label htmlFor="module-import" className="button-like">
                  {upload.isPending ? t("modules.importing") : t("modules.import")}
                </label>
                <input
                  id="module-import"
                  type="file"
                  accept=".dscn,application/zip,application/vnd.dscn+zip"
                  className="visually-hidden"
                  onChange={pick}
                  disabled={upload.isPending}
                />
              </div>
              {importFailure}
            </Choice>
          )}

          {way === "pdf" && (
            <Choice id="pdf" title={t("newModule.pdf")} hint={t("newModule.pdfHint")}>
              <form onSubmit={submitBook}>
                <div className="field">
                  <label htmlFor="pdf-file">{t("newModule.pdfFile")}</label>
                  <input id="pdf-file" type="file" accept="application/pdf,.pdf" onChange={pickBook} />
                  {dropped && book?.name === dropped && <span className="hint">{t("newModule.dropped", { name: dropped })}</span>}
                </div>
                <div className="field">
                  <label htmlFor="pdf-title">{t("newModule.pdfTitle")}</label>
                  <input id="pdf-title" value={bookTitle} onChange={(e) => setBookTitle(e.target.value)} />
                </div>
                <fieldset className="field depth">
                  <legend>{t("newModule.depth")}</legend>
                  <div className="depth-option">
                    <label className="check">
                      <input
                        type="radio"
                        name="pdf-depth"
                        value="thorough"
                        checked={depth === "thorough"}
                        disabled={!thoroughOk}
                        onChange={() => setPicked("thorough")}
                      />
                      {t("newModule.thorough")}
                    </label>
                    <p className="hint">
                      {options.data && !thoroughOk
                        ? t("newModule.thoroughUnavailable", { reason: options.data.thorough.reason ?? "" })
                        : t("newModule.thoroughHint")}
                    </p>
                  </div>
                  <div className="depth-option">
                    <label className="check">
                      <input type="radio" name="pdf-depth" value="quick" checked={depth === "quick"} onChange={() => setPicked("quick")} />
                      {t("newModule.quick")}
                    </label>
                    <p className="hint">{t("newModule.quickHint")}</p>
                  </div>
                </fieldset>
                <fieldset className="field">
                  <legend>{t("newModule.mode")}</legend>
                  {MODES.map((m) => (
                    <label key={m} className="check">
                      <input type="radio" name="pdf-mode" value={m} checked={mode === m} onChange={() => setMode(m)} />
                      {t(`newModule.mode.${m}`)}
                    </label>
                  ))}
                </fieldset>
                <div className="field">
                  <label htmlFor="pdf-comments">{t("conversionNotes.comments")}</label>
                  <textarea
                    id="pdf-comments"
                    rows={3}
                    maxLength={COMMENTS_MAX}
                    value={comments}
                    aria-describedby="pdf-comments-hint"
                    onChange={(e) => setComments(e.target.value)}
                  />
                  <p className="hint" id="pdf-comments-hint">
                    {t("conversionNotes.commentsHint", { max: String(COMMENTS_MAX) })}
                  </p>
                </div>
                {depth === "quick" && (
                  <div className="field">
                    <label className="check">
                      <input type="checkbox" checked={bookMaps} onChange={(e) => setBookMaps(e.target.checked)} />
                      {t("newModule.bookMaps")}
                    </label>
                    <p className="hint">{t("newModule.bookMapsHint")}</p>
                  </div>
                )}
                <button type="submit" className="primary" disabled={uploading || !book || !bookTitle.trim()}>
                  {t("newModule.convert")}
                </button>
              </form>
              {failure(convert.error, "newModule.startFailed")}
            </Choice>
          )}

          {way === "describe" && (
            <Choice id="describe" title={t("newModule.describe")} hint={t("newModule.describeHint")}>
              <form onSubmit={submitRequest}>
                <div className="field">
                  <label htmlFor="module-request">{t("newModule.request")}</label>
                  <textarea
                    id="module-request"
                    rows={4}
                    value={request}
                    onChange={(e) => {
                      setRequest(e.target.value);
                      setScope(null);
                    }}
                  />
                  {LOOKS_LIKE_IMPORT.test(request) && (
                    <p className="hint" role="note">
                      {t("conversionNotes.looksLikeImport")} <Link to="/modules/new?way=pdf">{t("conversionNotes.toPdfForm")}</Link>
                    </p>
                  )}
                </div>
                {sizeUp.isPending && (
                  <p className="hint" role="status">
                    {t("newModule.sizingUp")}
                  </p>
                )}
                {scope && (
                  <fieldset className="scope-questions">
                    <legend>{t("newModule.scopeQuestions")}</legend>
                    <p className="hint">{t(SCOPE_HINTS[scope.scale])}</p>
                    <p className="hint">{t("newModule.scopeHint")}</p>
                    {scope.questions.map((q) => (
                      <div className="field" key={q.id}>
                        <label htmlFor={`scope-${q.id}`}>{q.text}</label>
                        <input
                          id={`scope-${q.id}`}
                          type="text"
                          value={answers[q.id] ?? ""}
                          placeholder={q.default}
                          onChange={(e) => setAnswers({ ...answers, [q.id]: e.target.value })}
                        />
                      </div>
                    ))}
                  </fieldset>
                )}
                <div className="field">
                  <label className="check">
                    <input
                      type="checkbox"
                      checked={paintPictures && picturesAllowed}
                      disabled={!picturesAllowed}
                      onChange={(e) => setPaintPictures(e.target.checked)}
                    />
                    {t("newModule.pictures")}
                  </label>
                  {paintPictures && picturesAllowed && (
                    <label className="check picture-limit">
                      {t("newModule.picturesLimit")}
                      <select value={pictureLimit} onChange={(e) => setPictureLimit(Number(e.target.value))}>
                        {Array.from({ length: PICTURES_MAX }, (_, n) => (
                          <option key={n + 1} value={n + 1}>
                            {n + 1}
                          </option>
                        ))}
                      </select>
                    </label>
                  )}
                  <p className="hint">{t("newModule.picturesHint")}</p>
                  {!picturesAllowed && <p className="hint">{t("newModule.picturesOwner")}</p>}
                  {options.data?.pictures?.paid && picturesAllowed && paintPictures && <p className="hint">{t("newModule.picturesPaid")}</p>}
                </div>
                <button type="submit" className="primary" disabled={uploading || !request.trim()}>
                  {t("newModule.generate")}
                </button>
              </form>
              {failure(generate.error, "newModule.startFailed")}
            </Choice>
          )}
        </>
      ) : (
        <ul className="choices">
          {WAYS.map((id) => (
            <li key={id}>
              <button type="button" className="choice choice-pick" onClick={() => setParams({ way: id })}>
                <span className="choice-title">{t(TITLES[id])}</span>
                <span className="hint">{t(HINTS[id])}</span>
              </button>
            </li>
          ))}
        </ul>
      )}

      <ConversionsPanel />

      {failure(conversions.error, "newModule.conversionsFailed")}
    </section>
  );
}

const TITLES: Record<Way, string> = {
  empty: "newModule.empty",
  pdf: "newModule.pdf",
  describe: "newModule.describe",
  dscn: "newModule.dscn",
};
const HINTS: Record<Way, string> = {
  empty: "newModule.emptyHint",
  pdf: "newModule.pdfHint",
  describe: "newModule.describeHint",
  dscn: "modules.importHint",
};

/** The picked way's form: a region named by its heading. */
function Choice({ id, title, hint, children }: { id: string; title: string; hint: string; children: ReactNode }) {
  return (
    <section className="choice" aria-labelledby={`choice-${id}`} data-testid={`choice-${id}`}>
      <h2 id={`choice-${id}`}>{title}</h2>
      <p className="hint">{hint}</p>
      {children}
    </section>
  );
}

/** Where a book draft's job is: its page and its place among the pages a conversion drafts. */
interface BookMapTarget {
  module_id?: string;
  page?: string;
  batch?: { index: number; count: number };
}

/**
 * The drafts a made module's book maps get (faithful modules B2): "Drawing the map of page 37 (2 of 3)" while one is
 * drawn, from the jobs' `target`, followed by the `conversion` events; once they have all ended, "Review the drafts",
 * the module's Maps tab. With warnings, "See the warnings" opens the module's page, which lists them.
 */
function BookMaps({ moduleId, conversions, warnings }: { moduleId: string; conversions: Conversion[]; warnings: Conversion["warnings"] }) {
  const t = useT();
  const client = useQueryClient();
  const subscribe = useContext(EventsContext);
  const jobs = conversions.filter((c) => c.kind === "book-map" && (c.target as BookMapTarget | null | undefined)?.module_id === moduleId);
  const known = jobs.map((c) => `${c.id}:${c.status}`).join(" ");

  // A job this list doesn't know yet, or one that ended: fetch the list again, for its target or its end.
  useEffect(
    () =>
      subscribe({
        conversion: (data) => {
          const event = data as ConversionEvent | null;
          if (event && !known.includes(`${event.id}:${event.status}`)) client.invalidateQueries({ queryKey: queryKeys.conversions });
        },
      }),
    [subscribe, client, known],
  );

  const drawing = jobs.find((c) => c.status === "running");
  const target = (drawing?.target ?? {}) as BookMapTarget;
  const page = target.page?.match(/(\d+)(?:-\d+)?$/)?.[1] ?? drawing?.title ?? "";
  const module = `/modules/${encodeURIComponent(moduleId)}`;
  return (
    <div className="actions">
      {drawing ? (
        <p className="row-meta">
          {t("newModule.drawingPage", {
            page,
            index: String(target.batch?.index ?? 1),
            count: String(target.batch?.count ?? 1),
          })}
        </p>
      ) : (
        jobs.length > 0 && (
          <Link className="button-like" to={`${module}?tab=maps`}>
            {t("newModule.reviewDrafts")}
          </Link>
        )
      )}
      {warnings.length > 0 && (
        <Link to={module} state={{ warnings, from: "conversion" }}>
          {t("newModule.seeWarnings")}
        </Link>
      )}
    </div>
  );
}
