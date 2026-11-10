"""Translation (plan 4 Task 7, spec §7.7): stored state stays English, and each seat reads its own language.

Into English: a submission, table talk and a question are put into English by a side pass of Preferences' `translation`
job before they are stored (`to_english`), and keep their original words beside the English. English costs nothing.
A failed translation keeps the original, marked `failed`: an act still joins the beat, "(not translated)".

Out of English: a `dm_text`, a `talk`, an `answer` or a `recap` is translated for each language of the present seats
that may see it, other than English and the words' own. The DM's reply is translated paragraph by paragraph as it
streams (`Outgoing`): a paragraph ends at a blank line, or at the end of the reply, and each language's paragraphs are
translated in order. Readers of English get the entry itself, with no delay. Each step is stored in `translations`,
and published as a `translation` event `{campaign_id, entry_id, language, text, status}` with the entry's audience,
for the seats of that language only: `translating` (with the text so far) at once, then `done`, or `failed`, which
leaves the English to read. A translation never holds up the beat: it runs in tasks of its own.

The words of a seat in its own language (an act, talk, a question) are that language's translation as they are.

A shared Ask the DM answer (a `talk` with an `answer`, plan 7 Task 18) is translated whole, its question and its
answer, for each language of the present seats other than English, the asker's language too, whose question is the
asker's own words: the `translation` event and the stored row carry the answer's as `answer`.

The prompt holds the language's glossary of game terms (`delve.i18n.glossary`) and, as never to translate, the names
of the campaign's characters, the module's NPCs and its keyed places that the text holds.
"""

from __future__ import annotations

import asyncio
import contextlib
import re
import threading
from collections import OrderedDict, deque
from collections.abc import Iterable
from typing import TYPE_CHECKING, NamedTuple

from delve.domain.campaigns import StoryEntry, StoryKind, TranslationStatus
from delve.domain.settings import LANGUAGE_NAMES
from delve.i18n import glossary
from delve.modules.text import ModuleText
from delve.play.audience import can_see, seat_controls
from delve.storage.interfaces import Storage

if TYPE_CHECKING:
    from delve.play.table import AppServices

__all__ = [
    "ENGLISH",
    "TRANSLATION_TIMEOUT",
    "English",
    "Outgoing",
    "glossary",
    "has_words",
    "is_english",
    "never_translate",
    "out_of_english",
    "paragraphs",
    "settle",
    "to_english",
    "translate_entry",
    "translation_prompt",
    "usable",
]

TRANSLATION_TIMEOUT = 60.0
ENGLISH = "en"
OUT_OF_ENGLISH: frozenset[StoryKind] = frozenset({"dm_text", "talk", "answer", "recap", "say"})

RULES = (
    "This is a tabletop role-playing game of old-school fantasy. Keep the meaning, the tone, the Markdown and the "
    "paragraphs; add nothing and leave nothing out. Answer with the translation alone: no notes, no quotes, no "
    "explanation."
)

_BLANK_LINE = re.compile(r"\n[ \t]*\n")
_WORD = re.compile(r"[^\W\d_]")
_TAG_BLOCK = re.compile(r"<([A-Za-z_][\w-]*)\b[^>]*>.*?</\1\s*>", re.DOTALL)
_TAG = re.compile(r"</?[A-Za-z_][\w-]*\b[^>]*>")
# Words of the prompt that a translation never holds unless its original did: a reply with them echoes the prompt.
_PROMPT_WORDS = ("THE TEXT:", "GAME TERMS", "NEVER TRANSLATE", "Translate the text below", "translation instructions")


class English(NamedTuple):
    """Words put into English: the English, or the original when `failed`."""

    text: str
    failed: bool = False


def is_english(language: str) -> bool:
    return language.split("-")[0].lower() == ENGLISH


def has_words(text: str) -> bool:
    """Whether `text` holds a word to translate: `---`, a bare number or Markdown alone has none."""
    return _WORD.search(text) is not None


