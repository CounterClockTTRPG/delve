from dataclasses import replace

from delve.domain.backends import ModelInfo, ProviderCapabilities
from delve.domain.settings import BackendChoice, Effort, Job, Settings, Unusable, resolve

FAKE = ProviderCapabilities(
    id="fake",
    title="Fake",
    jobs=frozenset({Job.DM, Job.SIDE}),
    models=("fake-large", "fake-small"),
    efforts=(Effort.AUTO, Effort.LOW, Effort.HIGH),
    default_model="fake-large",
)
PICS = ProviderCapabilities(id="pics", title="Pictures", jobs=frozenset({Job.IMAGE_PORTRAIT, Job.IMAGE_SCENE}))
AVAILABLE = [FAKE, PICS]
DEFAULTS = {
    Job.DM: BackendChoice("fake", "fake-large", Effort.AUTO),
    Job.SIDE: BackendChoice("fake", "fake-large", Effort.AUTO),
    Job.IMAGE_PORTRAIT: BackendChoice("pics"),
    Job.IMAGE_SCENE: BackendChoice("pics"),
}


def only_warning_names(warnings: list[str], name: str) -> str:
    assert len(warnings) == 1, warnings
    assert warnings[0].startswith(f"{name}: "), warnings
    return warnings[0]


def test_resolve_empty_gives_defaults_without_warnings():
    settings, warnings = resolve({}, AVAILABLE, DEFAULTS)
    assert settings == Settings(choices=DEFAULTS, language="en")
    assert warnings == []


def test_resolve_keeps_valid_choice():
    stored = {
        "choices": {
            "dm": {"provider": "fake", "model": "fake-small", "effort": "high"},
            "side": {"provider": "fake", "model": None, "effort": None},
        },
        "language": "nl",
    }
    settings, warnings = resolve(stored, AVAILABLE, DEFAULTS)
    assert settings.choices[Job.DM] == BackendChoice("fake", "fake-small", Effort.HIGH)
    assert settings.choices[Job.SIDE] == BackendChoice("fake")
    assert settings.choices[Job.IMAGE_PORTRAIT] == BackendChoice("pics")
    assert settings.language == "nl"
    assert warnings == []


def test_resolve_falls_back_on_unknown_provider():
    stored = {"choices": {"dm": {"provider": "gone", "model": "big"}}}
    settings, warnings = resolve(stored, AVAILABLE, DEFAULTS)
    assert settings.choices[Job.DM] == BackendChoice("fake", "fake-large", Effort.AUTO)
    assert "'gone'" in only_warning_names(warnings, "dm")


def test_resolve_falls_back_on_unoffered_model_and_effort():
    settings, warnings = resolve({"choices": {"dm": {"provider": "fake", "model": "x"}}}, AVAILABLE, DEFAULTS)
    assert settings.choices[Job.DM] == BackendChoice("fake", "fake-large", Effort.AUTO)
    assert only_warning_names(warnings, "dm") == "dm: model 'x' is not offered by 'fake'; using default"

    settings, warnings = resolve({"choices": {"side": {"provider": "fake", "effort": "max"}}}, AVAILABLE, DEFAULTS)
    assert settings.choices[Job.SIDE] == BackendChoice("fake", "fake-large", Effort.AUTO)
    assert "effort 'max'" in only_warning_names(warnings, "side")

    stored = {"choices": {"dm": {"provider": "fake", "model": "x", "effort": "turbo"}}}
    settings, warnings = resolve(stored, AVAILABLE, DEFAULTS)
    assert settings.choices[Job.DM] == BackendChoice("fake", "fake-large", Effort.AUTO)
    warning = only_warning_names(warnings, "dm")
    assert "model 'x'" in warning and "effort 'turbo'" in warning


def test_resolve_falls_back_when_provider_lacks_job():
    stored = {"choices": {"image.portrait": {"provider": "fake"}}}
    settings, warnings = resolve(stored, AVAILABLE, DEFAULTS)
    assert settings.choices[Job.IMAGE_PORTRAIT] == BackendChoice("pics")
    assert "'fake'" in only_warning_names(warnings, "image.portrait")


def test_resolve_ignores_unknown_job_with_warning():
    stored = {"choices": {"music": {"provider": "fake"}, "dm": {"provider": "fake", "model": "fake-small"}}}
    settings, warnings = resolve(stored, AVAILABLE, DEFAULTS)
    assert settings.choices[Job.DM] == BackendChoice("fake", "fake-small")
    assert set(settings.choices) == set(DEFAULTS)
    only_warning_names(warnings, "music")


def test_resolve_bad_language_becomes_en():
    settings, warnings = resolve({"language": "es"}, AVAILABLE, DEFAULTS)
    assert settings == Settings(choices=DEFAULTS, language="en")
    assert "'es'" in only_warning_names(warnings, "language")


