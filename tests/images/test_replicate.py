"""The Replicate client (plan 6 Task 10), against `httpx.MockTransport`: never a real call. A prediction is created
with `Prefer: wait`, polled at `urls.get` until it succeeds, fails or times out, and its output downloaded. The token
comes from `REPLICATE_API_TOKEN` or `<data dir>/replicate-token`, and goes only to Replicate's API."""

import asyncio
import json

import httpx
import pytest

from delve.__main__ import build_registries
from delve.config import Config
from delve.domain.settings import BackendChoice, Job
from delve.images.portraitgen import PORTRAITGEN
from delve.images.provider import ImageFile, ImageRequest
from delve.images.replicate import (
    API_URL,
    MODEL_INFO,
    MODELS,
    REPLICATE,
    STYLE_BASE,
    STYLE_RULES,
    THROTTLE_TRIES,
    THROTTLE_WAIT_S,
    TOKEN_ENV,
    TOKEN_FILE,
    ReplicateFailed,
    ReplicateImages,
    full_prompt,
    load_token,
    model_input,
    size_input,
    throttle_wait,
)

TOKEN = "r8_SECRET-TOKEN"
PNG = b"\x89PNG painted"
OUTPUT = "https://replicate.delivery/xezq/out-0.png"
CHOICE = BackendChoice(REPLICATE)


def prediction(status: str, **more) -> dict:
    return {"id": "p1", "status": status, "urls": {"get": f"{API_URL}/predictions/p1"}, **more}


class Replicate:
    """A fake Replicate: answers the create with `created`, each poll with the next of `polls`, and the output."""

    def __init__(self, created: dict, polls: list[dict] = (), status: int = 201) -> None:
        self.created, self.polls, self.status = created, list(polls), status
        self.requests: list[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        url = str(request.url)
        if request.method == "POST":
            return httpx.Response(self.status, json=self.created)
        if url == OUTPUT:
            return httpx.Response(200, content=PNG, headers={"Content-Type": "image/png"})
        if url.startswith(f"{API_URL}/predictions/"):
            return httpx.Response(200, json=self.polls.pop(0) if len(self.polls) > 1 else self.polls[0])
        return httpx.Response(404, json={"detail": "not found"})


def generate(
    fake: Replicate, job=Job.IMAGE_PORTRAIT, *, choice=CHOICE, timeout_s=5.0, prompt="a stout dwarf", aspect=""
):
    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(fake)) as client:
            images = ReplicateImages(TOKEN, client=client, timeout_s=timeout_s, poll_s=0)
            return await images.generate(ImageRequest(job, prompt, choice, tone="grimdark", aspect=aspect))

    return asyncio.run(run())


def test_a_prediction_that_succeeds_at_once():
    fake = Replicate(prediction("succeeded", output=OUTPUT))
    assert generate(fake) == ImageFile(PNG, "image/png")
    create, download = fake.requests
    assert str(create.url) == f"{API_URL}/models/black-forest-labs/flux-2-pro/predictions"
    assert create.headers["Authorization"] == f"Bearer {TOKEN}"
    assert create.headers["Prefer"] == "wait"
    body = json.loads(create.content)
    assert body["input"] == {
        "prompt": full_prompt(Job.IMAGE_PORTRAIT, "grimdark", "a stout dwarf"),
        "aspect_ratio": "1:1",
        "output_format": "png",
        "safety_tolerance": 5,
    }
    assert str(download.url) == OUTPUT
    assert "Authorization" not in download.headers, "the token goes only to Replicate's API"


def test_a_prediction_polled_until_it_succeeds_with_a_list_of_outputs():
    fake = Replicate(prediction("starting"), [prediction("processing"), prediction("succeeded", output=[OUTPUT])])
    assert generate(fake, Job.IMAGE_SCENE, choice=BackendChoice(REPLICATE, MODELS[1])) == ImageFile(PNG, "image/png")
    create, *polls, download = fake.requests
    assert str(create.url) == f"{API_URL}/models/black-forest-labs/flux-schnell/predictions"
    assert json.loads(create.content)["input"]["aspect_ratio"] == "16:9", "a scene is wide"
    assert len(polls) == 2 and all(p.headers["Authorization"] == f"Bearer {TOKEN}" for p in polls)
    assert str(download.url) == OUTPUT


def test_a_request_with_an_aspect_sends_it_and_one_without_sends_the_jobs():
    wide = Replicate(prediction("succeeded", output=OUTPUT))
    generate(wide, Job.IMAGE_SCENE, aspect="21:9", choice=BackendChoice(REPLICATE, MODELS[1]))
    assert json.loads(wide.requests[0].content)["input"]["aspect_ratio"] == "21:9", "a banner is wider"
    scene = Replicate(prediction("succeeded", output=OUTPUT))
    generate(scene, Job.IMAGE_SCENE)
    assert json.loads(scene.requests[0].content)["input"]["aspect_ratio"] == "16:9"


