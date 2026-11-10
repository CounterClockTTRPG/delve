"""Pictures from assetgen (portraits plan Task 5), over `httpx`, as its README's REST section says.

assetgen runs on the owner's machine or LAN; its URL and optional token are the owner's Connection (`assetgen.json`,
`delve.images.connections`). Its models aren't Delve's to know: they are read live from `GET /api/models?kind=image`
(`assetgen_capabilities`), cached for a minute, so a model added to assetgen later shows without a restart. Each
becomes a `ModelInfo` with its backend and price; a `local` model is free, and any other backend, an unknown one
included, counts as paid. When assetgen doesn't answer, the provider has no models and a `problem`.

A painting goes to assetgen's project `delve`, created without a style when it is missing: Delve sends its own
`full_prompt` (base, tone or the install's style, brief) with `"style": true`, so nothing doubles unless the owner gives that project a style.
The job is polled at `GET /api/jobs/{id}` every second, cancelled after `timeout_s` (`local_timeout_s` for a `local`
model, which runs on assetgen's own machine) counted from when it starts running, not while it waits in assetgen's
queue, and the asset's current file downloaded. It never falls back to another provider.

Its job is the request's `watch`'s as soon as assetgen answers, with its place in assetgen's queue while it waits. A
Delve that stopped while it was painting follows the same job at its next start (the request's `follow`) rather than
sending a copy; only a job assetgen no longer knows is sent again (DEL-138). A Delve that stops leaves its jobs in
assetgen's queue for that.

The URL is checked again (`check_url`) before each connection. The token goes only to assetgen, as
`Authorization: Bearer`, and never into an error: an error page is answered with its status code alone, and a job's
own error has the token taken out.
"""

from __future__ import annotations

import asyncio
import threading
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Protocol
from urllib.parse import quote

import httpx

from delve.domain.backends import ModelInfo, ProviderCapabilities, Registry
from delve.domain.settings import Job
from delve.images import connections
from delve.images.provider import ImageFile, ImageRequest, ProviderJob
from delve.images.replicate import ASPECT_RATIOS, IMAGE_TYPES, full_prompt

if TYPE_CHECKING:
    from delve.config import Config

ASSETGEN = "assetgen"
PROJECT = "delve"
JOBS = frozenset({Job.IMAGE_PORTRAIT, Job.IMAGE_NPC_PORTRAIT, Job.IMAGE_SCENE, Job.IMAGE_POSSESSION})
CACHE_S = 60.0
# A read that failed is tried again sooner, so assetgen coming up shows within seconds.
FAILED_CACHE_S = 10.0
READ_TIMEOUT_S = 3.0
REQUEST_TIMEOUT_S = 30.0
TIMEOUT_S = 300.0
# A model on assetgen's own machine is free but slow (FLUX schnell on a CPU: about six minutes a picture).
LOCAL_TIMEOUT_S = 900.0
POLL_S = 1.0
# While a job is followed, assetgen may be down a while (a restart of its own keeps its queue): it fails the painting
# only after this long without an answer.
UNREACHABLE_S = 120.0
TERMINAL = frozenset({"succeeded", "failed", "cancelled", "interrupted"})
ERROR_CHARS = 300


class AssetgenFailed(Exception):
    """A painting assetgen didn't deliver: unreachable, refused, failed, or took too long. Never holds the token."""


class AssetgenUnreachable(AssetgenFailed):
    """assetgen didn't answer at all."""


class AssetgenGone(AssetgenFailed):
    """assetgen answered 404: it doesn't know what was asked for."""


def capabilities_of(
    models: tuple[str, ...] = (),
    info: Mapping[str, ModelInfo] | None = None,
    *,
    default=None,
    problem: str | None = None,
) -> ProviderCapabilities:
    return ProviderCapabilities(
        id=ASSETGEN,
        title="assetgen",
        jobs=JOBS,
        models=models,
        default_model=default,
        model_info=dict(info or {}),
        problem=problem,
    )


def _in_a_thread(work: Callable[[], None]) -> None:
    threading.Thread(target=work, name="assetgen-models", daemon=True).start()


