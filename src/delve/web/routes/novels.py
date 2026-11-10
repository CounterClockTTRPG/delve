"""Novels (novelization Task 5): a campaign or a module written as a novel in the background. The owner's alone
(`Owner`), reads too: a novel may hold every secret of the campaign (owner decision 7), so an organiser seat gets 403
as every other seat does.

A start answers 202 with the novel at once (`writing`); its job's progress arrives as `conversion` events, which hold
the job's title ("Novel: <source name>"), step and counts and never the novel's text. One job runs at a time: a start
or a Continue while another runs is 409 "A conversion is running.", with the running one. The list answers each novel
without its chapters' text; `GET /api/novels/{id}` answers the whole novel.
"""

from __future__ import annotations

from dataclasses import replace
from typing import Any

from fastapi import APIRouter, FastAPI, HTTPException, Request, Response
from pydantic import BaseModel, ConfigDict

from delve.conversions import ConversionRunning, cancel
from delve.domain.novels import Novel
from delve.domain.settings import Job
from delve.novels.jobs import TITLE_LENGTH, NovelRequest, NovelServices, NovelStateError, continue_novel, start_novel
from delve.novels.material import SessionRangeError
from delve.web.auth import Owner
from delve.web.routes.conversions import _running, conversions
from delve.web.routes.preferences import current_preferences

router = APIRouter()

BAD_RANGE = "That range of sessions can't be written."
STILL_WRITING = "The novel is being written: cancel it first."


def novels(app: FastAPI) -> NovelServices:
    """The app's novel services, made on first use: its conversion services, and Preferences' choice for the `novel`
    job."""
    services = getattr(app.state, "novels", None)
    if services is None:
        services = NovelServices(conversions(app), writer=lambda: _writer(app))
        app.state.novels = services
    return services


def _writer(app: FastAPI) -> tuple[Any, Any]:
    choice = current_preferences(app).choices.get(Job.NOVEL)
    if choice is None:
        raise RuntimeError("No provider does the novel job: choose one under Preferences.")
    return app.state.registries.dm.get(choice.provider), choice


def novel_json(novel: Novel) -> dict[str, Any]:
    return novel.to_dict()


def listed_json(novel: Novel) -> dict[str, Any]:
    """A novel for the list: its chapters' titles and summaries, and whether each is written, never their text."""
    chapters = [{"title": c.title, "summary": c.summary, "written": c.text is not None} for c in novel.chapters]
    return {**novel.to_dict(), "chapters": chapters}


def _novel(request: Request, id: str) -> Novel:
    novel = request.app.state.storage.novels.get(id)
    if novel is None:
        raise HTTPException(status_code=404, detail="No such novel.")
    return novel


def _not_found(source: str) -> HTTPException:
    return HTTPException(status_code=404, detail=f"No such {source}.")


class NovelIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source: str
    id: str
    length: str = "recap"
    tone: str = "classic"
    custom_tone: str = ""
    language: str = "en"
    instructions: str = ""
    sessions: tuple[int, int] | None = None
    revision: int | None = None


@router.post("/api/novels", status_code=202)
async def create_novel(request: Request, principal: Owner, body: NovelIn) -> dict:
    """Novelize a campaign (all its sessions, or `sessions`: first and last) or a module (at `revision`, else the
    latest): 422 for a bad choice or range, 404 for no such source, 409 while a job runs."""
    try:
        novel = await start_novel(novels(request.app), NovelRequest(**body.model_dump()))  # type: ignore[arg-type]
    except SessionRangeError as error:
        raise HTTPException(status_code=422, detail={"error": BAD_RANGE, "hint": error.hint}) from None
    except ConversionRunning as error:
        raise _running(error) from None
    except KeyError:
        raise _not_found("revision" if body.revision is not None else body.source) from None
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from None
    return novel_json(novel)


@router.get("/api/novels")
def list_novels(
    request: Request, principal: Owner, campaign_id: str | None = None, module_id: str | None = None
) -> list[dict]:
    """The novels of one campaign or one module, newest first, without their chapters' text."""
    storage = request.app.state.storage
    if (campaign_id is None) == (module_id is None):
        raise HTTPException(status_code=422, detail="Name a campaign_id or a module_id.")
    if campaign_id is not None:
        if storage.campaigns.get(campaign_id) is None:
            raise _not_found("campaign")
        found = storage.novels.for_campaign(campaign_id)
    else:
        if storage.modules.get(module_id) is None:
            raise _not_found("module")
        found = storage.novels.for_module(module_id)
    return [listed_json(novel) for novel in found]


@router.get("/api/novels/{novel_id}")
def get_novel(request: Request, principal: Owner, novel_id: str) -> dict:
    return novel_json(_novel(request, novel_id))


class RenameIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str


@router.patch("/api/novels/{novel_id}")
def rename_novel(request: Request, principal: Owner, novel_id: str, body: RenameIn) -> dict:
    novel = _novel(request, novel_id)
    title = body.title.strip()
    if not title or len(title) > TITLE_LENGTH:
        raise HTTPException(status_code=422, detail=f"A novel's title has 1 to {TITLE_LENGTH} characters.")
    return novel_json(request.app.state.storage.novels.save(replace(novel, title=title)))


@router.delete("/api/novels/{novel_id}", status_code=204)
def delete_novel(request: Request, principal: Owner, novel_id: str) -> Response:
    novel = _novel(request, novel_id)
    if novel.status == "writing":
        raise HTTPException(status_code=409, detail=STILL_WRITING)
    request.app.state.storage.novels.delete(novel.id)
    return Response(status_code=204)


@router.post("/api/novels/{novel_id}/continue", status_code=202)
async def continue_writing(request: Request, principal: Owner, novel_id: str) -> dict:
    """Write the rest of a failed or cancelled novel: 409 for another status, or while a job runs."""
    _novel(request, novel_id)
    try:
        novel = await continue_novel(novels(request.app), novel_id)
    except ConversionRunning as error:
        raise _running(error) from None
    except NovelStateError as error:
        raise HTTPException(status_code=409, detail=str(error)) from None
    except SessionRangeError as error:
        raise HTTPException(status_code=422, detail={"error": BAD_RANGE, "hint": error.hint}) from None
    return novel_json(novel)


@router.post("/api/novels/{novel_id}/cancel")
async def cancel_novel(request: Request, principal: Owner, novel_id: str) -> dict:
    """Stop the novel's job: it ends `cancelled`, keeping its chapters. A novel not being written stays as it is."""
    novel = _novel(request, novel_id)
    if novel.status != "writing":
        return novel_json(novel)
    if novel.conversion_id is not None:
        await cancel(novels(request.app).conversions, novel.conversion_id)
    storage = request.app.state.storage
    novel = _novel(request, novel_id)
    if novel.status == "writing":  # its job wasn't running here: a Delve that stopped left it
        novel = storage.novels.save(replace(novel, status="cancelled"))
    return novel_json(novel)
