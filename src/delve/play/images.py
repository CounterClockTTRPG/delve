"""Pictures (plan 6 Task 10, spec §5.2): free portraits at once, and paid ones painted in the background.

A portraitgen portrait is only a description and a seed (`TraitsPortrait`), set on the subject at once; the browser
draws it. A paid picture is a `campaign_images` row: `request` makes it `painting`, inside the DM's tool call, and
`paint` runs the image provider later, in a task of its own (`schedule`), so the beat is never held up. When it is
done, a portrait or a possession's picture becomes the subject's `ImagePortrait`, and a scene a `scene` story entry,
`{image_id, caption}`, for the row's audience. When it fails, the row keeps its error, the host gets a notice in the
story, and a character's portrait falls back to portraitgen. The brief never reaches the story.

A campaign's banner is a wide row of its own kind, painted with the scene's choice of model at `ASPECTS["banner"]`.
When it lands it replaces the campaign's older banners; when it fails it keeps its error for the campaign's page and
tells no seat. A `waiting` banner is held back by the paid gate: `resume` never paints it (`delve.play.banners` does).

Paid images are off for each campaign until the host turns them on (the play setting `paid_images`). The gate goes
per model (`is_paid`): portraitgen, the fake and a model that says it is free (assetgen's `local` ones) paint with
them off too. With them off and a model that costs money, a portrait is portraitgen's, and a scene or a possession's
picture is refused with a hint.

Paid pictures have limits too (DEL-153, audit finding 6), so that neither a seat pressing "Paint this scene" in a loop
nor a DM steered by a player's words can spend without end. A campaign paints at most `paid_images_per_day` paid
pictures (a play setting beside the switch, `PAID_PER_DAY` by default) in any 24 hours, the seats' scenes and the DM's
pictures together, a failed one included: the provider may have charged for it. A day, not a session: a session is
opened and ended by the DM's own tools, which a player's words can steer, and one left open spans days. Within a beat
the DM paints at most `SCENES_PER_BEAT` paid scenes and one paid picture of each subject. A refusal is `PaidUsedUp`
(429 to a seat) or `PlayError`, with a hint the DM can narrate around. Each request is counted by its
`picture_requested` event, `paid` when it costs money; free pictures are never limited, and neither are banners,
which an organiser paints outside play, one at a time, and no seat or DM can ask for.

A painting still running when Delve stops stays `painting`. A provider with a queue of its own (assetgen) keeps its
job there, and the row keeps the job's id (`provider_job`), so the next start follows that job (`resume`) rather than
sending a copy, and a restart is never counted against it; while it waits, the row has its place in the queue
(`queue`), for the table to show. A row without a provider's job is asked for again, once: a row asked for twice
already is failed instead (`attempts`). Only the provider's own failures fail a painting (DEL-138).
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any, Protocol

from delve.dm.tools.redact import scene_view
from delve.domain import new_id
from delve.domain.backends import Registry
from delve.domain.campaigns import Character, Event, Seat
from delve.domain.characters import Sheet
from delve.domain.image_styles import stored_style_text
from delve.domain.portrait_traits import TraitsError, checked
from delve.domain.settings import BackendChoice, Job
from delve.domain.world import CampaignImage, ImageKind, ImagePortrait, Portrait, Possession, TraitsPortrait
from delve.images.fake import FAKE_IMAGES_CAPABILITIES
from delve.images.none import NO_PORTRAIT, NPC_PORTRAITS_OFF
from delve.images.portraitgen import PORTRAITGEN
from delve.images.provider import ImageFile, ImageRequest, PortraitTraits, ProviderJob
from delve.play import audience, table
from delve.play.audience import Audience, for_seats, resolve, seat_controls
from delve.play.context import CampaignContext, NotFound, PlayError, context_for
from delve.play.portraits import PORTRAIT_STYLES
from delve.storage import Storage

if TYPE_CHECKING:
    # `delve.play.table` imports the DM's tools, whose pictures import this module: its names are read at call time.
    from delve.play.table import AppServices

__all__ = [
    "ASPECTS",
    "BANNER",
    "BEAT_HINT",
    "BEAT_SCENES",
    "BEAT_SUBJECT",
    "NPC_PORTRAITS_OFF",
    "PAID_HINT",
    "PAID_OFF",
    "PAID_USED_UP",
    "PAID_USED_UP_HINT",
    "SCENES_PER_BEAT",
    "BriefFailed",
    "PaidUsedUp",
    "Subject",
    "can_see",
    "check_paid_limit",
    "describe",
    "find_subject",
    "free_portrait",
    "is_paid",
    "now",
    "npc_portrait",
    "paid_images",
    "paid_limit",
    "paint",
    "paint_this_scene",
    "painting_portrait",
    "painting_scenes",
    "portrait_failed",
    "portrait_job",
    "portrait_provider",
    "portrait_style",
    "repaint",
    "request",
    "resume",
    "schedule",
    "schedule_waiting",
    "stop",
    "waiting",
]

log = logging.getLogger(__name__)

PAID_OFF = "Paid images are off for this campaign."
PAID_HINT = (
    "The chosen model costs money. The host can turn paid images on in the campaign's play settings; a portrait can "
    "be portraitgen's, free."
)
NOTHING_TO_PAINT = "There is no narration to paint yet."
SCENE_FAILED = "The scene couldn't be painted."
PORTRAIT_FAILED = "{name}'s portrait couldn't be painted; the free portrait stands in."
PICTURE_FAILED = "The picture of {name} couldn't be painted."
STILL_PAINTING = "{name}'s portrait is being painted already."
NOT_EDITABLE = "Only a player character's drawn portrait is edited, while Preferences draw them with portraitgen."
INTERRUPTED = "Delve stopped while painting it, twice."
PAID_USED_UP = "This campaign's {limit} paid pictures for the last 24 hours are used up."
PAID_USED_UP_HINT = (
    "Tell it in words for now: a picture can be painted again once a day has passed since the earlier ones. The host "
    "can raise the limit in the table options."
)
BEAT_SCENES = "This beat has painted its {n} scenes already."
BEAT_SUBJECT = "A picture of {name} is being painted in this beat already."
BEAT_HINT = "Tell the rest in words; paint again in a later beat if it is worth it."
SCENES_PER_BEAT = 2
"""The DM's paid scenes in one beat: a vista and the thing in it, never a picture of every step."""
DAY = timedelta(hours=24)
SCENE = "scene"
BANNER = "banner"
REQUESTED = "picture_requested"

