"""The entities prompt (faithful modules Task 15): an encounter's creatures go in `fixed` with their stat lines, and an
appendix stat block of a person named elsewhere is that person's NPC."""

from importlib.resources import files

PROMPT = files("delve.modules.books").joinpath("prompts/entities.md").read_text(encoding="utf-8")


def test_an_encounters_creatures_go_in_fixed_with_their_stat_lines():
    assert "creatures go in `fixed`" in PROMPT
    assert "its stat line as printed in `notes`" in PROMPT


def test_an_appendix_stat_block_is_the_persons_npc():
    assert "appendix" in PROMPT
    assert "the same `name`" in PROMPT


def test_a_pregens_notes_for_the_dm_go_in_its_description():
    """Final review fix 5: `background` is what a player who takes the pregen may read; the book's notes for the DM
    (a secret, a hook, how to play them) go in `description`, which the party's picker never shows."""
    assert '"background": "…", "description": "…"' in PROMPT
    assert "its background or notes in `background`" not in PROMPT
    assert "Put in `background` only what the player who takes it" in PROMPT
    assert "notes meant for the DM" in PROMPT and "in `description`" in PROMPT