def test_an_aspect_the_model_lacks_is_a_custom_size_of_about_a_megapixel():
    # flux-2-pro lists no 21:9 and answers it with HTTP 422; it takes a custom width and height, multiples of 16.
    fake = Replicate(prediction("succeeded", output=OUTPUT))
    generate(fake, Job.IMAGE_SCENE, aspect="21:9")
    sent = json.loads(fake.requests[0].content)["input"]
    assert sent["aspect_ratio"] == "custom"
    assert sent["width"] % 16 == 0 and sent["height"] % 16 == 0
    assert abs(sent["width"] / sent["height"] - 21 / 9) < 0.05
    assert 0.9e6 < sent["width"] * sent["height"] < 1.1e6, "the model's default 1 MP, not its 4 MP maximum"


def test_a_refused_request_says_why():
    fake = Replicate({"detail": "- input.aspect_ratio: aspect_ratio must be one of the following"}, status=422)
    with pytest.raises(ReplicateFailed, match=r"HTTP 422: - input.aspect_ratio: aspect_ratio must be one"):
        generate(fake)


THROTTLED = (
    "Request was throttled. Your rate limit for creating predictions is reduced to 6 requests per minute with a burst"
    " of 1 requests while you have less than $5.0 in credit. Your rate limit resets in ~9s."
)


class Throttling(Replicate):
    """A fake Replicate that throttles the first `times` creates with a 429 (with `headers`), then answers."""

    def __init__(self, times: int, headers: dict | None = None) -> None:
        super().__init__(prediction("succeeded", output=OUTPUT))
        self.times, self.headers = times, headers or {}

    def __call__(self, request: httpx.Request) -> httpx.Response:
        if request.method == "POST" and self.times > 0:
            self.times -= 1
            self.requests.append(request)
            return httpx.Response(
                429, json={"title": "Request was throttled", "detail": THROTTLED}, headers=self.headers
            )
        return super().__call__(request)


def generate_unhurried(fake: Replicate):
    """`generate`, with no real wait on a 429."""

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(fake)) as client:
            images = ReplicateImages(TOKEN, client=client, timeout_s=5.0, poll_s=0, throttle_wait_max_s=0)
            return await images.generate(ImageRequest(Job.IMAGE_SCENE, "a banner", CHOICE, tone="grimdark"))

    return asyncio.run(run())


def test_a_throttled_request_waits_and_is_sent_again():
    """DEL-233: two 429s, then the prediction: the picture comes, after three creates."""
    fake = Throttling(2)
    assert generate_unhurried(fake) == ImageFile(PNG, "image/png")
    assert [r.method for r in fake.requests] == ["POST", "POST", "POST", "GET"]


def test_a_request_throttled_every_time_is_refused_after_the_last_try():
    fake = Throttling(10)
    with pytest.raises(ReplicateFailed, match=r"HTTP 429: Request was throttled"):
        generate_unhurried(fake)
    assert len(fake.requests) == THROTTLE_TRIES


def test_the_wait_a_429_asks_for():
    """Its Retry-After, else the detail's "resets in ~9s", else the default; a second more than it says."""

    def throttled(headers=None, detail=THROTTLED):
        return httpx.Response(429, json={"detail": detail}, headers=headers or {})

    assert throttle_wait(throttled({"Retry-After": "4"})) == 5
    assert throttle_wait(throttled()) == 10
    assert throttle_wait(throttled(detail="Your rate limit resets in ~2.5s.")) == 3.5
    assert throttle_wait(throttled({"Retry-After": "Wed, 21 Oct 2026 07:28:00 GMT"}, detail="")) == THROTTLE_WAIT_S


def test_an_unknown_model_is_the_first_one():
    fake = Replicate(prediction("succeeded", output=OUTPUT))
    generate(fake, Job.IMAGE_POSSESSION, choice=BackendChoice(REPLICATE, "someone/else"))
    assert str(fake.requests[0].url) == f"{API_URL}/models/{MODELS[0]}/predictions"
    assert json.loads(fake.requests[0].content)["input"]["aspect_ratio"] == "1:1"


def test_a_failed_prediction_raises_with_its_error():
    fake = Replicate(prediction("starting"), [prediction("failed", error="NSFW content detected")])
    with pytest.raises(ReplicateFailed, match="NSFW content detected"):
        generate(fake)


def test_a_refused_request_raises_without_the_token():
    fake = Replicate({"detail": "Unauthenticated"}, status=401)
    with pytest.raises(ReplicateFailed) as raised:
        generate(fake)
    assert "401" in str(raised.value) and TOKEN not in str(raised.value)


def test_a_prediction_that_takes_too_long_times_out():
    fake = Replicate(prediction("starting"), [prediction("processing")])
    with pytest.raises(ReplicateFailed, match="took too long"):
        generate(fake, timeout_s=0.05)


def test_a_poll_url_elsewhere_is_never_sent_the_token():
    fake = Replicate({**prediction("starting"), "urls": {"get": "https://evil.example/p1"}})
    with pytest.raises(ReplicateFailed):
        generate(fake)
    assert all("evil.example" not in str(r.url) for r in fake.requests)


