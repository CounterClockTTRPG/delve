"""Paid images from Replicate (spec §5.2, plan 6 Task 10), over `httpx`, as ttrpg2 painted them with Flux.

A prediction is created with `Prefer: wait`, which answers once it is done or after a while; one not done yet is
polled at its `urls.get` until it succeeds, fails, or `timeout_s` pass, and its output is downloaded. The token is sent
to Replicate's API only, never to the host the output is downloaded from, and never appears in an error.

The token comes from `REPLICATE_API_TOKEN` or `<data dir>/replicate-token` (`load_token`). It is never stored in the
database and never sent to a browser; without one, Replicate isn't registered, so Preferences don't offer it.
"""

from __future__ import annotations

import asyncio
import os
import re
import time
from collections.abc import Mapping
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

import httpx

from delve.domain.backends import ModelInfo, ProviderCapabilities
from delve.domain.image_styles import BROM, DITERLIZZI, ELMORE
from delve.domain.settings import Job
from delve.images.provider import ImageFile, ImageRequest

REPLICATE = "replicate"
API_URL = "https://api.replicate.com/v1"
TOKEN_ENV = "REPLICATE_API_TOKEN"
TOKEN_FILE = "replicate-token"
TIMEOUT_S = 120.0
POLL_S = 1.0
THROTTLE_TRIES = 4
"""How many times a request is sent while Replicate throttles it (HTTP 429, DEL-233): below $5 of credit it allows 6
predictions a minute, one at a time, so two pictures at once meet it."""
THROTTLE_WAIT_S = 10.0
"""How long to wait on a 429 that says nothing of when to try again."""
THROTTLE_WAIT_MAX_S = 30.0
"""The longest wait on one 429, whatever it says."""
_RESETS_IN = re.compile(r"resets in ~?\s*(\d+(?:\.\d+)?)\s*s", re.IGNORECASE)


@dataclass(frozen=True)
class ModelInputs:
    """What a model's input schema takes (Replicate's `GET /v1/models/{model}`, read 2026-10-27): the ratios its
    `aspect_ratio` lists, whether it takes `custom` with a width and height, the `output_format`s it takes (none: it
    takes no such input), and whether it takes a `safety_tolerance`."""

    label: str
    ratios: frozenset[str]
    custom: bool = False
    formats: frozenset[str] = frozenset()
    safety: bool = False
    price: str | None = None


_FLUX2 = frozenset({"1:1", "16:9", "3:2", "2:3", "4:5", "5:4", "9:16", "3:4", "4:3"})
_WIDE = frozenset({"1:1", "16:9", "21:9", "3:2", "2:3", "4:5", "5:4", "3:4", "4:3", "9:16", "9:21"})
_JPG_PNG = frozenset({"jpg", "png"})
_ALL = frozenset({"webp", "jpg", "png"})
# Every Replicate model costs money. A price is Replicate's (replicate.com/pricing) or assetgen's registry where one
# is known; the others' aren't known here. Every model but flux-2-pro paints a banner's 21:9 as it is.
MODEL_INPUTS: dict[str, ModelInputs] = {
    "black-forest-labs/flux-2-pro": ModelInputs("flux-2-pro", _FLUX2, custom=True, formats=_ALL, safety=True),
    "black-forest-labs/flux-schnell": ModelInputs("flux-schnell", _WIDE, formats=_ALL, price="~$0.003 / image"),
    "black-forest-labs/flux-1.1-pro-ultra": ModelInputs("FLUX 1.1 Pro Ultra", _WIDE, formats=_JPG_PNG, safety=True),
    "black-forest-labs/flux-dev": ModelInputs("FLUX dev", _WIDE, formats=_ALL, price="$0.025 / image"),
    "google/nano-banana-pro": ModelInputs("Nano Banana Pro", _WIDE - {"9:21"}, formats=_JPG_PNG),
    "google/nano-banana": ModelInputs("Nano Banana", _WIDE - {"9:21"}, formats=_JPG_PNG),
    "bytedance/seedream-4": ModelInputs(
        "Seedream 4", frozenset({"1:1", "4:3", "3:4", "16:9", "9:16", "3:2", "2:3", "21:9"})
    ),
    "stability-ai/stable-diffusion-3.5-large": ModelInputs(
        "Stable Diffusion 3.5 Large",
        frozenset({"16:9", "1:1", "21:9", "2:3", "3:2", "4:5", "5:4", "9:16", "9:21"}),
        formats=_ALL,
    ),
    "luma/photon": ModelInputs("Photon", frozenset({"1:1", "3:4", "4:3", "9:16", "16:9", "9:21", "21:9"})),
}
MODELS = tuple(MODEL_INPUTS)
MODEL_INFO = {model: ModelInfo(i.label, REPLICATE, i.price, paid=True) for model, i in MODEL_INPUTS.items()}

