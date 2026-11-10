"""A pack imports Delve only through the modules of `PACK_IMPORTS`."""

import ast
import os
from pathlib import Path

from delve.packs.api import PACK_IMPORTS

ROOT = Path(__file__).resolve().parents[2]


def pack_sources() -> list[Path]:
    """The `src` folder of each pack in the repo's `packs/` and, when `$DELVE_PACKS_SRC` is set, of each pack in it."""
    sources = sorted(ROOT.glob("packs/*/src"))
    extra = os.environ.get("DELVE_PACKS_SRC")
    if extra:
        sources += sorted(p for p in Path(extra).expanduser().glob("*/src") if p.is_dir())
    return sources


def allowed(module: str) -> bool:
    return any(module == ok or module.startswith(ok + ".") for ok in PACK_IMPORTS)


def test_pack_imports_only_the_pack_api():
    refused = []
    for src in pack_sources():
        for path in sorted(src.rglob("*.py")):
            for node in ast.walk(ast.parse(path.read_text("utf-8"), str(path))):
                if isinstance(node, ast.Import):
                    modules = [(a.name, node.lineno) for a in node.names]
                elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                    modules = [(node.module, node.lineno)]
                else:
                    continue
                for module, line in modules:
                    if (module == "delve" or module.startswith("delve.")) and not allowed(module):
                        refused.append(f"{path}:{line}: {module}")
    assert not refused, "\n".join(refused)


def test_core_never_imports_a_pack():
    """Core reaches a pack only through the loader, never by importing its package."""
    refused = []
    for path in sorted((ROOT / "src" / "delve").rglob("*.py")):
        for node in ast.walk(ast.parse(path.read_text("utf-8"), str(path))):
            if isinstance(node, ast.Import):
                modules = [(a.name, node.lineno) for a in node.names]
            elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                modules = [(node.module, node.lineno)]
            else:
                continue
            for module, line in modules:
                if module.split(".")[0].startswith("delve_"):
                    refused.append(f"{path}:{line}: {module}")
    assert not refused, "\n".join(refused)