def test_the_prompt_is_the_style_the_tone_and_the_brief():
    portrait = full_prompt(Job.IMAGE_PORTRAIT, "grimdark", "a stout dwarf")
    assert portrait.startswith(STYLE_BASE) and "character portrait" in portrait
    assert "Brom and Jeff Easley" in portrait and portrait.endswith("a stout dwarf")
    scene = full_prompt(Job.IMAGE_SCENE, "classic", "the bridge at dusk")
    assert "character portrait" not in scene, "ttrpg2 forced it into every prompt"
    assert "Larry Elmore" in scene and scene.endswith("the bridge at dusk")
    assert "character portrait" not in full_prompt(Job.IMAGE_POSSESSION, "classic", "a cog")
    # A tone of its own words (custom, or one ttrpg2 has no style for) is its own clause, as ttrpg2 did.
    assert "moonlit and eerie." in full_prompt(Job.IMAGE_SCENE, "moonlit and eerie", "a crypt")


def test_the_token_from_the_environment_or_the_data_dir(tmp_path):
    assert load_token(tmp_path, {}) is None
    (tmp_path / TOKEN_FILE).write_text(f"  {TOKEN}\n")
    assert load_token(tmp_path, {}) == TOKEN
    assert load_token(tmp_path, {TOKEN_ENV: "r8_from_env"}) == "r8_from_env"
    (tmp_path / TOKEN_FILE).write_text("\n")
    assert load_token(tmp_path, {TOKEN_ENV: " "}) is None


def test_replicate_is_registered_only_with_a_token(tmp_path, monkeypatch):
    monkeypatch.delenv(TOKEN_ENV, raising=False)
    config = Config(data_dir=tmp_path)
    without = [caps.id for caps in build_registries(config=config).images.capabilities()]
    assert without[0] == PORTRAITGEN and REPLICATE not in without
    (tmp_path / TOKEN_FILE).write_text(TOKEN)
    registries = build_registries(config=config)
    ids = [caps.id for caps in registries.images.capabilities()]
    # No portrait does only NPCs' portraits (DEL-248), so the paid jobs still default to Replicate.
    assert ids[:3] == [PORTRAITGEN, "none", REPLICATE], "portraits default to portraitgen, the paid jobs to Replicate"
    assert isinstance(registries.images.get(REPLICATE), ReplicateImages)


# ----- the install's image style and the models (DEL-201, DEL-202) -----


def test_a_style_replaces_the_tone_and_the_cover_art_look():
    styled = full_prompt(Job.IMAGE_PORTRAIT, "grimdark", "a stout dwarf", "A black-ink woodcut")
    assert styled == f"{STYLE_RULES} A black-ink woodcut. a stout dwarf"
    assert "AD&D" not in styled and "Brom" not in styled
    scene = full_prompt(Job.IMAGE_SCENE, "classic", "the bridge", "Woodcut.")
    assert "character portrait" not in scene and "non-violent" in scene and scene.endswith("Woodcut. the bridge")
    assert full_prompt(Job.IMAGE_SCENE, "classic", "the bridge", "  ") == full_prompt(
        Job.IMAGE_SCENE, "classic", "the bridge"
    )


def test_the_models_and_what_each_takes():
    assert MODELS[:2] == ("black-forest-labs/flux-2-pro", "black-forest-labs/flux-schnell"), "the default stays"
    assert set(MODELS) >= {
        "black-forest-labs/flux-1.1-pro-ultra", "black-forest-labs/flux-dev", "google/nano-banana-pro",
        "google/nano-banana", "bytedance/seedream-4", "stability-ai/stable-diffusion-3.5-large", "luma/photon",
    }  # fmt: skip
    assert all(MODEL_INFO[m].paid for m in MODELS)
    for model in MODELS[1:]:
        assert model_input(model, "p", "21:9")["aspect_ratio"] == "21:9", f"{model} paints a banner as it is"
    assert model_input("black-forest-labs/flux-2-pro", "p", "21:9") == {
        "prompt": "p", "aspect_ratio": "custom", "width": 1520, "height": 656, "output_format": "png",
        "safety_tolerance": 5,
    }  # fmt: skip
    assert model_input("bytedance/seedream-4", "p", "16:9") == {"prompt": "p", "aspect_ratio": "16:9"}
    assert model_input("black-forest-labs/flux-schnell", "p", "1:1") == {
        "prompt": "p", "aspect_ratio": "1:1", "output_format": "png",
    }  # fmt: skip
    assert model_input("unknown/model", "p", "1:1") == {
        "prompt": "p", "aspect_ratio": "1:1", "output_format": "png", "safety_tolerance": 5,
    }  # fmt: skip


def test_a_ratio_a_model_doesnt_list_is_its_nearest():
    assert size_input("google/imagen-4", "21:9") == {"aspect_ratio": "21:9"}, "a model Delve doesn't know"
    assert size_input("luma/photon", "3:2") == {"aspect_ratio": "4:3"}
