"""`delve qa`: the hand QA's tools, made general, for the thorough conversion's agents (thorough conversion Task 3).

An agent runs them in its job folder as `<data dir>/bin/qa <command> …` (the wrapper around `delve qa`, outside every
folder, `thorough.workspace.qa_path`), and they read and write only in the folder: every path they are given is checked with `paths.inside`, and a path outside the folder is refused
with exit code 2. Exit codes: 0 done (and, for `textcheck` and `mapcheck`, nothing found); 1 something found (flags,
map errors) or the input can't be read; 2 refused (a path outside the folder, a wrong argument).

- `pages <pdf> <out-dir> [--dpi 150] [--first N] [--last M]`: `p-NNN.png` and `ocr-NNN.txt` (`pages`).
- `keys <ocr-dir> --pattern <regex> [--first N] [--last M] [--stop <regex>]… [--out <file>]`: the book's entries by key,
  as JSON, printed or written to `<file>` with a line per key printed (`textcheck`).
- `textcheck <parts.json> <file.md>… [--pages <ocr-dir>]`: the text checker (`textcheck`).
- `rotate <in.png> <out.png> <degrees>` and `tile <in.png> <out.png> X0 Y0 X1 Y1 <px> OX OY <width>` (`trace`).
- `mapcheck <file.dmap> [--fix-doors]`: parse, validate, `<file>.svg` and `<file>.png` (`mapcheck`).
- `join <maps-dir> <out-dir>`: the exits joined, and `join-doubts.json` (`join`).
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from delve.conversions.qa.paths import OutsideFolder, inside

REFUSED = 2


def _here(given: str) -> Path:
    return inside(Path.cwd(), given)


def _pages(args: argparse.Namespace) -> int:
    from delve.conversions.qa.pages import render_pages
    from delve.modules.books.pdf import PdfError, tesseract_ocr

    pdf, out = _here(args.pdf), _here(args.out_dir)
    try:
        written = render_pages(pdf, out, dpi=args.dpi, first=args.first, last=args.last, ocr=tesseract_ocr())
    except PdfError as e:
        print(e, file=sys.stderr)
        return 1
    print(f"pages {written[0]} to {written[-1]} written to {args.out_dir} at {args.dpi} dpi")
    return 0


def _keys(args: argparse.Namespace) -> int:
    from delve.conversions.qa.textcheck import book_keys, entries_json

    out = _here(args.out) if args.out else None
    entries = entries_json(
        book_keys(_here(args.ocr_dir), args.pattern, first=args.first, last=args.last, stops=args.stop)
    )
    written = json.dumps(entries, indent=2, ensure_ascii=False)
    if out is None:
        print(written)
        return 0
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(written + "\n", "utf-8")
    for key, entry in entries.items():
        print(f"{key}: page {entry['page']}, {len(entry['text'].split())} words")
    print(f"{len(entries)} keys written to {args.out}")
    return 0


def _textcheck(args: argparse.Namespace) -> int:
    from delve.conversions.qa.textcheck import check_text, read_parts

    parts_path, pages = _here(args.parts), _here(args.pages)
    files = [_here(f) for f in args.files]
    parts = read_parts(parts_path)
    flagged = False
    for path, given in zip(files, args.files, strict=True):
        report = check_text(Path(given).name, path.read_text(), parts, pages)
        print("\n".join(report.lines()))
        flagged = flagged or report.flagged
    return 1 if flagged else 0


def _rotate(args: argparse.Namespace) -> int:
    from delve.conversions.qa.trace import rotate

    size = rotate(_here(args.src), _here(args.out), args.degrees)
    print(f"{size[0]} x {size[1]}")
    return 0


def _tile(args: argparse.Namespace) -> int:
    from delve.conversions.qa.trace import tile

    src, out = _here(args.src), _here(args.out)
    size = tile(src, out, (args.x0, args.y0, args.x1, args.y1), args.px, (args.ox, args.oy), args.width)
    print(f"{size[0]} x {size[1]}")
    return 0


def _mapcheck(args: argparse.Namespace) -> int:
    from delve.conversions.qa.mapcheck import check_map

    path = _here(args.map)
    svg, png = _here(str(Path(args.map).with_suffix(".svg"))), _here(str(Path(args.map).with_suffix(".png")))
    result = check_map(path, svg, png, mend_doors=args.fix_doors)
    for fix in result.fixes:
        print(f"door: {fix}")
    for error in result.errors:
        print(f"error: {error}")
    for warning in result.warnings:
        print(f"warning: {warning}")
    if result.counts:
        print(result.counts)
    if svg.exists() and png.exists() and not any("can't be drawn" in e for e in result.errors):
        print(f"drawn: {svg.name}, {png.name}")
    return 1 if result.errors else 0


def _join(args: argparse.Namespace) -> int:
    from delve.conversions.qa.join import DOUBTS_FILE, join_folder

    joined, doubts = join_folder(_here(args.maps_dir), _here(args.out_dir))
    print(f"{len(joined)} maps written to {args.out_dir}, {len(doubts)} doubts in {DOUBTS_FILE}")
    for doubt in doubts:
        print(f"  {doubt['part']}: {doubt['text']}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="delve qa", description="The thorough conversion's tools; every path is inside the job folder."
    )
    commands = parser.add_subparsers(dest="command", metavar="command", required=True)

    pages = commands.add_parser("pages", help="the PDF's pages as p-NNN.png and their text as ocr-NNN.txt")
    pages.add_argument("pdf")
    pages.add_argument("out_dir")
    pages.add_argument("--dpi", type=int, default=150)
    pages.add_argument("--first", type=int)
    pages.add_argument("--last", type=int)
    pages.set_defaults(func=_pages)

    keys = commands.add_parser("keys", help="the book's entries by key, from the ocr-NNN.txt files, as JSON")
    keys.add_argument("ocr_dir")
    keys.add_argument("--pattern", required=True, help=r"the part's key pattern, for example ^\d+[a-z]?")
    keys.add_argument("--first", type=int)
    keys.add_argument("--last", type=int)
    keys.add_argument("--stop", action="append", default=[], help="another part's key pattern, which ends an entry")
    keys.add_argument("--out", help="write the JSON to this file and print one line per key")
    keys.set_defaults(func=_keys)

    textcheck = commands.add_parser("textcheck", help="each keyed section compared with the book's text layer")
    textcheck.add_argument("parts")
    textcheck.add_argument("files", nargs="+")
    textcheck.add_argument("--pages", default="pages", help="the ocr-NNN.txt files (default pages)")
    textcheck.set_defaults(func=_textcheck)

    rotate = commands.add_parser("rotate", help="a scan turned counter-clockwise (negative: clockwise)")
    rotate.add_argument("src")
    rotate.add_argument("out")
    rotate.add_argument("degrees", type=float)
    rotate.set_defaults(func=_rotate)

    tile = commands.add_parser("tile", help="the squares X0..X1 × Y0..Y1 of a scan, with a numbered grid")
    tile.add_argument("src")
    tile.add_argument("out")
    for name in ("x0", "y0", "x1", "y1"):
        tile.add_argument(name, type=int)
    tile.add_argument("px", type=float, help="a square's size in pixels")
    tile.add_argument("ox", type=float, help="the pixel where square 0 starts, across")
    tile.add_argument("oy", type=float, help="the pixel where square 0 starts, down")
    tile.add_argument("width", type=int, help="the picture's largest side in pixels")
    tile.set_defaults(func=_tile)

    mapcheck = commands.add_parser("mapcheck", help="a .dmap parsed, validated and drawn as .svg and .png")
    mapcheck.add_argument("map")
    mapcheck.add_argument("--fix-doors", action="store_true", help="move doors between rooms that don't meet")
    mapcheck.set_defaults(func=_mapcheck)

    join = commands.add_parser("join", help="the maps' exits joined into exit statements")
    join.add_argument("maps_dir")
    join.add_argument("out_dir")
    join.set_defaults(func=_join)
    return parser


def main(argv: list[str]) -> int:
    parser = build_parser()
    try:
        args = parser.parse_args(argv)
    except SystemExit as exit_:
        return int(exit_.code or 0)
    try:
        return args.func(args)
    except OutsideFolder as e:
        print(e, file=sys.stderr)
        return REFUSED
