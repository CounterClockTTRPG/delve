"""The assetgen backend (portraits plan Task 5), against `httpx.MockTransport` playing assetgen: never a real call.
Its image models are read live from `GET /api/models?kind=image`, cached 60 s; a painting goes to the project
`delve`, is polled at `GET /api/jobs/{id}`, and its PNG downloaded. The token goes only as `Authorization: Bearer`,
and never into an error (Review Focus 1)."""

import asyncio
import json
import logging

import httpx
import pytest

from delve.__main__ import build_registries
from delve.config import Config
from delve.domain.backends import ModelInfo, Registry
from delve.domain.settings import BackendChoice, Job
from delve.images import assetgen
from delve.images.assetgen import (
    ASSETGEN,
    CACHE_S,
    LOCAL_TIMEOUT_S,
    TIMEOUT_S,
    AssetgenFailed,
    AssetgenImages,
    assetgen_capabilities,
    register_assetgen,
)
from delve.images.connections import save_assetgen
from delve.images.fake import FAKE_IMAGES_CAPABILITIES
from delve.images.provider import ImageFile, ImageRequest, ProviderJob
from delve.images.replicate import full_prompt
from delve.play.images import is_paid

TOKEN = "tok-SECRET-XYZZY"
URL = "http://127.0.0.1:47898"
PNG = b"\x89PNG painted by assetgen"

MODELS = {
    "kinds": [{"id": "image", "default_model": "flux-schnell"}],
    "models": [
        {
            "id": "flux-schnell",
            "kind": "image",
            "backend": "replicate",
            "label": "FLUX schnell",
            "price": "~$0.003 / image",
            "params": [{"name": "aspect_ratio"}, {"name": "output_format"}, {"name": "seed"}],
        },
        {
            "id": "pixel-local",
            "kind": "image",
            "backend": "local",
            "label": "Pixel (local)",
            "price": "free (local CPU)",
            "params": [{"name": "steps"}],
        },
        {"id": "odd-one", "kind": "image", "backend": "quantum", "label": "Odd", "params": []},
        {"id": "sao-small", "kind": "audio", "backend": "local", "label": "Stable Audio Open Small", "price": "free"},
    ],
}


@pytest.fixture(autouse=True)
def every_log(caplog):
    caplog.set_level(logging.DEBUG)
    return caplog


class Assetgen:
    """A fake assetgen: its models, its projects, one generate's job polled through `polls`, the asset and its PNG.
    Its error pages echo the request's headers, as a traceback holding the request would."""

    def __init__(self, *, projects=(), polls=({"status": "succeeded", "result": {"asset_id": "a-1"}},), models=MODELS):
        self.projects = [dict(project) for project in projects]
        self.polls = list(polls)
        self.models = models
        self.requests: list[httpx.Request] = []
        self.generated: list[dict] = []
        self.fail: dict[str, int] = {}

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        path, method = request.url.path, request.method
        echoed = f"Traceback (most recent call last): request {request.method} {dict(request.headers)}"
        if path in self.fail:
            return httpx.Response(self.fail[path], text=echoed)
        if (method, path) == ("GET", "/api/models"):
            kind = request.url.params.get("kind")
            models = [model for model in self.models["models"] if kind is None or model["kind"] == kind]
            return httpx.Response(200, json={**self.models, "models": models})
        if (method, path) == ("GET", "/api/projects"):
            return httpx.Response(200, json={"current": "default", "projects": self.projects})
        if (method, path) == ("POST", "/api/projects"):
            project = {"id": "delve", **json.loads(request.content)}
            self.projects.append(project)
            return httpx.Response(201, json=project)
        if method == "POST" and path.endswith("/generate"):
            self.generated.append(json.loads(request.content))
            return httpx.Response(202, json={"job": {"id": "j-1", "status": "queued"}})
        if (method, path) == ("GET", "/api/jobs/j-1"):
            return httpx.Response(
                200, json={"id": "j-1", **(self.polls.pop(0) if len(self.polls) > 1 else self.polls[0])}
            )
        if (method, path) == ("DELETE", "/api/jobs/j-1"):
            return httpx.Response(200, json={"id": "j-1", "status": "cancelled"})
        if (method, path) == ("GET", "/api/assets/a-1"):
            return httpx.Response(200, json={"id": "a-1", "kind": "image", "current": "v001.png"})
        if (method, path) == ("GET", "/api/assets/a-1/file/v001.png"):
            return httpx.Response(200, content=PNG, headers={"Content-Type": "image/png"})
        return httpx.Response(404, text=echoed)

    def paths(self) -> list[tuple[str, str]]:
        return [(request.method, request.url.path) for request in self.requests]


