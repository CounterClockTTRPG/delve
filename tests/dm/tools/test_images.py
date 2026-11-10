"""Showing images to players (plan 3 Task 8; spec §7.5): `show_image` shows a player image of the campaign's pinned
revision, the story gets an `image` entry after its tool row, and the campaign's image route serves only those images.
A DM-only attachment never reaches a player (Review Focus 3), and the pinned revision keeps serving an image deleted
from the working copy until the host upgrades (Review Focus 2)."""

import asyncio
import dataclasses
import json

import pytest
from fastapi.testclient import TestClient

from delve.config import Config
from delve.dice import SeededRng
from delve.dm.fake import FakeDM
from delve.dm.provider import TextDelta, ToolCall, ToolResult
from delve.dm.tools import player_view
from delve.domain.modules import ModuleMap
from delve.domain.settings import BackendChoice
from delve.modules.source import ATTACHMENT, Attachment, load_source, save_source
from delve.play import seats
from delve.play.context import context_for
from delve.play.sessions import primer
from delve.play.table import AppServices, run_beat, story, wait_beat
from delve.web.app import create_app
from tests.dm.tools.conftest import CRYPT
from tests.fixtures import SAMPLES
from tests.web.conftest import BASE_URL, make_registries

PNG = (SAMPLES / "scenarios" / "crypt-of-saint-vellis" / "assets" / "img" / "ritualist-token.png").read_bytes()
SVG = b'<svg xmlns="http://www.w3.org/2000/svg" width="4" height="4"><rect width="4" height="4"/></svg>'
PDF = b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n1 0 obj << >> endobj\ntrailer << >>\n%%EOF\n"
DM_ONLY_DESCRIPTION = "SECRET-XYZZY: the lich's true face, behind the altar."


def attach(storage, module_id: str, id: str, data: bytes, media_type: str, description: str, audience: str):
    """Add an attachment to the module's working source, its bytes in the blob store."""
    sha = storage.blobs.put(data, media_type)
    storage.blobs.link(module_id, ATTACHMENT, sha)
    source = load_source(storage, module_id)
    attachment = Attachment(id, media_type, sha, len(data), description, audience)
    save_source(storage, module_id, dataclasses.replace(source, attachments=[*source.attachments, attachment]))


@pytest.fixture
def campaign(storage):
    """The crypt with a player image (the gate), a player SVG (a plan), a DM-only image (the lich) and a player PDF,
    and a campaign pinned on that revision."""
    module = storage.modules.create("The Crypt")
    storage.modules.put_map(module.id, ModuleMap("crypt", "map", CRYPT, is_default=True))
    attach(storage, module.id, "gate", PNG, "image/png", "The crypt's gate at dusk: show it when they arrive.", "player")
    attach(storage, module.id, "plan", SVG, "image/svg+xml", "The vestry's floor plan, once they find it.", "player")
    attach(storage, module.id, "lich", PNG, "image/png", DM_ONLY_DESCRIPTION, "gm")
    attach(storage, module.id, "rules", PDF, "application/pdf", "The ritual's rules.", "player")
    revision = storage.revisions.snapshot(module.id)
    return storage.campaigns.create("Tuesday", module.id, revision.number, ruleset="osric", setting="greyhawk")


@pytest.fixture
def call(host, campaign):
    def run(tool, /, beat="beat-1", **args):
        return host.call(campaign.id, beat, tool, args)

    return run


@pytest.fixture
def client(tmp_path, storage):
    """Another device presenting the owner token: the owner, from anywhere."""
    config = Config(data_dir=tmp_path / "data")
    app = create_app(config, storage, make_registries())
    with TestClient(app, base_url=BASE_URL) as opened:
        opened.headers["Authorization"] = f"Bearer {config.token_path.read_text().strip()}"
        yield opened


def image_url(campaign, asset: str) -> str:
    return f"/api/campaigns/{campaign.id}/images/{asset}"


def services_for(storage, host, dm) -> AppServices:
    return AppServices(
        storage=storage,
        catalogs=host.catalogs,
        spec_lookup=host.spec,
        dm=lambda campaign_id: (dm, BackendChoice("fake")),
        side=lambda campaign_id: (dm, BackendChoice("fake")),
    )


def play(storage, host, campaign, *calls: tuple[str, dict]) -> list:
    """Play one beat in which the fake DM calls `show_image` with each of `calls`' args and gets `calls`' results;
    the story's entries then."""
    events = [TextDelta("The gate looms.")]
    for n, (args, result) in enumerate(calls):
        events += [ToolCall(f"t{n}", "show_image", args), ToolResult(f"t{n}", "error" not in result, json.dumps(result))]
    services = services_for(storage, host, FakeDM([events]))

    async def beat():
        await run_beat(services, campaign.id, {"player": seats.owner_seat(storage, campaign.id).id, "character_ids": [], "kind": "act", "text": "On."})
        await wait_beat(services, campaign.id)

    asyncio.run(beat())
    return story(storage, campaign.id, seats.owner_seat(storage, campaign.id))["entries"]


