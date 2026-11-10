"""`dscn` — pack, unpack, validate, vendor, key and render scenarios."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .container import Bundle, ScenarioError
from .convert import convert_module, upgrade_dmapproj
from .keys import suggest
from .maps import vendor
from .metadata import normalise as normalise_metadata
from .render import render_html
from .validate import has_errors, validate


def _load(path: str) -> Bundle:
    return Bundle.load(path)


def _save(bundle: Bundle, path: str) -> None:
    """Write back in the form the path already has (dir stays dir)."""
    p = Path(path)
    if p.is_dir() or not p.suffix:
        bundle.write_dir(p)
    else:
        bundle.write_zip(p)


def _report(diags) -> int:
    for d in diags:
        print(d, file=sys.stderr if d.severity == "error" else sys.stdout)
    errors = sum(d.severity == "error" for d in diags)
    warnings = len(diags) - errors
    print(f"{errors} error(s), {warnings} warning(s)")
    return 1 if errors else 0


def cmd_new(a) -> int:
    root = Path(a.dir)
    if (root / "scenario.json").exists():
        print(f"{root}/scenario.json already exists", file=sys.stderr)
        return 1
    b = Bundle.new(a.title, system=a.system)
    b.write_dir(root)
    print(f"created {root} (id {b.id})")
    return 0


def cmd_pack(a) -> int:
    b = Bundle.from_dir(Path(a.dir))
    diags = validate(b)
    if has_errors(diags) and not a.force:
        _report(diags)
        print("refusing to pack an invalid scenario (use --force)", file=sys.stderr)
        return 1
    if not a.include_sources:
        _strip_sources(b)
    b.write_zip(a.out)
    print(f"packed {a.out} ({len(b.files) + 1} files)")
    return 0


def _strip_sources(b: Bundle) -> None:
    """R8: published-module sources ship only when asked."""
    keep = []
    for asset in b.entries("assets"):
        if asset.get("role") == "source":
            b.files.pop(asset.get("file"), None)
        else:
            keep.append(asset)
    if "assets" in b.manifest:
        b.manifest["assets"] = keep


def cmd_unpack(a) -> int:
    b = Bundle.load(a.file)
    b.write_dir(Path(a.dir))
    print(f"unpacked to {a.dir}")
    return 0


def cmd_validate(a) -> int:
    return _report(validate(_load(a.path)))


def cmd_vendor(a) -> int:
    b = _load(a.path)
    added = vendor(b)
    _save(b, a.path)
    print("vendored: " + (", ".join(added) if added else "nothing to add"))
    return 0


def cmd_keys(a) -> int:
    b = _load(a.path)
    entries = suggest(b)
    if a.apply:
        b.set_keys(b.entries("keys") + entries)
        _save(b, a.path)
        print(f"added {len(entries)} key(s)")
    else:
        print(json.dumps(entries, indent=2, ensure_ascii=False))
    return 0


def cmd_convert(a) -> int:
    root = Path(a.out)
    b = Bundle.load(root) if (root / "scenario.json").exists() else Bundle.new(a.title or a.id)
    md = Path(a.module).read_text(encoding="utf-8")
    entry, n = convert_module(b, md, text_id=a.id, map_name=a.map, title=a.title,
                              audience=a.audience)
    b.write_dir(root)
    print(f"{entry['file']}: {n} anchor(s) added")
    return 0


def cmd_render(a) -> int:
    html = render_html(_load(a.path))
    Path(a.out).write_text(html, encoding="utf-8")
    print(f"wrote {a.out}")
    return 0


def cmd_upgrade(a) -> int:
    b = upgrade_dmapproj(Path(a.file).read_bytes())
    _save(b, a.out)
    print(f"wrote {a.out} (id {b.id})")
    return 0


def cmd_info(a) -> int:
    b = _load(a.path)
    m = b.manifest
    if a.json:
        print(json.dumps(normalise_metadata(m), indent=2, ensure_ascii=False))
        return 0
    print(f"{b.title}  [{b.id}]")
    for sec in ("maps", "text", "assets", "worldmaps", "keys"):
        print(f"  {sec:10} {len(b.entries(sec))}")
    for kind, path in (m.get("entities") or {}).items():
        print(f"  {kind:10} {len(b.entities(kind))}  ({path})")
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="dscn", description=__doc__)
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("new", help="start a scenario directory")
    s.add_argument("dir"); s.add_argument("--title", required=True)
    s.add_argument("--system"); s.set_defaults(fn=cmd_new)

    s = sub.add_parser("pack", help="directory → deterministic .dscn")
    s.add_argument("dir"); s.add_argument("out")
    s.add_argument("--include-sources", action="store_true",
                   help="keep role=source assets (published module PDFs, …)")
    s.add_argument("--force", action="store_true", help="pack even with validation errors")
    s.set_defaults(fn=cmd_pack)

    s = sub.add_parser("unpack", help=".dscn → directory")
    s.add_argument("file"); s.add_argument("dir"); s.set_defaults(fn=cmd_unpack)

    s = sub.add_parser("validate", help="check a .dscn or directory")
    s.add_argument("path"); s.set_defaults(fn=cmd_validate)

    s = sub.add_parser("vendor", help="copy missing include libraries into maps/lib/")
    s.add_argument("path"); s.set_defaults(fn=cmd_vendor)

    s = sub.add_parser("keys", help="suggest keys[] entries for keyed text")
    s.add_argument("path")
    s.add_argument("--suggest", action="store_true", help="print suggestions (default)")
    s.add_argument("--apply", action="store_true", help="append the suggestions to keys[]")
    s.set_defaults(fn=cmd_keys)

    s = sub.add_parser("convert-module", help="ttrpg2 module.md → keyed text in a scenario dir")
    s.add_argument("module"); s.add_argument("-o", "--out", required=True)
    s.add_argument("--id", default="module"); s.add_argument("--map")
    s.add_argument("--title"); s.add_argument("--audience", choices=("gm", "player"))
    s.set_defaults(fn=cmd_convert)

    s = sub.add_parser("render", help="scenario → one self-contained HTML page")
    s.add_argument("path"); s.add_argument("-o", "--out", required=True)
    s.set_defaults(fn=cmd_render)

    s = sub.add_parser("upgrade", help=".dmapproj → .dscn (maps only)")
    s.add_argument("file"); s.add_argument("out"); s.set_defaults(fn=cmd_upgrade)

    s = sub.add_parser("info", help="summarise a scenario")
    s.add_argument("path")
    s.add_argument("--json", action="store_true", help="print the normalised metadata as JSON")
    s.set_defaults(fn=cmd_info)
    return p


def main(argv: list[str] | None = None) -> int:
    a = build_parser().parse_args(argv)
    try:
        return a.fn(a)
    except ScenarioError as e:
        print(f"error: {e}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
