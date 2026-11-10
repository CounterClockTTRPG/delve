"""The kinds of monsters' pictures, for every campaign of the install (DEL-275).

An enemy on the initiative strip shows the picture of its kind when there is one, and its initial when there isn't, as
before. A kind is found by its slug (`slug`): the combatant's name is tried first ("Kobold leader", its number cut
off), then its kind as the DM added it ("Beetle, Giant Fire"), each also as a singular and with a comma's parts the
other way round (`candidates`).

The pictures are the install's, not a campaign's: the owner's own paintings are loaded by `delve monster-pictures
seed` (`seed`), and an organiser has a missing one painted, or a poor one painted again (`ask`), from the strip or a
monster's Rulesets entry. It is painted once, on the possessions' choice of model, in the locked style of those
paintings (`STYLE`, not a campaign's tone or the install's image style, so that every kind looks of one set), and then
every table has it. While it is painted again its old picture stays.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
from dataclasses import replace
from pathlib import Path
from typing import TYPE_CHECKING, Any

from delve.domain.reference import RulesetReference
from delve.domain.settings import Job
from delve.domain.world import MonsterPicture
from delve.images.provider import ImageFile, ImageRequest
from delve.play.context import PlayError, context_for
from delve.storage import Storage

if TYPE_CHECKING:
    from delve.play.table import AppServices

__all__ = [
    "JOB",
    "STYLE",
    "ask",
    "candidates",
    "find",
    "picture_json",
    "resume",
    "seed",
    "slug",
    "subject",
    "what_it_is",
]

log = logging.getLogger(__name__)

JOB = Job.IMAGE_POSSESSION
"""The job whose model paints a kind: its square is the token's."""

STYLE = (
    "Painted in warm oil in the TSR Gold Box tradition of Larry Elmore, Keith Parkinson and Clyde Caldwell: visible "
    "brushwork, glazed depth, a muted earthy palette of weathered leather, dull iron, oiled wood and dark hide, "
    "dramatic single-source light from the upper left against cool shadow. A single creature alone, true to its own "
    "body: a beast is painted as the animal it is, on its own legs, coils, wings or fins, never with a person's torso, "
    "arms, clothing, armour or weapons it doesn't have. A close portrait filling the square from edge to edge and cut "
    "off by the bottom of the frame: a creature that walks upright its head, shoulders and chest; a beast its head and "
    "forebody (a snake its raised head and the coils below it). Centred, facing the viewer at a three-quarter angle. "
    "Set flat against a plain unobtrusive backdrop of dark earthy tone, softly vignetted, its silhouette separated from "
    "the backdrop by a rim of warm light along one edge. Painted, not rendered. No scenery, no ground, no other "
    "figures, no border, no frame, no token ring, no text, no lettering, no signature, no watermark."
)
"""The goldbox token lane's locked style (`tools/monster-art/src/style.ts`), which painted the seeded set; since DEL-359
true to a beast's body, where its bust framing had painted a crocodile as a lizard man in armour."""

DESCRIBED = 2
"""How many sentences of the reference's description go into the brief."""

INTERRUPTED = "Delve stopped while painting it."
NO_PAINTER = "No image model paints pictures of things; choose one in Preferences."
PAINTING = "A picture of {name} is being painted already."

_NUMBERED = re.compile(r"\s*(#?\d+|[ivx]+)$", re.IGNORECASE)


def slug(name: str) -> str:
    """'Skeleton, Animal' is 'skeleton-animal'."""
    return "-".join(re.findall(r"[a-z0-9]+", name.lower()))


def _singular(word: str) -> str:
    if word.endswith("ies") and len(word) > 4:
        return word[:-3] + "y"
    if word.endswith(("ches", "shes", "xes", "sses")):
        return word[:-2]
    if word.endswith("s") and not word.endswith("ss") and len(word) > 3:
        return word[:-1]
    return word


def candidates(*names: str | None) -> list[str]:
    """The slugs a combatant's picture may have, best first: each name with its number cut off ("Kobold 2"), as a
    singular, and a comma's parts the other way round ("Beetle, Giant Fire" is "giant-fire-beetle"), or a name's last
    word first ("hill giant" is also "giant-hill"). Never the first part alone: an animal's skeleton is no skeleton's
    picture."""
    found: list[str] = []
    for name in names:
        if not name or not name.strip():
            continue
        name = _NUMBERED.sub("", name.strip())
        forms = [name]
        if "," in name:
            head, rest = (part.strip() for part in name.split(",", 1))
            forms.append(f"{rest} {head}")
        elif len(words := name.split()) > 1:
            # A kind said in order ("hill giant", DEL-325) may have its picture as the book indexed it ("giant-hill").
            forms.append(f"{words[-1]} {' '.join(words[:-1])}")
        for form in forms:
            s = slug(form)
            words = s.split("-")
            for each in (s, "-".join([*words[:-1], _singular(words[-1])])):
                if each and each not in found:
                    found.append(each)
    return found


