"""A field a ruleset's engine keeps is not the DM's to patch (DEL-387)."""


def test_the_dm_cannot_patch_d20(call):
    call("create_character", name="Garrek", sheet={"hp_max": 8})
    out = call("update_character", ref="Garrek", patch={"d20": {"bab": 9}})
    assert out["error"].startswith("Can't change 'd20'")
    assert "d20" not in out["hint"]