def usable(answer: str, original: str) -> str | None:
    """The side pass's `answer` as a translation of `original`, or None when it is none: it echoes the prompt, or
    holds nothing once the markup the original lacks (an `<ip_reminder>` block, say) is cut out."""
    if any(word in answer and word not in original for word in _PROMPT_WORDS):
        return None
    kept = _TAG_BLOCK.sub(lambda m: m.group(0) if m.group(0) in original else "", answer)
    kept = _TAG.sub(lambda m: m.group(0) if m.group(0) in original else "", kept)
    kept = _BLANK_LINE.sub("\n\n", kept).strip()
    return kept or None


def paragraphs(text: str) -> list[str]:
    """The paragraphs of `text`: they end at a blank line."""
    return [part.strip() for part in _BLANK_LINE.split(text) if part.strip()]


# ----- into English -----


async def to_english(services: AppServices, campaign_id: str, text: str, language: str) -> English:
    """`text`, in `language`, put into English; `text` as it is for English. On failure, the original with
    `failed`."""
    if is_english(language) or not text.strip():
        return English(text)
    try:
        answer = await _translate(services, campaign_id, translation_prompt(services, campaign_id, text, language))
    except Exception:  # noqa: BLE001 (any failure leaves the original, marked)
        return English(text, failed=True)
    kept = usable(answer, text)
    return English(kept) if kept else English(text, failed=True)


# ----- the prompt -----


def translation_prompt(services: AppServices, campaign_id: str, text: str, source: str, target: str = ENGLISH) -> str:
    """The side pass's prompt to put `text` from `source` into `target`. Its first line is `Translate the text below
    from <name> (<code>) into <name> (<code>).`, and the text comes last, after a line `THE TEXT:`."""
    parts = [f"Translate the text below from {_name(source)} ({source}) into {_name(target)} ({target}).", RULES]
    other = target if is_english(source) else source
    terms = glossary(other)
    if terms:
        lines = []
        for term, said in terms.items():
            if said is None:
                lines.append(f"- {term}: keep it as it is")
            elif is_english(source):
                lines.append(f"- {term}: {said}")
            else:
                lines.append(f"- {said}: {term}")
        parts.append("GAME TERMS (translate them this way):\n" + "\n".join(lines))
    names = never_translate(services.storage, campaign_id, text)
    if names:
        parts.append("NEVER TRANSLATE these names:\n" + "\n".join(f"- {name}" for name in names))
    parts.append(f"THE TEXT:\n{text}")
    return "\n\n".join(parts)


def never_translate(storage: Storage, campaign_id: str, text: str | None = None) -> list[str]:
    """The names of the campaign's characters, and of its module's NPCs and keyed places at the pinned revision; with
    `text`, only those it holds (in any case). DEL-171: every paragraph's prompt held all 298 of Thracia's, about 2k
    tokens, and read and parsed the revision's text again; a revision's names are read once (`_module_names`)."""
    names = [c.name for c in storage.characters.list(campaign_id)]
    campaign = storage.campaigns.get(campaign_id)
    if campaign is not None:
        names += _module_names(storage, campaign.module_id, campaign.revision)
    found = list(dict.fromkeys(name.strip() for name in names if name.strip()))
    if text is None:
        return found
    within = text.casefold()
    return [name for name in found if name.casefold() in within]


MODULE_NAMES_KEPT = 32
"""How many revisions' names `_module_names` keeps."""
_names: OrderedDict[tuple[str, int], tuple[str, ...]] = OrderedDict()
_names_lock = threading.Lock()


def _module_names(storage: Storage, module_id: str, revision: int) -> tuple[str, ...]:
    """The names of the NPCs and the keyed places of a module's revision, which never changes once made."""
    key = (module_id, revision)
    with _names_lock:
        if key in _names:
            _names.move_to_end(key)
            return _names[key]
    raw = storage.module_texts.revision(module_id, revision)
    names: list[str] = []
    if raw:
        text = ModuleText.from_json(raw)
        names += [str(npc["name"]) for npc in text.entities.get("npcs", []) if npc.get("name")]
        names += [key.title for key in text.keys if key.title]
    kept = tuple(names)
    with _names_lock:
        _names[key] = kept
        while len(_names) > MODULE_NAMES_KEPT:
            _names.popitem(last=False)
    return kept


