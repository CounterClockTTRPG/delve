"""A setting page's text (settings plan Task 4): its DM-only sections, the shipped wiki's markup as Delve Markdown, its
`[[…]]` links, and the snippets search shows. Pure: it imports nothing of Delve.

A DM-only section is the lines between a line that is `::: dm` and the next line that is `:::`; one left unclosed runs
to the end of the text."""

from __future__ import annotations

import re
from collections.abc import Sequence

DM_OPEN = "::: dm"
DM_CLOSE = ":::"

_BLANK_RUNS = re.compile(r"\n{3,}")
_LINK = re.compile(r"\[\[([^\[\]|]+)(?:\|[^\[\]]*)?\]\]")
_DROPPED_LINK = re.compile(
    r"\[\[\s*(?:file|image|category)\s*:[^\[\]]*(?:\[\[[^\[\]]*\]\][^\[\]]*)*\]\]", re.IGNORECASE
)
_REF = re.compile(r"<ref[^>/]*/>|<ref[^>]*>.*?</ref>", re.IGNORECASE | re.DOTALL)
_TAG = re.compile(r"</?[a-zA-Z][^<>]*>")
_COMMENT = re.compile(r"<!--.*?-->", re.DOTALL)
_HEADING = re.compile(r"^(={2,6})\s*(.*?)\s*\1\s*$", re.MULTILINE)
_BOLD = re.compile(r"'''(.+?)'''")
_ITALIC = re.compile(r"''(.+?)''")
_EXTERNAL = re.compile(r"(?<!\[)\[(?:https?:)?//[^\s\]]+\s+([^\]]+)\]|(?<!\[)\[(?:https?:)?//[^\s\]]+\]")


def player_text(text: str) -> str:
    """`text` without its DM-only sections, its runs of blank lines collapsed to one."""
    kept: list[str] = []
    in_dm = False
    for line in text.split("\n"):
        marker = line.strip()
        if in_dm:
            in_dm = marker != DM_CLOSE
        elif marker == DM_OPEN:
            in_dm = True
        else:
            kept.append(line)
    return _BLANK_RUNS.sub("\n\n", "\n".join(kept)).strip()


def dm_section(text: str) -> str:
    """`text` as one DM-only section."""
    return f"{DM_OPEN}\n{text.strip()}\n{DM_CLOSE}"


def _drop_templates(raw: str) -> str:
    """`raw` without its `{{…}}` templates, nested ones included; an unclosed one runs to the end."""
    out: list[str] = []
    depth = 0
    i = 0
    while i < len(raw):
        pair = raw[i : i + 2]
        if pair == "{{":
            depth += 1
            i += 2
        elif pair == "}}" and depth:
            depth -= 1
            i += 2
        else:
            if not depth:
                out.append(raw[i])
            i += 1
    return "".join(out)


def wiki_markdown(raw: str) -> str:
    """The shipped wiki's markup as Delve Markdown: templates (the infobox comes as the page's fields), files, images,
    categories, references, comments and HTML tags dropped; `==H==` as `## H`, one `#` more per level; `'''b'''` as
    `**b**`, `''i''` as `*i*`; `[url label]` as `label`. The `[[Target]]` and `[[Target|label]]` links stay."""
    text = _COMMENT.sub("", raw)
    text = _drop_templates(text)
    text = _DROPPED_LINK.sub("", text)
    text = _REF.sub("", text)
    text = _TAG.sub("", text)
    text = _EXTERNAL.sub(lambda m: m.group(1) or "", text)
    text = _HEADING.sub(lambda m: f"\n{'#' * len(m.group(1))} {m.group(2)}\n", text)
    text = _BOLD.sub(r"**\1**", text)
    text = _ITALIC.sub(r"*\1*", text)
    lines = [line.rstrip() for line in text.split("\n")]
    return _BLANK_RUNS.sub("\n\n", "\n".join(lines)).strip()


def snippet(text: str, words: Sequence[str], width: int = 120) -> str:
    """About `width` characters of `text` around the first of `words` found (ignoring case), on one line, each word
    found marked `<<…>>`, with an ellipsis where it was cut. The start of the text when no word is found."""
    flat = " ".join(text.split())
    patterns = [re.escape(word) for word in words if word]
    found = [m.start() for p in patterns if (m := re.search(p, flat, re.IGNORECASE))]
    first = min(found, default=0)
    start = max(0, first - width // 3)
    end = min(len(flat), start + width)
    start = max(0, min(start, end - width))
    excerpt = flat[start:end]
    if patterns:
        excerpt = re.sub(
            "|".join(sorted(patterns, key=len, reverse=True)),
            lambda m: f"<<{m.group(0)}>>",
            excerpt,
            flags=re.IGNORECASE,
        )
    return ("…" if start else "") + excerpt + ("…" if end < len(flat) else "")