def test_resolve_malformed_choices_never_raise():
    stored = {"choices": {"dm": "fake", "side": {"model": "fake-small"}, "image.scene": {"provider": 3}}}
    settings, warnings = resolve(stored, AVAILABLE, DEFAULTS)
    assert settings.choices == DEFAULTS
    assert sorted(w.split(":")[0] for w in warnings) == ["dm", "image.scene", "side"]

    settings, warnings = resolve({"choices": ["dm"], "language": None}, AVAILABLE, DEFAULTS)
    assert settings == Settings(choices=DEFAULTS, language="en")
    assert sorted(w.split(":")[0] for w in warnings) == ["choices", "language"]


def test_resolve_job_without_default_is_left_out():
    stored = {"choices": {"conversion": {"provider": "gone"}}}
    settings, warnings = resolve(stored, AVAILABLE, DEFAULTS)
    assert Job.CONVERSION not in settings.choices
    assert only_warning_names(warnings, "conversion").endswith("no default, left unset")


def test_resolve_gives_the_novel_job_its_default():
    from delve.dm.claude_cli.provider import CLAUDE_CLI_CAPABILITIES
    from delve.domain.settings import JOB_DEFAULTS

    settings, warnings = resolve({}, [CLAUDE_CLI_CAPABILITIES], JOB_DEFAULTS)
    assert settings.choices[Job.NOVEL] == BackendChoice("claude-cli", "sonnet", Effort.MEDIUM)
    assert Job.NOVEL.value == "novel"
    assert warnings == []


def test_thorough_conversion_defaults_to_opus_high():
    from delve.dm.claude_cli.provider import CLAUDE_CLI_CAPABILITIES
    from delve.domain.settings import JOB_DEFAULTS

    settings, warnings = resolve({}, [CLAUDE_CLI_CAPABILITIES], JOB_DEFAULTS)
    assert settings.choices[Job.CONVERSION_THOROUGH] == BackendChoice("claude-cli", "opus", Effort.HIGH)
    assert Job.CONVERSION_THOROUGH.value == "conversion.thorough"
    assert "opus" in CLAUDE_CLI_CAPABILITIES.models
    assert warnings == []


def test_thorough_conversion_only_on_claude_cli():
    from delve.dm.claude_cli.provider import CLAUDE_CLI_CAPABILITIES
    from delve.dm.fake import FAKE_DM_CAPABILITIES
    from delve.domain.settings import JOB_DEFAULTS

    assert Job.CONVERSION_THOROUGH in CLAUDE_CLI_CAPABILITIES.jobs
    assert Job.CONVERSION_THOROUGH not in FAKE_DM_CAPABILITIES.jobs
    codex = ProviderCapabilities(id="codex", title="Codex", jobs=frozenset({Job.CONVERSION}))
    stored = {"choices": {"conversion.thorough": {"provider": "codex"}}}
    settings, warnings = resolve(stored, [CLAUDE_CLI_CAPABILITIES, codex], JOB_DEFAULTS)
    assert settings.choices[Job.CONVERSION_THOROUGH] == JOB_DEFAULTS[Job.CONVERSION_THOROUGH]
    [warning] = warnings
    assert warning.code == "provider_wrong_job"
    assert warning.args == {"job": "conversion.thorough", "provider": "codex", "outcome": "default"}


# ----- live providers (portraits plan Task 4) -----

LIVE = ProviderCapabilities(
    id="assetgen",
    title="assetgen",
    jobs=frozenset({Job.IMAGE_SCENE}),
    models=("flux-schnell",),
    model_info={"flux-schnell": ModelInfo("FLUX schnell", "replicate", "~$0.003 / image", paid=True)},
    live=True,
)
DOWN = replace(LIVE, models=(), model_info={}, problem="assetgen isn't answering at http://localhost:8765")


def test_a_choice_of_a_live_provider_with_a_problem_is_kept_with_a_warning():
    stored = {"choices": {"image.scene": {"provider": "assetgen", "model": "flux-schnell"}}}
    settings, warnings = resolve(stored, [FAKE, PICS, DOWN], DEFAULTS)
    assert settings.choices[Job.IMAGE_SCENE] == BackendChoice("assetgen", "flux-schnell"), "kept, not replaced"
    assert warnings == ["image.scene: can't be used: assetgen isn't answering at http://localhost:8765"]
    assert all(isinstance(w, Unusable) for w in warnings), "a warning that doesn't refuse a save"


