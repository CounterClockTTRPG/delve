"""Preferences: which backend, model and effort each job uses, the interface language and the image style (DEL-202,
`delve.domain.image_styles`). Organisers only."""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Body, HTTPException, Request

from delve.domain import image_styles
from delve.domain.backends import ModelInfo, ProviderCapabilities
from delve.domain.settings import BackendChoice, Job, Settings, SettingsWarning, Unusable, resolve
from delve.play import seats
from delve.play.images import is_paid
from delve.web.auth import Organiser
from delve.web.defaults import default_choices, job_providers

router = APIRouter()


@router.get("/api/backends")
def backends(request: Request, principal: Organiser) -> dict:
    return {
        "jobs": [str(job) for job in Job],
        "providers": [_capabilities_json(caps) for caps in job_providers(request.app.state.registries)],
        "image_styles": [
            {"id": p.id, "name": p.name, "prompt": p.prompt, "sample": p.sample} for p in image_styles.PRESETS
        ],
    }


@router.get("/api/preferences")
def get_preferences(request: Request, principal: Organiser) -> dict:
    settings, warnings = _resolve(request, request.app.state.storage.settings.load())
    return {**preferences_json(settings), **warnings_json(warnings)}


@router.put("/api/preferences")
async def put_preferences(request: Request, principal: Organiser, raw: Annotated[dict[str, Any], Body()]) -> dict:
    """Store the preferences if every choice in them is valid; otherwise refuse them all with 422 and the warnings. A
    choice that can't be used only now (a live provider's problem, a model gone from it) is stored, with its
    warning, since assetgen may be down only for a moment. A body without `choices` (the side bar's language switch)
    changes only the language: the stored choices stay as they are stored, even those that can't be used now. A body
    without `image_style` keeps the stored one."""
    if "choices" not in raw:
        return _put_language(request, raw)
    if "image_style" not in raw:
        raw = {**raw, "image_style": request.app.state.storage.settings.load().get("image_style")}
    settings, warnings = _resolve(request, raw)
    if any(not isinstance(warning, Unusable) for warning in warnings):
        detail = {"error": "Some preferences can't be used.", **warnings_json(warnings)}
        raise HTTPException(status_code=422, detail=detail)
    stored = preferences_json(settings)
    # The rest of the stored settings (the backup time) stays as it is.
    request.app.state.storage.settings.update(stored)
    seats.follow_install_language(request.app.state.storage)
    request.app.state.events.publish("preferences", stored)
    from delve.web.routes.play import wake_banners  # it imports this module's `image_paid`

    wake_banners(request.app)  # a free model chosen for the scene opens the banners' gate
    return {**stored, **warnings_json(warnings)}


def _put_language(request: Request, raw: dict[str, Any]) -> dict:
    """Store `raw`'s language beside the stored choices, untouched; answer as GET does."""
    checked, refused = resolve({"language": raw.get("language")}, [], {})
    if refused:
        detail = {"error": "Some preferences can't be used.", **warnings_json(refused)}
        raise HTTPException(status_code=422, detail=detail)
    storage = request.app.state.storage
    saved = storage.settings.update({"language": checked.language})
    seats.follow_install_language(storage)
    settings, warnings = _resolve(request, saved)
    request.app.state.events.publish("preferences", preferences_json(settings))
    return {**preferences_json(settings), **warnings_json(warnings)}


def warnings_json(warnings: list[SettingsWarning]) -> dict[str, Any]:
    """The warnings as before, English strings, and beside them `coded_warnings`, the same ones as `{code, args,
    text}`, which the web says in the reader's language (open fixes Task 6)."""
    return {"warnings": list(warnings), "coded_warnings": [warning.to_json() for warning in warnings]}


# Models a provider no longer lists because no model means the same: claude-cli's "default" was the CLI's own.
RETIRED_MODELS = {("claude-cli", "default")}


def _resolve(request: Request, raw: dict[str, Any]) -> tuple[Settings, list[SettingsWarning]]:
    return _resolved(request.app, raw)


def _resolved(app, raw: Any) -> tuple[Settings, list[SettingsWarning]]:
    registries = app.state.registries
    return resolve(_unretired(raw), job_providers(registries), default_choices(registries))


def _unretired(raw: Any) -> Any:
    """`raw` with each choice of a retired model as no model, so a choice stored with one keeps working."""
    choices = raw.get("choices") if isinstance(raw, dict) else None
    if not isinstance(choices, dict):
        return raw
    retired = {
        job: {**choice, "model": None}
        for job, choice in choices.items()
        if isinstance(choice, dict) and (choice.get("provider"), choice.get("model")) in RETIRED_MODELS
    }
    return {**raw, "choices": {**choices, **retired}} if retired else raw


def current_preferences(app) -> Settings:
    """The app's stored preferences as they can be used now, with defaults for what can't."""
    return _resolved(app, app.state.storage.settings.load())[0]


def image_paid(app, job: Job) -> bool:
    """Whether the model Preferences chose for the image job costs money (`is_paid`); no choice counts as paid."""
    choice = current_preferences(app).choices.get(job)
    return choice is None or is_paid(app.state.registries, job, choice)


def preferences_json(settings: Settings) -> dict[str, Any]:
    """Preferences in their stored and API form, the jobs in their usual order."""
    choices = {str(job): _choice_json(settings.choices[job]) for job in Job if job in settings.choices}
    return {"choices": choices, "language": settings.language, "image_style": settings.image_style.to_json()}


def _choice_json(choice: BackendChoice) -> dict[str, Any]:
    effort = str(choice.effort) if choice.effort is not None else None
    return {"provider": choice.provider, "model": choice.model, "effort": effort}


def _capabilities_json(caps: ProviderCapabilities) -> dict[str, Any]:
    return {
        "id": caps.id,
        "title": caps.title,
        "jobs": [str(job) for job in Job if job in caps.jobs],
        "models": list(caps.models),
        "efforts": [str(effort) for effort in caps.efforts],
        "default_model": caps.default_model,
        "model_info": {model: _model_json(info) for model, info in caps.model_info.items()},
        "problem": caps.problem,
        "development": caps.development,
    }


def _model_json(info: ModelInfo) -> dict[str, Any]:
    return {"label": info.label, "backend": info.backend, "price": info.price, "paid": info.paid}
