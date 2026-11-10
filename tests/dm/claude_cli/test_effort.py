from delve.dm.claude_cli.effort import TurnContext, auto_effort, turn_effort
from delve.domain.settings import Effort

QUIET = TurnContext()


def test_auto_effort_cases():
    assert auto_effort("I open the door.", QUIET) is Effort.LOW
    assert auto_effort("", QUIET) is Effort.LOW
    assert auto_effort("I open the door.", TurnContext(in_combat=True)) is Effort.HIGH
    assert auto_effort("x" * 300, QUIET) is Effort.HIGH
    assert auto_effort("x" * 299, QUIET) is Effort.LOW
    for marker in ("We SNEAK past", "I cast sleep", "let's plan this", "I try to haggle", "lie to the guard"):
        assert auto_effort(marker, QUIET) is Effort.HIGH, marker
    npcs = TurnContext(npc_names=("Brother Aldo", "Mira the Fence"))
    # Two NPCs, not two names: "Brother Aldo" matches by its full name and its first name, and is one NPC.
    assert auto_effort("I ask Brother Aldo about the crypt.", npcs) is Effort.LOW
    assert auto_effort("I ask brother aldo and Mira who is lying.", npcs) is Effort.HIGH
    # A first name counts only when it is longer than three letters.
    assert auto_effort("Ana and Bo talk.", TurnContext(npc_names=("Ana Smith", "Bo Hill"))) is Effort.LOW


def test_turn_effort_follows_the_choice():
    assert turn_effort(Effort.AUTO, "I cast sleep", QUIET) is Effort.HIGH
    assert turn_effort(Effort.MEDIUM, "I cast sleep", QUIET) is Effort.MEDIUM
    assert turn_effort(None, "I cast sleep", QUIET) is None


def test_auto_effort_judges_the_players_words_not_a_hidden_note():
    # The session start's note is Delve's, ~280 characters: with it, a short act read as a plan, and the effort held
    # high for the whole session.
    from delve.play.table import BEGIN_SESSION

    assert auto_effort(f"{BEGIN_SESSION}\n\nCan you give a campaign intro", QUIET) is Effort.LOW
    assert auto_effort(f"{BEGIN_SESSION}\n\nI cast sleep", QUIET) is Effort.HIGH
    assert auto_effort(f"{BEGIN_SESSION}\n\n" + "x" * 300, QUIET) is Effort.HIGH