@dataclass
class AssetgenModels:
    """assetgen's image models, read from `GET /api/models?kind=image` and cached `CACHE_S`: called, the provider's
    capabilities. `params(model)` names the parameters the model takes, from the same read.

    Only the first read waits for assetgen (DEL-172): after it, a call answers what was last read at once, and an
    answer older than its cache is read again behind (`behind`, a thread), one read at a time. It is called on the event
    loop, through the Preferences, and a silent assetgen held it 3 s every 10 s. `refresh_behind` reads it ahead."""

    url: str
    token: str | None = field(repr=False)
    transport: httpx.MockTransport | None = field(default=None, repr=False)
    now: Callable[[], float] = time.monotonic
    resolve: connections.Resolve | None = field(default=None, repr=False)
    timeout_s: float = READ_TIMEOUT_S
    behind: Callable[[Callable[[], None]], None] = field(default=_in_a_thread, repr=False)
    _read_at: float | None = field(default=None, init=False, repr=False)
    _caps: ProviderCapabilities | None = field(default=None, init=False, repr=False)
    _params: dict[str, frozenset[str]] = field(default_factory=dict, init=False, repr=False)
    _reading: bool = field(default=False, init=False, repr=False)
    _lock: threading.Lock = field(default_factory=threading.Lock, init=False, repr=False)

    def __call__(self) -> ProviderCapabilities:
        caps = self._caps
        if caps is None:
            return self._refresh()
        if self._read_at is not None and self.now() - self._read_at >= (
            CACHE_S if caps.problem is None else FAILED_CACHE_S
        ):
            self.refresh_behind()
        return self._caps or caps

    def refresh_behind(self) -> None:
        """Read the models again behind, unless a read is under way."""
        with self._lock:
            if self._reading:
                return
            self._reading = True
        self.behind(self._refresh_and_release)

    def _refresh_and_release(self) -> None:
        try:
            self._refresh()
        finally:
            with self._lock:
                self._reading = False

    def _refresh(self) -> ProviderCapabilities:
        caps, params = self._read()
        with self._lock:
            self._caps, self._params, self._read_at = caps, params, self.now()
        return caps

    def params(self, model: str) -> frozenset[str]:
        return self._params.get(model, frozenset())

    def _read(self) -> tuple[ProviderCapabilities, dict[str, frozenset[str]]]:
        down = capabilities_of(problem=f"assetgen isn't answering at {self.url}")
        try:
            url = connections.check_url(self.url, resolve=self.resolve)
        except connections.ConnectionError as error:
            return capabilities_of(problem=str(error)), {}
        try:
            with httpx.Client(transport=self.transport) as client:
                response = client.get(
                    f"{url}/api/models", params={"kind": "image"}, headers=_auth(self.token), timeout=self.timeout_s
                )
            answer = response.json() if response.status_code == 200 else None
        except (httpx.HTTPError, ValueError):
            return down, {}
        listed = answer.get("models") if isinstance(answer, dict) else answer
        if not isinstance(listed, list):
            return down, {}
        models, info, params = [], {}, {}
        for model in listed:
            if not isinstance(model, dict) or model.get("kind") != "image" or not isinstance(model.get("id"), str):
                continue
            backend = model.get("backend") if isinstance(model.get("backend"), str) else "unknown"
            price = model.get("price") if isinstance(model.get("price"), str) and model["price"] else None
            models.append(model["id"])
            info[model["id"]] = ModelInfo(model["id"], backend, price, paid=backend != "local")
            params[model["id"]] = frozenset(
                p["name"] for p in model.get("params") or () if isinstance(p, dict) and isinstance(p.get("name"), str)
            )
        default = _default_model(answer, models)
        return capabilities_of(tuple(models), info, default=default), params


def assetgen_capabilities(
    url: str,
    token: str | None,
    *,
    transport: httpx.MockTransport | None = None,
    now: Callable[[], float] = time.monotonic,
    resolve: connections.Resolve | None = None,
    behind: Callable[[Callable[[], None]], None] = _in_a_thread,
) -> AssetgenModels:
    """The live capabilities of assetgen at `url`: a callable answering them, read anew behind after `CACHE_S`. On
    failure `models=()` and `problem="assetgen isn't answering at <url>"`. `transport` and `behind` are for tests."""
    return AssetgenModels(url, token, transport=transport, now=now, resolve=resolve, behind=behind)


