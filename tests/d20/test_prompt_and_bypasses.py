"""The prompt's THAC0 and save wording, module stat lines and pregens under a d20 engine (DEL-387)."""

from delve.dm.prompt import build_system_prompt
from delve.dm.tools.pregens import pregen_sheet
from delve.play.context import context_for
from tests.fixtures.d20 import d20_catalogs, fake_engine


def test_the_prompt_uses_the_engines_terms(d20_storage, d20_campaign):
    fake_engine().called.clear()
    ctx = context_for(d20_storage, d20_campaign.id, "beat-1", catalogs=d20_catalogs())
    text = "\n".join(build_system_prompt(ctx, tone="classic", detail=0))
    assert "saves, attack bonus, XP" in text
    assert "**Saving throws**: one save, `save`." in text
    section = text.split("## The Ruleset", 1)[1].split("\n## ", 1)[0]
    assert "THAC0" not in section
    assert "THAC0" not in "\n".join(build_system_prompt(ctx, tone="classic", detail=0)[-1:])
    assert "prompt_terms" in fake_engine().called


def test_a_d20_pregen_keeps_only_the_books_words():
    record = {"stats": {"adnd2e": {"thac0": 17}}, "class": "Fighter", "level": 3}
    assert pregen_sheet(record, d20=True) == {"cls": "Fighter", "level": 3}
    record |= {"race": "Elf", "alignment": "NG", "background": "A scout."}
    assert pregen_sheet(record, d20=True) == {
        "race": "Elf",
        "cls": "Fighter",
        "level": 3,
        "alignment": "NG",
        "background": "A scout.",
    }
    assert pregen_sheet(record)["thac0"] == 17


def test_a_d20_setup_combat_has_no_module_stat_note(d20_call, monkeypatch):
    from delve.play import combat

    monkeypatch.setattr(combat, "stated_differences", lambda *a: ["The module gives Goblin AC 5"])
    out = d20_call("setup_combat", enemies=[{"name": "goblin"}], surprise=False)
    assert not any("The module gives" in n for n in out.get("notes", []))