JOBS: dict[ImageKind, Job] = {
    "portrait": Job.IMAGE_PORTRAIT,
    "scene": Job.IMAGE_SCENE,
    "possession": Job.IMAGE_POSSESSION,
    "banner": Job.IMAGE_SCENE,
}
ASPECTS: dict[ImageKind, str] = {"banner": "21:9"}
"""The kinds painted at a ratio of their own, not their job's."""

Subject = Character | Possession
FREE = frozenset({PORTRAITGEN, NO_PORTRAIT, FAKE_IMAGES_CAPABILITIES.id})
"""The providers that never cost money."""


class HasImages(Protocol):
    """The app's registries (`delve.web.app.Registries`), as far as the paid gate reads them."""

    images: Registry[Any]


# ttrpg2's `rewrite_for_image` (tools/dm_session.py `_IMAGE_PROMPT_SYSTEM`): narration to a painter's brief.
SCENE_BRIEF = (
    "You translate fantasy RPG narrative prose into a focused image-generation prompt for a Flux model.\n\n"
    "The user's input is either:\n"
    "  - a NARRATIVE on its own, OR\n"
    "  - a NARRATIVE section followed by a HINT line. The HINT is the player's direction about what the picture "
    "should emphasise (subject, framing, mood). When a HINT is present, use it as the primary anchor for the prompt "
    "and pull supporting visual detail from the narrative.\n\n"
    "Extract only the *visual* scene: subject(s), action, setting, lighting, time of day, mood, palette. Drop "
    "dialogue, internal thoughts, dice results, NPC stat blocks, exposition, and anything an image cannot show.\n\n"
    "Return one English paragraph of 60 to 120 words describing the scene the way a painter's brief would. No "
    "preface, no bullets, no explanation, no quotation marks around the output — just the prompt itself."
)
NARRATIONS = 2
BRIEF_TIMEOUT = 90.0


class BriefFailed(PlayError):
    """The side pass wrote no painter's brief."""


class PaidUsedUp(PlayError):
    """The campaign's paid pictures for the last 24 hours are used up (DEL-153): 429 to a seat."""


def now() -> datetime:
    """The time the limit counts back from; patched in tests."""
    return datetime.now(UTC)


# ----- the settings -----


def paid_images(storage: Storage, campaign_id: str) -> bool:
    """Whether the host turned paid images on for the campaign."""
    return table.play_settings(storage, campaign_id)["paid_images"] is True


