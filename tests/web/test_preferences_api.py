import asyncio

import pytest

from delve.domain.backends import ModelInfo, ProviderCapabilities
from delve.domain.image_styles import PRESETS
from delve.domain.settings import BackendChoice, Effort, Job
from delve.images.fake import FakeImages
from delve.images.replicate import REPLICATE_CAPABILITIES
from delve.web.defaults import default_choices
from delve.web.routes.preferences import image_paid
from tests.web.conftest import make_registries

JOBS = [
    "dm",
    "side",
    "translation",
    "conversion",
    "conversion.thorough",
    "novel",
    "image.portrait",
    "image.npc_portrait",
    "image.scene",
    "image.possession",
]
FAKE_DM = {"provider": "fake", "model": "fake-large", "effort": "auto"}
FAKE_IMAGES = {"provider": "fake-images", "model": None, "effort": None}
DEFAULTS = {
    "dm": FAKE_DM,
    "side": FAKE_DM,
    "translation": FAKE_DM,
    "conversion": FAKE_DM,
    "novel": FAKE_DM,
    "image.portrait": FAKE_IMAGES,
    # portraitgen, the NPCs' default (DEL-248), isn't registered here: the first that does the job.
    "image.npc_portrait": FAKE_IMAGES,
    "image.scene": FAKE_IMAGES,
    "image.possession": FAKE_IMAGES,
}
TONE = {"preset": "tone", "custom": ""}
"""The image style of preferences that never chose one: the campaign's tone."""


def published(app):
    """The events published so far."""

    async def run():
        bus = app.state.events
        events = bus.subscribe(since=0)
        found = []
        pending = asyncio.ensure_future(anext(events))
        while True:
            done, _ = await asyncio.wait({pending}, timeout=0.05)
            if not done:
                break
            found.append(pending.result())
            pending = asyncio.ensure_future(anext(events))
        pending.cancel()
        await asyncio.gather(pending, return_exceptions=True)
        await events.aclose()
        return found

    return asyncio.run(run())


def test_default_choices():
    defaults = default_choices(make_registries())
    assert defaults[Job.DM] == BackendChoice("fake", "fake-large", Effort.AUTO)
    assert defaults[Job.IMAGE_SCENE] == BackendChoice("fake-images", None, None)
    assert list(defaults) == [job for job in Job if job is not Job.CONVERSION_THOROUGH]
    assert Job.CONVERSION_THOROUGH not in defaults, "only the Claude CLI does a thorough conversion"


def test_the_conversion_job_defaults_to_sonnet_at_medium_effort_on_claude():
    from delve.dm.claude_cli.provider import CLAUDE_CLI_CAPABILITIES
    from delve.domain.settings import JOB_DEFAULTS

    registries = make_registries()
    registries.dm.register(CLAUDE_CLI_CAPABILITIES, object)
    defaults = default_choices(registries)
    assert (
        defaults[Job.CONVERSION] == JOB_DEFAULTS[Job.CONVERSION] == BackendChoice("claude-cli", "sonnet", Effort.MEDIUM)
    )
    assert defaults[Job.DM].provider == "fake", "the other jobs keep the first provider that does them"
    assert default_choices(make_registries())[Job.CONVERSION].provider == "fake", "without claude, the first one"
    assert defaults[Job.TRANSLATION] == BackendChoice("claude-cli", "haiku", Effort.LOW), "translation: small and quick"
    assert defaults[Job.NOVEL] == BackendChoice("claude-cli", "sonnet", Effort.MEDIUM), "novels: as conversions"
    assert defaults[Job.CONVERSION_THOROUGH] == BackendChoice("claude-cli", "opus", Effort.HIGH)


def test_default_choices_skip_jobs_nobody_does():
    registries = make_registries()
    registries.images = type(registries.images)()
    registries.dm.register(ProviderCapabilities("quiet", "Quiet", frozenset({Job.DM})), object)
    defaults = default_choices(registries)
    assert defaults[Job.DM].provider == "fake"
    assert Job.IMAGE_PORTRAIT not in defaults


