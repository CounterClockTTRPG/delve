import asyncio
import os
from pathlib import Path

import pytest

from delve.config import Config
from delve.dm.claude_cli.argv import AUX_ARGS
from delve.dm.claude_cli.effort import TurnContext
from delve.dm.claude_cli.provider import (
    CLAUDE_CLI_CAPABILITIES,
    HANDOVER_PROMPT,
    REHYDRATE_ADDENDUM,
    SIDE_TIMEOUT,
    ClaudeCliError,
    ClaudeCliProvider,
    MemorySessions,
)
from delve.dm.provider import DMError, TurnEnd, Usage
from delve.domain.settings import BackendChoice, Effort, Job
from tests.dm.claude_cli.test_resident import collect, run, spec, text_of

LOCAL = ("127.0.0.1", 50000)


def test_capabilities():
    caps = CLAUDE_CLI_CAPABILITIES
    assert caps.id == "claude-cli"
    assert caps.jobs == frozenset({Job.DM, Job.SIDE, Job.TRANSLATION, Job.CONVERSION, Job.CONVERSION_THOROUGH, Job.NOVEL})
    assert caps.models == ("opus", "sonnet", "haiku")
    assert caps.efforts == (Effort.AUTO, Effort.LOW, Effort.MEDIUM, Effort.HIGH, Effort.MAX)
    assert caps.default_model is None, "no model: the CLI's own, which Preferences call Provider default"
    assert set(caps.model_info) == set(caps.models)
    assert [caps.model_info[m].label for m in caps.models] == ["Opus (most capable)", "Sonnet", "Haiku (fastest)"]


def test_open_resumes_the_stored_session(provider, claude, sessions):
    sessions.set("cmp_1", "claude-cli", "sess-earlier", 1000)
    sessions.set("cmp_2", "fake", "fake-3", 0)
    claude.script([[{"text": "Welcome back."}], [{"text": "Hello."}]])

    async def scenario():
        resumed = await provider.open(spec())
        assert resumed.id == "sess-earlier"
        await collect(resumed, "Where were we?")
        other = await provider.open(spec(campaign_id="cmp_2"))
        assert other.id == "", "another provider's conversation is not resumed"
        await collect(other, "Hi.")

    run(provider, scenario)
    first, second = claude.spawns()
    assert first["argv"][first["argv"].index("--resume") + 1] == "sess-earlier"
    assert "--resume" not in second["argv"]


def test_auto_effort_changes_only_when_a_fight_starts_or_ends(claude, data_dir, sessions):
    # Another effort is another claude process, which reads the whole prompt cache again (a dollar a beat in play):
    # auto keeps the effort the conversation has until a fight starts (high) or ends (decided afresh).
    context = {"in_combat": False}
    provider = ClaudeCliProvider(data_dir, sessions, turn_context=lambda campaign_id: TurnContext(**context))
    claude.script([[{"text": t}] for t in "abcdef"])

    async def scenario():
        conversation = await provider.open(spec(Effort.AUTO))
        await collect(conversation, "I look around.")  # low
        await collect(conversation, "I cast sleep on them.")  # a marker word, but no fight: still low
        await collect(conversation, "I wait.")  # still low: no process was started for the spell
        context["in_combat"] = True
        await collect(conversation, "I swing.")  # the fight starts: high
        await collect(conversation, "I swing again.")  # still high
        context["in_combat"] = False
        await collect(conversation, "We loot the bodies.")  # the fight ended: decided afresh, low

    run(provider, scenario)
    efforts = [spawn["argv"][spawn["argv"].index("--effort") + 1] for spawn in claude.spawns()]
    assert efforts == ["low", "high", "low"]