class AssetgenImages:
    """Paints portraits, possessions' pictures and scenes with the chosen assetgen model (its default without one)."""

    def __init__(
        self,
        url: str,
        token: str | None,
        *,
        client: httpx.AsyncClient,
        capabilities: Callable[[], ProviderCapabilities] | None = None,
        poll_s: float = POLL_S,
        timeout_s: float = TIMEOUT_S,
        local_timeout_s: float = LOCAL_TIMEOUT_S,
        resolve: connections.Resolve | None = None,
    ) -> None:
        self.url = url
        self._token = token
        self._client = client
        self._read = capabilities or assetgen_capabilities(url, token, resolve=resolve)
        self.poll_s = poll_s
        self.timeout_s = timeout_s
        self.local_timeout_s = local_timeout_s
        self._resolve = resolve
        self._project: str | None = None

    def __repr__(self) -> str:
        return f"AssetgenImages({self.url!r})"

    @property
    def capabilities(self) -> ProviderCapabilities:
        return self._read()

    async def generate(self, req: ImageRequest) -> ImageFile:
        if req.job not in JOBS:
            raise ValueError(f"'{req.job}' is not an image job")
        try:
            url = connections.check_url(self.url, resolve=self._resolve)
        except connections.ConnectionError as error:
            raise AssetgenFailed(str(error)) from None
        caps = self._read()
        model = req.choice.model or caps.default_model
        if model is None or model not in caps.models:
            if caps.problem is not None:
                raise AssetgenFailed(caps.problem)
            raise AssetgenFailed(f"assetgen no longer offers '{model}'.")
        takes = getattr(self._read, "params", lambda model: frozenset())(model)
        wanted = {"aspect_ratio": req.aspect or ASPECT_RATIOS[req.job], "output_format": "png"}
        body = {
            "kind": "image",
            "model": model,
            "prompt": full_prompt(req.job, req.tone, req.prompt, req.style),
            "params": {name: value for name, value in wanted.items() if name in takes},
            "style": True,
        }
        info = caps.model_info.get(model)
        limit = self.local_timeout_s if info is not None and info.backend == "local" else self.timeout_s
        job = await self._followed(url, req.follow) if req.follow else None
        if job is None:
            project = await self._project_id(url)
            answer = await self._api("POST", f"{url}/api/projects/{quote(project, safe='')}/generate", json=body)
            job = answer.get("job") if isinstance(answer.get("job"), dict) else answer
        job_id = job.get("id")
        if not isinstance(job_id, str) or not job_id:
            raise AssetgenFailed("assetgen answered no job to follow.")
        job_url = f"{url}/api/jobs/{quote(job_id, safe='')}"
        told: ProviderJob | None = None
        deadline: float | None = None
        unreachable_since: float | None = None
        while True:
            status = job.get("status")
            seen = ProviderJob(job_id, _position(job) if status == "queued" else None)
            if req.watch is not None and seen != told:
                req.watch(seen)
                told = seen
            if status in TERMINAL:
                break
            if status != "queued" and deadline is None:
                deadline = time.monotonic() + limit  # the time runs from its start, not while it waits its turn
            if deadline is not None and time.monotonic() >= deadline:
                await self._cancel(job_url)
                raise AssetgenFailed(f"assetgen took too long (over {limit:g} s); the job was cancelled.")
            await asyncio.sleep(self.poll_s)
            try:
                job = await self._api("GET", job_url)
                unreachable_since = None
            except AssetgenUnreachable:
                unreachable_since = unreachable_since or time.monotonic()
                if time.monotonic() - unreachable_since >= UNREACHABLE_S:
                    raise
        if status != "succeeded":
            reason = self._scrub(job.get("error")) or "no reason given"
            raise AssetgenFailed(f"assetgen failed: {reason}" if status == "failed" else f"assetgen {status}: {reason}")
        asset_id = (job.get("result") or {}).get("asset_id") if isinstance(job.get("result"), dict) else None
        if not isinstance(asset_id, str) or not asset_id:
            raise AssetgenFailed("assetgen's job has no picture.")
        return await self._download(url, asset_id)

    async def _followed(self, url: str, job_id: str) -> dict[str, Any] | None:
        """The job an earlier start sent, as assetgen has it now; None when assetgen no longer knows it (it keeps
        finished jobs a week), so the picture is asked for again."""
        try:
            return await self._api("GET", f"{url}/api/jobs/{quote(job_id, safe='')}")
        except AssetgenGone:
            return None

    async def aclose(self) -> None:
        await self._client.aclose()

    async def _project_id(self, url: str) -> str:
        """The project `delve`'s id: found by name once, created without a style when it is missing."""
        if self._project is None:
            listed = (await self._api("GET", f"{url}/api/projects")).get("projects")
            found = next(
                (p["id"] for p in listed or () if isinstance(p, dict) and p.get("name") == PROJECT and p.get("id")),
                None,
            )
            if found is None:
                found = (await self._api("POST", f"{url}/api/projects", json={"name": PROJECT})).get("id")
            if not isinstance(found, str) or not found:
                raise AssetgenFailed("assetgen answered no project.")
            self._project = found
        return self._project

    async def _download(self, url: str, asset_id: str) -> ImageFile:
        asset_url = f"{url}/api/assets/{quote(asset_id, safe='')}"
        current = (await self._api("GET", asset_url)).get("current")
        if not isinstance(current, str) or not current:
            raise AssetgenFailed("assetgen's picture has no file.")
        response = await self._request("GET", f"{asset_url}/file/{quote(current, safe='')}")
        mime = response.headers.get("Content-Type", "image/png").split(";")[0].strip().lower() or "image/png"
        if mime not in IMAGE_TYPES:
            raise AssetgenFailed(f"assetgen's output isn't a picture Delve shows: {mime}")
        return ImageFile(response.content, mime)

    async def _cancel(self, job_url: str) -> None:
        try:
            await self._client.delete(job_url, headers=_auth(self._token), timeout=READ_TIMEOUT_S)
        except httpx.HTTPError:
            pass  # the job's own end; assetgen keeps it at most a week

    async def _api(self, method: str, url: str, *, json: Any = None) -> dict[str, Any]:
        response = await self._request(method, url, json=json)
        try:
            answer = response.json()
        except ValueError:
            raise AssetgenFailed("assetgen answered something other than JSON.") from None
        if not isinstance(answer, dict):
            raise AssetgenFailed("assetgen answered something Delve doesn't read.")
        return answer

    async def _request(self, method: str, url: str, *, json: Any = None) -> httpx.Response:
        try:
            response = await self._client.request(
                method, url, json=json, headers=_auth(self._token), timeout=REQUEST_TIMEOUT_S
            )
        except httpx.HTTPError:
            raise AssetgenUnreachable(f"assetgen isn't answering at {self.url}") from None
        if response.status_code >= 400:  # its error page may hold the request, the token with it
            failed = AssetgenGone if response.status_code == 404 else AssetgenFailed
            raise failed(f"assetgen failed ({response.status_code}).")
        return response

    def _scrub(self, text: Any) -> str:
        """assetgen's own words, at most `ERROR_CHARS`, without the token."""
        if not isinstance(text, str):
            return ""
        if self._token:
            text = text.replace(self._token, "…")
        return text.strip()[:ERROR_CHARS]


