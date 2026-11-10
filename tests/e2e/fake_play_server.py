"""`delve serve` on a fake `claude`, for the browser checks (`make e2e-browser`, `web/e2e/*.spec.ts`).

    python -m tests.e2e.fake_play_server --port 47811

It makes a fresh data directory in the temp folder, builds the reference there, imports the Crypt of Saint Vellis
with a campaign on the seeded house rules, puts `tests/fixtures/fake_claude.py` first on `PATH` as `claude`, and
then becomes `delve serve` on 127.0.0.1. The fake's first beat builds a party through the real bridge, then thinks
for a few seconds before it narrates, so the page can be reloaded in the middle of it. Its second beat
(`web/e2e/table.spec.ts`, a table of a host and a Dutch player) tells Pippa something alone, then narrates in two
paragraphs, which the fake translates into Dutch as `NL: …`, and the player's Dutch act into English from
`TRANSLATIONS`. The real `claude` never runs.

The campaign is in Greyhawk, its party placed in the Free City on the setting's region map, and the first beat draws
Garrek's and Pippa's portraits with portraitgen, for the World panel and the portraits (`web/e2e/world.spec.ts`), and Prior Anselm's, an NPC of the campaign with the
planted secret in his DM notes, who then speaks a frightened line through `say` between two narrations, for the said
line (`web/e2e/play.spec.ts`). The campaign starts in the `illustrated` style; the world's spec chooses `inkwash` on
the campaign page, and saves and removes a fake Replicate token in Connections (no `REPLICATE_*` variable reaches the
server, and nothing is painted for money). Its banner waits in storage, and Delve paints it with the free fake
images when it starts (`web/e2e/looks.spec.ts`).
The DM has proposed a fact to the setting for it (`HARBOUR_MASTER`, pending), and the install holds a DM-only fact
(`HIDDEN_FACT`, with the planted secret), for the Settings area and the Setting tab (`web/e2e/settings.spec.ts`).

A conversion's side calls (`web/e2e/new-module.spec.ts`) are answered by their prompt, with the answers of
`tests/e2e/test_books_and_quick_dungeons.py`: `claude` on `PATH` is this file with `--claude`, which answers those
and hands every other call to the fake. Converting a chunk takes a few seconds, so the page can be seen and reloaded
during the conversion. `--book PATH` writes that test's PDF, for the page to upload. A dungeon map drawn from a
description (`web/e2e/worldmap.spec.ts`) is the warren's, or the shrine's when the description names a shrine.

The faithful book of `tests/e2e/test_a_faithful_book.py` (`web/e2e/zz-faithful.spec.ts`, last by file order), which
`--faithful-book PATH` writes: its side and vision calls (the conversion, the classifying, the gaps, the dedupe and the
drafts from its two map pages) are answered by their prompt with that test's answers (`faithful_answer`), and the
fake's fifth beat (after the tavern's and the fight's) makes its campaign's party from the module's pregens, as that test's first beat does; the beats
after it narrate a line each (`STORY_LINES`), for a story long enough to scroll back. The spec makes
its module, campaign and story itself, through the API, at its start: nothing of it is made here.

A novel's side calls (`web/e2e/x-novels.spec.ts`, after the world maps') are answered by their prompt with the answers
of `tests/e2e/test_a_novel.py` (`novel_answer`): an outline of three chapters for a short story, then each chapter, a
few seconds each, so the progress can be watched. The spec novelizes the crypt's campaign once it has been played.

A history's side calls (`web/e2e/y-carry.spec.ts`, after the novel's) are answered by their prompt (`history_answer`):
the DM's text, with its Loose ends, then the table's, a few seconds each, so the progress can be watched. The spec
carries the crypt's party on into the module New module made.

A world map's picture (`web/e2e/worldmap.spec.ts`, `tests/e2e/test_read_a_world_map.py`) is the synthetic `hex_map`
of `tests/maps/geo/pictures.py`, which `--picture PATH` writes as a PNG. Its vision calls (`--input-format
stream-json` without `--mcp-config`: the colours and the labels) are answered by their prompt from that picture's
truth (`fake_look`); any other vision call goes to the fake. `DELVE_OCR=off`: tesseract never runs, so the labels come
from the vision calls.

The fake's fourth beat is a fight (`FIGHT`, `web/e2e/timeline.spec.ts`, after the thorough conversion's): its own
campaign's party of two, one of them casting Sleep, two goblins, and a spell the DM rules interrupted, for the
initiative timeline on desktop and on a phone.

A thorough conversion (`web/e2e/thorough-conversion.spec.ts`, thorough conversion Task 8) converts the fake agent's
book, which `--thorough-book PATH` writes (the house and the ship, keyed 1, 2, 3 each, the house's map on page 3). Its
agent sessions (`claude -p --tools Read,Write,…`) are `tests/fakes/fake_claude_agent.py`, which the `claude` wrapper
runs straight away (`agent_dispatch`), and whose first cleaning session
meets the usage limit, "resets 3am (UTC)" (`AGENT_PLAN`): the job pauses, for the page to show it and Resume it. The
second cleaning session is slow, so the spec queues a second book behind it and pauses it by hand. Its
side calls (the drafts, the entities, the ship's sketch) are answered as the pipeline tests answer them
(`thorough_answer`). The book is marked by its texts, so no other book's calls get these answers.

The Storage section and the library (`web/e2e/zzz-storage.spec.ts`, cloud storage, last by file order) work against
folders, never a cloud: `--stores DIR` makes `backups`, `library` and `library-read` (the library's folder again, read
only) there, and Delve opens them as `LocalStore`s (`fake_stores`). The backups' folder refuses the settings' objects,
so a backup run fails in part; the library's read-only view probes as the read right. No credential exists anywhere.
"""

