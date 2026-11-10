"""What a history's writer reads (carry-the-party-on plan Task 4): the campaign's record without its module, the
factions, the quests and the party's earlier history, for the DM or for the table. The table's material is filtered
at the source: nothing DM-only reaches it, whatever a prompt says."""

from dataclasses import replace

import pytest

from delve.domain.campaigns import LootItem
from delve.domain.characters import Item, Sheet
from delve.domain.histories import History
from delve.domain.world import Faction, Possession, Quest, QuestNote
from delve.histories.material import history_material
from delve.novels.material import MODULE_HEADING, campaign_material, render
from delve.play.audience import for_seats
from tests.novels.test_material import played, storage  # noqa: F401 (fixtures)

SECRETS = (
    "I pocket the coin.",  # a private act
    "You hear a whisper.",  # a line told only to Mira
    "HOST-NOTE-XYZ",  # a note for the host
    "The keeper is a ghoul himself.",  # a secret never revealed
    "The niche is empty now.",  # a DM's room note
    "SECRETWORD",  # an NPC's notes
    "The Hidden Hand",  # an unknown faction
    "HAND-NOTES-XYZ",
    "The Lost Relic",  # an unknown quest
    "QUEST-NOTES-XYZ",  # a known quest's DM notes
    "QUEST-LOG-XYZ",  # a known quest's log line the players never learned
    "TALK-XYZ",  # table talk
    "ASK-XYZ",  # a question to the DM, out of the game
    "ANSWER-XYZ",
    "POSSESSION-NOTES-XYZ",  # a possession's DM notes
)


@pytest.fixture
def secrets(storage, played):  # noqa: F811 (fixture)
    """The crypt campaign with something of every DM-only kind, a known faction at reputation −37, and what the party
    carries: Mira's rope, the party's coin and loot, Mira's mule and the party's cart."""
    campaign_id = played.id
    host = storage.seats.list(campaign_id)[0]
    story = storage.story
    story.append(campaign_id, None, "dm_text", {"text": "HOST-NOTE-XYZ"}, for_seats([host.id]))
    story.append(campaign_id, None, "talk", {"name": "Raf", "text": "TALK-XYZ"})
    story.append(campaign_id, None, "ask", {"text": "ASK-XYZ"})
    story.append(campaign_id, None, "answer", {"text": "ANSWER-XYZ"})
    story.append(campaign_id, None, "dm_text", {"text": "The ghouls flee into the dark."})
    storage.characters.create(
        campaign_id,
        "Sister Hel",
        kind="npc",
        sheet=Sheet(kind="npc", background="a nun of the Lamp", notes_md="SECRETWORD", faction="hand"),
    )
    storage.factions.put(Faction(campaign_id, "hand", "The Hidden Hand", known=False, notes_md="HAND-NOTES-XYZ"))
    storage.factions.put(Faction(campaign_id, "order", "The Order of the Lamp", known=True, reputation=-37))
    storage.quests.put(Quest(campaign_id, "relic", "The Lost Relic", stakes="the saint's ring", known=False))
    storage.quests.put(
        Quest(
            campaign_id,
            "crypt",
            "Clear the crypt",
            giver="Brother Oswin",
            stakes="the village sleeps again",
            status="complete",
            known=True,
            log=(QuestNote(1, "The ghouls are gone."), QuestNote(2, "QUEST-LOG-XYZ", known=False)),
            notes_md="QUEST-NOTES-XYZ",
        )
    )
    mira = next(c for c in storage.characters.list(campaign_id) if c.name == "Mira")
    storage.characters.save(replace(mira, state=replace(mira.state, inventory=(Item("Silk rope", 1, 8.0, "50 ft"),))))
    state = storage.campaign_states.get(campaign_id)
    storage.campaign_states.put(
        replace(state, coin={**state.coin, "gp": 120, "sp": 7}, loot=(LootItem("gem", "a moonstone", 50),))
    )
    storage.possessions.put(
        Possession(campaign_id, "pos_mule", "Bess the mule", "mount", owner_id=mira.id, notes_md="POSSESSION-NOTES-XYZ")
    )
    storage.possessions.put(Possession(campaign_id, "pos_cart", "The crypt cart", "vehicle", location="Hommlet"))
    return played


def test_novel_material_unchanged_by_default(storage, played):  # noqa: F811 (fixture)
    material = campaign_material(storage, played.id, None)

    assert material.parts[-1].heading == MODULE_HEADING
    assert material == campaign_material(storage, played.id, None, audience="all", with_module=True)


def test_without_module_has_no_module_part(storage, played):  # noqa: F811 (fixture)
    material = campaign_material(storage, played.id, None, with_module=False)

    assert MODULE_HEADING not in [part.heading for part in material.parts]
    assert "silver ring" not in render(material)
    assert material.parts[:-1] == campaign_material(storage, played.id, None).parts[:-2]


def test_table_material_leaks_nothing(storage, secrets):  # noqa: F811 (fixture)
    table = render(history_material(storage, secrets.id, "table"))

    for secret in SECRETS:
        assert secret not in table
    assert "-37" not in table and "−37" not in table
    assert "The DM's secrets and notes" not in table and MODULE_HEADING not in table
    assert "The Order of the Lamp: unfriendly" in table
    assert "Clear the crypt" in table and "The ghouls are gone." in table
    assert "Aldric: I go down." in table and "The stair is cold." in table
    assert "The ghouls flee into the dark." in table
    assert "They went down the stair." in table  # the session's recap
    assert "Sister Hel" in table and "a nun of the Lamp" in table
    _carries(table)


