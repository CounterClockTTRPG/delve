"""Convert a real module PDF with the real `claude` (plan 5 Task 8): the owner's opt-in check, never run in ci.

    make convert-live PDF=<file> [TITLE="The Sunken Shrine"]
    uv run python scripts/convert_live.py <file> [--title …] [--mode ready|draft] [--out DIR]

It spends tokens. The conversion runs as `delve serve` runs it (`delve.conversions.start_pdf`, with the `conversion`
job's default: `claude-cli`, model `sonnet`, effort `medium`, `CONVERSION_TIMEOUT` per call), with tesseract for
scanned pages when it is installed, into a temporary data dir: the owner's data dir is never opened. It prints the
time of every Claude call (each chunk of pages, each text's entities, each map sketch, the metadata), the module's warnings, and the
word coverage: the words of the module's texts out of the words read from the PDF. The module is left as a `.dscn` in
`evals/recordings/conversions/` (kept out of git), to open in Delve with "Import a .dscn".
"""

from __future__ import annotations

import argparse
import asyncio
import re
import shutil
import sys
import tempfile
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from delve.config import Config
from delve.conversions import ConversionServices, start_pdf, wait
from delve.conversions.runner import CONVERSION_TIMEOUT
from delve.dm.claude_cli import ClaudeCliProvider, MemorySessions
from delve.dm.provider import Usage
from delve.domain.settings import JOB_DEFAULTS, BackendChoice, Job
from delve.modules.books.pdf import read_pdf, tesseract_ocr
from delve.modules.dscn import slugify
from delve.modules.exporter import export_module
from delve.modules.source import load_source
from delve.storage import open_storage

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_OUT = ROOT / "evals" / "recordings" / "conversions"

KINDS = {
    "You are converting part of": "chunk",
    "Below, between `<text>`": "entities",
    "You draw a schematic map": "sketch",
    "You describe a role-playing adventure module": "metadata",
}
_PAGES = re.compile(r"was read from (pages? [\d–]+)")
_TEXT = re.compile(r"`text:([^#`]+)#")


@dataclass
class Call:
    kind: str
    what: str
    seconds: float
    prompt_chars: int
    answer_chars: int
    error: str = ""


class Timed:
    """The provider's side calls, timed one by one."""

    def __init__(self, provider: ClaudeCliProvider) -> None:
        self.provider = provider
        self.calls: list[Call] = []

    async def side_call(
        self,
        prompt: str,
        choice: BackendChoice,
        *,
        timeout: float | None = None,
        on_usage: Callable[[Usage], None] | None = None,
    ) -> str:
        kind = next((kind for start, kind in KINDS.items() if prompt.startswith(start)), "other")
        found = (_PAGES if kind == "chunk" else _TEXT).search(prompt)
        what = found.group(1) if found else ("retry" if "\n---\n\nYour map:" in prompt else "")
        started = time.monotonic()
        try:
            answer = await self.provider.side_call(prompt, choice, timeout=timeout, on_usage=on_usage)
        except Exception as error:
            self.calls.append(Call(kind, what, time.monotonic() - started, len(prompt), 0, str(error)))
            raise
        self.calls.append(Call(kind, what, time.monotonic() - started, len(prompt), len(answer)))
        return answer


def words(text: str) -> int:
    return len(re.findall(r"\w+", text))


async def convert(pdf: Path, title: str, mode: str, out: Path) -> int:
    if shutil.which("claude") is None:
        print("convert-live needs `claude` on PATH.", file=sys.stderr)
        return 2
    data_dir = Path(tempfile.mkdtemp(prefix="delve-convert-live-"))
    storage = open_storage(Config(data_dir=data_dir))
    timed = Timed(ClaudeCliProvider(data_dir, MemorySessions()))
    choice = JOB_DEFAULTS[Job.CONVERSION]
    ocr = tesseract_ocr()
    print(f"Converting {pdf} as “{title}” ({mode}), into {data_dir}")
    print(f"Claude: {choice.provider}, model {choice.model}, effort {choice.effort}; {CONVERSION_TIMEOUT:g} s per call")
    print(f"OCR: {'tesseract' if ocr else 'none (scanned pages become warnings)'}\n")

    last = [""]

    def publish(kind: str, data: dict) -> None:
        line = f"  {data['status']:<9} {data['step']:<11} {data['done']}/{data['total']}"
        if line != last[0]:
            print(line, flush=True)
            last[0] = line

    services = ConversionServices(storage, conversion=lambda: (timed, choice), publish=publish, ocr=ocr)
    work = data_dir / "upload.pdf"
    shutil.copyfile(pdf, work)  # the job removes its file when it ends
    started = time.monotonic()
    try:
        conversion = await wait(services, (await start_pdf(services, work, title, mode)).id)
    finally:
        took = time.monotonic() - started

    print(f"\nClaude calls ({len(timed.calls)}):")
    for call in timed.calls:
        failed = f"  FAILED: {call.error}" if call.error else ""
        print(
            f"  {call.kind:<9} {call.what:<28} {call.seconds:7.1f} s"
            f"  prompt {call.prompt_chars:>7} chars  answer {call.answer_chars:>7} chars{failed}"
        )
    print(f"\nThe conversion {conversion.status} in {took:.0f} s.")
    if conversion.status != "done" or conversion.module_id is None:
        print(f"No module: {conversion.error}")
        storage.close()
        return 1

    print(f"\nWarnings ({len(conversion.warnings)}):")
    for warning in conversion.warnings:
        print(f"  {warning['code']:<18} {warning['ref']:<24} {warning['message']}")

    book = read_pdf(pdf, ocr=ocr)
    source = load_source(storage, conversion.module_id)
    read = sum(words(page.text) for page in book.pages)
    kept = sum(words(text.markdown) for text in source.texts)
    share = kept / read if read else 0.0
    print(f"\nWord coverage: {kept} words in {len(source.texts)} texts, of {read} read from {len(book.pages)} pages")
    print(f"  ({share:.0%}; headings' anchors and Markdown add a little, page headers and footers left out take some)")
    short = [w for w in conversion.warnings if w["code"] == "conversion-short"]
    if short:
        print(f"  {len(short)} chunks kept the PDF's text instead of Claude's: {', '.join(w['ref'] for w in short)}")

    out.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    dscn = export_module(storage, conversion.module_id).write_zip(out / f"{slugify(title) or 'module'}-{stamp}.dscn")
    storage.close()
    print(f"\nThe module: {dscn}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("pdf", type=Path)
    parser.add_argument("--title", help="the module's title (default: the file's name)")
    parser.add_argument("--mode", choices=("ready", "draft"), default="draft")
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT, help="where the .dscn goes")
    args = parser.parse_args(argv)
    if not args.pdf.is_file():
        parser.error(f"no such file: {args.pdf}")
    title = (args.title or args.pdf.stem).strip()
    return asyncio.run(convert(args.pdf, title, args.mode, args.out))


if __name__ == "__main__":
    sys.exit(main())
