"""`play.notes`: DM-only secrets and public chronicle lines (ttrpg2 `tools/secrets.py` and `log_note`)."""

import pytest

from delve.play import notes
from delve.play.context import NotFound, PlayError


def events(ctx, type):
    return [e.data for e in ctx.storage.events.list(ctx.campaign_id) if e.type == type]


def test_secrets_filter_and_reveal(ctx):
    """ttrpg2 `dm_secrets`: the filters are AND-combined, a tag matches part of any tag, `related_to` the whole slug,
    `contains` part of the text, all ignoring case. Revealing a secret makes it a public event."""
    motive = notes.dm_note(ctx, "The innkeeper reports to the cult.", tags=["motive", "Cult"], related_to="innkeeper")
    rumour = notes.dm_note(ctx, "The well is not poisoned.", tags=["rumour"], related_to="well")
    plot = notes.dm_note(ctx, "The cult meets at the well.", tags=["plot", "cult"], related_to="well")
    assert motive["stored"] is True and motive["id"].startswith("note_")
    assert events(ctx, "dm_note") == [] and ctx.storage.events.list(ctx.campaign_id) == []  # secrets aren't events

    def ids(**filters):
        return [s["id"] for s in notes.dm_secrets(ctx, **filters)["secrets"]]

    assert ids() == [motive["id"], rumour["id"], plot["id"]]
    assert ids(tag="CULT") == [motive["id"], plot["id"]]
    assert ids(tag="cult", related_to="Well") == [plot["id"]]
    assert ids(contains="WELL") == [rumour["id"], plot["id"]]
    assert ids(tag="mot") == [motive["id"]]
    assert notes.dm_secrets(ctx, related_to="nobody") == {"count": 0, "secrets": []}

    out = notes.dm_secret_update(ctx, rumour["id"], revealed=True)
    assert out == {"id": rumour["id"], "updated": True, "revealed": True}
    assert events(ctx, "secret_revealed") == [
        {"id": rumour["id"], "slug": "well", "notes": "The well is not poisoned."}
    ]
    notes.dm_secret_update(ctx, plot["id"], text="The cult meets under the well.", tags=["plot"])
    [updated] = notes.dm_secrets(ctx, related_to="well", tag="plot")["secrets"]
    assert (updated["text"], updated["tags"], updated["revealed"]) == (
        "The cult meets under the well.",
        ["plot"],
        False,
    )
    notes.dm_secret_update(ctx, plot["id"], related_to="cult")
    assert ids(related_to="cult") == [plot["id"]]
    with pytest.raises(NotFound):
        notes.dm_secret_update(ctx, "note_000000000000", text="x")
    with pytest.raises(PlayError):
        notes.dm_note(ctx, "  ")


def test_log_note_is_a_public_chronicle_line(ctx):
    out = notes.log_note(ctx, "The party entered the crypt.")
    assert out["text"] == "The party entered the crypt." and out["session"] == 1
    assert events(ctx, "log_note") == [{"id": out["id"], "text": "The party entered the crypt."}]
    assert notes.dm_secrets(ctx)["count"] == 0  # a chronicle line is no secret
    with pytest.raises(PlayError):
        notes.log_note(ctx, "")