def paid_limit(storage: Storage, campaign_id: str) -> int:
    """How many paid pictures the campaign may paint in 24 hours (`paid_images_per_day`)."""
    return int(table.play_settings(storage, campaign_id)["paid_images_per_day"])


def is_paid(registries: HasImages, job: Job, choice: BackendChoice) -> bool:
    """Whether painting `job` with `choice` costs money. portraitgen and the fake are free; otherwise the model's
    `ModelInfo.paid` decides (no model is the provider's default). An unknown provider, a provider that doesn't do
    the job, and a model it says nothing about all count as paid, so a wrong guess never spends the owner's money."""
    if choice.provider in FREE:
        return False
    caps = next((c for c in registries.images.capabilities() if c.id == choice.provider), None)
    if caps is None or job not in caps.jobs:
        return True
    info = caps.model_info.get(choice.model or caps.default_model or "")
    return True if info is None else info.paid


def portrait_provider(storage: Storage, job: Job = Job.IMAGE_PORTRAIT) -> str:
    """The provider Preferences chose for `job`'s portraits, a PC's or an NPC's (DEL-248); portraitgen when they chose
    none, as the default is for both."""
    choices = storage.settings.load().get("choices")
    chosen = choices.get(str(job)) if isinstance(choices, dict) else None
    provider = chosen.get("provider") if isinstance(chosen, dict) else None
    return provider if isinstance(provider, str) and provider else PORTRAITGEN


def portrait_style(storage: Storage, campaign_id: str, job: Job = Job.IMAGE_PORTRAIT) -> str:
    """The style portraitgen draws `job`'s portraits in at the campaign: the campaign's own when it chose one, else
    the style Preferences picked for the job as portraitgen's model (DEL-252), else `illustrated`."""
    own = table.play_settings(storage, campaign_id)["portrait_style"]
    if own in PORTRAIT_STYLES:
        return own
    choices = storage.settings.load().get("choices")
    chosen = choices.get(str(job)) if isinstance(choices, dict) else None
    model = chosen.get("model") if isinstance(chosen, dict) and chosen.get("provider") in (PORTRAITGEN, None) else None
    return model if model in PORTRAIT_STYLES else PORTRAIT_STYLES[0]


def portrait_job(subject: Subject) -> Job:
    """An NPC's portrait is its own job, with its own painter (DEL-248); a PC's, and a possession's, are not."""
    return Job.IMAGE_NPC_PORTRAIT if isinstance(subject, Character) and subject.kind == "npc" else Job.IMAGE_PORTRAIT


def _job(storage: Storage, campaign_id: str, kind: ImageKind, subject_id: str | None) -> Job:
    """The job a picture of `kind` is painted by: a portrait's is its subject's (`portrait_job`)."""
    if kind == "portrait" and subject_id is not None:
        character = storage.characters.get(subject_id)
        if character is not None and character.campaign_id == campaign_id:
            return portrait_job(character)
    return JOBS[kind]


def npc_portrait(ctx: CampaignContext, npc: Character, description: str = "") -> dict[str, Any] | None:
    """An NPC's portrait as Preferences choose for NPCs (DEL-248): none with No portrait; portraitgen's, free and at
    once; else a painting, while paid images are on and the campaign's limit allows, otherwise portraitgen's after
    all. What the portrait tool answers, `{"portrait"}` or `{"image_id", "status"}`; None when NPCs get none."""
    provider = portrait_provider(ctx.storage, Job.IMAGE_NPC_PORTRAIT)
    if provider == NO_PORTRAIT:
        return None
    described = description.strip() or describe(npc)
    may_paint = paid_images(ctx.storage, ctx.campaign_id) or not ctx.image_paid(Job.IMAGE_NPC_PORTRAIT)
    if provider != PORTRAITGEN and may_paint:
        try:
            image = request(ctx, "portrait", npc.id, described, None)
            return {"image_id": image.id, "status": image.status}
        except PlayError:  # the day's paid pictures are used up, or this beat's: the free portrait stands in
            pass
    return {"portrait": free_portrait(ctx, npc, described).to_dict()}


