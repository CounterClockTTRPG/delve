"""Conversions (plan 5 Task 5, spec §8.3): a PDF or a request becomes a module in the background. Organisers only.

A start answers 202 with the conversion at once; its progress arrives as `conversion` events, `{id, status, step,
done, total, steps}`, and is stored on the conversion, so a reload sees it (`GET /api/conversions`). One conversion runs at a
time. A PDF uploaded while one runs is `queued`, and starts by itself, oldest first, when the slot frees; any other
start is then 409 "A conversion is running.", with the running one. The module is made at the end.

The queue (thorough conversion, owner addition 2026-10-23): `GET /api/conversions/queue` lists the jobs that aren't
over in the order they get the slot, with its switch, `{"paused", "jobs"}`; `PUT` with `{"paused"}` pauses it (no
queued job starts, nor a resume by itself; a running job runs on) or unpauses it. A running thorough job is paused by
hand with `POST /api/conversions/{id}/pause`.

The PDF upload's body is the book. The guard has let only `application/pdf` through; it streams to a temporary file in
`<data dir>/uploads`, at most `PDF_LIMIT` bytes (413), and must start with `%PDF-` (400). The job owns the file from
there and removes it when it ends. Its title and mode are checked first (422), so a refused start takes in no book. At
startup, an upload that no running job owns was left by a Delve that stopped, and is removed
(`remove_leftover_uploads`).

A PDF is converted thoroughly by default (`thorough=true`, thorough conversion Task 8): by agents in a job folder
under `<data dir>/conversions/`, on Preferences' `conversion.thorough` choice, which must be the Claude CLI, with
`claude` installed (`thorough_unavailable`; 409 with the code `thorough_unavailable` otherwise, and
`GET /api/conversions/options` says why, so the form offers Quick alone). `thorough=false` is the quick conversion,
unchanged. A thorough job that pauses (Delve stopped, the usage limit, an error) is resumed with
`POST /api/conversions/{id}/resume`, which puts it back in the queue, and at startup (`resume_paused`). Its doubts
reach the DM only through
`POST /api/conversions/{id}/tell-dm`.

The PDF form's comments (table voice and fixes Task F1) travel as `comments=` on the upload, at most `COMMENTS_MAX`
characters (422 over). A job's questions and doubts are closed with `PUT /api/conversions/{id}/closed` (table voice
and fixes Task F3), which only hides them.
"""

from __future__ import annotations

import asyncio
import os
import tempfile
from dataclasses import asdict
from pathlib import Path
from typing import Any, Literal

from fastapi import APIRouter, FastAPI, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field
from starlette.concurrency import run_in_threadpool

from delve.conversions import (
    ConversionRunning,
    ConversionServices,
    answer_questions,
    cancel,
    check_pdf,
    conversion_json,
    set_queue_paused,
    start_generate,
    start_pdf,
    tell_dm,
)
from delve.conversions import thorough as thorough_jobs
from delve.conversions.dungeon_maps import draw_book_maps
from delve.conversions.runner import close_items, queue, scope_generate
from delve.conversions.thorough.pieces import AgentRunner
from delve.conversions.thorough.workspace import RECORDS, install_qa
from delve.dm.claude_cli.agent import AGENT_TIMEOUT, run_agent
from delve.dm.claude_cli.provider import PROVIDER_ID as CLAUDE_CLI
from delve.domain.campaigns import default_ruleset
from delve.domain.conversions import Conversion
from delve.domain.settings import BackendChoice, Job
from delve.maps.geo.reading.ocr import tesseract_words
from delve.modules.books.campaign import Answer
from delve.modules.books.pictures import MAX_PICTURES
from delve.web.guard import PDF_LIMIT, PDF_TYPE
from delve.web.routes.modules import Organiser, changed
from delve.web.routes.preferences import current_preferences, image_paid

router = APIRouter()

PDF_MAGIC = b"%PDF-"
LIST_LIMIT = 20
UPLOAD_PREFIX, UPLOAD_SUFFIX = "conversion-", ".pdf"
PAID_PICTURES = "Only the owner may paint with a paid image model."
THOROUGH_UNAVAILABLE = "thorough_unavailable"
"""The code of the 409 a thorough start gets when it can't run."""
NO_CLAUDE = "The Claude CLI isn't installed, and a thorough conversion runs on it."
NOT_CLAUDE = "A thorough conversion runs on the Claude CLI: choose it for Thorough conversion under Preferences."
REPOSITORY = Path(__file__).resolve().parents[4]
"""Delve's own source tree, which no agent may read (`agent_settings`)."""


