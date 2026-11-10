"""The privacy policy's and terms' data (DEL-208): open to all, the operator set by the owner alone, and the outside
services named only once they are set up."""

from delve.images.connections import save_replicate
from delve.web import oidc


def test_anyone_reads_it_and_nothing_is_set_at_first(lan):
    answer = lan.get("/api/legal")
    assert answer.status_code == 200
    assert answer.json() == {
        "operator": {"name": "", "email": ""},
        "services": {"google": False, "replicate": False, "backups": False},
    }


def test_the_owner_sets_the_operator(local, lan):
    saved = local.put("/api/legal", json={"name": "  Raf   Janssens ", "email": " raf@example.org "})
    assert saved.status_code == 200
    assert saved.json()["operator"] == {"name": "Raf Janssens", "email": "raf@example.org"}
    assert lan.get("/api/legal").json()["operator"] == {"name": "Raf Janssens", "email": "raf@example.org"}
    assert local.put("/api/legal", json={"name": "", "email": ""}).json()["operator"] == {"name": "", "email": ""}


def test_a_contact_that_won_t_do_is_refused(local):
    assert local.put("/api/legal", json={"name": "Raf", "email": "not an address"}).status_code == 422
    assert local.put("/api/legal", json={"name": "x" * 101, "email": ""}).status_code == 422
    assert local.put("/api/legal", json={"name": 3, "email": ""}).status_code == 422
    assert local.put("/api/legal", json={"name": "Raf"}).status_code == 422


def test_only_the_owner_sets_it(lan, player):
    assert lan.put("/api/legal", json={"name": "Mallory", "email": ""}).status_code in (401, 403)


def test_the_services_follow_what_is_set_up(lan, config):
    save_replicate(config.data_dir, "r8_token")
    oidc.save_client(config.data_dir, "google", "id", "secret")
    services = lan.get("/api/legal").json()["services"]
    assert services == {"google": True, "replicate": True, "backups": False}
    assert "r8_token" not in lan.get("/api/legal").text and "secret" not in lan.get("/api/legal").text
