"""The pregame (players and tavern Task F1): no beat is open or running, and no act has been sent since the last
recap, the end of a session."""

from dataclasses import replace

from delve.play.pregame import PAGE, in_pregame


def test_new_campaign_is_pregame(storage, campaign):
    assert in_pregame(storage, campaign.id)


def test_talk_alone_stays_pregame(storage, campaign):
    storage.story.append(campaign.id, None, "talk", {"text": "Hello."})
    assert in_pregame(storage, campaign.id)


def test_open_beat_is_not_pregame(storage, campaign):
    storage.beats.open(campaign.id, [])
    assert not in_pregame(storage, campaign.id)


def test_after_an_act_not_pregame(storage, campaign):
    beat = storage.beats.open(campaign.id, [], status="running")
    storage.story.append(campaign.id, beat.id, "player_act", {"text": "I open the door."})
    storage.beats.save(replace(beat, status="done", closed_at="2026-10-24T20:00:00Z"))
    storage.story.append(campaign.id, None, "talk", {"text": "Nice."})
    assert not in_pregame(storage, campaign.id)


def test_after_the_recap_pregame_again(storage, campaign):
    storage.story.append(campaign.id, None, "player_act", {"text": "I open the door."})
    storage.story.append(campaign.id, None, "dm_text", {"text": "It creaks."})
    storage.story.append(campaign.id, None, "recap", {"text": "The party opened a door."})
    storage.story.append(campaign.id, None, "talk", {"text": "Next week?"})
    assert in_pregame(storage, campaign.id)


def test_long_story_reads_back_by_pages(storage, campaign):
    assert PAGE == 200
    for seq in range(1, 451):
        kind = "player_act" if seq == 10 else "recap" if seq == 400 else "talk"
        storage.story.append(campaign.id, None, kind, {"text": str(seq)})
    assert in_pregame(storage, campaign.id)


def test_long_story_finds_an_old_act(storage, campaign):
    for seq in range(1, 451):
        kind = "player_act" if seq == 10 else "talk"
        storage.story.append(campaign.id, None, kind, {"text": str(seq)})
    assert not in_pregame(storage, campaign.id)
