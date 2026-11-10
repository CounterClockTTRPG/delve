"""Accounts' fixed values (players and tavern Task B1): the emblems, the colours and a username's default emblem."""

from delve.domain.accounts import COLOURS, EMBLEMS, LINK_HOURS, LINK_KINDS, USERNAME, default_emblem


def test_emblems_and_colours():
    assert EMBLEMS == (
        "lion", "eagle", "stag", "boar", "wolf", "dragon", "tower", "key", "sword", "crown", "moon", "oak",
    )  # fmt: skip
    assert COLOURS == ("teal", "jade", "gold", "ember")
    assert LINK_KINDS == ("set-password", "reset-password") and LINK_HOURS == 24
    assert USERNAME.fullmatch("a.b_c-1") and not USERNAME.fullmatch("ab") and not USERNAME.fullmatch("Ana")


def test_default_emblem_is_stable():
    names = ["ana", "bo", "carla", "dirk", "a.b_c-1"] + [f"player{n}" for n in range(40)]
    for name in names:
        assert default_emblem(name) == default_emblem(name) and default_emblem(name) in EMBLEMS
    assert len({default_emblem(name) for name in names}) > 1, "the emblems are spread over the usernames"