def test_reset_at_safe_boundary_rehydrates(claude, data_dir, sessions, monkeypatch):
    monkeypatch.setenv("DELVE_DM_RESET_TOKENS", "200000")
    context = {"in_combat": False}
    provider = ClaudeCliProvider(data_dir, sessions, turn_context=lambda campaign_id: TurnContext(**context))
    big = {"input_tokens": 50, "cache_read_input_tokens": 240000, "cache_creation_input_tokens": 1000}
    claude.script([
        {"steps": [{"text": "A long fight begins."}], "usage": big},
        {"steps": [{"text": "Swing and hit."}], "usage": big},
        {"steps": [{"text": "- Mira owes the party 20 gp."}], "result": "- Mira owes the party 20 gp."},
        {"steps": [{"text": "The dust settles."}]},
        {"steps": [{"text": "You walk on."}]},
    ])  # fmt: skip

    async def scenario():
        conversation = await provider.open(spec(Effort.LOW))
        await collect(conversation, "We attack.")
        old = conversation.id
        context["in_combat"] = True
        await collect(conversation, "I swing.")  # past the threshold, but mid-fight: no reset
        assert conversation.id == old
        context["in_combat"] = False
        after_fight = await collect(conversation, "We loot the bodies.")
        new = conversation.id
        later = await collect(conversation, "We walk on.")
        return old, new, after_fight, later

    old, new, after_fight, later = run(provider, scenario)

    # The player sees no break: no handover text, the beat answers as usual.
    assert text_of(after_fight) == "The dust settles."
    assert after_fight[-1] == TurnEnd("done")
    assert text_of(later) == "You walk on."
    assert new != old

    inputs = [entry["text"] for entry in claude.inputs()]
    assert inputs == ["We attack.", "I swing.", HANDOVER_PROMPT, "We loot the bodies.", "We walk on."]

    first, rehydrated, resumed = claude.spawns()
    assert first["pid"] != rehydrated["pid"]
    assert "--resume" not in rehydrated["argv"], "the fresh conversation starts without the old one"
    prompt = Path(rehydrated["argv"][rehydrated["argv"].index("--append-system-prompt-file") + 1]).read_text()
    assert prompt.startswith("You are the DM.")
    assert REHYDRATE_ADDENDUM in prompt and "session_primer" in prompt
    assert "Mira owes the party 20 gp." in prompt
    # The beat after that resumes the new conversation, and the rehydrate note is gone.
    assert resumed["argv"][resumed["argv"].index("--resume") + 1] == new
    resumed_prompt = Path(resumed["argv"][resumed["argv"].index("--append-system-prompt-file") + 1]).read_text()
    assert resumed_prompt == "You are the DM."
    assert sessions.get("cmp_1")["session_id"] == new


def test_reset_command_starts_fresh(provider, claude, sessions):
    claude.script([[{"text": "a"}], [{"text": "b"}]])

    async def scenario():
        conversation = await provider.open(spec())
        await collect(conversation, "One.")
        await provider.reset("cmp_1")
        assert sessions.get("cmp_1") is None
        await collect(await provider.open(spec()), "Two.")

    run(provider, scenario)
    assert len(claude.spawns()) == 2
    assert "--resume" not in claude.spawns()[1]["argv"]


def test_side_call_uses_aux_args(provider, claude, data_dir):
    claude.script([], side=["Bonjour.", "Second."])

    async def scenario():
        first = await provider.side_call("Translate: hello", BackendChoice("claude-cli", None, None))
        second = await provider.side_call("Again", BackendChoice("claude-cli", "sonnet", Effort.LOW))
        return first, second

    assert run(provider, scenario) == ("Bonjour.", "Second.")
    first, second = claude.spawns()
    assert first["argv"] == ["-p", "--model", "haiku", *AUX_ARGS]
    assert second["argv"] == ["-p", "--model", "sonnet", *AUX_ARGS, "--effort", "low"]
    assert [entry["text"] for entry in claude.inputs()] == ["Translate: hello", "Again"], "the prompts come on stdin"
    for spawn in (first, second):
        assert "--mcp-config" not in spawn["argv"]
        assert not spawn["cwd"].startswith(str(data_dir))
        assert not os.path.exists(spawn["cwd"]), "the temp directory is removed afterwards"