def test_backends_lists_providers_and_jobs(local):
    response = local.get("/api/backends")
    assert response.status_code == 200
    assert response.json() == {
        "jobs": JOBS,
        "providers": [
            {
                "id": "fake",
                "title": "Fake DM (scripted)",
                "jobs": ["dm", "side", "translation", "conversion", "novel"],
                "models": ["fake-large", "fake-small"],
                "efforts": ["auto", "low", "medium", "high", "max"],
                "default_model": "fake-large",
                "model_info": {},
                "problem": None,
                "development": False,
            },
            {
                "id": "fake-images",
                "title": "Fake images",
                "jobs": ["image.portrait", "image.npc_portrait", "image.scene", "image.possession"],
                "models": [],
                "efforts": [],
                "default_model": None,
                "model_info": {},
                "problem": None,
                "development": False,
            },
        ],
        "image_styles": [
            {"id": preset.id, "name": preset.name, "prompt": preset.prompt, "sample": preset.sample}
            for preset in PRESETS
        ],
    }


def test_preferences_default_when_empty(local):
    response = local.get("/api/preferences")
    assert response.status_code == 200
    assert response.json() == {
        "choices": DEFAULTS,
        "language": "en",
        "image_style": TONE,
        "warnings": [],
        "coded_warnings": [],
    }


def test_put_valid_preferences_persists_and_publishes(app, local, storage):
    choices = {**DEFAULTS, "side": {"provider": "fake", "model": "fake-small", "effort": "low"}}
    response = local.put("/api/preferences", json={"choices": choices, "language": "nl"})
    assert response.status_code == 200
    assert response.json() == {
        "choices": choices,
        "language": "nl",
        "image_style": TONE,
        "warnings": [],
        "coded_warnings": [],
    }

    assert storage.settings.load() == {"choices": choices, "language": "nl", "image_style": TONE}
    assert local.get("/api/preferences").json() == {
        "choices": choices,
        "language": "nl",
        "image_style": TONE,
        "warnings": [],
        "coded_warnings": [],
    }
    [event] = published(app)
    assert (event.type, event.data) == ("preferences", {"choices": choices, "language": "nl", "image_style": TONE})


def test_put_fills_left_out_jobs_with_defaults(local, storage):
    response = local.put("/api/preferences", json={"choices": {"dm": {"provider": "fake", "model": None}}})
    assert response.status_code == 200
    expected = {**DEFAULTS, "dm": {"provider": "fake", "model": None, "effort": None}}
    assert response.json() == {
        "choices": expected,
        "language": "en",
        "image_style": TONE,
        "warnings": [],
        "coded_warnings": [],
    }
    assert storage.settings.load()["choices"] == expected


def test_put_invalid_model_422_with_warning(app, local, storage):
    choices = {**DEFAULTS, "dm": {"provider": "fake", "model": "gpt-x", "effort": "auto"}}
    response = local.put("/api/preferences", json={"choices": choices, "language": "en"})
    assert response.status_code == 422
    body = response.json()
    assert set(body) == {"error", "warnings", "coded_warnings"}
    assert body["warnings"] == ["dm: model 'gpt-x' is not offered by 'fake'; using default"]
    assert body["coded_warnings"] == [
        {
            "code": "model_not_offered",
            "args": {"job": "dm", "provider": "fake", "model": "gpt-x", "outcome": "default"},
            "text": body["warnings"][0],
        }
    ], "the same warning, with its code and args, beside the old strings"
    assert storage.settings.load() == {}
    assert published(app) == []


def test_put_bad_language_422(local):
    response = local.put("/api/preferences", json={"choices": DEFAULTS, "language": "es"})
    assert response.status_code == 422
    assert response.json()["warnings"] == ["language: 'es' is not offered; using 'en'"]


def test_put_not_an_object_422_json(local):
    response = local.put("/api/preferences", json=["dm"])
    assert response.status_code == 422
    assert "error" in response.json()


def test_stored_stale_choice_falls_back_with_warning(local, storage):
    storage.settings.save({"choices": {"dm": {"provider": "gone", "model": "old"}}, "language": "nl"})
    response = local.get("/api/preferences")
    assert response.status_code == 200
    body = response.json()
    assert body["choices"] == DEFAULTS
    assert body["language"] == "nl"
    assert len(body["warnings"]) == 1 and body["warnings"][0].startswith("dm: ")


def test_stored_garbage_never_500(local, storage):
    storage.settings.save({"choices": ["dm"], "language": 3})
    response = local.get("/api/preferences")
    assert response.status_code == 200
    assert response.json()["choices"] == DEFAULTS
    assert len(response.json()["warnings"]) == 2