class Clock:
    def __init__(self) -> None:
        self.t = 1000.0

    def __call__(self) -> float:
        return self.t


def at_once(work):
    """A read behind run at once, so a test sees its answer in the same call."""
    work()


def reader(fake, *, token=TOKEN, now=None, behind=at_once):
    return assetgen_capabilities(URL, token, transport=httpx.MockTransport(fake), now=now or Clock(), behind=behind)


def generate(
    fake,
    job=Job.IMAGE_PORTRAIT,
    *,
    model="flux-schnell",
    token=TOKEN,
    timeout_s=5.0,
    local_timeout_s=5.0,
    aspect="",
    follow="",
    watch=None,
):
    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(fake)) as client:
            painter = AssetgenImages(
                URL,
                token,
                client=client,
                poll_s=0,
                timeout_s=timeout_s,
                local_timeout_s=local_timeout_s,
                capabilities=reader(fake, token=token),
            )
            request = ImageRequest(
                job,
                "a stout dwarf",
                BackendChoice(ASSETGEN, model),
                tone="grimdark",
                aspect=aspect,
                follow=follow,
                watch=watch,
            )
            return await painter.generate(request)

    return asyncio.run(run())


# The models, read live


def test_the_image_models_become_model_infos_and_audio_is_left_out():
    caps = reader(Assetgen())()
    assert caps.id == ASSETGEN
    assert caps.jobs == frozenset({Job.IMAGE_PORTRAIT, Job.IMAGE_NPC_PORTRAIT, Job.IMAGE_SCENE, Job.IMAGE_POSSESSION})
    assert caps.models == ("flux-schnell", "pixel-local", "odd-one")
    assert "sao-small" not in caps.model_info
    assert caps.default_model == "flux-schnell"
    assert caps.problem is None
    assert caps.model_info == {
        "flux-schnell": ModelInfo("flux-schnell", "replicate", "~$0.003 / image", paid=True),
        "pixel-local": ModelInfo("pixel-local", "local", "free (local CPU)", paid=False),
        "odd-one": ModelInfo("odd-one", "quantum", None, paid=True),
    }


def test_the_models_are_asked_for_by_kind_with_the_token():
    fake = Assetgen()
    reader(fake)()
    (request,) = fake.requests
    assert str(request.url) == f"{URL}/api/models?kind=image"
    assert request.headers["Authorization"] == f"Bearer {TOKEN}"


def test_no_token_sends_no_authorization():
    fake = Assetgen()
    reader(fake, token=None)()
    assert "Authorization" not in fake.requests[0].headers


def test_a_second_read_within_60_s_makes_no_request():
    fake, clock = Assetgen(), Clock()
    read = reader(fake, now=clock)
    read()
    clock.t += CACHE_S - 1
    read()
    assert len(fake.requests) == 1
    clock.t += 2
    read()
    assert len(fake.requests) == 2


def test_a_model_added_to_assetgen_shows_after_the_cache():
    fake, clock = Assetgen(), Clock()
    read = reader(fake, now=clock)
    assert "new-local" not in read().models
    fake.models = {**MODELS, "models": [*MODELS["models"], {"id": "new-local", "kind": "image", "backend": "local"}]}
    clock.t += CACHE_S + 1
    assert read().model_info["new-local"].paid is False


def test_a_stale_answer_comes_at_once_and_is_read_again_behind():
    """Only the first read waits for assetgen (DEL-172): a silent assetgen held the event loop 3 s every 10 s."""
    fake, clock, waiting = Assetgen(), Clock(), []
    read = reader(fake, now=clock, behind=waiting.append)
    first = read()
    assert len(fake.requests) == 1 and not waiting
    fake.models = {**MODELS, "models": [*MODELS["models"], {"id": "new-local", "kind": "image", "backend": "local"}]}
    clock.t += CACHE_S + 1
    assert read() is first and read() is first, "the last answer, without asking assetgen"
    assert len(fake.requests) == 1 and len(waiting) == 1, "one read behind at a time"
    waiting.pop()()
    assert "new-local" in read().models and len(fake.requests) == 2 and not waiting


