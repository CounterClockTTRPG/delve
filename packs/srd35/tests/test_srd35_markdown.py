"""The SRD's text as the Rulesets' Markdown (DEL-394): every table of the conversion a pipe table, paragraphs and list
items on one line each."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from srd35_extract.markdown import markdown


def test_a_simple_table_is_a_pipe_table_under_its_caption():
    text = (
        "Skill Points.\n\n"
        "  ------- ------------------- -----------\n"
        "  Level   Base Attack Bonus   Special\n"
        "  1st     +1                  Bonus feat\n"
        "  2nd     +2                  \n"
        "  ------- ------------------- -----------\n\n"
        "  : Table: The Fighter\n\n"
        "After."
    )
    assert markdown(text) == (
        "Skill Points.\n\n**Table: The Fighter**\n\n"
        "| Level | Base Attack Bonus | Special |\n| --- | --- | --- |\n| 1st | +1 | Bonus feat |\n| 2nd | +2 |  |\n\n"
        "After."
    )


def test_a_multiline_tables_rows_are_its_blocks():
    text = (
        "  ------ ------------- ------\n"
        "  NPC    Base Attack\\   Fort\\\n"
        "  Level  Bonus          Save\n\n"
        "  1st    +0             +0\n\n"
        "  2nd    +1             +0\n"
        "  ------ ------------- ------\n"
    )
    assert (
        markdown(text)
        == "| NPC Level | Base Attack Bonus | Fort Save |\n| --- | --- | --- |\n| 1st | +0 | +0 |\n| 2nd | +1 | +0 |"
    )


def test_a_simple_tables_title_and_footnotes_sit_outside_it():
    text = (
        "  ---------------------------------------------- ----------------\n"
        "  Narrow Surface Modifiers\n"
        "  Surface                                        DC Modifier^1^\n"
        "  Lightly obstructed                             +2\n"
        "  1 Add the appropriate modifier to the Balance DC of a narrow surface.\n"
        "  These modifiers stack.\n"
        "  ---------------------------------------------- ----------------\n"
    )
    assert markdown(text) == (
        "**Narrow Surface Modifiers**\n\n| Surface | DC Modifier¹ |\n| --- | --- |\n| Lightly obstructed | +2 |\n\n"
        "1 Add the appropriate modifier to the Balance DC of a narrow surface. These modifiers stack."
    )


def test_a_cell_that_overflows_its_column_stays_in_the_one_it_mostly_fills():
    text = "  ---- ---- ----\n  Load Max  Run\n  Med  +3  (20 ft.)\n  ---- ---- ----\n"
    assert markdown(text).splitlines()[-1] == "| Med | +3 | (20 ft.) |"


def test_a_grid_table_joins_its_cells_lines_and_a_word_broken_over_two():
    text = (
        "The spellcasting class gains.\n\n"
        "+-------+-----------+\n"
        "| Level | Spells    |\n"
        "|       | per Day   |\n"
        "+-------+-----------+\n"
        "| 1st   | <div>     |\n"
        "|       |           |\n"
        "|       | +1 level  |\n"
        "|       | spe       |\n"
        "|       | llcasting |\n"
        "|       | class/    |\n"
        "|       | </div>    |\n"
        "|       | <div>     |\n"
        "|       | +1 more   |\n"
        "|       | </div>    |\n"
        "+-------+-----------+\n\n"
        ": Table: The Mystic Theurge\n"
    )
    assert markdown(text) == (
        "The spellcasting class gains.\n\n**Table: The Mystic Theurge**\n\n"
        "| Level | Spells per Day |\n| --- | --- |\n| 1st | +1 level spellcasting class/+1 more |"
    )


def test_an_html_table_keeps_its_caption_column_group_and_footnote():
    text = (
        '<table class="full-width-table">\n<caption>Table: The Monk</caption>\n<tbody>\n'
        '<tr><th></th><th colspan="2"><span style="x">Spells\nper Day<sup>1</sup> </span></th></tr>\n'
        "<tr><th>Level</th><th>0</th><th>1st</th></tr>\n"
        "<tr><th>1st</th><th>3</th><th>—</th></tr>\n"
        '<tr><td colspan="3"><sup>1</sup> The value shown is for Medium monks. See it.</td></tr>\n'
        "</tbody>\n</table>\n\n: Table: The Monk\n"
    )
    assert markdown(text) == (
        "**Table: The Monk**\n\n| Level | Spells per Day¹: 0 | 1st |\n| --- | --- | --- |\n| 1st | 3 | — |\n\n"
        "¹ The value shown is for Medium monks. See it."
    )


def test_a_pipe_tables_separators_stay_dashes_and_its_repeated_footnote_shows_once():
    text = (
        "| **Creature** | **Faint** |\n"
        "| ------------ | --------- |\n"
        "| Evil creature **<sup>1</sup>** (HD) | 10 or lower |\n"
        "| 1 Except for undead and outsiders, which have their own entries. |\n"
        "1 Except for undead and outsiders, which have their own entries.\n"
        "2 Some characters who are not clerics may radiate an aura.\n"
    )
    assert markdown(text) == (
        "| **Creature** | **Faint** |\n| --- | --- |\n| Evil creature ¹ (HD) | 10 or lower |\n\n"
        "1 Except for undead and outsiders, which have their own entries.\n\n"
        "2 Some characters who are not clerics may radiate an aura."
    )


def test_pipe_rows_inside_a_simple_rule_lose_their_repeated_separators_and_empty_column():
    text = (
        "  -------------- ------------------\n"
        "|Lever (1d10)||Lever Function|\n| --- | --- | --- |\n"
        "|1           ||Extend/retract legs|\n| --- | --- | --- |\n"
        "  -------------- ------------------\n"
    )
    assert markdown(text) == "| Lever (1d10) | Lever Function |\n| --- | --- |\n| 1 | Extend/retract legs |"


def test_paragraphs_and_list_items_are_one_line_each():
    text = (
        "### Alignment\nA cleric's alignment must be\nwithin one step.\n\n"
        "-   <div>\n\n    +2 Strength, --2 Charisma.\n\n    </div>\n\n    <div>\n\n"
        "    A half-orc's Intelligence is\n    at least 3.\n\n    </div>\n\n"
        "-   Medium: As Medium creatures, half-orcs have no\n    special bonuses.\n\n"
        "Afterwards."
    )
    assert markdown(text) == (
        "### Alignment\n\nA cleric's alignment must be within one step.\n\n"
        "- +2 Strength, –2 Charisma. A half-orc's Intelligence is at least 3.\n"
        "- Medium: As Medium creatures, half-orcs have no special bonuses.\n\n"
        "Afterwards."
    )


def test_a_bold_label_loses_its_dash_decoration():
    assert markdown("**--------- Aura Power ---------**") == "**Aura Power**"


def test_a_header_over_rows_keeps_its_group_and_loses_its_styling():
    text = (
        "  -------- ------------------- ------------\n"
        '  Initial         []{style="\n'
        "                    display: block;\n"
        '        "}[New Attitude]{style="padding: 0 8px"}\n'
        "           Hostile             Friendly\n"
        "  Hostile  Less than 20        35\n"
        "  -------- ------------------- ------------\n"
    )
    assert markdown(text) == (
        "| Initial | New Attitude: Hostile | Friendly |\n| --- | --- | --- |\n| Hostile | Less than 20 | 35 |"
    )


def test_a_simple_tables_lines_behind_a_pipe_are_still_its_rows():
    """Bag of Tricks: tables side by side, their lines behind a `|` and between pipe separators."""

    def at(*cells: tuple[int, str]) -> str:
        line = ""
        for column, text in cells:
            line = line.ljust(column) + text
        return line

    rule = at((2, "-" * 70), (73, "-" * 10), (84, "-" * 10)) + "\n"
    text = (
        rule
        + at((0, "|"), (40, "d%"), (73, "Animal"), (84, "||Note|"))
        + "\n| --- | --- | --- |\n"
        + at((0, "|"), (39, "01--30"), (73, "Bat"), (84, "||Flies|"))
        + "\n| --- | --- | --- |\n"
        + rule
    )
    assert markdown(text) == "| d% | Animal | Note |\n| --- | --- | --- |\n| 01–30 | Bat | Flies |"


def test_a_grid_cells_styling_and_words_broken_anywhere_are_undone():
    text = (
        "Simple weapons deal bludgeoning damage, by weight.\n\n"
        "+-------+-------+\n"
        "| S     | Weig  |\n"
        "| imple | ht^1^ |\n"
        "+-------+-------+\n"
        "| :::   | 1 lb. |\n"
        "|  {sty | B     |\n"
        '| le="m | ludge |\n'
        '| 6em"} | oning |\n'
        "| Club  |       |\n"
        "| :::   |       |\n"
        "+-------+-------+\n"
    )
    assert markdown(text).endswith("| Simple | Weight¹ |\n| --- | --- |\n| Club | 1 lb. Bludgeoning |")