def find(storage: Storage, *names: str | None) -> MonsterPicture | None:
    """The first kind of `candidates` that has a picture to show (a repaint's or a failure's old one too)."""
    for each in candidates(*names):
        picture = storage.monster_pictures.get(each)
        if picture is not None and picture.blob is not None:
            return picture
    return None


def picture_json(picture: MonsterPicture | None, name: str) -> dict[str, Any]:
    """A kind's state for the strip's and the Rulesets' Paint: its slug, whether it has a picture and its version (for
    the browser's cache), whether one is being painted, and the last painting's error."""
    shown = picture is not None and picture.blob is not None
    return {
        "slug": picture.slug if picture is not None else slug(name),
        "picture": shown,
        "version": picture.updated_at if shown else None,
        "painting": picture is not None and picture.status == "painting",
        "error": picture.error if picture is not None and picture.status == "failed" else None,
    }


def subject(storage: Storage, lookups: RulesetReference | None, name: str, text: dict[str, Any] | None = None) -> str:
    """The brief's subject: the kind, and the first sentences of its ruleset's entry when there is one; else what the
    campaign's module `text` says it is (`what_it_is`), so that a module's own "mudviper" is painted as a snake."""
    rows = lookups.monster(name) if lookups is not None else []
    text_of_entry = (rows[0].get("description") or "") if rows else ""
    sentences = re.split(r"(?<=[.!?])\s+", " ".join(text_of_entry.split()))
    described = " ".join(sentences[:DESCRIBED]).strip()
    if described:
        return f"A {name.strip()}. {described}"
    what = what_it_is(text, name) if text is not None else None
    return f"A {name.strip()}" + (f", a {what}." if what else ".")


_STAT = re.compile(r"\d|^(ac|hd|mv|hp|al|int|thac0|#at|lvl|level)\b", re.IGNORECASE)
_WHAT = 60
"""The longest a module's word for what a kind is may be ("giant poisonous snake")."""


_STATS = re.compile(r"\b(AC|HD|MV)\s*-?\d", re.IGNORECASE)
_POINTER = re.compile(r"^(see|treat|as|cf|q\.?v|they|it|he|she|these|those|each|all|both)\b", re.IGNORECASE)


def _what(note: str) -> str | None:
    """A stat note's first clause when it names what the creature is and stats follow it: "giant poisonous snake,
    AC 5; MV 15"" is "giant poisonous snake"; "AC 5; HD 4+2", "q.v." and "see the Monster Manual" say nothing."""
    cut = re.search(r"[,;:(]", note)
    first, rest = (note[: cut.start()], note[cut.end() :]) if cut else (note, "")
    first = first.strip().strip("*_ ").rstrip(".")
    if len(first.split()) < 2 or len(first) > _WHAT or _STAT.search(first) or _POINTER.search(first):
        return None
    if not _STATS.search(rest):
        return None
    return first[0].lower() + first[1:] if first[1:2].islower() else first


def what_it_is(text: dict[str, Any], name: str) -> str | None:
    """What a module's text says the kind `name` is: the note of an encounter's creature of that kind ("monster:
    mudviper", "giant poisonous snake, AC 5; …"), else the parenthesis after the kind's name in its prose ("the
    **mudviper** (giant poisonous snake, AC 5 …)"). None when it says neither."""
    wanted = set(candidates(name))
    for encounter in (text.get("entities") or {}).get("encounters", []):
        for creature in encounter.get("fixed") or []:
            ref = str(creature.get("creature") or "").split(":", 1)[-1]
            if slug(ref) in wanted and (found := _what(str(creature.get("notes") or ""))):
                return found
    said = re.compile(rf"\b{re.escape(name.strip())}e?s?\b[*_]*\s*\(([^)]*)", re.IGNORECASE)
    for section in text.get("sections") or []:
        for match in said.finditer(str(section.get("markdown") or "")):
            if found := _what(match.group(1)):
                return found
    return None