def repaint(ctx: CampaignContext, character: Character) -> dict[str, Any]:
    """Paint the character's portrait again, from its sheet (`describe`), with the painter Preferences choose now for
    its job (`portrait_job`): the Repaint portrait button, and a failed portrait's Try again (DEL-135). portraitgen's
    is free and set at once, `{"portrait"}`; any other painter's is a `painting` row, `{"image_id", "status"}`, that the
    caller schedules, the old portrait standing until it lands. Unlike the DM's tool, a refusal is never portraitgen's
    after all but said, since the button asked for this painter: `PlayError` while paid images are off and the
    painter costs money, `PaidUsedUp` past the campaign's paid pictures for a day (a seat's request, so not the DM's
    limits for a beat), `PlayError` for an NPC with No portrait, and for a portrait that is being painted already."""
    job = portrait_job(character)
    provider = portrait_provider(ctx.storage, job)
    if provider == NO_PORTRAIT:
        raise PlayError(NPC_PORTRAITS_OFF, "Choose a painter for NPC portraits in Preferences.")
    if painting_portrait(ctx.storage, character) is not None:
        raise PlayError(STILL_PAINTING.format(name=character.name), "Wait for it to land.")
    described = describe(character)
    if provider == PORTRAITGEN:
        return {"portrait": free_portrait(ctx, character, described).to_dict()}
    image = request(ctx, "portrait", character.id, described, None, by_seat=True)
    return {"image_id": image.id, "status": image.status}


def editable(storage: Storage, character: Character) -> bool:
    """Whether the character's portrait is edited in portraitgen's editor rather than repainted (DEL-238): a PC's,
    while Preferences draw PCs' portraits with portraitgen."""
    return character.kind == "pc" and portrait_provider(storage, portrait_job(character)) == PORTRAITGEN


def edit(ctx: CampaignContext, character: Character, traits: Any) -> TraitsPortrait:
    """Set the character's portrait to the traits a player made in portraitgen's editor (DEL-238), checked
    (`portrait_traits.checked`): its description stays the sheet's, for a painter later, and its seed is the traits'.
    `PlayError` for a portrait that isn't `editable`, one being painted, and traits portraitgen didn't write."""
    if not editable(ctx.storage, character):
        raise PlayError(NOT_EDITABLE, "Repaint the portrait instead.")
    if painting_portrait(ctx.storage, character) is not None:
        raise PlayError(STILL_PAINTING.format(name=character.name), "Wait for it to land.")
    try:
        kept = checked(traits)
    except TraitsError as wrong:
        raise PlayError(f"These aren't portraitgen's traits: {wrong}.", "Save the portrait from the editor.") from None
    portrait = TraitsPortrait(describe(character), kept["seed"], traits=kept)
    _set_portrait(ctx.storage, character, portrait)
    ctx.log("portrait", character_id=character.id, kind="traits", edited=True)
    return portrait


def _tone(storage: Storage, campaign_id: str) -> str:
    """The campaign's tone for the painter: a tone's name, or a custom tone's own words."""
    settings = table.play_settings(storage, campaign_id)
    return str(settings.get("custom_tone") or "") if settings["tone"] == "custom" else str(settings["tone"])


# ----- the subject -----


def find_subject(ctx: CampaignContext, ref: str) -> Subject:
    """The character or the possession with the id `ref`, or the one whose name is exactly `ref` (any case)."""
    wanted = ref.strip()
    everyone = _everyone(ctx.storage, ctx.campaign_id)
    for subject in everyone:
        if subject.id == wanted:
            return subject
    named = [s for s in everyone if s.name.strip().casefold() == wanted.casefold()]
    if len(named) == 1:
        return named[0]
    if named:
        raise NotFound(f"'{ref}' is ambiguous: {len(named)} have that name.", map(_candidate, named))
    near = [s for s in everyone if wanted.casefold() and wanted.casefold() in s.name.casefold()]
    raise NotFound(f"No character or possession '{ref}'.", map(_candidate, near or everyone))


def _everyone(storage: Storage, campaign_id: str) -> list[Subject]:
    return [*storage.characters.list(campaign_id), *storage.possessions.list(campaign_id)]


def _candidate(subject: Subject) -> dict[str, Any]:
    kind = subject.kind if isinstance(subject, Character) else "possession"
    return {"id": subject.id, "name": subject.name, "kind": kind}


def describe(subject: Subject) -> str:
    """A portrait's description from the sheet: its `portrait_prompt`, what the character looks like (DEL-41: age,
    looks, dress), else "a male dwarf fighter". A possession's is its own, or its name. Never the sheet's `notes_md`,
    an NPC's story, which may hold its secrets."""
    if isinstance(subject, Possession):
        return subject.description.strip() or subject.name
    sheet: Sheet = subject.sheet
    if sheet.portrait_prompt.strip():
        return sheet.portrait_prompt.strip()
    words = " ".join(w.strip().lower() for w in (sheet.gender, sheet.race, sheet.cls) if w.strip())
    return f"a {words}" if words else "an adventurer"