JOBS = frozenset({Job.IMAGE_PORTRAIT, Job.IMAGE_NPC_PORTRAIT, Job.IMAGE_SCENE, Job.IMAGE_POSSESSION})
REPLICATE_CAPABILITIES = ProviderCapabilities(
    id=REPLICATE, title="Replicate", jobs=JOBS, models=MODELS, default_model=MODELS[0], model_info=MODEL_INFO
)

# ttrpg2's style (tools/images.py). Its base forced "character portrait" into every prompt; a scene and a possession's
# picture go without it. The install's image style (DEL-202), when it isn't the tone's, keeps only the base's rules
# (`STYLE_RULES`): its own look replaces the classic cover art and the tone's painter. It names no edition (DEL-307).
STYLE_LOOK = "Tabletop RPG game art illustration, classic 1980s fantasy roleplaying cover-art aesthetic."
STYLE_RULES = (
    "Medieval fantasy, non-violent character portrait, safe for work. "
    "No text, no labels, no UI elements. "
    "No firearms, no modern technology."
)
STYLE_BASE = f"{STYLE_LOOK} {STYLE_RULES}"
_NOT_A_PORTRAIT = "non-violent character portrait", "non-violent"

TONE_STYLES = {"high fantasy": ELMORE, "gritty realism": BROM, "comedy": DITERLIZZI}
# Delve's tones (`delve.dm.prompt.TONES`) as ttrpg2's; ttrpg2 played "high fantasy" by default. Any other tone is its
# own clause, as ttrpg2 did with a tone it had no style for.
DELVE_TONES = {
    "classic": "high fantasy",
    "heroic": "high fantasy",
    "grimdark": "gritty realism",
    "comedic": "comedy",
    "young": "comedy",
}

PORTRAIT_JOBS = frozenset({Job.IMAGE_PORTRAIT, Job.IMAGE_NPC_PORTRAIT})
ASPECT_RATIOS = {
    Job.IMAGE_PORTRAIT: "1:1",
    Job.IMAGE_NPC_PORTRAIT: "1:1",
    Job.IMAGE_POSSESSION: "1:1",
    Job.IMAGE_SCENE: "16:9",
}
CUSTOM_PIXELS = 1_000_000
"""A custom size's area: the model's default 1 MP, not its 4 MP maximum."""
DONE = frozenset({"succeeded", "failed", "canceled"})
# What a painting may be: never SVG or anything a browser would run.
IMAGE_TYPES = frozenset({"image/png", "image/jpeg", "image/webp"})


class ReplicateFailed(Exception):
    """A painting Replicate didn't deliver: refused, failed, or took too long."""


def _value(ratio: str) -> float:
    w, h = (int(n) for n in ratio.split(":"))
    return w / h