def ask(services: AppServices, name: str, *, campaign_id: str | None = None) -> MonsterPicture:
    """Paint the kind `name` (again), in the background: its row as `painting`, the old picture kept. `PlayError` for
    a name with no letters, one being painted already, and without a model that paints."""
    storage = services.storage
    kind = slug(name)
    if not kind:
        raise PlayError("A monster's picture needs its name.")
    old = storage.monster_pictures.get(kind)
    if old is not None and old.status == "painting":
        raise PlayError(PAINTING.format(name=old.name))
    if services.images is None:
        raise PlayError(NO_PAINTER)
    # The brief reads the asking campaign's ruleset (an OSRIC monster's own text); without a campaign, nothing.
    lookups = context_for(storage, campaign_id, "picture", catalogs=services.catalogs).lookups if campaign_id else None
    # A kind the ruleset doesn't know is what the campaign's module says it is (DEL-359).
    campaign = storage.campaigns.get(campaign_id) if campaign_id else None
    text = storage.module_texts.revision(campaign.module_id, campaign.revision) if campaign is not None else None
    prompt = subject(storage, lookups, name, text)
    base = old or MonsterPicture(kind, name.strip(), source="painted")
    row = storage.monster_pictures.put(replace(base, status="painting", prompt=prompt, error=None))
    _changed(services, row, campaign_id)
    key = f"monster:{kind}"
    task = asyncio.create_task(_paint_logged(services, kind, campaign_id))
    services.painting[key] = task
    task.add_done_callback(
        lambda done: services.painting.pop(key, None) if services.painting.get(key) is done else None
    )
    return row


async def paint(services: AppServices, kind: str, campaign_id: str | None = None) -> MonsterPicture | None:
    """Paint the row `kind` if it is `painting`, and land the result: `done` with its new picture, or `failed` with the
    reason and its old picture. A cancelled painting stays `painting` (`resume`)."""
    storage = services.storage
    row = storage.monster_pictures.get(kind)
    if row is None or row.status != "painting":
        return row
    try:
        if services.images is None:
            raise PlayError(NO_PAINTER)
        provider, choice = services.images(JOB)
        result = await provider.generate(ImageRequest(JOB, row.prompt, choice, style=STYLE, aspect="1:1"))
        if not isinstance(result, ImageFile):
            raise PlayError(NO_PAINTER)
    except asyncio.CancelledError:
        raise
    except Exception as error:  # noqa: BLE001 (a painting always ends, never a stuck row)
        reason = str(getattr(error, "message", "") or error) or type(error).__name__
        done = storage.monster_pictures.put(replace(row, status="failed", error=reason[:500]))
    else:
        sha = storage.blobs.put(result.data, result.mime)
        done = storage.monster_pictures.put(
            replace(row, status="done", blob=sha, mime=result.mime, error=None, source="painted")
        )
    _changed(services, done, campaign_id)
    return done


async def _paint_logged(services: AppServices, kind: str, campaign_id: str | None) -> None:
    try:
        await paint(services, kind, campaign_id)
    except asyncio.CancelledError:
        raise
    except Exception:
        log.exception("painting the monster picture %s failed", kind)


def _changed(services: AppServices, picture: MonsterPicture, campaign_id: str | None) -> None:
    """The organisers' screens read the kind again; the table that asked reads its strip again."""
    services.publish("monster_picture", {"slug": picture.slug, "status": picture.status})
    if campaign_id is not None:
        services.publish("timeline", {"campaign_id": campaign_id}, scope="table", campaign_id=campaign_id)


def resume(storage: Storage) -> list[str]:
    """At start: a painting a stopped Delve left `painting` is `failed`, its old picture kept; the slugs."""
    stopped = [p for p in storage.monster_pictures.list() if p.status == "painting"]
    for picture in stopped:
        storage.monster_pictures.put(replace(picture, status="failed", error=INTERRUPTED))
    return [picture.slug for picture in stopped]


SEEDED = "generated/"
"""The goldbox `assets.json` source of the owner's own paintings; the rest there are a counter set's, never shown."""


def seed(storage: Storage, assets: Path) -> list[str]:
    """Load the owner's own monster paintings from a goldbox assets folder (the one holding `assets.json` and
    `tokens/`): each token whose source is `generated/`, its `<key>-portrait.webp`, under the key's slug, an `osric-`
    one only where the plain key has none. A kind that already has a picture keeps it. The slugs loaded."""
    tokens = json.loads((assets / "assets.json").read_text("utf-8"))["tokens"]
    ours = [t for t in tokens if str(t.get("source", "")).startswith(SEEDED)]
    # The plain keys first, so that an `osric-` one fills only a kind still missing.
    ours.sort(key=lambda t: str(t["key"]).startswith("osric-"))
    loaded: list[str] = []
    for token in ours:
        key = str(token["key"]).removeprefix("osric-")
        kind = slug(key)
        path = assets / "tokens" / str(token.get("portrait") or f"{token['key']}-portrait.webp")
        if not kind or kind in loaded or not path.is_file():
            continue
        old = storage.monster_pictures.get(kind)
        if old is not None and old.blob is not None:
            continue
        sha = storage.blobs.put(path.read_bytes(), "image/webp")
        name = key.replace("-", " ").capitalize()
        storage.monster_pictures.put(MonsterPicture(kind, name, blob=sha, mime="image/webp", source="seeded"))
        loaded.append(kind)
    return loaded
