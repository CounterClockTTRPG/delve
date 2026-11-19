"""SRD 3.5's rules text: the Markdown files of `rules/`, one per section of the SRD's basic rules, each with its
`title`, `source` (the SRD file it comes from) and `section` (that file's chapter). `search` and `section` answer as
the other rulesets' rules lookups do (`RulesetReference.rules_search` and `rules_section`)."""

from __future__ import annotations

import re
from dataclasses import dataclass
from functools import cache
from importlib import resources

SEARCH_LIMIT = 20
_STOP = frozenset({"a", "an", "and", "or", "not", "the", "of", "to", "in", "on", "is", "it", "for", "with", "near"})


@dataclass(frozen=True)
class Section:
    id: int
    slug: str
    title: str
    source: str
    chapter: str
    body: str


def _front(text: str) -> tuple[dict[str, str], str]:
    if not text.startswith("---"):
        return {}, text
    _, head, body = text.split("---", 2)
    fields = {}
    for line in head.strip().splitlines():
        key, _, value = line.partition(":")
        fields[key.strip()] = value.strip().strip('"')
    return fields, body.strip()


@cache
def sections() -> tuple[Section, ...]:
    folder = resources.files("delve_srd35").joinpath("rules")
    found = []
    for number, path in enumerate(sorted(p for p in folder.iterdir() if p.name.endswith(".md")), start=1):
        fields, body = _front(path.read_text("utf-8"))
        slug = path.name.removesuffix(".md")
        found.append(
            Section(number, slug, fields.get("title", slug), fields.get("source", ""), fields.get("section", ""), body)
        )
    return tuple(found)


def _words(query: str) -> list[str]:
    return [w for w in re.findall(r"[a-z0-9]+", query.lower()) if w not in _STOP]


def _snippet(body: str, words: list[str], width: int = 220) -> str:
    flat = " ".join(body.split())
    sentences = re.split(r"(?<=[.!?])\s+", flat)
    hit = next((s for s in sentences if any(re.search(rf"\b{re.escape(w)}", s.lower()) for w in words)), sentences[0])
    text = hit if len(hit) <= width else hit[: width - 1].rsplit(" ", 1)[0] + " …"
    for word in words:
        text = re.sub(rf"\b({re.escape(word)}\w*)", r"<<\1>>", text, flags=re.IGNORECASE)
    return text


def _row(section: Section) -> dict:
    return {"id": section.id, "source": section.source, "label": section.chapter, "chapter": section.chapter,
            "section": section.title}  # fmt: skip


def search(query: str, source: str = "", limit: int = 5) -> list[dict]:
    """The sections whose title or text hold the query's words, best first (a word in the title counts thrice), with
    a snippet. Raises `ValueError` for a query with no words, as a full-text search would."""
    words = _words(query)
    if not words:
        raise ValueError(f"no words to search for in {query!r}")
    scored = []
    for s in sections():
        if source and s.source != source:
            continue
        title, body = s.title.lower(), s.body.lower()
        score = sum(3 * len(re.findall(rf"\b{re.escape(w)}", title)) + len(re.findall(rf"\b{re.escape(w)}", body))
                    for w in words)  # fmt: skip
        if score:
            scored.append((score, s))
    scored.sort(key=lambda pair: (-pair[0], pair[1].id))
    return [{**_row(s), "snippet": _snippet(s.body, words)} for _, s in scored[: min(limit, SEARCH_LIMIT)]]


def section(source: str, title: str) -> list[dict]:
    """The sections of `source` (all sources when it is empty) whose title holds `title`, the exact title first."""
    wanted = title.strip().lower()
    found = [s for s in sections() if (not source or s.source == source) and wanted in s.title.lower()]
    found.sort(key=lambda s: (s.title.lower() != wanted, s.id))
    return [{**_row(s), "body": s.body} for s in found[:10]]
