"""OSRIC is a pack of this repo (DEL-307): `packs/osric` installs like any other and its ruleset plays from it."""

from pathlib import Path

from delve.packs.loader import load_packs
from delve.packs.transit import install_pack
from delve.rules.catalog import catalog, make_ruleset

OSRIC = Path(__file__).resolve().parents[2] / "packs" / "osric"


def test_osric_installs_as_a_pack(tmp_path):
    from delve.packs import loader

    loader.reset()
    install_pack(OSRIC, tmp_path)
    packs, skipped = load_packs(tmp_path)
    assert not skipped
    cat = catalog(packs)
    assert "osric" in {e.id for e in cat}
    hits = make_ruleset("osric", cat).lookup("monster", "kobold")
    assert any("kobold" in h.title.lower() for h in hits)
    loader.reset()
