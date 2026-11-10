"""A setting page's text (settings plan Task 4): DM-only sections, the shipped wiki's markup as Markdown, its links and
search snippets."""

from delve.setting.text import DM_CLOSE, DM_OPEN, dm_section, player_text, snippet, wiki_markdown


def test_player_text_drops_a_closed_and_an_unclosed_dm_section():
    text = "Hardby is a port.\n\n::: dm\nSECRET-XYZZY the Despotrix.\n:::\n\nIts gates.\n\n::: dm\nSECRET-XYZZY again"
    assert player_text(text) == "Hardby is a port.\n\nIts gates."
    assert player_text("No secrets here.") == "No secrets here."
    assert player_text("::: dm\nAll of it.") == ""


def test_a_dm_marker_counts_only_as_a_line_of_its_own():
    text = "Write ::: dm inline.\n  ::: dm  \nhidden\n:::\nshown"
    assert player_text(text) == "Write ::: dm inline.\nshown"


def test_dm_section_wraps_the_text():
    assert dm_section("The Despotrix.") == f"{DM_OPEN}\nThe Despotrix.\n{DM_CLOSE}"
    assert player_text("Open.\n\n" + dm_section("SECRET-XYZZY")) == "Open."


def test_wiki_markdown():
    raw = (
        "{{Infobox settlement\n| name = Hardby\n| realm = {{flag|Hardby}}\n}}\n"
        "[[File:Hardby.png|thumb|The port]]\n"
        "==History==\n"
        "'''Hardby''' is ''old'', see [[Greyhawk City|the city]].<ref>WoG p. 12</ref> "
        "[https://example.org the site] <span>Hi</span>\n"
        "===Gates===\n[[Category:Settlements]]"
    )
    assert wiki_markdown(raw) == (
        "## History\n\n**Hardby** is *old*, see [[Greyhawk City|the city]]. the site Hi\n\n### Gates"
    )
    assert wiki_markdown("==History==\n'''Hardby''' … [[Greyhawk City|the city]]") == (
        "## History\n\n**Hardby** … [[Greyhawk City|the city]]"
    )


def test_snippet_marks_the_words():
    text = "Many towns line the Woolly Bay. " * 5 + "The port of hardby has eight gates. " + "It rains. " * 20
    found = snippet(text, ["Hardby", "gates"])
    assert "<<hardby>>" in found and "<<gates>>" in found
    assert found.startswith("…") and found.endswith("…")
    assert len(found) < 150
    assert snippet("Short text.", ["nothing"]) == "Short text."
    assert snippet("A\nport", ["port"]) == "A <<port>>"