def test_a_shown_image_is_in_the_story_and_served(call, host, storage, campaign, client):
    shown = call("show_image", asset="gate", caption="The gate of Saint Vellis")
    assert shown == {"image": {"asset": "gate", "caption": "The gate of Saint Vellis"}}
    assert call("show_image", asset="plan") == {"image": {"asset": "plan", "caption": ""}}
    # The `image` exception: the one tool output past the allow-list.
    assert player_view(host.spec("show_image"), {"asset": "gate"}, shown) == {"image": shown["image"]}

    entries = play(storage, host, campaign, ({"asset": "gate", "caption": "The gate of Saint Vellis"}, shown))
    assert [e.kind for e in entries] == ["player_act", "dm_text", "tool", "image"]
    assert entries[2].payload == {"name": "show_image"}
    assert entries[3].payload == {"asset": "gate", "caption": "The gate of Saint Vellis"}

    served = client.get(image_url(campaign, "gate"))
    assert served.status_code == 200 and served.content == PNG
    assert served.headers["content-type"] == "image/png"
    assert served.headers["x-content-type-options"] == "nosniff"
    plan = client.get(image_url(campaign, "plan"))
    assert plan.status_code == 200 and "sandbox" in plan.headers["content-security-policy"]


def test_a_dm_only_image_never_reaches_a_player(call, host, storage, campaign, client):
    """Review Focus 3: the tool refuses a DM-only image, the route answers 404 for it and for any id the pinned revision
    doesn't hold (with the owner token), and the story holds no `image` entry, even for a forged result."""
    refused = call("show_image", asset="lich", caption="Behold")
    assert refused["error"] == "That image is for the DM only."
    assert "candidates" not in refused
    assert player_view(host.spec("show_image"), {"asset": "lich"}, refused) == {"failed": True}

    forged = {"image": {"asset": "lich", "caption": "Behold"}}
    entries = play(storage, host, campaign, ({"asset": "lich"}, refused), ({"asset": "lich"}, forged))
    assert [e.kind for e in entries] == ["player_act", "dm_text", "tool", "tool"]
    assert entries[2].payload == {"name": "show_image", "failed": True}
    assert "SECRET-XYZZY" not in json.dumps([e.payload for e in entries])

    for asset in ("lich", "rules", "nothing", "map"):
        answer = client.get(image_url(campaign, asset))
        assert answer.status_code == 404, asset
        assert set(answer.json()) == {"error"}
    assert client.get("/api/campaigns/cmp_000000000000/images/gate").status_code == 404


def test_show_image_refuses_a_pdf_and_an_unknown_id(call):
    pdf = call("show_image", asset="rules")
    assert pdf["error"] == "That attachment is a PDF, not an image."
    unknown = call("show_image", asset="gaet")
    assert unknown["error"] == "No image 'gaet' in this module."
    # The candidates are the player images only: never the DM-only one or the PDF.
    assert unknown["candidates"] == [
        {"id": "gate", "description": "The crypt's gate at dusk: show it when they arrive."},
        {"id": "plan", "description": "The vestry's floor plan, once they find it."},
    ]


def test_the_pinned_revision_still_serves_a_deleted_image(call, storage, campaign, client):
    """Review Focus 2: the gate is deleted from the working copy; the campaign still shows and serves it from its
    pinned revision, until the host upgrades."""
    source = load_source(storage, campaign.module_id)
    gone = dataclasses.replace(source, attachments=[a for a in source.attachments if a.id != "gate"])
    save_source(storage, campaign.module_id, gone)
    storage.revisions.snapshot(campaign.module_id)

    assert call("show_image", asset="gate") == {"image": {"asset": "gate", "caption": ""}}
    served = client.get(image_url(campaign, "gate"))
    assert served.status_code == 200 and served.content == PNG

    assert client.post(f"/api/campaigns/{campaign.id}/upgrade", json={}).status_code == 200
    assert "error" in call("show_image", asset="gate")
    assert client.get(image_url(campaign, "gate")).status_code == 404


def test_a_campaign_on_a_module_without_attachments_has_no_images(storage, host, client):
    module = storage.modules.create("Only a map")
    storage.modules.put_map(module.id, ModuleMap("crypt", "map", CRYPT, is_default=True))
    revision = storage.revisions.snapshot(module.id)
    bare = storage.campaigns.create("Wednesday", module.id, revision.number, ruleset="osric", setting="greyhawk")
    unknown = host.call(bare.id, "beat-1", "show_image", {"asset": "gate"})
    assert unknown["error"] == "No image 'gate' in this module." and "candidates" not in unknown
    assert client.get(image_url(bare, "gate")).status_code == 404


def test_primer_lists_the_player_images(storage, host, campaign):
    ctx = context_for(storage, campaign.id, "beat-1", SeededRng(1), catalogs=host.catalogs)
    images = primer(ctx)["module"]["images"]
    assert images == [
        {"id": "gate", "description": "The crypt's gate at dusk: show it when they arrive."},
        {"id": "plan", "description": "The vestry's floor plan, once they find it."},
    ]


def test_working_copy_attachment_is_not_shown_before_upgrade(call, storage, campaign, client):
    """An image added to the working copy after the campaign pinned its revision isn't the campaign's yet."""
    attach(storage, campaign.module_id, "late", PNG, "image/png", "Added later.", "player")
    assert call("show_image", asset="late")["error"] == "No image 'late' in this module."
    assert client.get(image_url(campaign, "late")).status_code == 404
