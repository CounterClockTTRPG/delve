"""The reader's rulebook (rulesets spec, decisions 3, 6 and 9): a ruleset's book as one reader may see it.

- **Monsters are for organisers.** For anyone else the monsters section doesn't exist: not in the sections, and its
  facets, rows, entries and table raise `KeyError`, as an unknown section does; the search finds none.
- **The campaign's homebrew sits beside the book's.** Its item rules join Items, its class rules Classes, and its race
  rules make a Races section (there are no book races). They come first on the page that holds them, as
  `hr-<rule id>`, and are left out by any filter but the name.
- **A house rule's DM notes never reach a reader without the organiser role** (`cut_dm_notes`, on CommonMark's
  headings, with a fail-closed backstop).
"""

from __future__ import annotations

import re
from bisect import bisect_right
from dataclasses import replace
from itertools import accumulate

from markdown_it import MarkdownIt
from markdown_it.token import Token

from delve.domain.house_rules import HouseRule
from delve.domain.reference import Entry, Facet, RowsPage, Section
from delve.play.house_rules import effective_rules
from delve.rules.classic.rulebook import Rulebook, rank
from delve.storage.interfaces import Storage

MONSTERS = "monsters"
HOUSE_RULE_PREFIX = "hr-"
# The house rules' kinds, by the section they join; Races follows Classes.
SECTION_OF_KIND = {"item": "items", "class": "classes", "race": "races"}
SEARCH_POOL = 200
"""How many of the book's names a reader's search reads, so that the monsters it leaves out crowd no one out."""

_MARKDOWN = MarkdownIt("commonmark").enable("table")
_LINES = re.compile(r"[^\r\n]*(?:\r\n|\r|\n)|[^\r\n]+$")
_APOSTROPHES = re.compile(r"['\u2019]")
_PUNCTUATION = re.compile(r"[\W_]+")
DM_NOTES = (["dm", "notes"], ["dms", "notes"])
# The backstop: the words anywhere in what the headings left.
_DM_NOTES_ANYWHERE = re.compile(r"\bdm(?:['\u2019]?s)?[\W_]+notes\b", re.IGNORECASE)


def _plain(token: Token) -> str:
    """An inline token's text as a reader sees it: its text, its code and its links' and images' words."""
    parts = []
    for child in token.children or []:
        if child.type in ("text", "code_inline"):
            parts.append(child.content)
        elif child.type in ("softbreak", "hardbreak"):
            parts.append(" ")
        elif child.children:
            parts.append(_plain(child))
    return "".join(parts)


def _is_dm_notes(text: str) -> bool:
    """Whether a heading's words start with "DM Notes" (or "DM's Notes"), ignoring case and punctuation."""
    words = _PUNCTUATION.sub(" ", _APOSTROPHES.sub("", text.lower())).split()
    return any(words[: len(start)] == start for start in DM_NOTES)


def _dm_notes_spans(markdown: str, lines: int) -> list[tuple[int, int]]:
    """The DM notes' line spans as CommonMark parses them: each from its heading to the next heading of the same or a
    higher level in the same container (a blockquote, a list item), or to the end of that container."""
    headings: list[tuple[int, int, int, int, str]] = []  # (start, level, its container's id, its end, text)
    containers: list[Token] = []
    tokens = _MARKDOWN.parse(markdown)
    for index, token in enumerate(tokens):
        if token.type == "heading_open" and token.map:
            container = containers[-1] if containers else None
            end = container.map[1] if container is not None and container.map else lines
            text = _plain(tokens[index + 1]) if index + 1 < len(tokens) else ""
            headings.append((token.map[0], int(token.tag[1:]), id(container), end, text))
        if token.nesting == 1:
            containers.append(token)
        elif token.nesting == -1 and containers:
            containers.pop()
    spans = []
    for position, (start, level, container, end, text) in enumerate(headings):
        if not _is_dm_notes(text):
            continue
        following = (s for s, lvl, c, _, _ in headings[position + 1 :] if c == container and lvl <= level)
        spans.append((start, min(next(following, end), end)))
    return spans


def cut_dm_notes(markdown: str) -> str:
    """The rule without its DM notes: every heading CommonMark renders whose words start with "DM Notes" or "DM's
    Notes" (any case, any punctuation, any level, in any container) goes with its body (`_dm_notes_spans`). Fail
    closed: if the words still appear in what is left, it is cut from their line to the end. A rule without them
    comes back unchanged."""
    lines = _LINES.findall(markdown)
    cut = [False] * len(lines)
    for start, end in _dm_notes_spans(markdown, len(lines)):
        cut[start:end] = [True] * (end - start)
    kept = [line for line, gone in zip(lines, cut, strict=True) if not gone]
    left = _DM_NOTES_ANYWHERE.search("".join(kept))
    if left is not None:
        starts = list(accumulate((len(line) for line in kept), initial=0))
        kept = kept[: bisect_right(starts, left.start()) - 1]
    elif not any(cut):
        return markdown
    if left is not None or cut[-1]:  # cut to the end: no blank lines left trailing
        while kept and not kept[-1].strip():
            kept.pop()
    return "".join(kept)