from __future__ import annotations

import argparse
import base64
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from delve.cloud import connections
from delve.cloud.store import LocalStore, Refused
from delve.config import Config
from delve.dm.claude_cli.agent import TOOLS as AGENT_TOOLS
from delve.domain import new_id
from delve.domain.characters import Sheet
from delve.domain.setting_content import SettingFact
from delve.domain.world import CampaignImage
from delve.modules.dscn import Bundle
from delve.modules.importer import import_bundle
from delve.packs.catalogs import Catalogs
from delve.packs.transit import install_pack
from delve.play import banners, proposals, world_maps
from delve.play.context import context_for
from delve.play.house_rules import seed_house_rules, set_campaign_house_rules
from delve.play.images import BANNER
from delve.play.setting_layer import layer_for
from delve.setting.catalog import make_setting
from delve.storage import open_storage
from tests.conversions.test_worldmap_job import _answer as looked
from tests.conversions.thorough.test_pipeline import _answer as pipeline_answer
from tests.conversions.thorough.test_pipeline import _book as thorough_book
from tests.e2e.fake_fixit import fixit_answer
from tests.e2e.test_a_faithful_book import TURNS as FAITHFUL_TURNS
from tests.e2e.test_a_faithful_book import book_pdf as faithful_pdf
from tests.e2e.test_a_faithful_book import faithful_answer
from tests.e2e.test_a_novel import OUTLINE_PROMPT, novel_answer
from tests.e2e.test_books_and_quick_dungeons import SHRINE_MAP, WARREN_MAP, answer_for, book_pdf
from tests.e2e.test_play_with_fake_claude import FORBIDDEN_PORTS, GARREK, PIPPA, SECRET
from tests.fakes import fake_claude_agent
from tests.fixtures import SAMPLES, fake_claude
from tests.maps.geo.pictures import fake_look, hex_map

STORY_LINES = [
    line
    for n in range(1, 31)
    for line in (
        f"The floorboards creak under Aldon's boots ({n}).",
        f"Wind rattles the shutters of the old house, and somewhere below water drips ({n}).",
    )
]
"""The beats after the party's in the faithful book's campaign, for a story long enough to scroll back."""
THINKING_S = 6
CONVERTING_S = 6
WRITING_S = 3
ROOT = Path(__file__).resolve().parents[2]