def conversions(app: FastAPI) -> ConversionServices:
    """The app's conversion services, made on first use: its storage, Preferences' choice for the `conversion` job and
    for `conversion.thorough`, its event stream, tesseract for a world map's picture (none when it isn't installed, or
    under `DELVE_OCR=off`), and the thorough jobs' agent sessions, `claude -p` in the job folder (`agent_runner`;
    none when the Claude CLI isn't there)."""
    services = getattr(app.state, "conversions", None)
    if services is None:
        services = ConversionServices(
            storage=app.state.storage,
            conversion=lambda: _choice(app),
            publish=app.state.events.publish,
            picture_ocr=tesseract_words(),
            thorough=lambda: _choice(app, Job.CONVERSION_THOROUGH),
            agent=agent_runner(app) if _claude_cli(app) else None,
            images=lambda job: _images(app, job),
            image_paid=lambda job: image_paid(app, job),
            settings=app.state.registries.catalogs.settings,
            game=_game(app),
        )
        app.state.conversions = services
    return services


def _images(app: FastAPI, job: Job) -> tuple[Any, BackendChoice]:
    """The image provider and choice of an image job, as play has them."""
    from delve.web.routes.play import table_of  # it imports the modules' routes

    return table_of(app).images(job)


def agent_runner(app: FastAPI) -> AgentRunner:
    """One agent session of a thorough job: `run_agent` in the job folder, with `AGENT_TIMEOUT`, kept out of the
    app's data directory and Delve's source (`agent_settings`); `choice` is the `conversion.thorough` job's. Its Bash
    runs the `qa` wrapper alone, installed first for this Delve's Python (a job made by another install runs this
    one's tools), and Delve's records in the folder (`RECORDS`) are its to read only."""

    async def run(prompt: str, folder: Path, choice: BackendChoice) -> Any:
        data_dir = app.state.config.data_dir
        qa = await asyncio.to_thread(install_qa, data_dir)
        return await run_agent(
            prompt, folder, choice, timeout=AGENT_TIMEOUT, repo=REPOSITORY, data_dir=data_dir, qa=qa, records=RECORDS
        )

    return run


def _claude_cli(app: FastAPI) -> bool:
    return any(caps.id == CLAUDE_CLI for caps in app.state.registries.dm.capabilities())


def thorough_unavailable(app: FastAPI) -> str | None:
    """Why a thorough conversion can't run now, or None when it can: it needs the Claude CLI installed and chosen for
    Preferences' `conversion.thorough` job."""
    if not _claude_cli(app):
        return NO_CLAUDE
    choice = current_preferences(app).choices.get(Job.CONVERSION_THOROUGH)
    if choice is None or choice.provider != CLAUDE_CLI:
        return NOT_CLAUDE
    return None


async def resume_paused(app: FastAPI) -> Conversion | None:
    """At startup, after `close_orphans`: every paused thorough job that Delve's stop paused goes back in the queue,
    and the queue starts, unless its switch is paused (`thorough.resume_stopped`). A job paused at the usage limit
    gets its resume scheduled again, at its reset time. A job whose folder can't be read is left as it is, so Delve
    still starts. Answers the job started, if any."""
    return await thorough_jobs.resume_stopped(conversions(app))


def uploads_folder(app: FastAPI) -> Path:
    return app.state.config.data_dir / "uploads"


def remove_leftover_uploads(app: FastAPI) -> list[Path]:
    """Remove the uploaded PDFs that no running or queued job owns; answers the files removed."""
    services = conversions(app)
    owned = {live.upload for live in services.live.values()}
    owned |= {Path(c.target["upload"]) for c in services.storage.conversions.queued() if (c.target or {}).get("upload")}
    left = [p for p in sorted(uploads_folder(app).glob(f"{UPLOAD_PREFIX}*{UPLOAD_SUFFIX}")) if p not in owned]
    for path in left:
        path.unlink(missing_ok=True)
    return left