def test_a_beats_cost_is_its_own_not_the_processs_sum(provider, claude):
    """P-e: the fake's `cost` is the process's `total_cost_usd`, which adds up; each beat reports its own rise, and a
    new process starts from nothing."""
    claude.script([{"steps": [{"text": "a"}], "cost": 0.10}, {"steps": [{"text": "b"}], "cost": 0.25},
                   {"steps": [{"text": "c"}], "cost": 0.05}])  # fmt: skip

    async def scenario():
        conversation = await provider.open(spec())
        costs = []
        for text in ("One.", "Two."):
            costs += [e.cost_usd for e in await collect(conversation, text) if isinstance(e, Usage)]
        await provider.reset("cmp_1")
        restarted = await provider.open(spec())
        costs += [e.cost_usd for e in await collect(restarted, "Three.") if isinstance(e, Usage)]
        return costs

    assert run(provider, scenario) == [pytest.approx(0.10), pytest.approx(0.15), pytest.approx(0.05)]
    assert len(claude.spawns()) == 2


def test_side_and_vision_calls_report_their_usage(provider, claude):
    """With `on_usage`, a side call asks for JSON and reports the `result`'s usage and cost; without it, its argv is
    unchanged (`test_side_call_uses_aux_args`)."""
    claude.script([], side=["Bonjour."], vision=["A map."], side_cost=0.01)
    heard: list[Usage] = []

    async def scenario():
        answer = await provider.side_call("Translate: hello", BackendChoice("claude-cli"), on_usage=heard.append)
        seen = await provider.vision_call("Look.", b"\x89PNG", "image/png", BackendChoice("claude-cli"),
                                          on_usage=heard.append)  # fmt: skip
        return answer, seen

    assert run(provider, scenario) == ("Bonjour.", "A map.")
    side, vision = claude.spawns()
    assert side["argv"] == ["-p", "--model", "haiku", *AUX_ARGS, "--output-format", "json"]
    assert "--output-format" in vision["argv"]
    assert heard == [Usage(1200, 40, 0.01), Usage(1600, 20, 0.0)]


def test_a_long_side_prompt_reaches_claude_intact(provider, claude):
    """A prompt over Linux's 128 KB cap on one argument (a book's chapter) goes on stdin, so it fits."""
    claude.script([], side=["Read."])
    prompt = "".join(f"Room {n}: a damp cell, ünïcode ✓.\n" for n in range(6000))
    assert len(prompt.encode("utf-8")) > 200_000

    assert run(provider, lambda: provider.side_call(prompt, BackendChoice("claude-cli"))) == "Read."
    (spawn,) = claude.spawns()
    assert prompt not in spawn["argv"]
    assert [entry["text"] for entry in claude.inputs()] == [prompt]


def test_side_call_failure_raises(provider, claude, monkeypatch):
    monkeypatch.setenv("PATH", "/nonexistent")
    with pytest.raises(ClaudeCliError, match="not installed"):
        run(provider, lambda: provider.side_call("Hi", BackendChoice("claude-cli")))


def test_side_call_waits_for_its_timeout(tmp_path, monkeypatch):
    """A side call gives up after `timeout` when it is given (a conversion's 600 s), else after `SIDE_TIMEOUT`."""
    bin_dir = tmp_path / "slow-bin"
    bin_dir.mkdir()
    slow = bin_dir / "claude"
    slow.write_text("#!/bin/sh\nsleep 30\n", encoding="utf-8")
    slow.chmod(0o755)
    monkeypatch.setenv("PATH", f"{bin_dir}{os.pathsep}{os.environ['PATH']}")
    provider = ClaudeCliProvider(tmp_path / "data", MemorySessions())

    with pytest.raises(ClaudeCliError, match=r"no answer within 0\.2 s"):
        asyncio.run(provider.side_call("Convert this.", BackendChoice("claude-cli"), timeout=0.2))
    assert SIDE_TIMEOUT == 90.0