ANSELM = "Prior Anselm"
"""The crypt's quest giver, an NPC of the campaign from the start, with the planted secret in his DM notes: the first
beat draws his portrait and he speaks a line through `say` (`web/e2e/play.spec.ts`), between two narrations."""
ANSELM_LOOKS = "an elderly human prior, bald, grey stubble, a worried frown"
ANSELM_SAYS = "Thank the saint you have come. Something stirs below the chapel, and the brothers will not go down."
TAVERN_REPLY = "The innkeeper sets down two mugs, and the fire crackles in the hearth."
"""The third beat: the one a player of the tavern's campaign plays (`web/e2e/tavern.spec.ts`), between the table's and the
faithful book's. The fake's turns are one queue for every campaign."""
MIRELA = {
    "race": "Elf",
    "cls": "Mage",
    "level": 1,
    "hp_max": 4,
    "ac": 10,
    "thac0": 20,
    "ability_scores": {"str": 8, "dex": 15, "con": 10, "int": 17, "wis": 11, "cha": 12},
    "attacks": [{"name": "dagger", "speed": 2, "attacks": 1, "thac0": 20, "damage_sm": "1d4", "damage_l": "1d3"}],
    "movement_rate": 12,
}
TANSY = {
    "race": "Human",
    "cls": "Cleric",
    "level": 1,
    "hp_max": 8,
    "ac": 5,
    "thac0": 20,
    "ability_scores": {"str": 12, "dex": 10, "con": 14, "int": 10, "wis": 16, "cha": 11},
    "attacks": [{"name": "mace", "speed": 7, "attacks": 1, "thac0": 20, "damage_sm": "1d6+1", "damage_l": "1d6"}],
    "movement_rate": 12,
}
FIGHT_REPLY = "A sling stone cracks against Mirela's temple, and the words of her Sleep spell die on her lips."
"""The fourth beat: a fight (`web/e2e/timeline.spec.ts`, table voice and fixes Task B2.4), in the spec's own campaign.
Mirela casts Sleep against two goblins; the DM thinks a while (the timeline shows her span before any narration),
rules that she was hit (`interrupt`: the real dice can't be scripted through the bridge), resolves the round, and
narrates it, after which the timeline marks the spell interrupted."""
FIGHT = [
    {"tool": "create_character", "args": {"name": "Mirela", "sheet": MIRELA}},
    {"tool": "create_character", "args": {"name": "Tansy", "sheet": TANSY}},
    {
        "tool": "setup_combat",
        "args": {
            "enemies": [{"name": "goblin", "count": 2}],
            "surprise": False,
            "spells": [{"caster": "Mirela", "spell": "Sleep"}],
        },
    },
    {"sleep": THINKING_S},
    {"tool": "interrupt", "args": {"combatant": "Mirela", "reason": "Mirela was hit"}},
    {"tool": "combat_round", "args": {"actions": []}},
    {"text": FIGHT_REPLY},
]
TURNS = [
    [
        {"text": "Let me roll up your party. "},
        {"tool": "session_primer", "args": {}},
        {"tool": "new_session", "args": {"title": "Into the crypt"}},
        {"tool": "create_character", "args": {"name": "Garrek", "sheet": GARREK}},
        {"tool": "create_character", "args": {"name": "Pippa", "sheet": PIPPA}},
        {"tool": "set_marching_order", "args": {"order": ["Garrek", "Pippa"]}},
        {"tool": "portrait", "args": {"of": "Garrek", "description": "a broad human fighter, black beard, scarred"}},
        {"tool": "portrait", "args": {"of": "Pippa", "description": "a young halfling thief with red curls, smiling"}},
        {"sleep": THINKING_S},
        {"tool": "move_party", "args": {"to": "Entry Hall"}},
        {
            "text": (
                "Garrek the fighter and Pippa the thief go down the worn stairs into the **Entry Hall**, where "
                "Prior Anselm waits with a lamp that shakes in his hand."
            )
        },
        {"tool": "portrait", "args": {"of": ANSELM, "description": ANSELM_LOOKS}},
        {"tool": "say", "args": {"npc": ANSELM, "text": ANSELM_SAYS, "mood": "afraid"}},
        {"text": '"Dust and old incense," Pippa whispers. The hall is quiet, and a draught comes from the east.'},
    ],
    [
        {"tool": "tell", "args": {"characters": ["Pippa"], "text": "Pippa alone hears a voice behind the altar."}},
        {
            "text": (
                "The chapel door creaks open on a dusty nave.\n\n"
                "A cold draught comes from the east, and the candles gutter."
            )
        },
    ],
    [{"text": TAVERN_REPLY}],
    FIGHT,
    FAITHFUL_TURNS[0],
    *([{"text": line}] for line in STORY_LINES),
]
TRANSLATIONS = {"Ik open de deur van de kapel.": "I open the chapel door."}
DESCRIBED = "You draw the map of a tabletop adventure's dungeon"
LOOKS = ("# The terrain colours of a map picture", "# Labels on a map picture")
HARBOUR_MASTER = "The Free City's new harbour master is a half-orc."
"""The DM's proposal to the setting, pending, for the Proposals tab (`web/e2e/settings.spec.ts`)."""
HIDDEN_FACT = f"{SECRET}: the harbour master takes the Scarlet Brotherhood's gold."
"""A DM-only fact of the install's, which no seat's Setting tab may show."""
HISTORY_PROMPT = "You are the chronicler of a party of adventurers."
TABLE_HISTORY = (
    "## The party\n\nGarrek the fighter and Pippa the thief went down into the Crypt of Saint Vellis together, and "
    "both came out alive.\n\n"
    "## People met\n\n- **Prior Anselm**, the frightened prior of the chapel above the crypt, who sent them down.\n\n"
    "## Deeds\n\nThey opened the chapel door that the brothers would not go near.\n\n"
    "## Grudges and debts\n\nThe Prior owes them for going where his brothers would not.\n\n"
    "## Loot\n\nNothing of note yet."
)
"""The table's history the fake writes for the crypt's party."""
DM_HISTORY = (
    TABLE_HISTORY + "\n\n## Loose ends\n\n- Prior Anselm hid the key below the chapel; the party never learned it."
)
"""The DM's history: the table's, with its Loose ends, which no seat but the host and co-hosts reads."""


