"""DEL-117: every tool the table sees has a kind in `web/src/play/toolKinds.ts`, which gives its row in the story an
icon and a colour (docs/style-guide.md). A new tool fails here until it is given one."""

import re
from pathlib import Path

from delve.dm.tools import all_specs

KINDS = Path(__file__).parents[2] / "web" / "src" / "play" / "toolKinds.ts"


def listed() -> list[str]:
    body = KINDS.read_text().split("const BY_KIND", 1)[1].split("= {", 1)[1].split("};", 1)[0]
    return re.findall(r'"([a-z_]+)"', body)


def test_every_tool_the_table_sees_has_a_kind():
    seen = {spec.name for spec in all_specs() if spec.player_visible} - {"batch"}  # a batch shows as its steps
    assert sorted(seen - set(listed())) == []


def test_each_tool_has_one_kind_and_exists():
    names = listed()
    assert len(names) == len(set(names)), "a tool in two kinds"
    assert sorted(set(names) - {spec.name for spec in all_specs()}) == []


def test_every_tool_the_table_sees_has_a_name_in_each_language():
    """Its row reads `tool.<name>`: English keeps the tool's own name, the other languages a label."""
    import json

    i18n = KINDS.parents[1] / "i18n"
    seen = {spec.name for spec in all_specs() if spec.player_visible}
    for path in sorted(i18n.glob("*.json")):
        words = json.loads(path.read_text())
        assert sorted(n for n in seen if f"tool.{n}" not in words) == [], path.name
    english = json.loads((i18n / "en.json").read_text())
    assert all(english[f"tool.{n}"] == n for n in seen)