def test_a_cancelled_side_call_stops_its_claude(tmp_path, monkeypatch):
    """A paused conversion cancels its other calls: their `claude` stops too, never running on to spend for nothing."""
    bin_dir = tmp_path / "slow-bin"
    bin_dir.mkdir()
    pid_file = tmp_path / "pid"
    slow = bin_dir / "claude"
    slow.write_text(f"#!/bin/sh\necho $$ > {pid_file}\nexec sleep 30\n", encoding="utf-8")
    slow.chmod(0o755)
    monkeypatch.setenv("PATH", f"{bin_dir}{os.pathsep}{os.environ['PATH']}")
    provider = ClaudeCliProvider(tmp_path / "data", MemorySessions())

    async def scenario():
        call = asyncio.create_task(provider.side_call("Convert this.", BackendChoice("claude-cli")))
        while not pid_file.exists() or not pid_file.read_text().strip():
            await asyncio.sleep(0.02)
        call.cancel()
        with pytest.raises(asyncio.CancelledError):
            await call

    asyncio.run(scenario())
    with pytest.raises(ProcessLookupError):
        os.kill(int(pid_file.read_text()), 0)


def test_a_failed_side_call_says_what_claude_said(tmp_path, monkeypatch):
    """The CLI writes why it stopped on stdout (the `result`, or the text), with stderr empty: the error carries it,
    not a blank "exit code 1"."""
    bin_dir = tmp_path / "failing-bin"
    bin_dir.mkdir()
    failing = bin_dir / "claude"
    result = '{"type":"result","subtype":"success","is_error":true,"result":"API Error: 529 Overloaded"}'
    failing.write_text(
        "#!/bin/sh\ncat >/dev/null\ncase \"$*\" in *json*) echo '" + result + "' ;; *) echo 'API Error: 500' ;; esac\n"
        "exit 1\n",
        encoding="utf-8",
    )
    failing.chmod(0o755)
    monkeypatch.setenv("PATH", f"{bin_dir}{os.pathsep}{os.environ['PATH']}")
    provider = ClaudeCliProvider(tmp_path / "data", MemorySessions())
    choice = BackendChoice("claude-cli")

    with pytest.raises(ClaudeCliError, match=r"^claude stopped \(exit code 1\): API Error: 529 Overloaded$"):
        asyncio.run(provider.side_call("Convert this.", choice, on_usage=lambda usage: None))
    with pytest.raises(ClaudeCliError, match=r"^claude stopped \(exit code 1\): API Error: 500$"):
        asyncio.run(provider.side_call("Convert this.", choice))


def test_missing_claude_marks_unavailable(tmp_path, monkeypatch, sessions):
    from fastapi.testclient import TestClient

    from delve.__main__ import build_registries
    from delve.storage import open_storage
    from delve.web.app import create_app

    monkeypatch.setenv("PATH", str(tmp_path / "empty"))
    config = Config(data_dir=tmp_path / "data")
    registries = build_registries(config=config)
    assert "claude-cli" not in [caps.id for caps in registries.dm.capabilities()]

    storage = open_storage(config)
    try:
        with TestClient(create_app(config, storage, registries), base_url="http://localhost:7810", client=LOCAL) as client:
            assert client.get("/api/health").json()["dm"] == "unavailable"
            # Settings refuse a stored choice of it with a clear warning.
            storage.settings.save({"choices": {"dm": {"provider": "claude-cli"}}})
            warnings = client.get("/api/preferences").json()["warnings"]
            assert any("'claude-cli' is not available" in warning for warning in warnings)
    finally:
        storage.close()

    # A send without claude ends the beat with an error, never a hang.
    provider = ClaudeCliProvider(tmp_path / "data", sessions)

    async def scenario():
        return await collect(await provider.open(spec()), "Hello?")

    events = run(provider, scenario)
    assert events == [DMError("claude is not installed (not found on PATH)", False, events[0].detail), TurnEnd("error")]