def history_answer(prompt: str) -> str | None:
    """The fake writer's answer to a history's side call, by its prompt: the DM's text when it asks for Loose ends,
    else the table's; None for any other prompt."""
    if not prompt.startswith(HISTORY_PROMPT):
        return None
    return DM_HISTORY if "`## Loose ends`" in prompt else TABLE_HISTORY


AGENT_PLAN = {"plan": {"clean-1": ["limit", "slow"]}, "resets": "3am (UTC)", "slow_seconds": 120}
"""The fake agent's plan for the thorough conversion: its first cleaning session meets the usage limit, and the
second works slowly, so the organiser can pause it by hand while a second book waits in the queue."""
THOROUGH_MARKS = (fake_claude_agent.HOUSE[2], fake_claude_agent.SHIP[2])
"""Lines of the fake agent's book: a side call whose prompt holds one is the thorough conversion's."""


def thorough_answer(prompt: str) -> str | None:
    """The answer to a side call of the thorough conversion of the fake agent's book, as the pipeline tests answer it;
    None for any other prompt."""
    if not any(mark in prompt for mark in THOROUGH_MARKS):
        return None
    return pipeline_answer(prompt)


SIDE = ["A surprised character can't act for one round (PHB, chapter 9). A d10 roll of 1-3 surprises."]


