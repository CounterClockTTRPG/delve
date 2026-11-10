"""Rulesets are separable (DEL-302, DEL-307): Delve has none built in, and every ruleset is a pack's. With the packs'
packages gone, every module imports, the catalog is empty, a campaign of a ruleset that isn't installed says so, and
the fake ruleset plays its own numbers. Run in a fresh interpreter that refuses to import the packages."""

import subprocess
import sys
import textwrap

import pytest

RULESETS = ("delve_adnd2e", "delve_osric")
"""The packages of the ruleset packs Delve knows of."""


def block(*packages: str) -> str:
    """Code that makes `packages` (and their modules) unimportable, as if this Delve had been shipped without them."""
    return textwrap.dedent(
        f"""
        import importlib.abc, sys

        GONE = {packages!r}

        class Gone(importlib.abc.MetaPathFinder):
            def find_spec(self, name, path, target=None):
                if any(name == p or name.startswith(p + ".") for p in GONE):
                    raise ModuleNotFoundError(f"No module named {{name!r}}", name=name)

        sys.meta_path.insert(0, Gone())
        """
    )


def run_without(packages: tuple[str, ...], code: str) -> str:
    result = subprocess.run(
        [sys.executable, "-c", block(*packages) + textwrap.dedent(code)],
        check=False,
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert result.returncode == 0, result.stderr
    return result.stdout


@pytest.mark.parametrize("gone", [RULESETS])
def test_every_module_imports_without_a_ruleset(gone):
    out = run_without(
        gone,
        f"""
        import importlib, pkgutil
        import delve

        failed = []
        for module in pkgutil.walk_packages(delve.__path__, "delve."):
            if not module.name.startswith({gone!r}):
                try:
                    importlib.import_module(module.name)
                except Exception as error:
                    failed.append(f"{{module.name}}: {{error!r}}")
        print("\\n".join(failed) or "ok")
        """
    )
    assert out.strip() == "ok"


def test_without_packs_the_catalog_is_empty_and_a_campaign_of_a_missing_ruleset_says_so(tmp_path):
    out = run_without(
        RULESETS,
        f"""
        from delve.config import Config
        from delve.domain.backends import Registry
        from delve.domain.campaigns import MissingPack
        from delve.domain.modules import ModuleMap
        from delve.play.context import context_for
        from delve.rules import catalog
        from delve.rules.classic import checks
        from delve.storage import open_storage

        assert catalog.CATALOG == ()
        registry = Registry()
        catalog.register_rulesets(registry)
        assert [c.id for c in registry.capabilities()] == ["fake-rules"]
        assert catalog.catalog(()) == ()

        from pathlib import Path

        storage = open_storage(Config(data_dir=Path({str(tmp_path / "data")!r})))
        module = storage.modules.create("The Crypt")
        storage.modules.put_map(module.id, ModuleMap("crypt", "map", "map crypt {{}}\\n", is_default=True))
        revision = storage.revisions.snapshot(module.id)
        campaign = storage.campaigns.create("Tuesday", module.id, revision.number, ruleset="adnd2e", setting="greyhawk")
        try:
            context_for(storage, campaign.id, "b1")
        except MissingPack as missing:
            print(missing.message)
        fake = storage.campaigns.create("Fake", module.id, revision.number, ruleset="fake-rules", setting="aun")
        ctx = context_for(storage, fake.id, "b1")
        assert ctx.ruleset.id == "fake-rules" and ctx.rules.save_types == ("body", "mind")
        print(checks.save_type_for("b", rules=ctx.rules))
        storage.close()
        """
    )
    assert out.strip().split("\n") == ["This campaign's ruleset, adnd2e, isn't installed.", "body"]


def test_the_engine_quotes_and_cites_no_rulebook():
    """The classic engine is every ruleset's: its code and comments say how it plays in Delve's words, and name no
    ruleset's books or tables (a ruleset's own package may)."""
    import re
    from pathlib import Path

    import delve.rules.classic

    cited = re.compile(r"\b(PHB|DMG|MM|AD&D|2e)\b|Monstrous Manual|Player's Handbook|Dungeon Master'?s Guide|Table \d")
    for path in Path(delve.rules.classic.__file__).parent.glob("*.py"):
        for number, line in enumerate(path.read_text().splitlines(), start=1):
            assert not cited.search(line), f"{path.name}:{number}: {line.strip()}"


def test_core_has_no_2e():
    """AD&D 2e is a pack's (DEL-307): Delve has no package of it, and its code names none of its tables (`adnd_`).
    The id `adnd2e` is still data, named only where the allow-list says why; the migrations hold the past, and the
    built web app (`web/static`) is the web's own."""
    import importlib.util
    from pathlib import Path

    import delve

    assert importlib.util.find_spec("delve.rules.adnd2e") is None
    allowed = {
        "storage/sqlite/tables.py": "the `campaigns.ruleset` column's default, as migration 0007 made it",
        "dm/tools/pregens.py": "the module format's `stats.adnd2e` key, data a module carries",
        "modules/books/prompts/entities.md": "the module format's `stats.adnd2e` key, which conversions write",
        "modules/books/prompts/metadata.md": "the module format's `system` tag `adnd2e`",
        "modules/dscn/scenario.schema.json": "the module format's system tag and `stats.adnd2e` key",
    }
    root = Path(delve.__file__).parent
    found = {}
    for path in sorted(root.rglob("*")):
        name = path.relative_to(root).as_posix()
        if not path.is_file() or path.suffix == ".pyc" or name.startswith(("storage/migrations/", "web/static/")):
            continue
        text = path.read_text(encoding="utf-8", errors="ignore")
        assert "adnd_" not in text, name
        if "adnd" in text.lower():
            found[name] = text.lower().count("adnd")
    assert sorted(found) == sorted(allowed)