def size_input(model: str, ratio: str) -> dict[str, Any]:
    """The `aspect_ratio` input for `ratio`. A model that doesn't list it gets a custom width and height of that
    ratio, multiples of 16, about `CUSTOM_PIXELS` in area, when it takes `custom` (flux-2-pro refuses a banner's 21:9
    with HTTP 422 otherwise), else the nearest ratio it lists; a model Delve doesn't know gets the ratio as it is."""
    inputs = MODEL_INPUTS.get(model)
    if inputs is None or ratio in inputs.ratios:
        return {"aspect_ratio": ratio}
    if inputs.custom:
        w, h = (int(n) for n in ratio.split(":"))
        width = round((CUSTOM_PIXELS * w / h) ** 0.5 / 16) * 16
        return {"aspect_ratio": "custom", "width": width, "height": round(width * h / w / 16) * 16}
    listed = [r for r in inputs.ratios if re.fullmatch(r"\d+:\d+", r)]
    return {"aspect_ratio": min(listed, key=lambda r: abs(_value(r) - _value(ratio)))}


def model_input(model: str, prompt: str, ratio: str) -> dict[str, Any]:
    """The prediction's `input` for `model`: the prompt and the size, a PNG when the model takes an `output_format`
    (else the best it takes), and the most lenient `safety_tolerance` Delve sends when it takes one. A model Delve
    doesn't know gets all of them, as before."""
    inputs = MODEL_INPUTS.get(model)
    body: dict[str, Any] = {"prompt": prompt, **size_input(model, ratio)}
    if inputs is None or inputs.formats:
        formats = inputs.formats if inputs is not None else {"png"}
        body["output_format"] = next(f for f in ("png", "webp", "jpg") if f in formats)
    if inputs is None or inputs.safety:
        body["safety_tolerance"] = 5
    return body


def throttle_wait(response: httpx.Response) -> float:
    """How long a 429 says to wait, in seconds: its `Retry-After`, else the "resets in ~9s" of its detail, else
    `THROTTLE_WAIT_S`. A second more than it says, so the limit has surely reset."""
    after = response.headers.get("retry-after", "").strip()
    try:
        return max(0.0, float(after)) + 1
    except ValueError:
        pass
    found = _RESETS_IN.search(_refusal(response))
    return float(found.group(1)) + 1 if found else THROTTLE_WAIT_S


def _refusal(response: httpx.Response) -> str:
    """Replicate's reason for refusing a request (its `detail`, else its `title`), shortened; "" without one."""
    try:
        answer = response.json()
    except ValueError:
        return ""
    why = (answer.get("detail") or answer.get("title")) if isinstance(answer, dict) else None
    return " ".join(why.split())[:300] if isinstance(why, str) else ""


def load_token(data_dir: Path, environ: Mapping[str, str] | None = None) -> str | None:
    """The Replicate token: `REPLICATE_API_TOKEN`, else `<data dir>/replicate-token`; None without one."""
    environ = os.environ if environ is None else environ
    token = environ.get(TOKEN_ENV, "").strip()
    if token:
        return token
    path = data_dir / TOKEN_FILE
    try:
        token = path.read_text(encoding="utf-8").strip()
    except OSError:
        return None
    return token or None


def tone_clause(tone: str) -> str:
    named = DELVE_TONES.get(tone, tone)
    return TONE_STYLES.get(named, named).strip()


def full_prompt(job: Job, tone: str, brief: str, style: str = "") -> str:
    """ttrpg2's style base, the tone's clause and the brief; with the install's `style`, the base's rules, that style
    and the brief."""
    base = STYLE_RULES if style.strip() else STYLE_BASE
    if job not in PORTRAIT_JOBS:
        base = base.replace(*_NOT_A_PORTRAIT)
    clause = style.strip() or tone_clause(tone)
    if clause and not clause.endswith("."):
        clause += "."
    return " ".join(part for part in (base, clause, brief.strip()) if part)