def prepare(root: Path, packs: Path | None = None) -> dict[str, str]:
    """The data dir, the fake `claude` and its script under `root`; the environment for `delve serve`. OSRIC is
    installed into the data dir, or its `packs/` links to `packs`, a folder where it already is (a test's, so the
    test process imports OSRIC from one folder only)."""
    data_dir = root / "data"
    data_dir.mkdir(parents=True)
    config = Config(data_dir=data_dir)
    if packs is not None:
        config.packs_dir.symlink_to(packs)
    else:
        root = Path(__file__).resolve().parents[2]
        for pack in (root / "packs" / "osric", root / "tests" / "fixtures" / "packs" / "greyhawk"):
            install_pack(pack, config.packs_dir)
    storage = open_storage(config)
    try:
        bundle = seed_house_rules(storage)
        module = import_bundle(storage, Bundle.load(SAMPLES / "scenarios" / "crypt-of-saint-vellis").to_zip()).module
        revision = storage.revisions.latest(module.id) or storage.revisions.snapshot(module.id)
        campaign = storage.campaigns.create(
            "The Crypt of Saint Vellis", module.id, revision.number, ruleset="osric", setting="greyhawk"
        )
        storage.characters.create(
            campaign.id,
            ANSELM,
            kind="npc",
            sheet=Sheet(kind="npc", race="human", notes_md=f"{SECRET}: he hid the key."),
        )
        set_campaign_house_rules(storage, campaign.id, bundle_ids=[bundle.id], rule_ids=[])
        catalogs = Catalogs.installed(config)
        world_maps.place_party(context_for(storage, campaign.id, "setup", catalogs=catalogs), "greyhawk")
        setting_of = make_setting(campaign.setting, catalogs.settings)
        layer = layer_for(storage, setting_of, campaign_id=campaign.id, dm=True)
        proposals.propose_fact(storage, layer, campaign.id, HARBOUR_MASTER)
        storage.setting_facts.add(SettingFact(0, layer.id, HIDDEN_FACT, "", True))
        # Made here, not through the API, the campaign asks for its banner as the API would: free fake images paint
        # it when Delve starts (`banners.wake`), for the empty story's banner (`web/e2e/looks.spec.ts`).
        setting = make_setting(campaign.setting, catalogs.settings)
        metadata = module.metadata
        prompt = banners.brief(
            module.title,
            metadata["summary"] if isinstance(metadata.get("summary"), str) else "",
            metadata["description"] if isinstance(metadata.get("description"), str) else "",
            setting.title if setting is not None else campaign.setting or "",
        )
        storage.campaign_images.put(CampaignImage(new_id("img"), campaign.id, BANNER, status="waiting", prompt=prompt))
    finally:
        storage.close()
    fake = root / "fake"
    wrapper = fake_claude.install(fake / "bin")
    wrapper.write_text(
        agent_dispatch() + f'PYTHONPATH="{ROOT}" exec "{sys.executable}" -m tests.e2e.fake_play_server --claude "$@"\n',
        encoding="utf-8",
    )
    script = fake / "script.json"
    script.write_text(json.dumps({"turns": TURNS, "side": SIDE, "translations": TRANSLATIONS}), encoding="utf-8")
    agent = fake / "agent.json"
    agent.write_text(json.dumps({**AGENT_PLAN, "log": str(fake / "agent-log.jsonl")}), encoding="utf-8")
    return {
        # No token of the owner's: Connections (`web/e2e/world.spec.ts`) start unset, and nothing is painted for money.
        **{k: v for k, v in os.environ.items() if not k.startswith(("DELVE_", "FAKE_CLAUDE_", "REPLICATE_"))},
        "PATH": f"{fake / 'bin'}:{os.environ.get('PATH', '/usr/bin:/bin')}",
        "DELVE_DATA_DIR": str(data_dir),
        "FAKE_CLAUDE_SCRIPT": str(script),
        "FAKE_CLAUDE_ARGV_LOG": str(fake / "argv.jsonl"),
        "FAKE_AGENT_CONFIG": str(agent),
        "DELVE_DM_TURN_TIMEOUT": "60",
        "DELVE_OCR": "off",
    }


STORES_PREFIX = "delve-e2e-stores-"
"""The start of the stores' folder's name: only a folder so named is emptied at start."""


class RefusingSettings(LocalStore):
    """The backups' folder: it refuses to write a setting's object, as a store that broke off would, so a backup run
    uploads the modules and campaigns and fails in part."""

    async def put(self, name: str, data: bytes) -> None:
        if "/settings/" in name:
            raise Refused("The store refused the write.")
        await super().put(name, data)


def make_stores(root: Path) -> None:
    """`root` fresh, with `backups`, `library`, and `library-read`, the library's folder again."""
    if root.exists():
        if not root.name.startswith(STORES_PREFIX):
            raise SystemExit(f"{root} isn't the e2e stores' folder ({STORES_PREFIX}…); not emptying it")
        shutil.rmtree(root)
    for name in ("backups", "library"):
        (root / name).mkdir(parents=True)
    (root / "library-read").symlink_to(root / "library", target_is_directory=True)


