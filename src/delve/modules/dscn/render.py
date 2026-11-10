"""`dscn render` — the whole scenario as one self-contained HTML page:
each map (GM view) followed by its keyed text, read-aloud boxed.

Untrusted-input safe: raw HTML in author Markdown is escaped, not passed
through, and only `asset:` images become data URIs.
"""
from __future__ import annotations

from html import escape

import delve.maps.dsl as dungml
from markdown_it import MarkdownIt

from .assets import bundle_resolver, inline_marker_images
from .container import ENTITY_KINDS, Bundle
from .maps import analyse_maps
from .media import IMAGE_TYPES, data_uri
from .metadata import normalise as normalise_metadata
from .refs import _MD_WIKI_RX, ENTITY_REF_KINDS, parse_ref
from .text import _ANCHOR_RX, split_front_matter

_STYLE = """
:root { color-scheme: light; }
body { font-family: Georgia, 'Iowan Old Style', serif; font-size: 12pt; line-height: 1.45;
  color: #111; max-width: 9in; margin: 0.5in auto; padding: 0 0.5in; background: #fdfaf3; }
h1 { font-size: 24pt; margin-bottom: 0.2em; }
header.scenario { border-bottom: 2px solid #444; margin-bottom: 1em; }
.meta { color: #555; font-size: 10.5pt; }
blockquote { border: 1.5px solid #444; background: #f4ecd6; padding: 0.6em 1em; margin: 0.8em 0; }
blockquote p { margin: 0.3em 0; }
section.map { margin-top: 2em; padding-top: 1em; border-top: 1px dashed #999; page-break-before: always; }
section.map figure { margin: 1em 0; text-align: center; }
section.map svg { max-width: 100%; height: auto; }
.map-error { border: 1.5px dashed #b33; padding: 0.6em 1em; color: #b33; }
.audience { font: 9pt sans-serif; background: #8a6a32; color: #fff; padding: 1px 6px; border-radius: 3px; }
table { border-collapse: collapse; } td, th { border: 1px solid #aaa; padding: 2px 6px; }
section.entities h3 { margin-bottom: 0.2em; }
img { max-width: 100%; }
@media print { body { background: #fff; } }
"""


def _anchor_id(tid: str, anchor: str) -> str:
    return f"text-{tid}-{anchor}"


