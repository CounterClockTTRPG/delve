"""SRD 3.5's rules text: the Markdown files of `rules/`, one per section of the SRD's basic rules, each with its
`title`, `source` (the SRD file it comes from) and `section` (that file's chapter). `search` and `section` answer as
the other rulesets' rules lookups do (`RulesetReference.rules_search` and `rules_section`). The book reads the files
whole (`sections`); the search reads each `###` subsection as a section of its own (`indexed`)."""

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
    """One section a rules file, its body whole: what the book reads."""
    folder = resources.files("delve_srd35").joinpath("rules")
    found = []
    for number, path in enumerate(sorted(p for p in folder.iterdir() if p.name.endswith(".md")), start=1):
        fields, body = _front(path.read_text("utf-8"))
        slug = path.name.removesuffix(".md")
        found.append(
            Section(number, slug, fields.get("title", slug), fields.get("source", ""), fields.get("section", ""), body)
        )
    return tuple(found)


_SUBHEADING = re.compile(r"^### +(.+?)\s*$", re.MULTILINE)
STEM = 6
"""A query word longer than this matches by its first `STEM` letters ("consciousness" finds "conscious")."""


@cache
def indexed() -> tuple[Section, ...]:
    """What the search reads (DEL-447), in the book's order: each rules file's text before its first `###`
    subheading, as the file's own section (when it has any), then each `###` subsection as a section titled
    "<file title> — <subheading>", its `####` ones in its body. The files' sections keep their ids; the subsections
    are numbered after them."""
    found: list[Section] = []
    next_id = len(sections()) + 1
    for s in sections():
        intro, *rest = _SUBHEADING.split(s.body)
        if intro.strip() or not rest:
            found.append(Section(s.id, s.slug, s.title, s.source, s.chapter, intro.strip()))
        for heading, body in zip(rest[::2], rest[1::2], strict=True):
            found.append(Section(next_id, s.slug, f"{s.title} — {heading}", s.source, s.chapter, body.strip()))
            next_id += 1
    return tuple(found)


def _words(query: str) -> list[str]:
    """The query's words to look for: not a stopword nor a number, and one longer than `STEM` letters cut to them."""
    words = (w for w in re.findall(r"[a-z0-9]+", query.lower()) if w not in _STOP and not w.isdigit())
    return list(dict.fromkeys(w[:STEM] for w in words))


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


def _named(heading: str, query: str) -> int:
    """How many words the heading has when the query says it whole, its words in order ("recovering with help
    stable …" names "Recovering with Help", 3, and "Stable", 1, not "Recovering without Help"); else 0."""
    said = re.findall(r"[a-z0-9]+", heading.lower())
    named = said and f" {' '.join(said)} " in " " + " ".join(re.findall(r"[a-z0-9]+", query.lower())) + " "
    return len(said) if named else 0


def search(query: str, source: str = "", limit: int = 5) -> list[dict]:
    """The sections and subsections (`indexed`) whose title or text hold the query's words (`_words`), best first:
    one whose own heading the query names whole, the longer heading first (`_named`), then by how many of the words
    each holds, then by how often (a word in the title counts thrice), then in the book's order; with a snippet.
    Raises `ValueError` for a query with no words, as a full-text search would."""
    words = _words(query)
    if not words:
        raise ValueError(f"no words to search for in {query!r}")
    scored = []
    for place, s in enumerate(indexed()):
        if source and s.source != source:
            continue
        title, body = s.title.lower(), s.body.lower()
        counts = [3 * len(re.findall(rf"\b{re.escape(w)}", title)) + len(re.findall(rf"\b{re.escape(w)}", body))
                  for w in words]  # fmt: skip
        if any(counts):
            named = _named(s.title.rpartition(" — ")[2], query)
            scored.append((named, sum(1 for n in counts if n), sum(counts), place, s))
    scored.sort(key=lambda found: (-found[0], -found[1], -found[2], found[3]))
    return [{**_row(s), "snippet": _snippet(s.body, words)} for *_, s in scored[: min(limit, SEARCH_LIMIT)]]


def section(source: str, title: str) -> list[dict]:
    """The sections of `source` (all sources when it is empty) whose title holds `title`, the exact title first; with
    none, the subsections (`indexed`), so a title the search gave ("Injury and Death — Recovering with Help") is
    found."""
    wanted = title.strip().lower()
    found = [s for s in sections() if (not source or s.source == source) and wanted in s.title.lower()]
    if not found:
        found = [s for s in indexed() if (not source or s.source == source) and wanted in s.title.lower()]
    found.sort(key=lambda s: (s.title.lower() != wanted, s.id))
    return [{**_row(s), "body": s.body} for s in found[:10]]