def fake_stores(root: Path) -> None:
    """Delve opens the folders of `make_stores` as their stores: `backups` refusing the settings, and `library-read`
    read only. Any other store opens as it would."""
    opened = connections.Stores.open

    def open_store(self: connections.Stores, config: connections.StoreConfig):
        if config.provider == "local" and Path(config.root) == root / "backups":
            return RefusingSettings(root / "backups")
        if config.provider == "local" and Path(config.root) == root / "library-read":
            return LocalStore(root / "library-read", read_only=True)
        return opened(self, config)

    connections.Stores.open = open_store  # type: ignore[method-assign]


def fake_mail() -> None:
    """Email (DEL-314) with no network: Emailit's answers are an `httpx.MockTransport` giving 200 `{"id": "em_e2e"}`
    and keeping what it was handed, and `GET /api/e2e/mail` (made here, never in the app) shows it as `{"messages":
    [{"to", "subject", "text", "headers"}]}`, for `web/e2e/yz-email.spec.ts` to read its links. The spec turns the
    Email connection to Emailit itself (a fake key)."""
    import httpx

    from delve.web import app as web_app

    sent: list[dict[str, object]] = []

    def answer(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        sent.append(
            {
                "to": body.get("to"),
                "subject": body.get("subject"),
                "text": body.get("text"),
                "headers": body.get("headers") or {},
            }
        )
        return httpx.Response(200, json={"id": "em_e2e"})

    made = web_app.create_app

    def create_app(*args, **kwargs):
        app = made(*args, **kwargs)
        app.state.mail_transport = httpx.MockTransport(answer)

        async def outbox() -> dict[str, object]:
            return {"messages": sent}

        app.add_api_route("/api/e2e/mail", outbox, methods=["GET"])
        # Before the app's own catch-all routes.
        app.router.routes.insert(0, app.router.routes.pop())
        return app

    web_app.create_app = create_app  # type: ignore[assignment]


def serve(stores: Path, port: int) -> int:
    """`delve serve` in this process, with the stores' folders opened by `fake_stores` and Emailit by `fake_mail`."""
    from delve.__main__ import main as delve

    fake_stores(stores)
    fake_mail()
    return delve(["serve", "--host", "127.0.0.1", "--port", str(port)])


def picture_png() -> bytes:
    """The synthetic world map's picture, as the organiser uploads it."""
    out = io.BytesIO()
    hex_map().image.save(out, "PNG")
    return out.getvalue()


def vision(fake: list[str]) -> int:
    """A vision call: the picture reading's, answered from the synthetic picture's truth by its prompt, or the faithful
    book's (`faithful_answer`), as an `assistant` and a `result` line; any other goes to the fake, with its message on
    the fake's stdin."""
    raw = sys.stdin.buffer.read()
    content = json.loads(raw.decode("utf-8").strip().splitlines()[0])["message"]["content"]
    prompt = "".join(block.get("text", "") for block in content if block.get("type") == "text")
    answer = faithful_answer(prompt)
    if answer is None and not prompt.startswith(LOOKS):
        return subprocess.run(fake, input=raw, check=False).returncode
    if answer is None:
        [image] = [block for block in content if block.get("type") == "image"]
        source = image["source"]
        answer = looked(fake_look(hex_map().truth), prompt, base64.b64decode(source["data"]), source["media_type"])
    session = {"session_id": "fake-look"}
    for line in (
        {
            "type": "assistant",
            **session,
            "message": {"role": "assistant", "content": [{"type": "text", "text": answer}]},
        },
        {"type": "result", "subtype": "success", "is_error": False, "result": answer, **session, "total_cost_usd": 0.0},
    ):
        sys.stdout.write(json.dumps(line) + "\n")
    return 0


def agent_dispatch() -> str:
    """The start of the `claude` wrapper: a thorough agent session (`--tools` with the agent's tools) goes straight to
    the fake agent. Through this module, whose imports take most of a second, a session paused that soon after its
    start would stop before it took its plan's step, and the next session would take it instead."""
    agent = f'"{sys.executable}" "{Path(fake_claude_agent.__file__).resolve()}"'
    return (
        "#!/bin/sh\n"
        "previous=\n"
        'for arg in "$@"; do\n'
        f'  if [ "$previous" = --tools ] && [ "$arg" = "{AGENT_TOOLS}" ]; then exec {agent} "$@"; fi\n'
        '  previous="$arg"\n'
        "done\n"
    )


def claude(argv: list[str]) -> int:
    """`claude`: a conversion's side call is answered by its prompt, read from stdin; anything else goes to the fake,
    a side call with its prompt piped on the fake's stdin, and the DM's resident as it is. A vision call is `vision`'s.
    A thorough agent session never comes here: the wrapper sends it to the fake agent (`agent_dispatch`)."""
    fake = [sys.executable, str(fake_claude.FAKE_CLAUDE), *argv]
    if "--input-format" in argv and "--mcp-config" not in argv:
        return vision(fake)
    if "-p" not in argv or "--input-format" in argv:
        os.execv(fake[0], fake)
    prompt = sys.stdin.buffer.read()
    text = prompt.decode("utf-8")
    answer = (
        fixit_answer(text)
        or thorough_answer(text)
        or faithful_answer(text)
        or novel_answer(text)
        or history_answer(text)
        or answer_for(text)
    )
    if answer is None and text.startswith(DESCRIBED):
        answer = (
            SHRINE_MAP if "shrine" in text.split("## The description")[-1].split("\n## ")[0].lower() else WARREN_MAP
        )
    if answer is None:
        return subprocess.run(fake, input=prompt, check=False).returncode
    if prompt.startswith(b"You are converting part of"):
        time.sleep(CONVERTING_S)
    elif (novel_answer(text) is not None and OUTLINE_PROMPT not in text) or history_answer(text) is not None:
        time.sleep(WRITING_S)  # a chapter or a history's text: the progress can be seen
    if "--output-format" in argv and argv[argv.index("--output-format") + 1 :][:1] == ["json"]:
        # A side call that wants its usage (the conversion's): one `result` object, as the fake's.
        result = {"type": "result", "subtype": "success", "is_error": False, "result": answer, "total_cost_usd": 0.0}
        sys.stdout.write(json.dumps({**result, "usage": {"input_tokens": 1200, "output_tokens": 40}}) + "\n")
        return 0
    sys.stdout.write(answer + "\n")
    return 0


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if argv[:1] == ["--claude"]:
        return claude(argv[1:])
    if argv[:1] == ["--serve"]:
        return serve(Path(argv[1]), int(argv[2]))
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--port", type=int)
    parser.add_argument("--book", type=Path, help="write the conversion's PDF there, and stop")
    parser.add_argument("--picture", type=Path, help="write the world map's picture there, and stop")
    parser.add_argument("--faithful-book", type=Path, help="write the faithful book's PDF there, and stop")
    parser.add_argument("--thorough-book", type=Path, help="write the fake agent's book there, and stop")
    parser.add_argument("--stores", type=Path, help=f"make the stores' folders there (named {STORES_PREFIX}…)")
    args = parser.parse_args(argv)
    if args.book is not None:
        args.book.write_bytes(book_pdf())
        return 0
    if args.picture is not None:
        args.picture.write_bytes(picture_png())
        return 0
    if args.faithful_book is not None:
        args.faithful_book.write_bytes(faithful_pdf())
        return 0
    if args.thorough_book is not None:
        with tempfile.TemporaryDirectory() as folder:
            args.thorough_book.write_bytes(thorough_book(Path(folder)).read_bytes())
        return 0
    if args.port is None:
        parser.error("--port is needed")
    if args.port in FORBIDDEN_PORTS:
        parser.error(f"port {args.port} is the owner's; pick another")
    env = prepare(Path(tempfile.mkdtemp(prefix="delve-e2e-browser-")))
    if args.stores is not None:
        stores = args.stores.resolve()
        make_stores(stores)
        command = [sys.executable, "-m", "tests.e2e.fake_play_server", "--serve", str(stores), str(args.port)]
    else:
        command = [sys.executable, "-m", "delve", "serve", "--host", "127.0.0.1", "--port", str(args.port)]
    os.execvpe(command[0], command, env)
    return 0  # not reached


if __name__ == "__main__":
    sys.exit(main())