def _name(language: str) -> str:
    return LANGUAGE_NAMES.get(language, language)


async def _translate(services: AppServices, campaign_id: str, prompt: str) -> str:
    choose = services.translation or services.side
    provider, choice = choose(campaign_id)
    return (await provider.side_call(prompt, choice, timeout=TRANSLATION_TIMEOUT)).strip()


# ----- out of English -----


def translate_entry(services: AppServices, entry: StoryEntry, *, also: Iterable[str] = ()) -> None:
    """Translate a finished story entry for the seats at the table: the words' own language gets the original, and
    each other language a side pass. `also` are seats to count as present, such as who asked."""
    if not _loop_running():
        return
    if entry.kind == "talk" and entry.payload.get("answer"):
        _shared_answer(services, entry, set(also))
        return
    _own_words(services, entry)
    if entry.kind in OUT_OF_ENGLISH:
        outgoing = out_of_english(services, entry, also=also)
        if outgoing is not None:
            outgoing.end(str(entry.payload.get("text", "")))


def out_of_english(services: AppServices, entry: StoryEntry, *, also: Iterable[str] = ()) -> Outgoing | None:
    """The translations of `entry` out of English, to feed as its text grows; None when no seat needs one, or the
    text isn't English (its translation into English failed)."""
    if entry.payload.get("translation") == "failed" or not _loop_running():
        return None
    languages = _languages(services, entry, set(also))
    return Outgoing(services, entry, languages) if languages else None


class Outgoing:
    """One entry's translations out of English: a worker per language, fed paragraph by paragraph as the entry's
    text grows (`grow`), until it ends (`end`)."""

    def __init__(self, services: AppServices, entry: StoryEntry, languages: list[str]) -> None:
        self.entry = entry
        self._services = services
        self._prompt = lambda text, language: translation_prompt(services, entry.campaign_id, text, ENGLISH, language)
        self._text = ""
        self._sent = 0
        self._ended = False
        self._queues: dict[str, deque[str]] = {language: deque() for language in languages}
        self._wake: dict[str, asyncio.Event] = {language: asyncio.Event() for language in languages}
        for language in languages:
            self._put(language, "", "translating")
            task = asyncio.create_task(self._work(language))
            services.translating.add(task)
            task.add_done_callback(services.translating.discard)

    def grow(self, text: str) -> None:
        """The entry's text so far: its finished paragraphs go to be translated."""
        self._text = text
        parts = _BLANK_LINE.split(text)
        self._feed([part.strip() for part in parts[:-1] if part.strip()])

    def end(self, text: str | None = None) -> None:
        """The entry's text is whole: its last paragraph goes too, and each language ends."""
        if self._ended:
            return
        if text is not None:
            self._text = text
        self._feed(paragraphs(self._text))
        self._ended = True
        for wake in self._wake.values():
            wake.set()

    def _feed(self, finished: list[str]) -> None:
        for paragraph in finished[self._sent :]:
            for language, queue in self._queues.items():
                queue.append(paragraph)
                self._wake[language].set()
        self._sent = max(self._sent, len(finished))

    async def _work(self, language: str) -> None:
        queue, wake = self._queues[language], self._wake[language]
        done: list[str] = []
        failed = False
        final = False
        while True:
            while not queue and not self._ended:
                wake.clear()
                await wake.wait()
            if not queue:
                break
            paragraph = queue.popleft()
            if failed:
                continue
            try:
                if has_words(paragraph):
                    answer = await _translate(self._services, self.entry.campaign_id, self._prompt(paragraph, language))
                    # A reply that is no translation leaves this paragraph in English; the next is translated.
                    done.append(usable(answer, paragraph) or paragraph)
                else:
                    done.append(paragraph)
            except Exception:  # noqa: BLE001 (a failed translation leaves the English, never a stopped beat)
                failed = True
            final = failed or (self._ended and not queue)
            self._put(language, "\n\n".join(done), "failed" if failed else "done" if final else "translating")
        if not final:
            self._put(language, "\n\n".join(done), "failed" if failed else "done")

    def _put(self, language: str, text: str, status: TranslationStatus) -> None:
        _publish(self._services, self.entry, language, text, status)


