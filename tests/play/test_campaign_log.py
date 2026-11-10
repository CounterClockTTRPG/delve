"""`play.campaign_log`: the campaign's story from start to end in pages, by session, as a seat saw it (DEL-324)."""

import pytest

from delve.dice import Dice, ScriptedRng
from delve.play import campaign_log as log
from delve.play.campaign_log import campaign_log
from delve.play.context import NotFound


def beat(storage, campaign, *entries):
    """A played beat with its entries: `(kind, payload)` or `(kind, payload, audience)`."""
    played = storage.beats.open(campaign.id, [], status="done")
    for kind, payload, *audience in entries:
        storage.story.append(campaign.id, played.id, kind, payload, audience[0] if audience else None)
    return played


def act(text):
    return ("player_act", {"kind": "act", "text": text, "name": "Ana", "characters": []})


def told(text):
    return ("dm_text", {"text": text})


def test_an_empty_log_has_no_pages(storage, campaign, owner_seat):
    out = campaign_log(storage, campaign.id, owner_seat)
    assert (out["campaign"]["name"], out["pages"], out["page"], out["entries"]) == ("Tuesday", [], 0, [])


def test_the_pages_follow_the_sessions_in_even_parts_and_keep_a_beat_whole(storage, campaign, owner_seat, monkeypatch):
    monkeypatch.setattr(log, "PAGE_ENTRIES", 4)
    beat(storage, campaign, act("We make a party."), told("Six take shape."))  # before the first session
    storage.sessions.start(campaign.id, 1, "The Road")
    for n in range(3):
        beat(storage, campaign, act(f"Act {n}."), told(f"Reply {n}."))
    beat(storage, campaign, act("Last."), told("A"), told("B"), told("C"))
    storage.sessions.start(campaign.id, 2, "The Hills")
    beat(storage, campaign, act("On."), told("Hills."))

    out = campaign_log(storage, campaign.id, owner_seat, 2)
    index = [(p["page"], p["session"], p["title"], p["part"], p["parts"], p["entries"]) for p in out["pages"]]
    assert index == [
        (1, None, "", 1, 1, 2),
        (2, 1, "The Road", 1, 2, 4),
        (3, 1, "The Road", 2, 2, 6),  # the last beat joins the page it would leave short
        (4, 2, "The Hills", 1, 1, 2),
    ]
    assert [e["payload"]["text"] for e in out["entries"]] == ["Act 0.", "Reply 0.", "Act 1.", "Reply 1."]
    assert out["page"] == 2
    with pytest.raises(NotFound, match="pages 1 to 4"):
        campaign_log(storage, campaign.id, owner_seat, 5)


def test_the_log_is_the_story_the_seat_saw_with_the_players_dice(storage, campaign, owner_seat):
    garrek = storage.characters.create(campaign.id, "Garrek")
    ana = storage.seats.create(campaign.id, "Ana", "en", "player")
    dice = Dice(ScriptedRng((17, 4, 50)), storage.rolls, campaign.id, "beat-1")
    ours, theirs = (
        dice.roll("1d20", purpose="attack#1", actor=garrek.id),
        dice.roll("1d20", purpose="attack#1", actor="mon_1"),
    )
    weather = dice.roll("1d100", purpose="weather:temperate:day 1")
    beat(
        storage,
        campaign,
        act("I swing."),
        ("tool", {"name": "resolve_attack", "rolls": [ours.id, theirs.id]}),
        ("tool", {"name": "weather", "rolls": [weather.id]}),  # the DM's bookkeeping: no dice for the players
        ("talk", {"text": "brb"}),
        ("dm_error", {"message": "The DM didn't answer"}),
        ("dm_text", {"text": "For the host alone."}, {"seats": [owner_seat.id]}),
        told("The goblin falls."),
    )

    def kinds(seat):
        return [
            (e["kind"], e["payload"].get("text") or e["payload"].get("dice"))
            for e in campaign_log(storage, campaign.id, seat)["entries"]
        ]

    hosts = kinds(owner_seat)
    assert [k for k, _ in hosts] == ["player_act", "tool", "dm_text", "dm_text"]
    ((_, lines),) = [k for k in hosts if k[0] == "tool"]
    assert [(line["who"], line["faces"]) for line in lines] == [("Garrek", [17])], "the party's own, as a player reads"
    assert [k for k, _ in kinds(ana)] == ["player_act", "tool", "dm_text"], "not what was told the host alone"
    assert campaign_log(storage, campaign.id, ana)["names"] == {garrek.id: "Garrek"}
