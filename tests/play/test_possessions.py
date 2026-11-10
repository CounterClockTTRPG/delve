"""`play.possessions` (plan 6 Task 6, spec §7.9): mounts, vehicles, ships, houses and the rest, owned by a character
or the party. A possession's `notes_md` is DM-only. The mount defaults are a ruleset's; ttrpg2's (`tools/holdings.py`)
are AD&D 2e's, tested in its pack."""

import pytest

from delve.play import characters, possessions, sessions
from delve.play.context import NotFound, PlayError

SECRET = "SECRET-XYZZY"
HORSE = {"hp_max": 18, "ac": 7, "mv": 24, "thac0": 19}
"""A riding horse's stats, given: OSRIC has no mount defaults (AD&D 2e's are its pack's, whose tests read them)."""
PONY = {"hp_max": 9, "thac0": 19}


@pytest.fixture
def garrek(ctx):
    return characters.create(ctx, name="Garrek", sheet={"race": "Human", "cls": "Fighter", "hp_max": 10})


def test_an_unknown_species_needs_hp_max_and_thac0(ctx):
    with pytest.raises(PlayError) as refused:
        possessions.add(ctx, "Grumble", "mount", species="owlbear", stats={"hp_max": 30})
    assert "hp_max and thac0" in refused.value.message
    assert ctx.storage.possessions.list(ctx.campaign_id) == []
    owlbear = possessions.add(ctx, "Grumble", "mount", species="owlbear", stats={"hp_max": 30, "thac0": 15, "mv": 12})
    assert owlbear["stats"] == {"species": "owlbear", "hp": 30, "hp_max": 30, "thac0": 15, "mv": 12}


def test_kinds_owners_and_values_are_checked(ctx, garrek):
    with pytest.raises(PlayError):
        possessions.add(ctx, "The Gull", "boat")
    with pytest.raises(PlayError):
        possessions.add(ctx, " ", "house")
    with pytest.raises(PlayError):
        possessions.add(ctx, "The Gull", "ship", species="pony")  # a species is a mount's
    with pytest.raises(PlayError):
        possessions.add(ctx, "The Gull", "ship", stats={"mv": "fast"})
    with pytest.raises(NotFound) as unknown:
        possessions.add(ctx, "The Gull", "ship", owner="Nobody")
    assert unknown.value.candidates == [{"id": garrek.id, "name": "Garrek", "kind": "pc"}]
    ship = possessions.add(ctx, "The Gull", "ship", value_gp=5000, stats={"mv": 6, "capacity": 20})
    assert ship["stats"] == {"mv": 6, "capacity": 20} and ship["value_gp"] == 5000
    house = possessions.add(ctx, "Oakhill Cottage", "house", owner=garrek.id, location="Hommlet", stats={"rooms": 3})
    assert house["stats"] == {"rooms": 3} and house["location"] == "Hommlet"


def test_update_changes_only_what_is_given(ctx, garrek):
    bess = possessions.add(ctx, "Bess", "mount", owner="Garrek", species="riding-horse", stats=HORSE, notes="Skittish.")
    hurt = possessions.update(ctx, "Bess", hp_change=-5, location="the stable", inventory=["Saddlebags"])
    assert hurt["stats"]["hp"] == 13 and hurt["location"] == "the stable" and hurt["inventory"] == ["Saddlebags"]
    healed = possessions.update(ctx, bess["id"], hp_change=50)
    assert healed["stats"]["hp"] == 18  # never past hp_max
    given = possessions.update(ctx, "Bess", owner="", stats={"morale": 9})
    assert given["owner_id"] is None and given["stats"]["morale"] == 9 and given["stats"]["mv"] == 24
    assert ctx.storage.possessions.get(ctx.campaign_id, bess["id"]).notes_md == "Skittish."
    cottage = possessions.add(ctx, "Cottage", "house")
    with pytest.raises(PlayError):
        possessions.update(ctx, cottage["id"], hp_change=-1)  # a house has no hit points
    with pytest.raises(NotFound):
        possessions.update(ctx, "Nothing", name="x")


def test_names_must_be_exact_and_unambiguous(ctx):
    possessions.add(ctx, "Bess", "mount", species="pony", stats=PONY)
    possessions.add(ctx, "Bess", "vehicle", stats={"mv": 9, "capacity": 4})
    with pytest.raises(NotFound) as ambiguous:
        possessions.detail(ctx, "bess")
    assert len(ambiguous.value.candidates) == 2
    with pytest.raises(NotFound) as unknown:
        possessions.detail(ctx, "Be")
    assert {c["name"] for c in unknown.value.candidates} == {"Bess"}


def test_an_owner_who_dies_leaves_the_horse_to_the_party(ctx, garrek):
    bess = possessions.add(ctx, "Bess", "mount", owner="Garrek", species="riding-horse", stats=HORSE)
    ctx.storage.characters.delete(garrek.id)
    assert ctx.storage.possessions.get(ctx.campaign_id, bess["id"]).owner_id is None
    assert possessions.listing(ctx, owner="party")["possessions"][0]["name"] == "Bess"


def test_possessions_hide_notes_md(ctx, garrek):
    """The list and the add and update answers leave `notes_md` out; only `possession(id)`, a DM-only tool, has it."""
    added = possessions.add(
        ctx, "Bess", "mount", owner="Garrek", species="pony", stats=PONY, notes=f"{SECRET}: stolen."
    )
    updated = possessions.update(ctx, "Bess", description="A grey pony.")
    listed = possessions.listing(ctx)
    for answer in (added, updated, listed):
        assert SECRET not in str(answer) and "notes_md" not in str(answer)
    assert possessions.detail(ctx, "Bess")["notes_md"] == f"{SECRET}: stolen."


def test_the_list_filters_by_owner(ctx, garrek):
    possessions.add(ctx, "Bess", "mount", owner="Garrek", species="pony", stats=PONY)
    possessions.add(ctx, "The Gull", "ship", stats={"mv": 6, "capacity": 20})
    assert [p["name"] for p in possessions.listing(ctx)["possessions"]] == ["Bess", "The Gull"]
    assert [p["name"] for p in possessions.listing(ctx, owner="Garrek")["possessions"]] == ["Bess"]
    assert [p["name"] for p in possessions.listing(ctx, owner="party")["possessions"]] == ["The Gull"]
    assert possessions.listing(ctx)["count"] == 2


def test_remove(ctx):
    gull = possessions.add(ctx, "The Gull", "ship")
    assert possessions.remove(ctx, "The Gull") == {"id": gull["id"], "name": "The Gull", "removed": True}
    assert ctx.storage.possessions.list(ctx.campaign_id) == []


def test_the_primer_names_each_characters_possessions(ctx, garrek, make_ctx):
    possessions.add(
        ctx, "Bess", "mount", owner="Garrek", species="pony", stats=PONY, notes="Not for the primer's party."
    )
    possessions.add(ctx, "The Gull", "ship")
    digest = sessions.primer(make_ctx(1))["party"][0]  # the primer rolls the day's weather
    assert digest["possessions"] == ["Bess (mount)"]