def free_portrait(ctx: CampaignContext, character: Character, description: str) -> TraitsPortrait:
    """Set the character's portrait to portraitgen's: `description`, seeded by the character's id."""
    portrait = TraitsPortrait(description, character.id)
    _set_portrait(ctx.storage, character, portrait)
    ctx.log("portrait", character_id=character.id, kind="traits")
    return portrait


def _set_portrait(storage: Storage, subject: Subject, portrait: Portrait) -> None:
    if isinstance(subject, Possession):
        storage.possessions.put(replace(subject, portrait=portrait))
    else:
        storage.characters.save_sheet(replace(subject, sheet=replace(subject.sheet, portrait=portrait)))


def _subject_of(storage: Storage, image: CampaignImage) -> Subject | None:
    if image.subject_id is None:
        return None
    if image.kind == "possession":
        return storage.possessions.get(image.campaign_id, image.subject_id)
    character = storage.characters.get(image.subject_id)
    return character if character is not None and character.campaign_id == image.campaign_id else None


# ----- requests -----


def request(
    ctx: CampaignContext,
    kind: ImageKind,
    subject_id: str | None,
    prompt: str,
    audience: Audience,
    caption: str = "",
    *,
    by_seat: bool = False,
) -> CampaignImage:
    """A `painting` row for the picture, for `audience` (resolved to the seats now, as a story entry is); `paint`
    paints it later. `PlayError` with a hint while paid images are off and the model chosen for the job costs money
    (`ctx.image_paid`); the portrait tool gives portraitgen's portrait instead before it asks. A paid picture is held
    to the campaign's limit for a day (`PaidUsedUp`) and, unless a seat asked for it (`by_seat`), to the DM's limits
    for the beat `ctx.beat`."""
    if kind not in JOBS:
        raise PlayError(f"Unknown picture kind '{kind}'.", f"Use one of {', '.join(JOBS)}.")
    costs = ctx.image_paid(_job(ctx.storage, ctx.campaign_id, kind, subject_id))
    if costs:
        if not paid_images(ctx.storage, ctx.campaign_id):
            raise PlayError(PAID_OFF, PAID_HINT)
        check_paid_limit(ctx.storage, ctx.campaign_id)
        if not by_seat:
            _check_beat(ctx, kind, subject_id)
    image = CampaignImage(
        new_id("img"),
        ctx.campaign_id,
        kind,
        subject_id,
        prompt=prompt.strip(),
        caption=caption.strip(),
        audience=resolve(ctx.storage, ctx.campaign_id, audience),
    )
    stored = ctx.storage.campaign_images.put(image)
    ctx.log(REQUESTED, image_id=stored.id, kind=kind, subject_id=subject_id, paid=costs)
    return stored


def check_paid_limit(storage: Storage, campaign_id: str) -> None:
    """`PaidUsedUp` when the campaign has asked for its `paid_limit` of paid pictures in the last 24 hours."""
    since = now() - DAY
    asked = [e for e in _paid_requests(storage, campaign_id) if datetime.fromisoformat(e.at) > since]
    limit = paid_limit(storage, campaign_id)
    if len(asked) >= limit:
        raise PaidUsedUp(PAID_USED_UP.format(limit=limit), PAID_USED_UP_HINT)


def _check_beat(ctx: CampaignContext, kind: ImageKind, subject_id: str | None) -> None:
    """The DM's limits for a beat: `SCENES_PER_BEAT` paid scenes, and one paid picture of each subject."""
    asked = [e.data for e in _paid_requests(ctx.storage, ctx.campaign_id) if e.beat == ctx.beat]
    if kind == SCENE and sum(1 for data in asked if data.get("kind") == SCENE) >= SCENES_PER_BEAT:
        raise PlayError(BEAT_SCENES.format(n=SCENES_PER_BEAT), BEAT_HINT)
    if subject_id is not None and any(data.get("subject_id") == subject_id for data in asked):
        subject = next((s for s in _everyone(ctx.storage, ctx.campaign_id) if s.id == subject_id), None)
        raise PlayError(BEAT_SUBJECT.format(name=subject.name if subject else "it"), BEAT_HINT)


def _paid_requests(storage: Storage, campaign_id: str) -> list[Event]:
    """The campaign's requests for a picture that costs money, oldest first (those before DEL-153 say nothing)."""
    return [e for e in storage.events.list(campaign_id, types=[REQUESTED]) if e.data.get("paid") is True]