class ReplicateImages:
    """Paints portraits, possessions' pictures and scenes with the chosen model of `models` (the first by default)."""

    def __init__(
        self,
        token: str,
        *,
        client: httpx.AsyncClient,
        models: tuple[str, ...] = MODELS,
        timeout_s: float = TIMEOUT_S,
        poll_s: float = POLL_S,
        throttle_wait_max_s: float = THROTTLE_WAIT_MAX_S,
    ) -> None:
        self._token = token
        self._client = client
        self.models = models
        self.throttle_wait_max_s = throttle_wait_max_s
        self.capabilities = replace(REPLICATE_CAPABILITIES, models=models, default_model=models[0])
        self.timeout_s = timeout_s
        self.poll_s = poll_s

    async def generate(self, req: ImageRequest) -> ImageFile:
        if req.job not in JOBS:
            raise ValueError(f"'{req.job}' is not an image job")
        model = req.choice.model if req.choice.model in self.models else self.models[0]
        prompt = full_prompt(req.job, req.tone, req.prompt, req.style)
        body = {"input": model_input(model, prompt, req.aspect or ASPECT_RATIOS[req.job])}
        deadline = time.monotonic() + self.timeout_s
        prediction = await self._api("POST", f"{API_URL}/models/{model}/predictions", json=body, wait=True)
        while prediction.get("status") not in DONE:
            if time.monotonic() >= deadline:
                raise ReplicateFailed(f"Replicate took too long (over {self.timeout_s:g} s).")
            await asyncio.sleep(self.poll_s)
            poll = (prediction.get("urls") or {}).get("get")
            if not isinstance(poll, str) or not poll.startswith(f"{API_URL}/"):
                raise ReplicateFailed("Replicate answered no prediction to follow.")
            prediction = await self._api("GET", poll)
        if prediction["status"] != "succeeded":
            raise ReplicateFailed(f"Replicate {prediction['status']}: {prediction.get('error') or 'no reason given'}")
        return await self._download(prediction.get("output"))

    async def aclose(self) -> None:
        await self._client.aclose()

    async def _api(self, method: str, url: str, *, json: Any = None, wait: bool = False) -> dict[str, Any]:
        """One call of Replicate's API. A throttled one (429) waits as long as Replicate says, at most
        `throttle_wait_max_s`, and is sent again, `THROTTLE_TRIES` times in all; then it is refused as any other."""
        headers = {"Authorization": f"Bearer {self._token}"}
        if wait:
            headers["Prefer"] = "wait"
        for tries_left in range(THROTTLE_TRIES - 1, -1, -1):
            try:
                response = await self._client.request(method, url, json=json, headers=headers, timeout=self.timeout_s)
            except httpx.HTTPError as error:
                raise ReplicateFailed(f"Replicate can't be reached: {type(error).__name__}") from None
            if response.status_code != 429 or tries_left == 0:
                break
            await asyncio.sleep(min(throttle_wait(response), self.throttle_wait_max_s))
        if response.status_code >= 400:
            why = _refusal(response).replace(self._token, "…")
            raise ReplicateFailed(
                f"Replicate refused the request: HTTP {response.status_code}" + (f": {why}" if why else "")
            )
        try:
            answer = response.json()
        except ValueError:
            raise ReplicateFailed("Replicate answered something other than JSON.") from None
        if not isinstance(answer, dict):
            raise ReplicateFailed("Replicate answered something other than a prediction.")
        return answer

    async def _download(self, output: Any) -> ImageFile:
        url = output[0] if isinstance(output, list) and output else output
        if not isinstance(url, str) or not url.startswith("https://"):
            raise ReplicateFailed("Replicate's prediction has no image.")
        try:
            response = await self._client.get(url, timeout=self.timeout_s)
        except httpx.HTTPError as error:
            raise ReplicateFailed(f"The image can't be downloaded: {type(error).__name__}") from None
        if response.status_code >= 400:
            raise ReplicateFailed(f"The image can't be downloaded: HTTP {response.status_code}")
        mime = response.headers.get("Content-Type", "image/png").split(";")[0].strip().lower() or "image/png"
        if mime not in IMAGE_TYPES:
            raise ReplicateFailed(f"Replicate's output isn't a picture Delve shows: {mime}")
        return ImageFile(response.content, mime)