class RulebookView:
    """A rulebook as one reader sees it, with the same methods as the ruleset's `Rulebook`."""

    def __init__(self, rulebook: Rulebook, *, organiser: bool, rules: list[HouseRule]) -> None:
        self.rulebook = rulebook
        self.organiser = organiser
        self.rules = [rule for rule in rules if rule.kind in SECTION_OF_KIND]

    def columns(self, section: str) -> tuple[str, ...]:
        return self.rulebook.columns(section)

    def sections(self) -> list[Section]:
        sections = []
        for section in self.rulebook.sections():
            if section.key == MONSTERS and not self.organiser:
                continue
            sections.append(replace(section, count=section.count + len(self._rules_of(section.key))))
            if section.key == "classes" and self._rules_of("races"):
                sections.append(Section("races", "list", len(self._rules_of("races"))))
        return sections

    def facets(self, section: str) -> list[Facet]:
        if self._races(section):
            return []
        return self.rulebook.facets(self._gate(section))

    def rows(self, section: str, filters: dict[str, str], offset: int, limit: int) -> RowsPage:
        offset, limit = max(0, int(offset)), max(0, int(limit))
        filters = {key: str(value).strip() for key, value in filters.items()}
        rules = self._matching(section, filters)
        if self._races(section):
            return RowsPage([self._row(section, rule) for rule in rules[offset : offset + limit]], len(rules), offset)
        own = rules[offset : offset + limit]
        book = self.rulebook.rows(self._gate(section), filters, max(0, offset - len(rules)), limit - len(own))
        return RowsPage([*(self._row(section, rule) for rule in own), *book.rows], len(rules) + book.total, offset)

    def entry(self, section: str, id: str) -> Entry | None:
        races = self._races(section)
        if not races:
            self._gate(section)
        if id.startswith(HOUSE_RULE_PREFIX):
            rule = next((r for r in self._rules_of(section) if HOUSE_RULE_PREFIX + r.id == id), None)
            if rule is None:
                return None
            text = rule.body_md if self.organiser else cut_dm_notes(rule.body_md)
            return Entry(section, id, rule.title, {}, text, None, house_rule=True)
        return None if races else self.rulebook.entry(section, id)

    def table(self, section: str) -> list[dict]:
        return self.rulebook.table(self._gate(section))

    def search(self, q: str, limit: int) -> list[tuple[str, str, str]]:
        """Entries whose name contains `q`, the house rules' among the book's, in the store's order."""
        text = (q or "").strip()
        if not text or limit <= 0:
            return []
        hits = self.rulebook.search(text, limit if self.organiser else SEARCH_POOL)
        if not self.organiser:
            hits = [hit for hit in hits if hit[0] != MONSTERS]
            # The book's own sections, by name, in case the monsters filled the pool.
            for section in ("spells", "items", "classes"):
                hits += [
                    (section, row["id"], row["name"]) for row in self.rulebook.rows(section, {"q": text}, 0, limit).rows
                ]
        hits += [
            (SECTION_OF_KIND[rule.kind], HOUSE_RULE_PREFIX + rule.id, rule.title)
            for rule in self.rules
            if text.lower() in rule.title.lower()
        ]
        return sorted(dict.fromkeys(hits), key=lambda hit: rank(text, hit))[:limit]

    # The gate and the house rules.

    def _gate(self, section: str) -> str:
        if section == MONSTERS and not self.organiser:
            raise KeyError(section)
        return section

    def _races(self, section: str) -> bool:
        """Whether this is the Races section, which only the house rules make; `KeyError` when they make none."""
        if section != "races":
            return False
        if not self._rules_of(section):
            raise KeyError(section)
        return True

    def _rules_of(self, section: str) -> list[HouseRule]:
        rules = [rule for rule in self.rules if SECTION_OF_KIND[rule.kind] == section]
        return sorted(rules, key=lambda rule: (rule.title.lower(), rule.id))

    def _matching(self, section: str, filters: dict[str, str]) -> list[HouseRule]:
        """The section's house rules that the filters let through: only a name filter, matching part of the title."""
        if any(value for key, value in filters.items() if key != "q"):
            return []
        q = filters.get("q", "").lower()
        return [rule for rule in self._rules_of(section) if q in rule.title.lower()]

    def _row(self, section: str, rule: HouseRule) -> dict:
        columns = dict.fromkeys(self.rulebook.columns(section), "")
        return {"id": HOUSE_RULE_PREFIX + rule.id, "name": rule.title, **columns, "house_rule": True}


def view_for(
    rulebook: Rulebook, ruleset_id: str, storage: Storage | None, campaign_id: str | None, organiser: bool
) -> RulebookView:
    """The rulebook for this reader: with the campaign's effective item, class and race rules that fit the ruleset
    (none without a campaign). An unknown campaign is `NotFound`."""
    rules = []
    if storage is not None and campaign_id is not None:
        rules = [
            rule
            for rule in effective_rules(storage, campaign_id)
            if rule.kind in SECTION_OF_KIND and rule.ruleset in (None, ruleset_id)
        ]
    return RulebookView(rulebook, organiser=organiser, rules=rules)
