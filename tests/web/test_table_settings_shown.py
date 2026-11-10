"""The campaign's voice setting and initiative mode, and a character's departure, as the API shows them (table voice
and fixes Task 0): read-only here; the routes that set them are the workstreams'."""

from tests.web.test_play_api import campaign, dm, path, registries, settle  # noqa: F401 (fixtures)


def test_campaign_shows_voice_and_initiative(local, storage, campaign):  # noqa: F811
    shown = local.get(f"/api/campaigns/{campaign.id}").json()
    assert (shown["voice"], shown["initiative"]) == ("allowed", "combatant")
    storage.campaigns.set_voice(campaign.id, "off")
    storage.campaigns.set_initiative(campaign.id, "side")
    shown = local.get(f"/api/campaigns/{campaign.id}").json()
    assert (shown["voice"], shown["initiative"]) == ("off", "side")
    listed = next(c for c in local.get("/api/campaigns").json() if c["id"] == campaign.id)
    assert (listed["voice"], listed["initiative"]) == ("off", "side")


def test_play_state_shows_voice_and_initiative(local, storage, campaign):  # noqa: F811
    state = local.get(path(campaign, "play/state")).json()
    assert (state["voice"], state["initiative"]) == ("allowed", "combatant")
    storage.campaigns.set_voice(campaign.id, "off")
    assert local.get(path(campaign, "play/state")).json()["voice"] == "off"


def test_character_shows_its_departure(local, storage, campaign):  # noqa: F811
    tansy = storage.characters.create(campaign.id, "Tansy")
    shown = local.get(path(campaign, "characters")).json()
    assert [(c["departure"], c["departed_at"]) for c in shown] == [(None, None)]
    storage.characters.set_departure(tansy.id, "died", "2026-10-25T20:00:00+00:00")
    shown = local.get(path(campaign, "characters")).json()
    assert [(c["departure"], c["departed_at"]) for c in shown] == [("died", "2026-10-25T20:00:00+00:00")]


def test_the_runner_calls_the_timelines_hooks(local, dm, campaign, monkeypatch):  # noqa: F811
    """The seam B2 fills: every DM event of a beat goes to `timeline.after_event` with the entries it stored, and the
    closed beat to `timeline.after_beat`."""
    from delve.dm.provider import TextDelta, ToolCall, ToolResult
    from delve.play import timeline

    seen, closed = [], []
    monkeypatch.setattr(timeline, "after_event", lambda s, c, b, event, stored: seen.append((c, b, event, stored)))
    monkeypatch.setattr(timeline, "after_beat", lambda s, beat: closed.append(beat))
    dm._script = [
        [
            ToolCall("t1", "roll", {"notation": "1d20", "purpose": "the lever"}),
            ToolResult("t1", True, {"notation": "1d20", "rolls": [12], "total": 12}),
            TextDelta("The lever moves."),
        ]
    ]
    beat = local.post(path(campaign, "act"), json={"text": "I pull the lever."}).json()["beat"]
    settle(local, campaign)

    assert {(c, b) for c, b, _, _ in seen} == {(campaign.id, beat["id"])}
    events = [type(event).__name__ for _, _, event, _ in seen]
    assert events[:3] == ["ToolCall", "ToolResult", "TextDelta"]
    texts = [entry for _, _, event, stored in seen if isinstance(event, TextDelta) for entry in stored]
    assert [entry.kind for entry in texts] == ["dm_text"], "the hook sees the stored narration"
    assert [(b.id, b.status) for b in closed] == [(beat["id"], "done")]