class _Renderer:
    def __init__(self, bundle: Bundle):
        self.b = bundle
        self.md = MarkdownIt("commonmark", {"html": False}).enable("table").enable("strikethrough")
        self.names: dict[str, str] = {}
        for kind in ENTITY_KINDS:
            for r in bundle.entities(kind):
                if isinstance(r.get("id"), str):
                    pk = next(k for k, v in ENTITY_REF_KINDS.items() if v == kind)
                    self.names[f"{pk}:{r['id']}"] = str(r.get("name") or r["id"])

    def href(self, ref: str) -> str:
        r = parse_ref(ref)
        if r is None:
            return ref
        if r.kind == "text":
            return "#" + (_anchor_id(r.id, r.fragment) if r.fragment else f"text-{r.id}")
        if r.kind == "map":
            return f"#map-{r.id}"
        if r.kind in ENTITY_REF_KINDS:
            return f"#{r.kind}-{r.id}"
        if r.kind == "key":
            return f"#key-{r.id}"
        return "#"

    def markdown(self, text: str, tid: str | None = None) -> str:
        def wiki(m):
            ref = m.group(1)
            return f"[{self.names.get(ref, ref.split(':', 1)[1])}]({ref})"

        text = _MD_WIKI_RX.sub(wiki, text)
        tokens = self.md.parse(text)
        for i, tok in enumerate(tokens):
            if tok.type == "heading_open" and i + 1 < len(tokens):
                inline = tokens[i + 1]
                m = _ANCHOR_RX.search(inline.content)
                if m and tid:
                    tok.attrSet("id", _anchor_id(tid, m.group(1)))
                    for child in reversed(inline.children or []):
                        if child.type == "text":
                            child.content = _ANCHOR_RX.sub("", child.content)
                            break
            if tok.type == "inline":
                for child in tok.children or []:
                    if child.type == "link_open":
                        href = child.attrGet("href") or ""
                        if parse_ref(href):
                            child.attrSet("href", self.href(href))
                    elif child.type == "image":
                        src = child.attrGet("src") or ""
                        if src.startswith("asset:"):
                            a = self.b.asset_entry(src[6:])
                            if a and a.get("type") in IMAGE_TYPES and a.get("file") in self.b.files:
                                child.attrSet("src", data_uri(a["type"], self.b.files[a["file"]]))
        return self.md.renderer.render(tokens, self.md.options, {})

    def text_block(self, t: dict) -> str:
        if t.get("file") not in self.b.files:
            return ""
        _fm, body, _ = split_front_matter(self.b.read_text(t["file"]))
        aud = t.get("audience", "gm")
        badge = f'<span class="audience">{escape(aud)}</span>'
        title = escape(t.get("title") or t["id"])
        return (f'<section class="text" id="text-{escape(t["id"])}">'
                f"<h2>{title} {badge}</h2>{self.markdown(body, t['id'])}</section>")

    def render(self) -> str:
        b = self.b
        m = b.manifest
        md = normalise_metadata(m)
        parts = [f"<header class='scenario'><h1>{escape(b.title)}</h1>"]
        if md.get("subtitle"):
            parts.append(f"<p class='meta'><em>{escape(md['subtitle'])}</em></p>")
        if md.get("cover"):
            a = b.asset_entry(md["cover"][6:])
            if a and a.get("type") in IMAGE_TYPES and a.get("file") in b.files:
                parts.append(f"<img alt='cover' src='{data_uri(a['type'], b.files[a['file']])}'>")
        meta = [
            ", ".join(p["name"] for p in md.get("authors", [])) and
            "by " + ", ".join(p["name"] for p in md.get("authors", [])),
            md.get("release") and f"v{md['release']['version']}",
            md.get("system_name") or md.get("system"),
            md.get("setting"),
            _range_text("levels", (md.get("party") or {}).get("levels")),
            _range_text("players", (md.get("party") or {}).get("size")),
            _range_text("sessions", (md.get("duration") or {}).get("sessions")),
            (md.get("license") or {}).get("spdx") or (md.get("license") or {}).get("name"),
        ]
        meta = [x for x in meta if x]
        if meta:
            parts.append(f"<p class='meta'>{' · '.join(escape(str(x)) for x in meta)}</p>")
        for k in ("summary", "description"):
            if md.get(k):
                parts.append(self.markdown(str(md[k])))
        if md.get("content_warnings"):
            parts.append("<p class='meta'>Content warnings: "
                         f"{escape(', '.join(md['content_warnings']))}</p>")
        parts.append("</header>")

        texts = b.entries("text")
        for t in texts:
            if not t.get("map"):
                parts.append(self.text_block(t))

        infos = analyse_maps(b)
        resolver = bundle_resolver(b)
        for entry in b.maps("map"):
            name = entry["name"]
            info = infos.get(name)
            parts.append(f'<section class="map" id="map-{escape(name)}">'
                         f"<h2>{escape(entry.get('title') or name)}</h2>")
            if info is None or info.model is None:
                why = info.error if info else "not analysed"
                parts.append(f'<div class="map-error">map could not be rendered: {escape(str(why))}</div>')
            else:
                inline_marker_images(info.model, resolver, players=False)
                try:
                    svg = dungml.render(info.model)
                    parts.append(f"<figure>{svg}</figure>")
                except Exception as e:  # a renderer bug must not lose the text
                    parts.append(f'<div class="map-error">render failed: {escape(str(e))}</div>')
            for t in texts:
                if t.get("map") == name:
                    parts.append(self.text_block(t))
            parts.append("</section>")

        ents: list[str] = []
        for kind in ENTITY_KINDS:
            recs = b.entities(kind)
            if not recs:
                continue
            pk = next(k for k, v in ENTITY_REF_KINDS.items() if v == kind)
            ents.append(f"<h2>{escape(kind.title())}</h2>")
            for r in recs:
                rid = str(r.get("id"))
                name = escape(str(r.get("name") or rid))
                body = r.get("description") or r.get("text") or r.get("summary") or ""
                ents.append(f'<div id="{pk}-{escape(rid)}"><h3>{name}</h3>'
                            f"{self.markdown(str(body)) if body else ''}</div>")
        if ents:
            parts.append('<section class="entities">' + "".join(ents) + "</section>")

        return ("<!doctype html><html><head><meta charset='utf-8'>"
                "<meta name='viewport' content='width=device-width, initial-scale=1'>"
                f"<title>{escape(b.title)}</title><style>{_STYLE}</style></head>"
                f"<body>{''.join(parts)}</body></html>")


def _range_text(label: str, r: dict | None) -> str:
    if not r:
        return ""
    span = f"{r['min']}" if r["min"] == r["max"] else f"{r['min']}–{r['max']}"
    rec = r.get("recommended")
    return f"{label} {span}" + (f" (best {rec})" if rec is not None and r["min"] != r["max"] else "")


def render_html(bundle: Bundle) -> str:
    return _Renderer(bundle).render()
