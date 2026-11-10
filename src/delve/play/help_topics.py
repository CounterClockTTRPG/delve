"""Delve's Help, for Ask the DM (DEL-221): the topics of the app's Help (`web/src/help/topics/*.md`, DEL-145), read
by the server so a question about the app ("How do I assign a seat to myself?") is answered with the app's own
steps, not as a rules question.

A topic file is a `---` header (`title`, `audience`, `summary`, …) and its Markdown. The side pass gets the list of
every topic, by title, audience and summary, and the `HELP_TOPICS` that match the question best, whole up to
`HELP_TOPIC_CHARS`, their pictures and HTML left out. In a wheel the topics are inside the package
(`delve/help/topics`); from the repository they are read where the web app keeps them.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from functools import cache
from pathlib import Path

import delve

_PACKAGED = Path(delve.__file__).resolve().parent / "help" / "topics"
_IN_REPO = Path(__file__).resolve().parents[3] / "web" / "src" / "help" / "topics"
TOPICS_DIR = _PACKAGED if _PACKAGED.is_dir() else _IN_REPO

HELP_TOPICS = 2
"""At most this many topics whole for a question."""
HELP_TOPIC_CHARS = 3000
"""At most this many characters of a topic."""

AUDIENCE = {"player": "players", "organiser": "hosts and organisers", "owner": "the install's owner"}
ROLE = {
    "host": "the table's host",
    "cohost": "a co-host of the table",
    "player": "a player at the table",
    "observer": "an observer, who watches and never acts",
}


@dataclass(frozen=True)
class HelpTopic:
    slug: str
    title: str
    audience: str
    summary: str
    body: str


@cache
def topics(root: Path = TOPICS_DIR) -> tuple[HelpTopic, ...]:
    """The Help's topics, by slug; none when the folder isn't there."""
    if not root.is_dir():
        return ()
    found = []
    for path in sorted(root.glob("*.md")):
        match = re.match(r"^---\n(.*?)\n---\n?(.*)$", path.read_text(encoding="utf-8").replace("\r\n", "\n"), re.DOTALL)
        if not match:
            continue
        header = dict(line.split(":", 1) for line in match.group(1).splitlines() if ":" in line)
        header = {key.strip(): value.strip() for key, value in header.items()}
        title, audience, summary = header.get("title", path.stem), header.get("audience", ""), header.get("summary", "")
        found.append(HelpTopic(path.stem, title, audience, summary, _plain(match.group(2))))
    return tuple(found)


def help_for(words: list[str], role: str | None, root: Path = TOPICS_DIR) -> str:
    """The side pass's HOW DELVE WORKS: who asks, every topic in a line, and the best topics for the question's
    `words` whole. Empty without topics."""
    every = topics(root)
    if not every:
        return ""
    lines = ["HOW DELVE WORKS (the app's own Help; use it for any question about the app, its screens and buttons):"]
    if role in ROLE:
        lines.append(f"The asker is {ROLE[role]}: give the steps that are theirs, and say who else can do the rest.")
    lines.append("The Help's topics:")
    lines += [f"- {t.title} (for {AUDIENCE.get(t.audience, t.audience)}): {t.summary}" for t in every]
    for topic in _best(every, words):
        body = topic.body if len(topic.body) <= HELP_TOPIC_CHARS else topic.body[:HELP_TOPIC_CHARS].rstrip() + " …"
        lines.append(f"\nTHE HELP TOPIC \"{topic.title}\":\n{body}")
    return "\n".join(lines)


def _best(every: tuple[HelpTopic, ...], words: list[str]) -> list[HelpTopic]:
    """The topics that hold the most of the question's words, a word in the title or summary counting three times."""
    scored = []
    for topic in every:
        head = f"{topic.title} {topic.summary}".lower()
        body = topic.body.lower()
        score = sum(3 * (word in head) + (word in body) for word in words)
        if score:
            scored.append((-score, topic.slug, topic))
    return [topic for _, _, topic in sorted(scored)[:HELP_TOPICS]]


def _plain(markdown: str) -> str:
    """A topic's Markdown without its pictures, HTML (a figure and its caption) and links, for the side pass."""
    text = re.sub(r"<figure.*?</figure>", "", markdown, flags=re.DOTALL)
    text = re.sub(r"!\[[^\]]*\]\([^)]*\)", "", text)
    text = re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", text)  # a link to another topic: its words
    text = re.sub(r"<[^>]+>", "", text)
    return re.sub(r"\n{3,}", "\n\n", text).strip()
