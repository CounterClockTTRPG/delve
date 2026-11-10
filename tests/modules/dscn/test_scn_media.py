"""The SVG active-content check (§9.1) parses the picture instead of
matching a pattern (DEL-154, audit finding 12): each case below got past
the old regex, or would have, and must still be refused; plain art passes."""
from __future__ import annotations

from pathlib import Path

import pytest

from delve.modules.dscn.media import svg_is_active

NS = 'xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink"'


def svg(body: str, attrs: str = "") -> bytes:
    return f'<svg {NS} {attrs}>{body}</svg>'.encode()


PLAIN = [
    svg('<rect width="10" height="10" fill="red"/>'),
    svg('<defs><circle id="c" r="3"/></defs><use href="#c"/><use xlink:href="#c" x="5"/>'),
    svg('<image href="data:image/png;base64,iVBORw0KGgo=" width="4" height="4"/>'),
    svg('<linearGradient id="g"/><rect fill="url(#g)" style="fill: url(#g)"/>'),
    svg('<text font-family="Garamond">The <tspan>Crypt</tspan> &amp; the onion</text>'),
    svg('<style>rect { fill: url(#g); stroke: blue }</style><rect/>'),
    svg('<title>Entry hall</title><desc>Steps go down.</desc><rect/>'),
    b'<?xml version="1.0" encoding="UTF-8"?>\n' + svg("<rect/>"),
    b"\xef\xbb\xbf" + svg("<rect/>"),
    svg('<a href="#room-2"><rect/></a>'),
    # Illustrator's and older Inkscape's plain DOCTYPE: it declares nothing, and expat never fetches the DTD.
    b'<!DOCTYPE svg PUBLIC "-//W3C//DTD SVG 1.1//EN" '
    b'"http://www.w3.org/Graphics/SVG/1.1/DTD/svg11.dtd">' + svg("<rect/>"),
    svg('<rect/>', 'version="1.1" data-online="yes"'),
]


@pytest.mark.parametrize("data", PLAIN)
def test_plain_art_passes(data):
    assert svg_is_active(data) is False


def test_the_maps_own_svg_passes():
    fixture = Path(__file__).parents[2] / "maps" / "data" / "fogged_single.svg"
    assert svg_is_active(fixture.read_bytes()) is False


ACTIVE = {
    "script": svg("<script>alert(1)</script>"),
    "script, mixed case": svg("<ScRiPt>alert(1)</ScRiPt>"),
    "script, svg prefix": b'<svg:svg xmlns:svg="http://www.w3.org/2000/svg"><svg:script>alert(1)</svg:script></svg:svg>',
    "script, xhtml namespace": svg('<h:script xmlns:h="http://www.w3.org/1999/xhtml">alert(1)</h:script>'),
    "script, whitespace in the tag": svg("<script\n>alert(1)</script\n>"),
    "foreignObject": svg("<foreignObject><div/></foreignObject>"),
    "foreignobject, lower case": svg("<foreignobject><div/></foreignobject>"),
    "iframe": svg('<iframe src="https://evil.example/"/>'),
    "embed": svg('<embed src="x.swf"/>'),
    "object": svg('<object data="x.html"/>'),
    "handler": svg("", 'onload="alert(1)"'),
    "handler, upper case": svg('<rect ONCLICK="alert(1)"/>'),
    "handler, after a newline": svg('<rect\nonmouseover="alert(1)"/>'),
    "handler, whitespace round the equals": svg('<rect onfocusin\t=\t"alert(1)"/>'),
    "handler, in a namespace": svg('<rect xmlns:e="urn:x" e:onclick="alert(1)"/>'),
    "handler, quoted with apostrophes": svg("<rect onbegin='alert(1)'/>"),
    "javascript href": svg('<a href="javascript:alert(1)"><rect/></a>'),
    "javascript xlink:href, mixed case": svg('<a xlink:href="JaVaScRiPt:alert(1)"><rect/></a>'),
    "javascript, entity encoded": svg('<a href="javascript&#58;alert(1)"><rect/></a>'),
    "javascript, all entities": svg('<a href="&#x6a;&#x61;vascript:alert(1)"><rect/></a>'),
    "javascript, tab inside": svg('<a href="java&#9;script:alert(1)"><rect/></a>'),
    "javascript, leading space": svg('<a href="  javascript:alert(1)"><rect/></a>'),
    "javascript, other prefix for xlink": svg('<a xmlns:l="http://www.w3.org/1999/xlink" l:href="javascript:x()"/>'),
    "vbscript": svg('<a href="vbscript:msgbox(1)"><rect/></a>'),
    "data:text/html": svg('<a href="data:text/html,&lt;script&gt;alert(1)&lt;/script&gt;"><rect/></a>'),
    "data: in mixed case": svg('<a href="DATA:text/html;base64,PHNjcmlwdD4="><rect/></a>'),
    "a nested svg as data": svg('<image href="data:image/svg+xml;base64,PHN2Zz48L3N2Zz4="/>'),
    "external image": svg('<image href="https://tracker.example/p.png"/>'),
    "protocol-relative image": svg('<image xlink:href="//tracker.example/p.png"/>'),
    "external use": svg('<use href="other.svg#x"/>'),
    "external use, absolute": svg('<use xlink:href="https://evil.example/sprite.svg#x"/>'),
    "animated href": svg('<a><set attributeName="href" to="javascript:alert(1)"/><rect/></a>'),
    "animated xlink:href": svg('<a><animate attributeName="xlink:href" values="javascript:alert(1)"/></a>'),
    "external stylesheet": b'<?xml-stylesheet href="https://evil.example/x.css"?>' + svg("<rect/>"),
    "style @import": svg('<style>@import url("https://evil.example/x.css");</style>'),
    "style url, external": svg('<style>rect { fill: url(https://evil.example/x) }</style>'),
    "style attribute url, javascript": svg('<rect style="background: url( javascript:alert(1) )"/>'),
    "doctype with an internal subset": b'<!DOCTYPE svg [<!ATTLIST svg onload CDATA "alert(1)">]>' + svg("<rect/>"),
    "entity declaration": b'<!DOCTYPE svg [<!ENTITY js "javascript:alert(1)">]>' + svg('<a href="&js;"/>'),
    "billion laughs": b'<!DOCTYPE svg [<!ENTITY a "aaaaaaaaaa"><!ENTITY b "&a;&a;&a;&a;&a;&a;&a;&a;&a;&a;">'
                      b'<!ENTITY c "&b;&b;&b;&b;&b;&b;&b;&b;&b;&b;">]>' + svg("<text>&c;</text>"),
    "external entity": b'<!DOCTYPE svg [<!ENTITY x SYSTEM "file:///etc/passwd">]>' + svg("<text>&x;</text>"),
    "not well-formed": b'<svg xmlns="http://www.w3.org/2000/svg"><rect></svg>',
    "unbound prefix": b'<svg xmlns="http://www.w3.org/2000/svg"><x:script>alert(1)</x:script></svg>',
    "not xml at all": b"<svg <script>alert(1)</script>",
    "empty": b"",
}


@pytest.mark.parametrize("data", ACTIVE.values(), ids=ACTIVE.keys())
def test_active_content_is_refused(data):
    assert svg_is_active(data) is True