def _choice(app: FastAPI, job: Job = Job.CONVERSION) -> tuple[Any, Any]:
    choice = current_preferences(app).choices.get(job)
    if choice is None:
        raise RuntimeError(f"No provider does the {job} job: choose one under Preferences.")
    return app.state.registries.dm.get(choice.provider), choice


def _running(error: ConversionRunning) -> HTTPException:
    detail: dict[str, Any] = {"error": str(error)}
    if error.conversion is not None:
        detail["conversion"] = conversion_json(error.conversion)
    return HTTPException(status_code=409, detail=detail)


def _refused(error: ValueError) -> HTTPException:
    return HTTPException(status_code=422, detail=str(error))


async def _receive_pdf(request: Request, folder: Path) -> Path:
    """The body, streamed to a new file in `folder`: 413 past `PDF_LIMIT`, 400 if it doesn't start as a PDF. A refused
    upload leaves no file."""
    folder.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix=UPLOAD_PREFIX, suffix=UPLOAD_SUFFIX, dir=folder)
    path = Path(name)
    size = 0
    head = b""
    try:
        with os.fdopen(fd, "wb") as file:
            async for chunk in request.stream():
                size += len(chunk)
                if size > PDF_LIMIT:
                    raise HTTPException(status_code=413, detail=f"A PDF to convert may be at most {PDF_LIMIT} bytes.")
                if len(head) < len(PDF_MAGIC):
                    head += chunk[: len(PDF_MAGIC) - len(head)]
                file.write(chunk)
        if head != PDF_MAGIC:
            raise HTTPException(status_code=400, detail="The file isn't a PDF.")
    except BaseException:
        path.unlink(missing_ok=True)
        raise
    return path


@router.post("/api/conversions/pdf", status_code=202)
async def convert_pdf(
    request: Request,
    principal: Organiser,
    title: str = "",
    mode: str = "ready",
    book_maps: bool = True,
    thorough: bool = True,
    comments: str = "",
) -> dict:
    """Convert the PDF in the body into a module titled `title`, ready to play or a draft (`mode`): thoroughly (the
    default), or quickly with `thorough=false`; while another job runs, or the queue is paused, it is queued. A
    thorough start that can't run is 409 `thorough_unavailable`. With
    `book_maps` (the default; a quick conversion's only, as tracing the book's maps is part of a thorough one), each
    sketch is then drawn again from the book's map page, as a draft kept only on Keep. The organiser's `comments`
    (table voice and fixes Task F1; at most `COMMENTS_MAX` characters, 422 over) are kept on the job and given to its
    prompts; they travel in the query string, as the body is the book, and the access log drops them."""
    media_type = request.headers.get("content-type", "").split(";")[0].strip().lower()
    if media_type != PDF_TYPE:
        raise HTTPException(status_code=415, detail=f"Send the book as {PDF_TYPE}.")
    try:
        check_pdf(title, mode, comments)
    except ValueError as error:
        raise _refused(error) from None
    app = request.app
    unavailable = thorough_unavailable(app) if thorough else None
    if unavailable is not None:
        raise HTTPException(status_code=409, detail={"error": unavailable, "code": THOROUGH_UNAVAILABLE})
    services = conversions(app)
    path = await _receive_pdf(request, uploads_folder(app))
    try:
        if thorough:
            data_dir = app.state.config.data_dir
            conversion = await thorough_jobs.start_thorough(services, path, title, mode, data_dir=data_dir, comments=comments)  # type: ignore[arg-type]
        else:
            then = (lambda job: draw_book_maps(services, job.module_id)) if book_maps else None
            conversion = await start_pdf(services, path, title, mode, then=then, book_maps=book_maps, comments=comments)  # type: ignore[arg-type]
    except ValueError as error:
        raise _refused(error) from None
    return conversion_json(conversion)


class AnswerIn(BaseModel):
    text: str
    default: str = ""
    answer: str = ""


class GenerateIn(BaseModel):
    request: str
    mode: Literal["ready", "draft"] = "ready"
    scale: Literal["module", "campaign", "sandbox"] | None = None
    answers: list[AnswerIn] = []
    pictures: int = Field(0, ge=0, le=MAX_PICTURES)
    """At most how many handouts to paint for the module (DEL-347); 0 for none."""


class ScopeIn(BaseModel):
    request: str