async def paint_this_scene(services: AppServices, campaign_id: str, hint: str = "") -> CampaignImage:
    """The host's "Paint this scene": a side pass writes a painter's brief from the last two narrations everyone
    read, and the hint, and the scene is requested for everyone and scheduled. `PlayError` while paid images are off
    and the scene's model costs money, or before any narration; `PaidUsedUp` past the campaign's limit for a day;
    `BriefFailed` when the side pass writes none."""
    storage = services.storage
    costs = services.image_paid(Job.IMAGE_SCENE)
    if costs and not paid_images(storage, campaign_id):
        raise PlayError(PAID_OFF, PAID_HINT)
    if costs:
        check_paid_limit(storage, campaign_id)  # before the side pass: no brief for a picture that won't be painted
    narrations = [
        str(e.payload.get("text", "")).strip()
        for e in storage.story.list(campaign_id, limit=200)
        if e.kind == "dm_text" and e.audience is None and str(e.payload.get("text", "")).strip()
    ][-NARRATIONS:]
    if not narrations:
        raise PlayError(NOTHING_TO_PAINT, "Play a beat first.")
    provider, choice = services.side(campaign_id)
    try:
        brief = (await provider.side_call(brief_prompt(narrations, hint), choice, timeout=BRIEF_TIMEOUT)).strip()
    except Exception as error:  # any provider failure is the same refusal to the host
        raise BriefFailed("The scene's brief couldn't be written.", "Try again in a moment.") from error
    if not brief:
        raise BriefFailed("The scene's brief came back empty.", "Try again in a moment.")
    ctx = context_for(
        storage,
        campaign_id,
        "scene",
        image_paid=services.image_paid,
        catalogs=services.catalogs,
    )
    with storage.transaction():
        image = request(ctx, "scene", None, brief, None, by_seat=True)
    schedule(services, image.id)
    return image


def brief_prompt(narrations: list[str], hint: str = "") -> str:
    """The side pass's prompt: ttrpg2's rule of the brief, the narrative, and the host's hint."""
    narrative = "\n\n".join(narrations)
    hint = hint.strip()
    message = f"NARRATIVE:\n{narrative}"
    if hint:
        message += (
            f"\n\nHINT (the host's direction for the illustrator — prioritise this when shaping the prompt): {hint}"
        )
    return f"{SCENE_BRIEF}\n\n{message}"


# ----- painting -----


async def paint(services: AppServices, image_id: str) -> CampaignImage | None:
    """Paint the row `image_id` if it is still `painting`, and land the result; answers the row as it ends. A
    provider's failure is the row's `failed`, never an exception; a cancelled painting stays `painting`."""
    storage = services.storage
    image = storage.campaign_images.get(image_id)
    if image is None or image.status != "painting":
        return image
    job = _job(storage, image.campaign_id, image.kind, image.subject_id)

    def watched(queued: ProviderJob) -> None:
        nonlocal image
        image = storage.campaign_images.put(replace(image, provider_job=queued.id, queue=queued.position))
        _painting_changed(services, image)

    try:
        if services.images is None:
            raise PlayError(f"No provider does the {job} job.")
        provider, choice = services.images(job)
        # The provider's job from an earlier start is followed, and that start isn't counted again.
        follow = image.provider_job if image.provider_job and image.backend == choice.provider else ""
        attempts = image.attempts if follow else image.attempts + 1
        image = storage.campaign_images.put(
            replace(image, attempts=attempts, backend=choice.provider, provider_job=follow or None, queue=None)
        )
        req = ImageRequest(
            job,
            image.prompt,
            choice,
            tone=_tone(storage, image.campaign_id),
            style=stored_style_text(storage.settings.load()),
            aspect=ASPECTS.get(image.kind, ""),
            follow=follow,
            watch=watched,
        )
        result = await provider.generate(req)
    except asyncio.CancelledError:
        raise
    except Exception as error:  # noqa: BLE001 (a painting always ends, never a stuck row)
        return _failed(services, image, _reason(error))
    if isinstance(result, ImageFile):
        sha = storage.blobs.put(result.data, result.mime)
        done = replace(image, status="done", blob=sha, mime=result.mime, error=None, queue=None)
        picture: Portrait = ImagePortrait(image.id)
    elif isinstance(result, PortraitTraits) and image.kind == "portrait" and image.subject_id is not None:
        done = replace(image, status="done", error=None, queue=None)
        picture = TraitsPortrait(result.describe or image.prompt, image.subject_id)
    else:
        return _failed(services, image, "The provider answered no picture.")
    return _landed(services, done, picture)