def test_a_model_gone_from_a_live_provider_is_kept_with_a_warning():
    stored = {"choices": {"image.scene": {"provider": "assetgen", "model": "sdxl-local", "effort": None}}}
    settings, warnings = resolve(stored, [FAKE, PICS, LIVE], DEFAULTS)
    assert settings.choices[Job.IMAGE_SCENE] == BackendChoice("assetgen", "sdxl-local")
    assert warnings == ["image.scene: can't be used: model 'sdxl-local' is not offered by 'assetgen'"]
    assert isinstance(warnings[0], Unusable)

    stored = {"choices": {"image.scene": {"provider": "assetgen", "model": "flux-schnell"}}}
    assert resolve(stored, [FAKE, PICS, LIVE], DEFAULTS) == (
        Settings({**DEFAULTS, Job.IMAGE_SCENE: BackendChoice("assetgen", "flux-schnell")}),
        [],
    ), "a model it offers is just kept"


def test_a_live_provider_that_is_gone_or_lacks_the_job_still_falls_back():
    stored = {"choices": {"image.scene": {"provider": "assetgen"}, "dm": {"provider": "assetgen"}}}
    settings, warnings = resolve(stored, [FAKE, PICS], DEFAULTS)
    assert settings.choices[Job.IMAGE_SCENE] == BackendChoice("pics")
    settings, warnings = resolve(stored, [FAKE, PICS, DOWN], DEFAULTS)
    assert settings.choices[Job.IMAGE_SCENE] == BackendChoice("assetgen")
    assert settings.choices[Job.DM] == DEFAULTS[Job.DM]
    assert not any(isinstance(w, Unusable) for w in warnings if w.startswith("dm:"))


def test_a_static_provider_without_a_model_still_falls_back():
    settings, warnings = resolve({"choices": {"dm": {"provider": "fake", "model": "x"}}}, AVAILABLE, DEFAULTS)
    assert settings.choices[Job.DM] == DEFAULTS[Job.DM]
    assert not isinstance(warnings[0], Unusable)


# ----- warning codes (open fixes Task 6) -----


def test_an_unavailable_provider_has_a_code_and_args_with_the_old_text():
    _, warnings = resolve({"choices": {"dm": {"provider": "gone", "model": "big"}}}, AVAILABLE, DEFAULTS)
    [warning] = warnings
    assert warning.code == "provider_unavailable"
    assert warning.args == {"job": "dm", "provider": "gone", "outcome": "default"}
    assert warning == "dm: provider 'gone' is not available; using default"
    assert warning.to_json() == {"code": "provider_unavailable", "args": warning.args, "text": str(warning)}


def test_every_warning_has_its_code():
    cases = [
        ({"choices": ["dm"]}, AVAILABLE, "choices_not_mapping", {}),
        ({"choices": {"music": {"provider": "fake"}}}, AVAILABLE, "unknown_job", {"job": "music"}),
        ({"choices": {"dm": "fake"}}, AVAILABLE, "no_provider", {"job": "dm", "outcome": "default"}),
        (
            {"choices": {"conversion": {"provider": "gone"}}},
            AVAILABLE,
            "provider_unavailable",
            {"job": "conversion", "provider": "gone", "outcome": "unset"},
        ),
        (
            {"choices": {"image.portrait": {"provider": "fake"}}},
            AVAILABLE,
            "provider_wrong_job",
            {"job": "image.portrait", "provider": "fake", "outcome": "default"},
        ),
        (
            {"choices": {"dm": {"provider": "fake", "model": "x"}}},
            AVAILABLE,
            "model_not_offered",
            {"job": "dm", "provider": "fake", "model": "x", "outcome": "default"},
        ),
        (
            {"choices": {"side": {"provider": "fake", "effort": "max"}}},
            AVAILABLE,
            "effort_not_offered",
            {"job": "side", "provider": "fake", "effort": "max", "outcome": "default"},
        ),
        (
            {"choices": {"dm": {"provider": "fake", "model": "x", "effort": "turbo"}}},
            AVAILABLE,
            "model_and_effort_not_offered",
            {"job": "dm", "provider": "fake", "model": "x", "effort": "turbo", "outcome": "default"},
        ),
        (
            {"choices": {"image.scene": {"provider": "assetgen", "model": "flux-schnell"}}},
            [FAKE, PICS, DOWN],
            "provider_problem",
            {"job": "image.scene", "provider": "assetgen", "problem": DOWN.problem, "outcome": "kept"},
        ),
        (
            {"choices": {"image.scene": {"provider": "assetgen", "model": "sdxl-local"}}},
            [FAKE, PICS, LIVE],
            "model_not_offered",
            {"job": "image.scene", "provider": "assetgen", "model": "sdxl-local", "outcome": "kept"},
        ),
        ({"language": "es"}, AVAILABLE, "language_not_offered", {"language": "es"}),
    ]
    for stored, available, code, args in cases:
        _, warnings = resolve(stored, available, DEFAULTS)
        assert [(w.code, w.args) for w in warnings] == [(code, args)], stored
        assert all(isinstance(value, str) for value in warnings[0].args.values())