def test_registering_reads_the_models_behind(tmp_path):
    """So the first look at the Preferences, on the event loop, finds them read."""
    import time

    fake = Assetgen()
    save_assetgen(tmp_path, URL, TOKEN)
    register_assetgen_into(Registry(), tmp_path, fake)
    for _ in range(100):
        if fake.requests:
            break
        time.sleep(0.01)
    assert len(fake.requests) == 1


def test_without_a_default_the_first_model_is_the_default():
    fake = Assetgen(models={"models": MODELS["models"]})
    assert reader(fake)().default_model == "flux-schnell"


def test_a_plain_list_of_models_is_read_too():
    models = [model for model in MODELS["models"] if model["kind"] == "image"]

    def as_list(request):
        return httpx.Response(200, json=models)

    caps = assetgen_capabilities(URL, None, transport=httpx.MockTransport(as_list), now=Clock())()
    assert caps.models == ("flux-schnell", "pixel-local", "odd-one")


def test_a_connection_error_gives_the_problem(every_log):
    def down(request):
        raise httpx.ConnectError("refused", request=request)

    caps = assetgen_capabilities(URL, TOKEN, transport=httpx.MockTransport(down), now=Clock())()
    assert caps.models == ()
    assert caps.model_info == {}
    assert caps.problem == f"assetgen isn't answering at {URL}"
    assert TOKEN not in every_log.text


@pytest.mark.parametrize("answer", [httpx.Response(500, text=f"Bearer {TOKEN}"), httpx.Response(200, text="<html>")])
def test_a_failing_or_strange_answer_gives_the_problem_without_the_token(answer):
    caps = assetgen_capabilities(URL, TOKEN, transport=httpx.MockTransport(lambda request: answer), now=Clock())()
    assert caps.models == ()
    assert caps.problem == f"assetgen isn't answering at {URL}"
    assert TOKEN not in repr(caps)


def test_assetgen_down_at_start_and_up_later():
    state = {"up": False}
    fake, clock = Assetgen(), Clock()

    def handler(request):
        if not state["up"]:
            raise httpx.ConnectError("refused", request=request)
        return fake(request)

    read = assetgen_capabilities(URL, None, transport=httpx.MockTransport(handler), now=clock, behind=at_once)
    assert read().problem is not None
    state["up"] = True
    clock.t += CACHE_S + 1
    assert read().problem is None
    assert "flux-schnell" in read().models


def test_the_url_is_checked_again_before_reading_the_models():
    fake = Assetgen()
    caps = assetgen_capabilities(
        "http://assetgen.lan:47898",
        None,
        transport=httpx.MockTransport(fake),
        now=Clock(),
        resolve=lambda h, p: ["93.184.216.34"],
    )()
    assert fake.requests == []
    assert caps.models == ()
    assert caps.problem is not None and "assetgen" in caps.problem


# Painting


def test_a_portrait_returns_the_png():
    fake = Assetgen(projects=[{"id": "delve", "name": "delve"}])
    assert generate(fake) == ImageFile(PNG, "image/png")
    assert fake.paths()[-4:] == [
        ("POST", "/api/projects/delve/generate"),
        ("GET", "/api/jobs/j-1"),
        ("GET", "/api/assets/a-1"),
        ("GET", "/api/assets/a-1/file/v001.png"),
    ]
    assert all(request.headers["Authorization"] == f"Bearer {TOKEN}" for request in fake.requests)


def test_the_generate_body():
    fake = Assetgen(projects=[{"id": "delve", "name": "delve"}])
    generate(fake, Job.IMAGE_SCENE)
    assert fake.generated == [
        {
            "kind": "image",
            "model": "flux-schnell",
            "prompt": full_prompt(Job.IMAGE_SCENE, "grimdark", "a stout dwarf"),
            "params": {"aspect_ratio": "16:9", "output_format": "png"},
            "style": True,
        }
    ]


def test_a_request_with_an_aspect_sends_it_and_one_without_sends_the_jobs():
    fake = Assetgen(projects=[{"id": "delve", "name": "delve"}])
    generate(fake, Job.IMAGE_SCENE, aspect="21:9")
    generate(fake, Job.IMAGE_SCENE)
    assert [g["params"]["aspect_ratio"] for g in fake.generated] == ["21:9", "16:9"]