def _landed(services: AppServices, image: CampaignImage, picture: Portrait) -> CampaignImage | None:
    storage = services.storage
    if storage.campaigns.get(image.campaign_id) is None:
        return None  # the campaign went while it was painted
    cid = image.campaign_id
    if image.kind == BANNER:
        with storage.transaction():
            stored = storage.campaign_images.put(image)
            for older in storage.campaign_images.list(cid, kind=BANNER):
                if older.id == image.id:
                    break  # the list is oldest first: the rest are newer
                storage.campaign_images.delete(older.id)
        _banner_changed(services, image)
        return stored
    with storage.transaction():
        stored = storage.campaign_images.put(image)
        if image.kind == SCENE:
            entry = table.add_entry(storage, cid, None, SCENE, scene_view(image.id, image.caption), image.audience)
        else:
            entry = None
            subject = _subject_of(storage, image)
            if subject is not None:
                _set_portrait(storage, subject, picture)
    if entry is not None:
        table.told(services, entry)
        _scenes_changed(services, cid)
    else:
        _subject_changed(services, image)
    return stored


def _failed(services: AppServices, image: CampaignImage, reason: str) -> CampaignImage | None:
    """The row as failed with `reason`, a notice for the host, and a character's portrait from portraitgen unless it
    has a painted one."""
    storage = services.storage
    if storage.campaigns.get(image.campaign_id) is None:
        return None
    cid = image.campaign_id
    if image.kind == BANNER:  # its error is for the campaign's page, not the story nor any seat
        stored = storage.campaign_images.put(replace(image, status="failed", error=reason[:500], queue=None))
        services.publish("campaigns", {"id": cid})
        return stored
    with storage.transaction():
        stored = storage.campaign_images.put(replace(image, status="failed", error=reason[:500], queue=None))
        subject = _subject_of(storage, image)
        if image.kind == SCENE or subject is None:
            notice = SCENE_FAILED if image.kind == SCENE else PICTURE_FAILED.format(name="it")
        elif isinstance(subject, Character):
            notice = PORTRAIT_FAILED.format(name=subject.name)
            if not isinstance(subject.sheet.portrait, ImagePortrait):
                _set_portrait(storage, subject, TraitsPortrait(image.prompt or describe(subject), subject.id))
        else:
            notice = PICTURE_FAILED.format(name=subject.name)
        host = _host_seat(storage, cid)
        entry = table.add_entry(storage, cid, None, "dm_error", {"message": notice}, for_seats([host] if host else []))
    table.told(services, entry)
    if image.kind == SCENE:
        _scenes_changed(services, cid)
    if isinstance(subject, Character):
        _subject_changed(services, image)
    return stored


def _reason(error: Exception) -> str:
    if isinstance(error, PlayError):
        return error.message
    return str(error) or type(error).__name__


def _host_seat(storage: Storage, campaign_id: str) -> str | None:
    return next((s.id for s in storage.seats.list(campaign_id) if s.role == "host" and s.left_at is None), None)


def _subject_changed(services: AppServices, image: CampaignImage) -> None:
    """A character's portrait is in `characters`; a possession's picture is in the world."""
    kind = "world" if image.kind == "possession" else "characters"
    services.publish(kind, {"campaign_id": image.campaign_id}, scope="table", campaign_id=image.campaign_id)


def _scenes_changed(services: AppServices, campaign_id: str) -> None:
    """A scene began painting, landed or failed: the table reads its placeholders again (`painting_scenes`)."""
    services.publish("scenes", {"campaign_id": campaign_id}, scope="table", campaign_id=campaign_id)


def _painting_changed(services: AppServices, image: CampaignImage) -> None:
    """A painting got its provider's job, or moved in the provider's queue: whoever shows it reads it again."""
    if image.kind == SCENE:
        _scenes_changed(services, image.campaign_id)
    elif image.kind == BANNER:
        services.publish("campaigns", {"id": image.campaign_id})
    else:
        _subject_changed(services, image)


def _banner_changed(services: AppServices, image: CampaignImage) -> None:
    """The table reads the banner; the campaign's page reads it and its error."""
    cid = image.campaign_id
    services.publish("banner", {"campaign_id": cid, "image_id": image.id}, scope="table", campaign_id=cid)
    services.publish("campaigns", {"id": cid})