@router.post("/api/conversions/generate/scope")
async def generate_scope(request: Request, principal: Organiser, body: ScopeIn) -> dict:
    """Before Generate (DEL-134): `{scale, questions: [{id, text, default}]}`, the request's scale (`module` or
    `campaign`) and what to ask the organiser first, from one short side call. 422 for an empty request, 502 when the
    call fails (New module then starts the job, which scopes the request itself)."""
    try:
        scope = await scope_generate(conversions(request.app), body.request)
    except ValueError as error:
        raise _refused(error) from None
    except Exception as error:  # noqa: BLE001 (any provider failure is the same answer to the organiser)
        raise HTTPException(status_code=502, detail=f"The request couldn't be scoped: {error}") from None
    return {"scale": scope.scale, "questions": [asdict(q) for q in scope.questions]}


@router.post("/api/conversions/generate", status_code=202)
async def generate(request: Request, principal: Organiser, body: GenerateIn) -> dict:
    """Generate a module from a request ("a dungeon with kobolds, no plot"), with its `scale` and the organiser's
    `answers` to the scope questions when New module asked them (DEL-134); while another job runs, or the queue is
    paused, it is queued, as a PDF is (DEL-141), and at most `pictures` painted handouts (DEL-347). 422 for an empty
    one, and for pictures with a paid model unless the caller is the owner."""
    answers = [Answer(a.text, a.default, a.answer) for a in body.answers]
    if body.pictures and not principal.owner and await run_in_threadpool(image_paid, request.app, Job.IMAGE_SCENE):
        raise HTTPException(status_code=422, detail=PAID_PICTURES)
    try:
        conversion = await start_generate(
            conversions(request.app),
            body.request,
            body.mode,
            scale=body.scale,
            answers=answers,
            pictures=body.pictures,
            owner=principal.owner,
        )
    except ValueError as error:
        raise _refused(error) from None
    return conversion_json(conversion)


@router.get("/api/conversions/options")
async def conversion_options(request: Request, principal: Organiser) -> dict:
    """What the forms may offer: `{"thorough": {"available", "reason"}, "pictures": {"paid", "allowed"}}`, the reason
    null when it is available, and whether a generated module's pictures cost money and this caller may ask for them."""
    reason = thorough_unavailable(request.app)
    paid = await run_in_threadpool(image_paid, request.app, Job.IMAGE_SCENE)
    return {
        "thorough": {"available": reason is None, "reason": reason},
        "pictures": {"paid": paid, "allowed": principal.owner or not paid},
    }


@router.get("/api/conversions")
def list_conversions(request: Request, principal: Organiser) -> list[dict]:
    """The last `LIST_LIMIT` conversions, newest first."""
    return [conversion_json(c) for c in request.app.state.storage.conversions.list(limit=LIST_LIMIT)]


class QueueIn(BaseModel):
    paused: bool


def _queue_json(app: FastAPI) -> dict:
    storage = app.state.storage
    return {"paused": storage.conversions.queue_paused(), "jobs": [conversion_json(c) for c in queue(storage)]}


@router.get("/api/conversions/queue")
def read_queue(request: Request, principal: Organiser) -> dict:
    """The queue: `{"paused", "jobs"}`, the jobs that aren't over in the order they get the slot: the running one,
    the queued ones oldest first, then the paused ones."""
    return _queue_json(request.app)


@router.put("/api/conversions/queue")
async def put_queue(request: Request, principal: Organiser, body: QueueIn) -> dict:
    """Pause the queue (no queued job starts, nor a resume by itself; a running one runs on) or unpause it, which
    starts the oldest queued job when the slot is free. Stored, so it survives a restart. Answers the queue."""
    set_queue_paused(conversions(request.app), body.paused)
    return _queue_json(request.app)


@router.get("/api/conversions/{conversion_id}")
def read_conversion(request: Request, principal: Organiser, conversion_id: str) -> dict:
    conversion = request.app.state.storage.conversions.get(conversion_id)
    if conversion is None:
        raise HTTPException(status_code=404, detail="No such conversion.")
    return conversion_json(conversion)


@router.post("/api/conversions/{conversion_id}/cancel")
async def cancel_conversion(request: Request, principal: Organiser, conversion_id: str) -> dict:
    """Stop the conversion: it ends as `cancelled` and makes no module. One that has ended stays as it is."""
    try:
        return conversion_json(await cancel(conversions(request.app), conversion_id))
    except KeyError:
        raise HTTPException(status_code=404, detail="No such conversion.") from None


