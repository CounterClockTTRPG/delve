import pytest

from delve.domain.backends import ModelInfo, ProviderCapabilities, Registry
from delve.domain.settings import Effort, Job

TALKER = ProviderCapabilities(id="talker", title="Talker", jobs=frozenset({Job.DM, Job.SIDE}))
PAINTER = ProviderCapabilities(id="painter", title="Painter", jobs=frozenset({Job.IMAGE_PORTRAIT}))
BOTH = ProviderCapabilities(
    id="both", title="Both", jobs=frozenset({Job.SIDE, Job.IMAGE_PORTRAIT}), efforts=(Effort.AUTO,)
)


def test_register_with_a_known_id_replaces_it_in_its_place():
    registry: Registry[str] = Registry()
    registry.register(TALKER, lambda: "first")
    registry.register(PAINTER, lambda: "painter")
    assert registry.get("talker") == "first"
    renamed = ProviderCapabilities(id="talker", title="Talker again", jobs=frozenset({Job.DM}))
    assert registry.register(renamed, lambda: "second") == "first", "it answers what it dropped"
    assert registry.capabilities() == [renamed, PAINTER], "it keeps its place"
    assert registry.get("talker") == "second", "the new factory builds it"
    assert registry.built() == ["second"], "what the old factory built is dropped"


def test_unregister_drops_a_provider_and_answers_what_it_built():
    registry: Registry[str] = Registry()
    registry.register(TALKER, lambda: "talker")
    registry.register(PAINTER, lambda: "painter")
    assert registry.unregister("painter") is None, "nothing was built"
    assert registry.capabilities() == [TALKER]
    registry.get("talker")
    assert registry.unregister("talker") == "talker"
    assert registry.capabilities() == [] and registry.built() == []
    with pytest.raises(KeyError):
        registry.get("talker")
    assert registry.unregister("gone") is None, "unregistering an unknown id is nothing"


def test_registry_get_unknown_lists_known_ids():
    registry: Registry[str] = Registry()
    registry.register(TALKER, lambda: "talker")
    registry.register(PAINTER, lambda: "painter")
    with pytest.raises(KeyError) as excinfo:
        registry.get("gone")
    message = str(excinfo.value)
    assert "gone" in message and "talker" in message and "painter" in message


def test_get_builds_the_provider_once():
    built = []
    registry: Registry[object] = Registry()
    registry.register(TALKER, lambda: built.append(1) or object())
    assert registry.get("talker") is registry.get("talker")
    assert built == [1]


def test_a_live_providers_capabilities_are_read_on_each_call():
    models = ["sdxl-local"]
    reads = []

    def caps():
        reads.append(1)
        info = {model: ModelInfo(model, "local", None, paid=False) for model in models}
        return ProviderCapabilities("live", "Live", frozenset({Job.IMAGE_SCENE}), tuple(models), model_info=info)

    registry: Registry[str] = Registry()
    registry.register(TALKER, lambda: "talker")
    registry.register_live("live", caps, lambda: "painter")
    assert reads == [], "nothing is read at registration"
    (first,) = [caps for caps in registry.capabilities() if Job.IMAGE_SCENE in caps.jobs]
    assert first.models == ("sdxl-local",) and first.live and first.problem is None
    models.append("flux-schnell")
    second = registry.capabilities()[1]
    assert second.models == ("sdxl-local", "flux-schnell"), "a model added between two reads appears in the second"
    assert second.model_info["flux-schnell"] == ModelInfo("flux-schnell", "local", None, paid=False)
    assert len(reads) == 2
    assert registry.get("live") == "painter"


def test_register_live_replaces_a_known_id_in_its_place():
    registry: Registry[str] = Registry()
    registry.register(PAINTER, lambda: "static")
    registry.register(TALKER, lambda: "talker")
    registry.get("painter")
    live = ProviderCapabilities("painter", "Painter, live", frozenset({Job.IMAGE_PORTRAIT}), problem="it is down")
    assert registry.register_live("painter", lambda: live, lambda: "live") == "static"
    assert [caps.id for caps in registry.capabilities()] == ["painter", "talker"]
    assert registry.capabilities()[0].problem == "it is down"
    assert registry.get("painter") == "live"
    registry.register(PAINTER, lambda: "static again")
    assert registry.capabilities()[0] == PAINTER and not PAINTER.live, "registered static again, it is read once"
    assert registry.unregister("painter") is None and [c.id for c in registry.capabilities()] == ["talker"]


def test_static_capabilities_have_no_model_info_and_no_problem():
    assert TALKER.model_info == {} and TALKER.problem is None and TALKER.live is False