async def settle(services: AppServices) -> None:
    """Wait for every translation under way to end. Ended tasks are dropped here too: their done callback may not have
    run yet, and awaiting tasks that are already done never yields to the loop that would run it."""
    while services.translating:
        tasks = list(services.translating)
        await asyncio.gather(*tasks, return_exceptions=True)
        services.translating.difference_update(task for task in tasks if task.done())


def stop(services: AppServices) -> list[asyncio.Task]:
    """Cancel the translations under way (when Delve stops); the cancelled tasks, to await. The next start marks
    their rows failed."""
    tasks = list(services.translating)
    for task in tasks:
        task.cancel()
    return tasks


def _own_words(services: AppServices, entry: StoryEntry) -> None:
    """A seat's words in its own language are that language's translation of the entry, as they are."""
    language, original = entry.payload.get("language"), entry.payload.get("original")
    if isinstance(language, str) and isinstance(original, str) and original and not is_english(language):
        _publish(services, entry, language, original, "done")


def _shared_answer(services: AppServices, entry: StoryEntry, also: set[str]) -> None:
    """Translate a shared answer and its question for each language that needs it, in a task per language."""
    if entry.payload.get("translation") == "failed":
        return
    own = entry.payload.get("language") if entry.payload.get("original") else None
    for language in _languages(services, entry, also, own_too=True):
        _publish(services, entry, language, "", "translating")
        task = asyncio.create_task(_translate_shared(services, entry, language, own))
        services.translating.add(task)
        task.add_done_callback(services.translating.discard)


async def _translate_shared(services: AppServices, entry: StoryEntry, language: str, own: str | None) -> None:
    question, answer = str(entry.payload.get("text", "")), str(entry.payload.get("answer", ""))

    async def into(text: str) -> str:
        if not has_words(text):
            return text
        prompt = translation_prompt(services, entry.campaign_id, text, ENGLISH, language)
        return usable(await _translate(services, entry.campaign_id, prompt), text) or text

    try:
        asked = str(entry.payload["original"]) if language == own else await into(question)
        answered = await into(answer)
    except Exception:  # noqa: BLE001 (a failed translation leaves the English)
        _publish(services, entry, language, "", "failed")
        return
    _publish(services, entry, language, asked, "done", answer=answered)


def _languages(services: AppServices, entry: StoryEntry, also: set[str], *, own_too: bool = False) -> list[str]:
    """The languages of the present seats that may see `entry`, other than English and (unless `own_too`) the words'
    own."""
    storage = services.storage
    here = services.present(entry.campaign_id) | also
    own = entry.payload.get("language") if entry.payload.get("original") and not own_too else None
    of_characters = isinstance(entry.audience, dict) and "characters" in entry.audience
    languages: list[str] = []
    for seat in storage.seats.list(entry.campaign_id):
        language = seat.language
        if seat.id not in here or is_english(language) or language == own or language in languages:
            continue
        if can_see(seat, entry.audience, seat_controls(storage, seat) if of_characters else set()):
            languages.append(language)
    return languages


def _publish(
    services: AppServices,
    entry: StoryEntry,
    language: str,
    text: str,
    status: TranslationStatus,
    *,
    answer: str | None = None,
) -> None:
    services.storage.translations.put(entry.id, language, text, status, answer=answer)
    data = {
        "campaign_id": entry.campaign_id,
        "entry_id": entry.id,
        "language": language,
        "text": text,
        "status": status,
        **({"answer": answer} if answer is not None else {}),
    }
    services.publish(
        "translation", data, scope="table", campaign_id=entry.campaign_id, audience=entry.audience, language=language
    )


def _loop_running() -> bool:
    with contextlib.suppress(RuntimeError):
        asyncio.get_running_loop()
        return True
    return False