def _carries(text: str) -> None:
    part = text.split("What the party carries", 1)[1]
    assert "Mira: Silk rope (50 ft)" in part
    assert "120 gp" in part and "7 sp" in part
    assert "a moonstone (gem, 50 gp)" in part
    assert "Bess the mule (mount, Mira's)" in part
    assert "The crypt cart (vehicle, the party's, at Hommlet)" in part


def test_table_campaign_material_is_filtered_at_the_source(storage, secrets):  # noqa: F811 (fixture)
    table = render(campaign_material(storage, secrets.id, None, audience="table"))

    for secret in ("I pocket the coin.", "You hear a whisper.", "HOST-NOTE-XYZ", "SECRETWORD", "TALK-XYZ"):
        assert secret not in table
    assert "The keeper is a ghoul himself." not in table
    assert "hand" not in table.split("Sister Hel", 1)[1].split("\n", 1)[0]  # an unknown faction's id
    assert MODULE_HEADING in table


def test_dm_material_has_secrets_and_numbers(storage, secrets):  # noqa: F811 (fixture)
    material = history_material(storage, secrets.id, "dm")
    dm = render(material)

    for secret in SECRETS:
        assert secret in dm, secret
    assert "-37" in dm
    assert MODULE_HEADING not in dm
    assert [part.heading for part in material.parts][-4:] == [
        "The DM's secrets and notes",
        "Standing with the factions",
        "Quests",
        "What the party carries",
    ]
    _carries(dm)
    assert "Bess the mule (mount, Mira's). Notes: POSSESSION-NOTES-XYZ" in dm


def test_only_the_carried_pcs_things_are_carried(storage, secrets):  # noqa: F811 (fixture)
    """With the carried PCs named, the others' inventories and possessions stay out; the party's stay in."""
    aldric = next(c for c in storage.characters.list(secrets.id) if c.name == "Aldric")
    storage.characters.save(replace(aldric, state=replace(aldric.state, inventory=(Item("Aldric's shield"),))))
    storage.possessions.put(Possession(secrets.id, "pos_horse", "Aldric's warhorse", "mount", owner_id=aldric.id))
    mira = next(c for c in storage.characters.list(secrets.id) if c.name == "Mira")

    for audience in ("dm", "table"):
        part = render(history_material(storage, secrets.id, audience, carried=[mira.id]))
        part = part.split("What the party carries", 1)[1]
        assert "Silk rope" in part and "Bess the mule" in part and "The crypt cart" in part, audience
        assert "Aldric's shield" not in part and "Aldric's warhorse" not in part, audience
        everyone = render(history_material(storage, secrets.id, audience)).split("What the party carries", 1)[1]
        assert "Aldric's shield" in everyone and "Aldric's warhorse" in everyone, audience


def test_a_party_that_carries_nothing(storage, played):  # noqa: F811 (fixture)
    part = render(history_material(storage, played.id, "table")).split("What the party carries", 1)[1]

    assert "(nothing)" in part


@pytest.mark.parametrize(
    ("reputation", "word"),
    [
        (-100, "hostile"),
        (-50, "hostile"),
        (-49, "unfriendly"),
        (-10, "unfriendly"),
        (-9, "neutral"),
        (0, "neutral"),
        (9, "neutral"),
        (10, "friendly"),
        (49, "friendly"),
        (50, "allied"),
        (100, "allied"),
    ],
)
def test_the_table_reads_a_standing_word(storage, played, reputation, word):  # noqa: F811 (fixture)
    storage.factions.put(Faction(played.id, "order", "The Order of the Lamp", known=True, reputation=reputation))

    assert f"The Order of the Lamp: {word}" in render(history_material(storage, played.id, "table"))


def test_earlier_history_stacks_by_audience(storage, played):  # noqa: F811 (fixture)
    assert "The party's earlier history" not in render(history_material(storage, played.id, "dm"))
    storage.histories.put(History(played.id, dm_md="DMPAST", table_md="TABLEPAST", status="done"))

    dm = render(history_material(storage, played.id, "dm"))
    table = render(history_material(storage, played.id, "table"))

    assert "The party's earlier history" in dm and "DMPAST" in dm and "TABLEPAST" not in dm
    assert "The party's earlier history" in table and "TABLEPAST" in table and "DMPAST" not in table


def test_an_earlier_history_without_texts_is_left_out(storage, played):  # noqa: F811 (fixture)
    storage.histories.put(History(played.id, dm_md="", table_md="  ", status="writing"))

    for audience in ("dm", "table"):
        assert "The party's earlier history" not in render(history_material(storage, played.id, audience))


def test_a_failed_earlier_history_stacks_its_kept_texts(storage, played):  # noqa: F811 (fixture)
    """Review fix: a failed (or orphaned, or running) Write again keeps the old texts, and they still stack."""
    storage.histories.put(
        History(played.id, dm_md="DMPAST", table_md="TABLEPAST", status="failed", error="Delve stopped while writing.")
    )

    dm = render(history_material(storage, played.id, "dm"))
    table = render(history_material(storage, played.id, "table"))

    assert "DMPAST" in dm and "TABLEPAST" not in dm
    assert "TABLEPAST" in table and "DMPAST" not in table
