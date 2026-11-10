"""The jobs Preferences choose a backend for, and how stored choices are checked against the providers there are."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from typing import TYPE_CHECKING, Any, Self

from delve.domain import image_styles
from delve.domain.image_styles import ImageStyle

if TYPE_CHECKING:
    from delve.domain.backends import ProviderCapabilities

LANGUAGE_NAMES = {"en": "English", "nl": "Dutch", "fr": "French", "de": "German", "lv": "Latvian"}
"""The languages Delve's interface speaks (DEL-122), by their code, named in English as Claude's prompts name them.
The one list: novels, a seat's story and the join page take theirs from here, and web/src/i18n has a dictionary for
each."""

LANGUAGES = tuple(LANGUAGE_NAMES)


class Job(StrEnum):
    """What a backend is chosen for (spec §5.2)."""

    DM = "dm"
    SIDE = "side"
    TRANSLATION = "translation"
    CONVERSION = "conversion"
    CONVERSION_THOROUGH = "conversion.thorough"
    NOVEL = "novel"
    IMAGE_PORTRAIT = "image.portrait"
    IMAGE_NPC_PORTRAIT = "image.npc_portrait"
    """An NPC's portrait, painted apart from the PCs' (DEL-248): there may be many, so its own, cheaper, painter or
    none."""
    IMAGE_SCENE = "image.scene"
    IMAGE_POSSESSION = "image.possession"


class Effort(StrEnum):
    AUTO = "auto"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    MAX = "max"


@dataclass(frozen=True)
class BackendChoice:
    """A provider for one job; no model or effort means the provider's own default."""

    provider: str
    model: str | None = None
    effort: Effort | None = None


JOB_DEFAULTS: Mapping[Job, BackendChoice] = {
    Job.TRANSLATION: BackendChoice("claude-cli", "haiku", Effort.LOW),
    Job.CONVERSION: BackendChoice("claude-cli", "sonnet", Effort.MEDIUM),
    Job.CONVERSION_THOROUGH: BackendChoice("claude-cli", "opus", Effort.HIGH),
    Job.NOVEL: BackendChoice("claude-cli", "sonnet", Effort.MEDIUM),
    # Free and instant, whatever paints the PCs: an NPC never takes the PCs' painter by default (DEL-248).
    Job.IMAGE_NPC_PORTRAIT: BackendChoice("portraitgen"),
}
"""A job's default when its provider is registered (plan 5 Task 4, plan 4 Task 7, novelization Task 2, thorough
conversion Task 1); the other jobs get the first provider that does them."""


@dataclass(frozen=True)
class Settings:
    choices: Mapping[Job, BackendChoice]
    language: str = "en"
    image_style: ImageStyle = field(default_factory=ImageStyle)
    """Every painting's style (`delve.domain.image_styles`), the install's."""


class SettingsWarning(str):
    """A warning about stored settings: today's English text, with a `code` and its `args` (every value a string) so
    the web can say it in the reader's language. The codes are `choices_not_mapping`, `unknown_job`, `no_provider`,
    `provider_unavailable`, `provider_wrong_job`, `model_not_offered`, `effort_not_offered`,
    `model_and_effort_not_offered`, `provider_problem`, `language_not_offered` and `image_style_not_offered`. A job's warning has `job` and
    `outcome` in its args: `default` (the job's default is used), `unset` (no default, the job is left unset) or
    `kept` (an `Unusable` choice)."""

    code: str
    args: dict[str, str]

    def __new__(cls, text: str, code: str, args: Mapping[str, str] | None = None) -> Self:
        warning = super().__new__(cls, text)
        warning.code = code
        warning.args = dict(args or {})
        return warning

    def to_json(self) -> dict[str, Any]:
        return {"code": self.code, "args": dict(self.args), "text": str(self)}


class Unusable(SettingsWarning):
    """A warning about a stored choice that is kept although it can't be used now: its live provider has a problem,
    or no longer offers its model (assetgen down for a moment, a model removed from it). Saving such a choice isn't
    refused."""


@dataclass(frozen=True)
class _Problem:
    """What is wrong with a stored choice: its text, as in "{job}: {text}; using default", and its code and args."""

    text: str
    code: str
    args: Mapping[str, str]


