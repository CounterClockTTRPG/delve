"""The `claude` command lines: the DM's isolated resident (ttrpg2 `_build_args`), the side calls (`_AUX_ARGS`) and
the vision calls."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

from delve.domain.settings import Effort

CLAUDE = "claude"

# The DM's only tools are Delve's, through the bridge named `delve` in the MCP config (spec §6.2).
ALLOWED_TOOLS = "mcp__delve__*"

# ttrpg2's side-call flags without its `--model haiku`, which `side_argv` sets from the side job's model. A one-shot
# call keeps no session (DEL-155): without `--no-session-persistence` each one left its transcript behind.
AUX_ARGS = [
    "--tools", "", "--strict-mcp-config", "--disable-slash-commands", "--setting-sources", "", "--no-session-persistence",
]  # fmt: skip
SIDE_MODEL = "haiku"
FALLBACK_MODEL = "sonnet"

# The model Preferences call "default" is the CLI's own: no `--model`.
DEFAULT_MODEL = "default"

# The system prompt files a campaign's DM directory keeps: the newest, which a resident may still be running on.
PROMPT_FILES_KEPT = 3


def build_argv(
    *,
    mcp_config: Path,
    model: str | None,
    effort: Effort | None,
    system_prompt: Path | None,
    resume: str | None,
    resident: bool,
) -> list[str]:
    """The DM's argv. `resident` reads beats as stream-json on stdin; otherwise the caller appends the prompt.

    ttrpg2's flags, isolated: only the MCP config's bridge (`--strict-mcp-config`), no built-in tools, no settings
    files and no slash commands. Without `--system-prompt-snapshot off`, a `--resume` replays the first system prompt
    and drops later addenda. `effort` is a resolved effort: `auto` is decided per beat before this. `system_prompt` is
    the addenda's file (`write_system_prompt`).
    """
    if effort is Effort.AUTO:
        raise ValueError("resolve the auto effort before building the argv")
    argv = [CLAUDE, "-p"]
    if resident:
        argv += ["--input-format", "stream-json"]
    argv += [
        "--output-format", "stream-json",
        "--include-partial-messages",
        "--verbose",
        "--mcp-config", str(mcp_config),
        "--strict-mcp-config",
        "--tools", "",
        "--allowedTools", ALLOWED_TOOLS,
        "--setting-sources", "",
        "--disable-slash-commands",
    ]  # fmt: skip
    # The CLI refuses a fallback that is the main model.
    if model != FALLBACK_MODEL:
        argv += ["--fallback-model", FALLBACK_MODEL]
    argv += ["--exclude-dynamic-system-prompt-sections", "--system-prompt-snapshot", "off"]
    if model and model != DEFAULT_MODEL:
        argv += ["--model", model]
    if effort is not None:
        argv += ["--effort", str(effort)]
    if system_prompt is not None:
        argv += ["--append-system-prompt-file", str(system_prompt)]
    if resume:
        argv += ["--resume", resume]
    return argv


def side_argv(*, model: str | None, effort: Effort | None = None) -> list[str]:
    """A one-shot call with no tools and no MCP, on the small model unless the side job names another.

    The prompt isn't in it: the caller writes it to stdin, which `claude -p` reads when it has no prompt argument.
    Linux caps one argument at 128 KB, and a conversion's prompt can carry a whole chapter.
    """
    chosen = model if model and model != DEFAULT_MODEL else SIDE_MODEL
    argv = [CLAUDE, "-p", "--model", chosen, *AUX_ARGS]
    if effort is not None and effort is not Effort.AUTO:
        argv += ["--effort", str(effort)]
    return argv


def vision_argv(*, model: str | None, effort: Effort | None) -> list[str]:
    """A one-shot call with a picture: `side_argv`'s model and flags, reading one stream-json message on stdin (the
    picture as a base64 block, then the prompt) and answering in stream-json. No tools and no MCP, as a side call."""
    chosen = model if model and model != DEFAULT_MODEL else SIDE_MODEL
    argv = [
        CLAUDE, "-p",
        "--input-format", "stream-json",
        "--output-format", "stream-json",
        "--verbose",
        "--model", chosen,
        *AUX_ARGS,
    ]  # fmt: skip
    if effort is not None and effort is not Effort.AUTO:
        argv += ["--effort", str(effort)]
    return argv


def write_mcp_config(path: Path, *, command: list[str], url: str, campaign_id: str, secret: str) -> Path:
    """Write the MCP config of one campaign's DM: one server, `delve`, that runs `delve dm-bridge`.

    The bridge secret is in the server's env, so the file is the owner's only (0600) and the secret never shows in
    a process list.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    server = {
        "type": "stdio",
        "command": command[0],
        "args": [*command[1:], "dm-bridge", "--url", url, "--campaign", campaign_id],
        "env": {"DELVE_BRIDGE_SECRET": secret},
    }
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        json.dump({"mcpServers": {"delve": server}}, fh, indent=2)
    path.chmod(0o600)
    return path


def write_system_prompt(directory: Path, addenda: list[str]) -> Path | None:
    """Write the DM's system prompt addenda to a file for `--append-system-prompt-file`; None without any.

    Not an argument: Linux caps one argument at 128 KB, and a five-PC party with house rules came within 1.5 KB of it,
    so one more rule would have stopped the DM for good (DEL-160). The file is named by what it says, so a changed
    prompt is a changed argv and a fresh resident (`Resident.matches`), and the same prompt keeps its file. The newest
    few stay; the owner's only (0600), as the MCP config.
    """
    if not addenda:
        return None
    text = "\n\n".join(addenda)
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"system-prompt-{digest}.md"
    if path.exists():
        path.touch()
    else:
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(text)
    older = sorted(directory.glob("system-prompt-*.md"), key=lambda p: p.stat().st_mtime, reverse=True)
    for old in older[PROMPT_FILES_KEPT:]:
        old.unlink(missing_ok=True)
    return path