def test_a_model_without_those_params_gets_none():
    fake = Assetgen(projects=[{"id": "delve", "name": "delve"}])
    generate(fake, model="pixel-local")
    assert fake.generated[0]["params"] == {}
    assert fake.generated[0]["model"] == "pixel-local"


def test_no_model_chosen_paints_with_the_default():
    fake = Assetgen(projects=[{"id": "delve", "name": "delve"}])
    generate(fake, model=None)
    assert fake.generated[0]["model"] == "flux-schnell"


def test_a_model_gone_from_assetgen_fails_clearly():
    fake = Assetgen(projects=[{"id": "delve", "name": "delve"}])
    with pytest.raises(AssetgenFailed, match="assetgen no longer offers 'gone-model'"):
        generate(fake, model="gone-model")
    assert fake.generated == []


def test_the_project_is_created_once_then_reused():
    fake = Assetgen(projects=[{"id": "default", "name": "Default"}])

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(fake)) as client:
            painter = AssetgenImages(URL, TOKEN, client=client, poll_s=0, capabilities=reader(fake))
            request = ImageRequest(Job.IMAGE_PORTRAIT, "a dwarf", BackendChoice(ASSETGEN, "flux-schnell"))
            await painter.generate(request)
            await painter.generate(request)

    asyncio.run(run())
    creates = [request for request in fake.requests if (request.method, request.url.path) == ("POST", "/api/projects")]
    assert len(creates) == 1
    assert json.loads(creates[0].content) == {"name": "delve"}
    assert fake.paths().count(("GET", "/api/projects")) == 1
    assert fake.paths().count(("POST", "/api/projects/delve/generate")) == 2


def test_an_existing_delve_project_is_found_by_name():
    fake = Assetgen(projects=[{"id": "delve-3f2a", "name": "delve"}])
    generate(fake)
    assert ("POST", "/api/projects") not in fake.paths()
    assert ("POST", "/api/projects/delve-3f2a/generate") in fake.paths()


def test_a_job_is_polled_until_it_succeeds():
    fake = Assetgen(
        projects=[{"id": "delve", "name": "delve"}],
        polls=[{"status": "queued"}, {"status": "running"}, {"status": "succeeded", "result": {"asset_id": "a-1"}}],
    )
    assert generate(fake).data == PNG
    assert fake.paths().count(("GET", "/api/jobs/j-1")) == 3


def test_a_failed_job_raises_its_error_without_the_token(every_log):
    fake = Assetgen(
        projects=[{"id": "delve", "name": "delve"}],
        polls=[{"status": "failed", "error": f"NSFW content detected (sent Bearer {TOKEN})"}],
    )
    with pytest.raises(AssetgenFailed) as raised:
        generate(fake)
    assert str(raised.value).startswith("assetgen failed: NSFW content detected")
    assert TOKEN not in str(raised.value)
    assert TOKEN not in every_log.text


@pytest.mark.parametrize("status", ["cancelled", "interrupted"])
def test_a_job_that_ends_otherwise_fails(status):
    fake = Assetgen(projects=[{"id": "delve", "name": "delve"}], polls=[{"status": status}])
    with pytest.raises(AssetgenFailed, match=f"assetgen {status}"):
        generate(fake)


@pytest.mark.parametrize("path", ["/api/projects", "/api/projects/delve/generate", "/api/jobs/j-1", "/api/assets/a-1"])
def test_an_error_page_holding_the_request_is_answered_with_its_status_only(path, every_log):
    fake = Assetgen(projects=[{"id": "delve", "name": "delve"}])
    fake.fail = {path: 500}
    with pytest.raises(AssetgenFailed) as raised:
        generate(fake)
    assert str(raised.value) == "assetgen failed (500)."
    assert TOKEN not in every_log.text


def test_unreachable_while_painting_fails_clearly():
    def down(request):
        if request.url.path == "/api/models":
            return Assetgen()(request)
        raise httpx.ConnectError("refused", request=request)

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(down)) as client:
            painter = AssetgenImages(URL, TOKEN, client=client, poll_s=0, capabilities=reader(Assetgen()))
            return await painter.generate(
                ImageRequest(Job.IMAGE_SCENE, "a hall", BackendChoice(ASSETGEN, "flux-schnell"))
            )

    with pytest.raises(AssetgenFailed, match=f"assetgen isn't answering at {URL}"):
        asyncio.run(run())