# ----- the worker -----


def schedule(services: AppServices, image_id: str) -> bool:
    """Paint the row in a task of its own, unless it is being painted already; whether it was scheduled."""
    if image_id in services.painting:
        return False
    task = asyncio.create_task(_paint_logged(services, image_id))
    services.painting[image_id] = task

    def finished(done: asyncio.Task) -> None:
        if services.painting.get(image_id) is done:
            del services.painting[image_id]

    task.add_done_callback(finished)
    image = services.storage.campaign_images.get(image_id)
    if image is not None and image.kind == SCENE:
        _scenes_changed(services, image.campaign_id)
    return True


async def _paint_logged(services: AppServices, image_id: str) -> None:
    try:
        await paint(services, image_id)
    except asyncio.CancelledError:
        raise
    except Exception:  # the row stays painting; the next start tries it again
        log.exception("painting %s failed", image_id)


def schedule_waiting(services: AppServices, campaign_id: str) -> list[str]:
    """Schedule the campaign's rows a tool call just requested (never started); the ids scheduled."""
    waiting = services.storage.campaign_images.list(campaign_id, status="painting")
    return [image.id for image in waiting if image.attempts == 0 and schedule(services, image.id)]


def resume(services: AppServices) -> None:
    """At start: go on with every row a stopped Delve left `painting`. One whose provider has its job follows that job
    (a restart isn't a failed attempt); one without is asked for again, once: asked twice already, it fails."""
    for image in services.storage.campaign_images.painting():
        if image.attempts >= 2 and not image.provider_job:
            _failed(services, image, INTERRUPTED)
        else:
            schedule(services, image.id)


def stop(services: AppServices) -> list[asyncio.Task]:
    """Cancel the paintings under way, which stay `painting` for the next start; the tasks, to await. Only this
    event loop's: another loop's (a second test client on the same app) is that loop's to stop."""
    loop = asyncio.get_running_loop()
    tasks = [task for task in services.painting.values() if task.get_loop() is loop]
    for task in tasks:
        task.cancel()
    return tasks


# ----- who sees a picture -----


def painting_scenes(storage: Storage, seat: Seat) -> list[dict[str, Any]]:
    """The scenes still painting that the seat will see when they land, oldest first, as `{image_id, caption,
    provider, queue}`: the story shows a placeholder for each (DEL-115), with its place in the provider's queue while
    it waits there (DEL-138). The brief never leaves the server."""
    controls = seat_controls(storage, seat)
    return [
        {"image_id": image.id, "caption": image.caption, **waiting(image)}
        for image in storage.campaign_images.list(seat.campaign_id, kind=SCENE, status="painting")
        if audience.can_see(seat, image.audience, controls)
    ]


def waiting(image: CampaignImage) -> dict[str, Any]:
    """A painting's `{provider, queue}`: who paints it, and its place in that provider's queue (None once it runs, or
    when the provider doesn't say)."""
    return {"provider": image.backend, "queue": image.queue}


def painting_portrait(storage: Storage, character: Character) -> dict[str, Any] | None:
    """The `waiting` of the character's newest portrait still painting; None when none is."""
    rows = storage.campaign_images.list(character.campaign_id, kind="portrait", status="painting")
    mine = [image for image in rows if image.subject_id == character.id]
    return waiting(mine[-1]) if mine else None


def portrait_failed(storage: Storage, character: Character) -> bool:
    """Whether the character's newest portrait failed to paint and nothing has replaced its stand-in since: no later
    painting, and no free portrait set after it (the `portrait` event `free_portrait` logs). The sheet then offers Try
    again (DEL-135)."""
    mine = storage.campaign_images.list(character.campaign_id, kind="portrait", subject_id=character.id)
    if not mine or mine[-1].status != "failed":
        return False
    failed_at = datetime.fromisoformat(mine[-1].created_at)
    return not any(
        e.data.get("character_id") == character.id and datetime.fromisoformat(e.at) > failed_at
        for e in storage.events.list(character.campaign_id, types=["portrait"])
    )


def can_see(storage: Storage, seat: Seat, image: CampaignImage) -> bool:
    """Whether the seat may see the painted picture: a subject's portrait and the campaign's banner are everyone's at
    the table, a scene is for its audience."""
    if image.status != "done" or image.blob is None or image.campaign_id != seat.campaign_id:
        return False
    if image.kind == SCENE:
        return audience.can_see(seat, image.audience, seat_controls(storage, seat))
    return audience.can_see(seat, None, set())