def test_preferences_need_organiser(lan):
    for method, path in (("GET", "/api/preferences"), ("GET", "/api/backends"), ("PUT", "/api/preferences")):
        response = lan.request(method, path, json={} if method == "PUT" else None)
        assert response.status_code == 401, path
        assert response.json() == {"error": "Log in to go on."}


def test_token_cookie_reaches_preferences(lan, token):
    lan.cookies.set("delve_token", token)
    assert lan.get("/api/preferences").status_code == 200


def test_the_old_options_path_is_gone(local, storage):
    response = local.put("/api/settings", json={"choices": DEFAULTS, "language": "nl"})
    assert response.status_code in (404, 405)
    assert storage.settings.load() == {}


# ----- live providers, model labels and the paid gate (portraits plan Task 4) -----

ASSETGEN_UP = ProviderCapabilities(
    "assetgen",
    "assetgen",
    frozenset({Job.IMAGE_SCENE}),
    models=("flux-schnell", "sdxl-local"),
    model_info={
        "flux-schnell": ModelInfo("FLUX schnell", "replicate", "~$0.003 / image", paid=True),
        "sdxl-local": ModelInfo("SDXL", "local", None, paid=False),
    },
    default_model="flux-schnell",
)
DOWN = "assetgen isn't answering at http://localhost:8765"


def live_assetgen(registries, state):
    """assetgen as a live provider: up while `state["up"]`, with a problem otherwise."""

    def caps():
        if state["up"]:
            return ASSETGEN_UP
        return ProviderCapabilities("assetgen", "assetgen", frozenset({Job.IMAGE_SCENE}), problem=DOWN)

    registries.images.register_live("assetgen", caps, FakeImages)


def test_backends_lists_each_models_label_backend_price_and_paid(local, registries):
    registries.images.register(REPLICATE_CAPABILITIES, FakeImages)
    state = {"up": True}
    live_assetgen(registries, state)
    providers = {p["id"]: p for p in local.get("/api/backends").json()["providers"]}
    assert providers["replicate"]["model_info"]["black-forest-labs/flux-schnell"] == {
        "label": "flux-schnell",
        "backend": "replicate",
        "price": "~$0.003 / image",
        "paid": True,
    }
    assert set(providers["replicate"]["model_info"]) == set(providers["replicate"]["models"])
    assert providers["assetgen"]["models"] == ["flux-schnell", "sdxl-local"]
    assert providers["assetgen"]["model_info"]["sdxl-local"] == {
        "label": "SDXL",
        "backend": "local",
        "price": None,
        "paid": False,
    }
    assert providers["assetgen"]["problem"] is None

    state["up"] = False
    providers = {p["id"]: p for p in local.get("/api/backends").json()["providers"]}
    assert providers["assetgen"]["models"] == [] and providers["assetgen"]["problem"] == DOWN, "read on each call"


def test_a_choice_that_cant_be_used_is_saved_with_its_warning(app, local, registries, storage):
    state = {"up": False}
    live_assetgen(registries, state)
    choices = {**DEFAULTS, "image.scene": {"provider": "assetgen", "model": "sdxl-local", "effort": None}}
    response = local.put("/api/preferences", json={"choices": choices, "language": "en"})
    assert response.status_code == 200, response.json()
    warning = f"image.scene: can't be used: {DOWN}"
    coded = {
        "code": "provider_problem",
        "args": {"job": "image.scene", "provider": "assetgen", "problem": DOWN, "outcome": "kept"},
        "text": warning,
    }
    assert response.json() == {
        "choices": choices,
        "language": "en",
        "image_style": TONE,
        "warnings": [warning],
        "coded_warnings": [coded],
    }
    assert storage.settings.load()["choices"]["image.scene"]["provider"] == "assetgen", "not refused"
    assert local.get("/api/preferences").json()["warnings"] == [warning]
    [event] = published(app)
    assert event.data == {"choices": choices, "language": "en", "image_style": TONE}, "the warnings aren't stored"

    state["up"] = True
    assert local.get("/api/preferences").json() == {
        "choices": choices,
        "language": "en",
        "image_style": TONE,
        "warnings": [],
        "coded_warnings": [],
    }


