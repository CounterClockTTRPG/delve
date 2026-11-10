from delve.modules.dscn import Bundle, check
from tests.fixtures import SAMPLES

SAMPLE = SAMPLES / "scenarios" / "crypt-of-saint-vellis"


def test_requires_dungml_checked():
    # dungml read its version from the installed distribution; delve.modules.dscn takes it from delve.maps.dsl.
    bundle = Bundle.from_dir(SAMPLE)
    bundle.manifest["requires"] = {"dungml": ">=99"}
    (diag,) = [d for d in check(bundle).diagnostics if d.code == "requires"]
    assert diag.severity == "warning"
    assert "0.1.0" in diag.message