def test_the_timeout_cancels_the_job():
    fake = Assetgen(projects=[{"id": "delve", "name": "delve"}], polls=[{"status": "running"}])
    with pytest.raises(AssetgenFailed, match="took too long"):
        generate(fake, timeout_s=0)
    assert fake.paths()[-1] == ("DELETE", "/api/jobs/j-1")


def test_a_local_model_has_the_longer_time():
    """A model on assetgen's own machine (FLUX schnell on a CPU) takes minutes: it waits `local_timeout_s`, a paid one
    `timeout_s`."""
    running = [{"status": "running"}, {"status": "succeeded", "result": {"asset_id": "a-1"}}]
    local = Assetgen(projects=[{"id": "delve", "name": "delve"}], polls=running)
    assert generate(local, model="pixel-local", timeout_s=0, local_timeout_s=5.0).data == PNG
    paid = Assetgen(projects=[{"id": "delve", "name": "delve"}], polls=running)
    with pytest.raises(AssetgenFailed, match="over 0 s"):
        generate(paid, model="flux-schnell", timeout_s=0, local_timeout_s=5.0)
    slow = Assetgen(projects=[{"id": "delve", "name": "delve"}], polls=[{"status": "running"}])
    with pytest.raises(AssetgenFailed, match="over 0 s"):
        generate(slow, model="pixel-local", timeout_s=5.0, local_timeout_s=0)


def test_the_time_runs_from_the_jobs_start_not_while_it_waits_its_turn():
    """Five portraits on a local model queue behind one another for half an hour: none is cancelled for waiting."""
    queued = [{"status": "queued", "position": n} for n in (4, 3, 2, 1)]
    fake = Assetgen(
        projects=[{"id": "delve", "name": "delve"}],
        polls=[*queued, {"status": "succeeded", "result": {"asset_id": "a-1"}}],
    )
    assert generate(fake, timeout_s=0).data == PNG


def test_the_watch_hears_of_the_job_and_its_place_in_the_queue():
    fake = Assetgen(
        projects=[{"id": "delve", "name": "delve"}],
        polls=[
            {"status": "queued", "position": 2},
            {"status": "queued", "position": 2},
            {"status": "queued", "position": 1},
            {"status": "running", "position": None},
            {"status": "succeeded", "result": {"asset_id": "a-1"}},
        ],
    )
    heard = []
    generate(fake, watch=heard.append)
    assert heard == [ProviderJob("j-1"), ProviderJob("j-1", 2), ProviderJob("j-1", 1), ProviderJob("j-1")]


def test_a_job_from_an_earlier_start_is_followed_not_sent_again():
    fake = Assetgen(
        projects=[{"id": "delve", "name": "delve"}],
        polls=[{"status": "running"}, {"status": "succeeded", "result": {"asset_id": "a-1"}}],
    )
    heard = []
    assert generate(fake, follow="j-1", watch=heard.append).data == PNG
    assert fake.generated == []
    assert heard == [ProviderJob("j-1")]


def test_a_job_assetgen_no_longer_knows_is_sent_again():
    fake = Assetgen(projects=[{"id": "delve", "name": "delve"}])
    heard = []
    assert generate(fake, follow="j-gone", watch=heard.append).data == PNG
    assert ("GET", "/api/jobs/j-gone") in fake.paths() and len(fake.generated) == 1
    assert heard == [ProviderJob("j-1")]


def test_assetgen_down_a_moment_while_a_job_is_followed_is_waited_out(monkeypatch):
    fake = Assetgen(
        projects=[{"id": "delve", "name": "delve"}],
        polls=[{"status": "queued"}, {"status": "succeeded", "result": {"asset_id": "a-1"}}],
    )
    outages = iter([True, True])

    def flaky(request):
        if request.url.path == "/api/jobs/j-1" and next(outages, False):
            raise httpx.ConnectError("refused", request=request)
        return fake(request)

    assert generate(flaky).data == PNG
    monkeypatch.setattr(assetgen, "UNREACHABLE_S", 0.0)
    outages = iter([True])
    with pytest.raises(AssetgenFailed, match="isn't answering"):
        generate(flaky)


def test_a_local_model_waits_fifteen_minutes_by_default():
    assert LOCAL_TIMEOUT_S == 900.0 and TIMEOUT_S == 300.0