def test_a_refusing_warning_still_refuses_beside_one_that_doesnt(local, registries, storage):
    live_assetgen(registries, {"up": False})
    choices = {
        **DEFAULTS,
        "image.scene": {"provider": "assetgen", "model": None, "effort": None},
        "dm": {"provider": "fake", "model": "gpt-x", "effort": None},
    }
    response = local.put("/api/preferences", json={"choices": choices, "language": "en"})
    assert response.status_code == 422
    assert response.json()["warnings"] == [
        "dm: model 'gpt-x' is not offered by 'fake'; using default",
        f"image.scene: can't be used: {DOWN}",
    ]
    assert storage.settings.load() == {}


def test_image_paid_asks_the_model_preferences_chose(app, registries, storage):
    live_assetgen(registries, {"up": True})
    assert image_paid(app, Job.IMAGE_SCENE) is False, "the fake is free"
    storage.settings.save({"choices": {"image.scene": {"provider": "assetgen", "model": "sdxl-local"}}})
    assert image_paid(app, Job.IMAGE_SCENE) is False
    storage.settings.save({"choices": {"image.scene": {"provider": "assetgen", "model": "flux-schnell"}}})
    assert image_paid(app, Job.IMAGE_SCENE) is True
    storage.settings.save({"choices": {"image.scene": {"provider": "assetgen", "model": None}}})
    assert image_paid(app, Job.IMAGE_SCENE) is True, "its default model, flux-schnell"
    registries.images = type(registries.images)()
    assert image_paid(app, Job.IMAGE_SCENE) is True, "no provider for the job counts as paid"


def test_saving_preferences_wakes_banners_whose_gate_opened(local, storage, registries):
    """Looks and banners plan Task 2: the scene's choice becomes the free fake, and the waiting banner is painted."""
    from tests.web.test_campaigns_api import HeldPainter, banner_painters, campaign, crypt_module, settled

    banner_painters(registries, storage, HeldPainter(), "dear")
    cid = campaign(local, crypt_module(local)["id"])["id"]
    [row] = storage.campaign_images.list(cid, kind="banner")
    assert row.status == "waiting"

    response = local.put("/api/preferences", json={"choices": {"image.scene": FAKE_IMAGES}})

    assert response.status_code == 200, response.json()
    assert storage.campaign_images.get(row.id).status in ("painting", "done"), "no longer waiting"
    assert settled(storage, row.id).status == "done"


def test_backends_mark_the_development_providers(config, monkeypatch):
    from delve.__main__ import build_registries

    monkeypatch.delenv("REPLICATE_API_TOKEN", raising=False)
    registries = build_registries(config)
    caps = {c.id: c for c in [*registries.dm.capabilities(), *registries.images.capabilities()]}
    assert caps["fake"].development and caps["fake-images"].development
    assert not caps["portraitgen"].development
    assert caps["fake-images"].title == "Fake images (development)", "the title still says so"


def test_backends_say_whether_a_provider_is_for_development(local, registries):
    from dataclasses import replace

    from delve.images.fake import FAKE_IMAGES_CAPABILITIES

    registries.images.register(replace(FAKE_IMAGES_CAPABILITIES, development=True), FakeImages)
    providers = {p["id"]: p for p in local.get("/api/backends").json()["providers"]}
    assert providers["fake-images"]["development"] is True
    assert providers["fake"]["development"] is False


def test_backends_label_the_claude_models(local, registries):
    from delve.dm.claude_cli.provider import CLAUDE_CLI_CAPABILITIES

    registries.dm.register(CLAUDE_CLI_CAPABILITIES, object)
    claude = next(p for p in local.get("/api/backends").json()["providers"] if p["id"] == "claude-cli")
    assert claude["models"] == ["opus", "sonnet", "haiku"], "no bare 'default': no model is the CLI's own"
    assert claude["default_model"] is None
    assert {model: info["label"] for model, info in claude["model_info"].items()} == {
        "opus": "Opus (most capable)",
        "sonnet": "Sonnet",
        "haiku": "Haiku (fastest)",
    }


def test_a_stored_default_claude_model_reads_as_the_clis_own(app, local, registries, storage):
    from delve.dm.claude_cli.provider import CLAUDE_CLI_CAPABILITIES
    from delve.web.routes.preferences import current_preferences

    registries.dm.register(CLAUDE_CLI_CAPABILITIES, object)
    storage.settings.save({"choices": {"dm": {"provider": "claude-cli", "model": "default", "effort": "high"}}})
    body = local.get("/api/preferences").json()
    assert body["choices"]["dm"] == {"provider": "claude-cli", "model": None, "effort": "high"}
    assert body["warnings"] == [], "kept as it was meant, not replaced by the default"
    assert current_preferences(app).choices[Job.DM] == BackendChoice("claude-cli", None, Effort.HIGH)

    old_tab = {"choices": {"side": {"provider": "claude-cli", "model": "default", "effort": None}}}
    response = local.put("/api/preferences", json=old_tab)
    assert response.status_code == 200
    assert storage.settings.load()["choices"]["side"] == {"provider": "claude-cli", "model": None, "effort": None}


