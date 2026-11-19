"""A pack imports Delve only through the modules of `PACK_IMPORTS`."""

import ast
import os
from pathlib import Path

from delve.packs.api import PACK_IMPORTS, PACK_TOOL_IMPORTS

ROOT = Path(__file__).resolve().parents[2]


def pack_sources() -> list[Path]:
    """The `src` folder of each pack in the repo's `packs/` and, when `$DELVE_PACKS_SRC` is set, of each pack in it."""
    sources = sorted(ROOT.glob("packs/*/src"))
    extra = os.environ.get("DELVE_PACKS_SRC")
    if extra:
        sources += sorted(p for p in Path(extra).expanduser().glob("*/src") if p.is_dir())
    return sources


def tools_module(path: Path) -> bool:
    """Whether the pack file at `path` is its engine's tools module, `<package>/engine/tools.py` in the pack's `src`:
    the one an engine's `tools()` imports, and the only one `PACK_TOOL_IMPORTS` opens to."""
    return path.name == "tools.py" and path.parent.name == "engine" and path.parent.parent.parent.name == "src"


def allowed(module: str, path: Path | None = None) -> bool:
    """Whether the pack file at `path` may import `module`: the engine's tools module also the modules of
    `PACK_TOOL_IMPORTS`."""
    fence = PACK_IMPORTS + (PACK_TOOL_IMPORTS if path is not None and tools_module(path) else ())
    return any(module == ok or module.startswith(ok + ".") for ok in fence)


def refused_imports(path: Path) -> list[str]:
    """The Delve modules the pack file at `path` imports beyond its fence, as `path:line: module`."""
    refused = []
    for node in ast.walk(ast.parse(path.read_text("utf-8"), str(path))):
        if isinstance(node, ast.Import):
            modules = [(a.name, node.lineno) for a in node.names]
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            # `from delve.play import characters` is the module `delve.play.characters` when it is one
            modules = [(node.module, node.lineno, f"{node.module}.{a.name}") for a in node.names]
        else:
            continue
        for module, line, *named in modules:
            if not (module == "delve" or module.startswith("delve.")) or allowed(module, path):
                continue
            if not (named and allowed(named[0], path)):
                refused.append(f"{path}:{line}: {module}")
    return refused


def test_pack_imports_only_the_pack_api():
    refused = [found for src in pack_sources() for path in sorted(src.rglob("*.py")) for found in refused_imports(path)]
    assert not refused, "\n".join(refused)


def _engine(tmp_path: Path) -> Path:
    folder = tmp_path / "src" / "delve_x" / "engine"
    folder.mkdir(parents=True)
    return folder


def test_only_the_engines_tools_module_imports_the_play_layer(tmp_path):
    source = "from delve.play import characters\nfrom delve.dm.tools.host import all_specs\n"
    engine = _engine(tmp_path)
    (engine / "tools.py").write_text(source)
    (engine / "combat.py").write_text(source)
    assert refused_imports(engine / "tools.py") == []
    assert len(refused_imports(engine / "combat.py")) == 2


def test_a_tools_py_elsewhere_in_the_pack_is_fenced(tmp_path):
    # Only `<package>/engine/tools.py` is the module `tools()` imports: a `tools.py` beside it in the package, or
    # deeper, isn't.
    source = "from delve.play import characters\n"
    engine = _engine(tmp_path)
    (engine.parent / "tools.py").write_text(source)
    (engine / "deeper").mkdir()
    (engine / "deeper" / "tools.py").write_text(source)
    assert len(refused_imports(engine.parent / "tools.py")) == 1
    assert len(refused_imports(engine / "deeper" / "tools.py")) == 1


def test_a_tools_module_still_keeps_out_the_rest(tmp_path):
    tools = _engine(tmp_path) / "tools.py"
    tools.write_text("from delve.storage import open_storage\nimport delve.web.app\n")
    assert len(refused_imports(tools)) == 2


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
