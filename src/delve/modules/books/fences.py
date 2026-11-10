"""Claude's answer without its fence, for every step of a conversion that reads one (the converter, the classifier).

A module of its own so that a step can read an answer without importing `convert`.
"""

from __future__ import annotations

import re

_FENCED = re.compile(r"\A```[\w-]*[ \t]*\n(.*?)\n?```\Z", re.DOTALL)
_FENCE_BLOCK = re.compile(r"^```([\w-]*)[ \t]*\n(.*?)\n?^```[ \t]*$", re.MULTILINE | re.DOTALL)
_ANSWER_FENCES = {"markdown", "md", "json"}


def _words(text: str) -> int:
    return len(re.findall(r"\w+", text))


def unfenced(reply: str) -> str:
    """The answer without its fence: a fenced whole, or the one fenced block of an answer with prose around it. The
    block must be marked as Markdown or JSON or outweigh the prose, so a text holding one code block keeps its prose.
    """
    reply = reply.strip()
    fenced = _FENCED.match(reply)
    if fenced:
        return fenced.group(1).strip()
    blocks = list(_FENCE_BLOCK.finditer(reply))
    if len(blocks) == 1:
        block = blocks[0]
        prose = reply[: block.start()] + reply[block.end() :]
        if block.group(1).lower() in _ANSWER_FENCES or _words(prose) < _words(block.group(2)):
            return block.group(2).strip()
    return reply