def test_a_language_only_put_keeps_the_stored_choices_as_stored(app, local, storage):
    stored_choices = {
        "dm": {"provider": "gone", "model": "old", "effort": None},
        "image.scene": {"provider": "replicate", "model": "black-forest-labs/flux-schnell", "effort": None},
    }
    storage.settings.save({"choices": stored_choices, "language": "en"})
    assert local.get("/api/preferences").json()["choices"] == DEFAULTS, "neither can be used now"

    response = local.put("/api/preferences", json={"language": "nl"})
    assert response.status_code == 200, response.json()
    assert storage.settings.load() == {"choices": stored_choices, "language": "nl"}, "unchanged, not the defaults"
    body = response.json()
    assert body["choices"] == DEFAULTS and body["language"] == "nl"
    assert len(body["warnings"]) == 2, "as GET says them"
    [event] = published(app)
    assert event.data == {"choices": DEFAULTS, "language": "nl", "image_style": TONE}


def test_a_language_only_put_still_refuses_a_bad_language(local, storage):
    storage.settings.save({"choices": {"dm": FAKE_DM}, "language": "en"})
    response = local.put("/api/preferences", json={"language": "xx"})
    assert response.status_code == 422
    assert storage.settings.load() == {"choices": {"dm": FAKE_DM}, "language": "en"}


@pytest.mark.parametrize("language", ["fr", "de", "lv"])
def test_put_each_new_interface_language(local, language):
    """DEL-122: French, German and Latvian are interface languages too."""
    response = local.put("/api/preferences", json={"choices": DEFAULTS, "language": language})
    assert response.status_code == 200 and response.json()["language"] == language


def test_the_owners_seats_follow_the_interface_language(local, storage):
    """The story is translated into a seat's language, so the owner's seats take the language the owner picks in the
    side bar or Preferences, and a new table's host seat starts in it."""
    from delve.play.seats import owner_seat
    from tests.web.test_campaigns_api import campaign, crypt_module

    module = crypt_module(local)
    tuesday = campaign(local, module["id"])
    assert owner_seat(storage, tuesday["id"]).language == "en"
    assert local.put("/api/preferences", json={"language": "nl"}).status_code == 200
    assert owner_seat(storage, tuesday["id"]).language == "nl"
    friday = campaign(local, module["id"], "Friday")
    assert owner_seat(storage, friday["id"]).language == "nl"
    assert local.put("/api/preferences", json={"choices": DEFAULTS, "language": "de"}).status_code == 200
    assert {owner_seat(storage, c["id"]).language for c in (tuesday, friday)} == {"de"}


def test_the_image_style_is_stored_and_a_save_without_it_keeps_it(local, storage):
    woodcut_style = {"preset": "woodcut", "custom": ""}
    response = local.put("/api/preferences", json={"choices": DEFAULTS, "language": "en", "image_style": woodcut_style})
    assert response.status_code == 200 and response.json()["image_style"] == woodcut_style
    assert storage.settings.load()["image_style"] == woodcut_style
    assert local.put("/api/preferences", json={"choices": DEFAULTS, "language": "en"}).json()["image_style"] == woodcut_style
    assert local.put("/api/preferences", json={"language": "nl"}).json()["image_style"] == woodcut_style
    custom = {"preset": "custom", "custom": "ink and wash"}
    put = local.put("/api/preferences", json={"choices": DEFAULTS, "language": "en", "image_style": custom})
    assert local.get("/api/preferences").json()["image_style"] == custom == put.json()["image_style"]


def test_an_image_style_that_isnt_offered_is_refused(local, storage):
    bad = {"choices": DEFAULTS, "language": "en", "image_style": {"preset": "pixel art"}}
    response = local.put("/api/preferences", json=bad)
    assert response.status_code == 422
    assert [w["code"] for w in response.json()["coded_warnings"]] == ["image_style_not_offered"]
    assert storage.settings.load() == {}
