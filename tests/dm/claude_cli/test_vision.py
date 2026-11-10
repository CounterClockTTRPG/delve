"""The vision side call (plan 7 Task 6): a picture and a prompt to a stateless `claude -p` with no tools, as one
stream-json message on stdin, answered by the fake `claude`'s vision mode."""

import asyncio
import io
import os

import pytest
from PIL import Image

from delve.dm.claude_cli.argv import AUX_ARGS, vision_argv
from delve.dm.claude_cli.provider import MAX_VISION_BYTES, ClaudeCliError, ClaudeCliProvider, MemorySessions
from delve.dm.fake import FakeDM
from delve.domain.settings import BackendChoice, Effort
from delve.maps.vision import VISION_MAX_SIDE, fit_for_vision
from tests.dm.claude_cli.test_resident import run


def _png(width: int = 8, height: int = 6) -> bytes:
    out = io.BytesIO()
    Image.new("RGB", (width, height), (40, 120, 200)).save(out, "PNG")
    return out.getvalue()


def test_vision_argv_has_no_mcp_and_no_tools():
    argv = vision_argv(model=None, effort=None)
    assert argv == [
        "claude", "-p",
        "--input-format", "stream-json",
        "--output-format", "stream-json",
        "--verbose",
        "--model", "haiku",
        *AUX_ARGS,
    ]  # fmt: skip
    assert "--mcp-config" not in argv and "--allowedTools" not in argv
    assert vision_argv(model="sonnet", effort=None)[7:9] == ["--model", "sonnet"]
    assert vision_argv(model="default", effort=None)[7:9] == ["--model", "haiku"]
    assert vision_argv(model=None, effort=Effort.HIGH)[-2:] == ["--effort", "high"]
    assert vision_argv(model=None, effort=Effort.AUTO) == argv


def test_the_picture_reaches_claude_and_the_answer_comes_back(provider, claude, data_dir):
    claude.script([], vision=['{"1": "forest"}'])
    png = _png()

    answer = run(provider, lambda: provider.vision_call("Which terrain?", png, "image/png", BackendChoice("claude-cli")))

    assert answer == '{"1": "forest"}'
    assert claude.vision_calls() == [{"prompt": "Which terrain?", "media_type": "image/png", "size": len(png)}]
    (spawn,) = claude.spawns()
    assert spawn["argv"] == vision_argv(model=None, effort=None)[1:]
    assert not spawn["cwd"].startswith(str(data_dir))
    assert not os.path.exists(spawn["cwd"]), "the temp directory is removed afterwards"


def test_without_a_scripted_answer_the_fake_says_so(provider, claude):
    answer = run(provider, lambda: provider.vision_call("What is it?", _png(), "image/png", BackendChoice("claude-cli")))
    assert answer == "(fake vision answer)"


def test_a_vision_call_takes_no_side_answer(provider, claude):
    claude.script([], side=["A side answer."], vision=["A vision answer."])

    async def scenario():
        seen = await provider.vision_call("Look.", _png(), "image/png", BackendChoice("claude-cli"))
        said = await provider.side_call("Say.", BackendChoice("claude-cli"))
        return seen, said

    assert run(provider, scenario) == ("A vision answer.", "A side answer.")


def test_a_vision_call_fails_after_its_timeout(tmp_path, monkeypatch):
    bin_dir = tmp_path / "slow-bin"
    bin_dir.mkdir()
    slow = bin_dir / "claude"
    slow.write_text("#!/bin/sh\nsleep 30\n", encoding="utf-8")
    slow.chmod(0o755)
    monkeypatch.setenv("PATH", f"{bin_dir}{os.pathsep}{os.environ['PATH']}")
    provider = ClaudeCliProvider(tmp_path / "data", MemorySessions())

    with pytest.raises(ClaudeCliError, match=r"no answer within 0\.2 s"):
        asyncio.run(provider.vision_call("Look.", _png(), "image/png", BackendChoice("claude-cli"), timeout=0.2))


def test_a_vision_call_without_claude_fails(provider, claude, monkeypatch):
    monkeypatch.setenv("PATH", "/nonexistent")
    with pytest.raises(ClaudeCliError, match="not installed"):
        run(provider, lambda: provider.vision_call("Look.", _png(), "image/png", BackendChoice("claude-cli")))


def test_a_picture_too_big_is_refused_before_claude_runs(provider, claude):
    big = b"\x89PNG" + b"\0" * MAX_VISION_BYTES
    with pytest.raises(ClaudeCliError, match="too big"):
        run(provider, lambda: provider.vision_call("Look.", big, "image/png", BackendChoice("claude-cli")))
    assert claude.spawns() == []


def test_fake_dm_answers_vision_calls():
    png = _png()
    dm = FakeDM([], vision_answers={"Which terrain?": "forest"}, vision_handler=lambda p, i, m: f"{m} {len(i)}")
    choice = BackendChoice("fake", "fake-large")

    async def scenario():
        return (
            await dm.vision_call("Which terrain?", png, "image/png", choice),
            await dm.vision_call("Other?", png, "image/jpeg", choice, timeout=5.0),
            await FakeDM([]).vision_call("Echo?", png, "image/png", choice),
        )

    assert asyncio.run(scenario()) == ("forest", f"image/jpeg {len(png)}", "(fake vision answer to: Echo?)")
    assert dm.vision_prompts == ["Which terrain?", "Other?"]
    assert dm.vision_images == [("image/png", len(png)), ("image/jpeg", len(png))]
    assert dm.side_prompts == [], "a vision call is not a side call"


def test_fit_for_vision_shrinks_to_the_longer_side():
    big = Image.new("RGB", (4000, 1000), (10, 200, 30))
    data, media_type = fit_for_vision(big)
    assert media_type == "image/png"
    fitted = Image.open(io.BytesIO(data))
    assert fitted.format == "PNG"
    assert fitted.size == (VISION_MAX_SIDE, VISION_MAX_SIDE // 4)
    assert VISION_MAX_SIDE == 1568

    small = Image.new("P", (100, 50))
    data, _ = fit_for_vision(small)
    assert Image.open(io.BytesIO(data)).size == (100, 50), "a small picture keeps its size"