def test_claude_on_path_is_registered_first(claude, tmp_path):
    from fastapi.testclient import TestClient

    from delve.__main__ import build_registries
    from delve.storage import open_storage
    from delve.web.app import create_app

    config = Config(data_dir=tmp_path / "data")
    registries = build_registries(config=config)
    assert [caps.id for caps in registries.dm.capabilities()] == ["claude-cli", "fake"]
    provider = registries.dm.get("claude-cli")
    assert isinstance(provider, ClaudeCliProvider)
    assert provider.bridge_url == f"http://127.0.0.1:{config.port}"

    storage = open_storage(config)
    try:
        with TestClient(create_app(config, storage, registries), base_url="http://localhost:7810", client=LOCAL) as client:
            assert client.get("/api/health").json()["dm"] == "available"
            assert client.get("/api/preferences").json()["choices"]["dm"]["provider"] == "claude-cli"
    finally:
        storage.close()
    asyncio.run(provider.close())



def test_serve_wires_the_provider_to_storage_and_the_bridge(claude, tmp_path):
    from delve.__main__ import build_registries
    from delve.storage import open_storage
    from delve.web.app import create_app

    config = Config(data_dir=tmp_path / "data")
    storage = open_storage(config)
    try:
        registries = build_registries(config=config, storage=storage, bridge_secret="s3cret")
        app = create_app(config, storage, registries, bridge_secret="s3cret")
        provider = registries.dm.get("claude-cli")
        assert provider.sessions is storage.dm_sessions
        assert provider.bridge_secret == app.state.bridge_secret == "s3cret"
        module = storage.modules.create("M")
        campaign = storage.campaigns.create(
            "C", module.id, storage.revisions.snapshot(module.id).number, ruleset="osric", setting="greyhawk"
        )
        storage.characters.create(campaign.id, "Brother Anselm", kind="npc")
        assert provider.turn_context(campaign.id) == TurnContext(in_combat=False, npc_names=("Brother Anselm",))
    finally:
        storage.close()


def test_one_shot_calls_leave_nothing_behind(provider, claude, tmp_path, monkeypatch):
    """DEL-155: the CLI keeps a folder for every working directory, and each call has its own, so 513 temp folders and
    3009 `projects` folders had piled up. A call keeps no session, its temp dir is in its own directory, and its
    `projects` folder is removed when it ends."""
    config = tmp_path / "claude-config"
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(config))
    claude.script([], side=["Bonjour."], vision=["A map."])

    async def scenario():
        await provider.side_call("Translate: hello", BackendChoice("claude-cli"))
        await provider.vision_call("Look.", b"\x89PNG", "image/png", BackendChoice("claude-cli"))

    run(provider, scenario)
    for spawn in claude.spawns():
        assert "--no-session-persistence" in spawn["argv"]
        assert spawn["tmpdir"] == os.path.join(spawn["cwd"], "tmp"), "the CLI's temp dir goes with the call's own"
    assert list((config / "projects").iterdir()) == [], "the CLI's folder for the call is gone"


def test_too_long_a_command_line_isnt_retried(tmp_path, sessions, monkeypatch):
    """E2BIG fails the same way every time: the beat ends with an error Retry isn't offered for (DEL-160)."""
    import errno

    from delve.dm.claude_cli import provider as module

    async def too_long(*args, **kwargs):
        raise OSError(errno.E2BIG, "Argument list too long")

    monkeypatch.setattr(module.Resident, "spawn", too_long)
    provider = ClaudeCliProvider(tmp_path / "data", sessions)

    async def scenario():
        return await collect(await provider.open(spec()), "Hello?")

    events = run(provider, scenario)
    assert events == [DMError(module.TOO_LONG, False, events[0].detail), TurnEnd("error")]