@router.post("/api/conversions/{conversion_id}/resume", status_code=202)
async def resume_conversion(request: Request, principal: Organiser, conversion_id: str) -> dict:
    """Put a paused thorough conversion back in the queue, to run again from its first unfinished piece: 202 with the
    job, running when the slot was free, else queued. 409 for a job that isn't paused, or whose state can't be
    read."""
    try:
        return conversion_json(await thorough_jobs.resume(conversions(request.app), conversion_id))
    except KeyError:
        raise HTTPException(status_code=404, detail="No such conversion.") from None
    except thorough_jobs.NotPaused as error:
        raise HTTPException(status_code=409, detail=str(error)) from None


@router.post("/api/conversions/{conversion_id}/pause")
async def pause_conversion(request: Request, principal: Organiser, conversion_id: str) -> dict:
    """Pause a running thorough conversion by hand: its agent sessions stop now, the pieces in progress are started
    over at the resume, and the next queued job starts. Answers the job, paused. 409 for any other job (a quick one,
    a queued one)."""
    try:
        return conversion_json(await thorough_jobs.pause(conversions(request.app), conversion_id))
    except KeyError:
        raise HTTPException(status_code=404, detail="No such conversion.") from None
    except thorough_jobs.NotPausable as error:
        raise HTTPException(status_code=409, detail=str(error)) from None


@router.post("/api/conversions/{conversion_id}/tell-dm")
def tell_the_dm(request: Request, principal: Organiser, conversion_id: str) -> dict:
    """Pass a thorough conversion's doubts to the DM: they are written into the module's DM-only text "Notes from
    making this module". Answers the job's entry, as the questions route does; 404 for a job without doubts or whose
    module is gone."""
    storage = request.app.state.storage
    try:
        entry = tell_dm(storage, conversion_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="No doubts to tell the DM for this conversion.") from None
    changed(request, storage.conversions.get(conversion_id).module_id)
    return entry


class AnswersIn(BaseModel):
    answers: dict[str, str] = {}
    remarks: list[str] = []


@router.put("/api/conversions/{conversion_id}/questions")
def put_answers(request: Request, principal: Organiser, conversion_id: str, body: AnswersIn) -> dict:
    """Answer the questions asked while making a module, by id, with remarks: they are written into the module's DM-only
    text "Notes from making this module" (`making-notes`), and the job isn't run again. 404 for a job that asked
    nothing or whose module is gone, 422 for an answer to a question it didn't ask."""
    storage = request.app.state.storage
    try:
        entry = answer_questions(storage, conversion_id, body.answers, body.remarks)
    except KeyError:
        raise HTTPException(status_code=404, detail="No questions to answer for this conversion.") from None
    except ValueError as error:
        raise _refused(error) from None
    changed(request, storage.conversions.get(conversion_id).module_id)
    return entry


class ClosedIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    closed: list[str]


@router.put("/api/conversions/{conversion_id}/closed")
def put_closed(request: Request, principal: Organiser, conversion_id: str, body: ClosedIn) -> dict:
    """Close the job's questions and doubts named by their keys (`question:<id>`, `doubt:<index>`), and reopen the
    others: stored on the job, so every organiser sees the same, and published as `modules` `{id}`. Closing only hides:
    the notes and what the DM is told don't change. Answers the job's entry; 404 for a job that asked nothing, 422 for a
    key that names no question or doubt of it."""
    storage = request.app.state.storage
    try:
        entry = close_items(storage, conversion_id, body.closed)
    except KeyError:
        raise HTTPException(status_code=404, detail="No questions or doubts for this conversion.") from None
    except ValueError as error:
        raise _refused(error) from None
    module_id = storage.conversions.get(conversion_id).module_id
    if module_id is not None:
        changed(request, module_id)
    return entry


def _game(app: FastAPI) -> str:
    """The title of the ruleset a new campaign takes on this install (its packs' preferred one, else the first), for
    what a generated module is written for; "" without one."""
    rulesets = app.state.registries.catalogs.rulesets
    chosen = default_ruleset([e.id for e in rulesets], {e.id for e in rulesets if e.preferred})
    return next((e.title for e in rulesets if e.id == chosen), "")