class Registries(Protocol):
    """What `register_assetgen` needs of the app's registries (`delve.web.app.Registries`), which this package may not
    import."""

    images: Registry[Any]


def register_assetgen(registries: Registries, config: Config, *, transport: httpx.MockTransport | None = None):
    """Register assetgen, live, from `<data dir>/assetgen.json`, replacing it in its place, or unregister it without
    one. At start it comes last, so it is never a job's default: it is chosen in Preferences. The provider it dropped,
    for the caller to close; otherwise None. `transport` is for tests."""
    stored = connections.load_assetgen(config.data_dir)
    if stored is None:
        return registries.images.unregister(ASSETGEN)
    read = assetgen_capabilities(stored.url, stored.token, transport=transport)
    read.refresh_behind()  # so the first look at the Preferences, on the event loop, doesn't wait (DEL-172)

    def assetgen() -> AssetgenImages:
        return AssetgenImages(
            stored.url, stored.token, client=httpx.AsyncClient(transport=transport), capabilities=read
        )

    return registries.images.register_live(ASSETGEN, read, assetgen)


def _auth(token: str | None) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"} if token else {}


def _position(job: dict[str, Any]) -> int | None:
    position = job.get("position")
    return position if isinstance(position, int) and not isinstance(position, bool) and position > 0 else None


def _default_model(answer: Any, models: list[str]) -> str | None:
    """assetgen's own default for images when it offers it, else its first image model."""
    kinds = answer.get("kinds") if isinstance(answer, dict) else None
    for kind in kinds if isinstance(kinds, list) else ():
        if isinstance(kind, dict) and kind.get("id") == "image" and kind.get("default_model") in models:
            return kind["default_model"]
    return models[0] if models else None