def resolve(
    stored: Mapping[str, Any],
    available: Sequence[ProviderCapabilities],
    defaults: Mapping[Job, BackendChoice],
) -> tuple[Settings, list[SettingsWarning]]:
    """Turn stored settings into usable ones, with a warning for everything that had to be replaced or ignored.

    `stored` has the shape `{"choices": {job: {"provider", "model", "effort"}}, "language": "en", "image_style":
    {"preset", "custom"}}`. A stored choice
    is kept only if its provider is available, does that job, and offers its model and effort (None always passes);
    otherwise the job's default is used. A choice of a live provider that has a problem, or that doesn't offer its
    model now, is kept with an `Unusable` warning, "{job}: can't be used: {reason}". Nothing in `stored` makes this
    raise.
    """
    warnings: list[SettingsWarning] = []
    providers = {caps.id: caps for caps in available}

    raw_choices = stored.get("choices", {})
    if not isinstance(raw_choices, Mapping):
        warnings.append(SettingsWarning("choices: not a mapping of jobs; using defaults", "choices_not_mapping"))
        raw_choices = {}

    choices = dict(defaults)
    for key, raw in raw_choices.items():
        try:
            job = Job(key)
        except ValueError:
            warnings.append(SettingsWarning(f"{key}: not a known job; ignored", "unknown_job", {"job": str(key)}))
            continue
        choice, problem = _check_choice(job, raw, providers)
        if choice is not None:
            choices[job] = choice
            if problem:
                warnings.append(_warning(Unusable, f"{job}: can't be used: {problem.text}", job, problem, "kept"))
        elif job in defaults:
            warnings.append(_warning(SettingsWarning, f"{job}: {problem.text}; using default", job, problem, "default"))
        else:
            choices.pop(job, None)
            text = f"{job}: {problem.text}; no default, left unset"
            warnings.append(_warning(SettingsWarning, text, job, problem, "unset"))

    language = stored.get("language", "en")
    if language not in LANGUAGES:
        text = f"language: {language!r} is not offered; using 'en'"
        warnings.append(SettingsWarning(text, "language_not_offered", {"language": str(language)}))
        language = "en"

    image_style, problem = image_styles.parse(stored.get("image_style"))
    if problem:
        text = f"image_style: {problem}; using the campaign's tone"
        warnings.append(SettingsWarning(text, "image_style_not_offered", {"problem": problem}))

    return Settings(choices=choices, language=language, image_style=image_style), warnings


def _warning(kind: type[SettingsWarning], text: str, job: Job, problem: _Problem, outcome: str) -> SettingsWarning:
    return kind(text, problem.code, {"job": str(job), **problem.args, "outcome": outcome})


def _check_choice(
    job: Job, raw: Any, providers: Mapping[str, ProviderCapabilities]
) -> tuple[BackendChoice | None, _Problem | None]:
    """The stored choice for `job` if it is usable, else None and what is wrong with it; a choice kept although it
    can't be used now comes with why."""
    if not isinstance(raw, Mapping) or not isinstance(raw.get("provider"), str):
        return None, _Problem("the stored choice names no provider", "no_provider", {})
    provider, model, effort = raw["provider"], raw.get("model"), raw.get("effort")
    caps = providers.get(provider)
    if caps is None:
        return None, _Problem(f"provider {provider!r} is not available", "provider_unavailable", {"provider": provider})
    if job not in caps.jobs:
        text = f"provider {provider!r} does not do {job}"
        return None, _Problem(text, "provider_wrong_job", {"provider": provider})

    gone = model is not None and model not in caps.models
    model_refused = gone and not (caps.live and isinstance(model, str))
    effort_refused = effort is not None and effort not in caps.efforts
    if model_refused or effort_refused:
        problems, args = [], {"provider": provider}
        if model_refused:
            problems.append(f"model {model!r} is not offered by {provider!r}")
            args["model"] = str(model)
        if effort_refused:
            problems.append(f"effort {effort!r} is not offered by {provider!r}")
            args["effort"] = str(effort)
        refused = "model_and_effort" if model_refused and effort_refused else "model" if model_refused else "effort"
        code = f"{refused}_not_offered"
        return None, _Problem(" and ".join(problems), code, args)
    choice = BackendChoice(provider, model, Effort(effort) if effort is not None else None)
    if caps.problem:
        return choice, _Problem(caps.problem, "provider_problem", {"provider": provider, "problem": caps.problem})
    if gone:
        text = f"model {model!r} is not offered by {provider!r}"
        return choice, _Problem(text, "model_not_offered", {"provider": provider, "model": str(model)})
    return choice, None