def test_a_download_that_is_not_a_picture_fails():
    fake = Assetgen(projects=[{"id": "delve", "name": "delve"}])
    plain = fake.__call__

    def svg(request):
        if request.url.path.endswith("/file/v001.png"):
            return httpx.Response(200, content=b"<svg/>", headers={"Content-Type": "image/svg+xml"})
        return plain(request)

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(svg)) as client:
            painter = AssetgenImages(URL, None, client=client, poll_s=0, capabilities=reader(fake))
            return await painter.generate(
                ImageRequest(Job.IMAGE_PORTRAIT, "x", BackendChoice(ASSETGEN, "flux-schnell"))
            )

    with pytest.raises(AssetgenFailed, match="isn't a picture"):
        asyncio.run(run())


def test_the_url_is_checked_again_before_painting():
    fake = Assetgen()

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(fake)) as client:
            painter = AssetgenImages(
                "http://assetgen.lan:47898",
                None,
                client=client,
                poll_s=0,
                capabilities=lambda: reader(fake)(),
                resolve=lambda host, port: ["169.254.169.254"],
            )
            return await painter.generate(
                ImageRequest(Job.IMAGE_PORTRAIT, "x", BackendChoice(ASSETGEN, "flux-schnell"))
            )

    with pytest.raises(AssetgenFailed, match="loopback or private"):
        asyncio.run(run())
    assert not [request for request in fake.requests if request.url.path != "/api/models"]


def test_the_painter_says_its_capabilities_live():
    fake = Assetgen()

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(fake)) as client:
            return AssetgenImages(URL, None, client=client, capabilities=reader(fake)).capabilities

    assert asyncio.run(run()).models == ("flux-schnell", "pixel-local", "odd-one")


def test_its_repr_holds_no_token():
    async def run():
        async with httpx.AsyncClient() as client:
            return repr(AssetgenImages(URL, TOKEN, client=client, capabilities=reader(Assetgen())))

    assert TOKEN not in asyncio.run(run())


# Registration


def config_for(tmp_path) -> Config:
    return Config(data_dir=tmp_path)


def test_nothing_is_registered_without_assetgen_json(tmp_path):
    registries = build_registries(config=config_for(tmp_path))
    assert ASSETGEN not in [caps.id for caps in registries.images.capabilities()]


def test_assetgen_is_registered_at_start_last_and_live(tmp_path):
    save_assetgen(tmp_path, URL, TOKEN)
    registries = build_registries(config=config_for(tmp_path))
    ids = list(registries.images._caps)  # the ids alone: reading the capabilities would call assetgen
    assert ids[-1] == ASSETGEN
    assert ids.index(FAKE_IMAGES_CAPABILITIES.id) < ids.index(ASSETGEN)


def test_register_assetgen_reads_its_models_through_the_transport(tmp_path):
    save_assetgen(tmp_path, URL, TOKEN)
    images: Registry = Registry()
    fake = Assetgen()
    register_assetgen_into(images, tmp_path, fake)
    (caps,) = images.capabilities()
    assert caps.live is True
    assert caps.models == ("flux-schnell", "pixel-local", "odd-one")
    assert isinstance(images.get(ASSETGEN), AssetgenImages)


def test_register_assetgen_unregisters_without_its_file(tmp_path):
    save_assetgen(tmp_path, URL, None)
    images: Registry = Registry()
    register_assetgen_into(images, tmp_path, Assetgen())
    (tmp_path / "assetgen.json").unlink()
    register_assetgen_into(images, tmp_path, Assetgen())
    assert images.capabilities() == []


def test_local_models_are_free_and_the_rest_paid(tmp_path):
    save_assetgen(tmp_path, URL, None)
    registries = build_registries(config=config_for(tmp_path))
    registries.images.unregister(ASSETGEN)
    register_assetgen_into(registries.images, tmp_path, Assetgen())
    assert is_paid(registries, Job.IMAGE_SCENE, BackendChoice(ASSETGEN, "pixel-local")) is False
    assert is_paid(registries, Job.IMAGE_SCENE, BackendChoice(ASSETGEN, "flux-schnell")) is True
    assert is_paid(registries, Job.IMAGE_SCENE, BackendChoice(ASSETGEN, "odd-one")) is True
    assert is_paid(registries, Job.IMAGE_SCENE, BackendChoice(ASSETGEN, "not-there")) is True


def register_assetgen_into(images: Registry, data_dir, fake):
    class Registries:
        pass

    registries = Registries()
    registries.images = images
    return register_assetgen(registries, Config(data_dir=data_dir), transport=httpx.MockTransport(fake))
