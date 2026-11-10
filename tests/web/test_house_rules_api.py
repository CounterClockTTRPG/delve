"""The house-rules API (plan 2a Task 9): the library, bundles, a campaign's choice and the rules in effect."""

from delve.play import house_rules as hr
from tests.web.test_campaigns_api import crypt_module

RULE = {
    "title": "Lizardfolk",
    "body_md": "Bite 1d6.",
    "kind": "race",
    "phases": ["level-up", "character-creation"],
    "ruleset": "osric",
    "setting": None,
    "subject": "Lizard Folk",
    "enabled": True,
}


def rule(local, **fields) -> dict:
    response = local.post("/api/house-rules", json={**RULE, **fields})
    assert response.status_code == 201, response.json()
    return response.json()


def bundle(local, rule_ids, title="My table") -> dict:
    response = local.post("/api/house-rule-bundles", json={"title": title, "rule_ids": rule_ids})
    assert response.status_code == 201, response.json()
    return response.json()


def published(app) -> list[tuple[str, dict]]:
    return [(e.type, e.data) for e in app.state.events._buffer]


def test_api_crud_and_organiser_only(local, lan, app):
    assert local.get("/api/house-rules").json() == []
    lizard = rule(local)
    assert lizard["id"].startswith("hr_")
    # Phases come back in their canonical order; the subject is normalised.
    assert {k: v for k, v in lizard.items() if k != "id"} == {
        **RULE,
        "phases": ["character-creation", "level-up"],
        "subject": "lizard-folk",
    }
    assert local.get(f"/api/house-rules/{lizard['id']}").json() == lizard
    hp = rule(local, title="Max HP", kind="general", phases=["character-creation"], subject="", ruleset="")
    assert (hp["subject"], hp["ruleset"], hp["body_md"]) == (None, None, "Bite 1d6.")
    assert [r["id"] for r in local.get("/api/house-rules").json()] == [lizard["id"], hp["id"]]

    edited = local.put(f"/api/house-rules/{lizard['id']}", json={**RULE, "title": "Lizard men", "enabled": False})
    assert edited.status_code == 200 and (edited.json()["title"], edited.json()["enabled"]) == ("Lizard men", False)
    assert local.get(f"/api/house-rules/{lizard['id']}").json()["title"] == "Lizard men"

    table = bundle(local, [hp["id"], lizard["id"]])
    assert table["id"].startswith("hb_") and table["rule_ids"] == [hp["id"], lizard["id"]]
    assert table["description_md"] == ""
    reordered = local.put(
        f"/api/house-rule-bundles/{table['id']}",
        json={"title": "Usual", "description_md": "Tuesdays.", "rule_ids": [lizard["id"], hp["id"]]},
    )
    assert reordered.status_code == 200
    assert reordered.json() == {
        "id": table["id"],
        "title": "Usual",
        "description_md": "Tuesdays.",
        "rule_ids": [lizard["id"], hp["id"]],
    }
    assert local.get("/api/house-rule-bundles").json() == [reordered.json()]
    assert local.get(f"/api/house-rule-bundles/{table['id']}").json() == reordered.json()

    assert local.request("DELETE", f"/api/house-rules/{hp['id']}", json={}).status_code == 204
    assert local.get(f"/api/house-rule-bundles/{table['id']}").json()["rule_ids"] == [lizard["id"]]
    assert local.request("DELETE", f"/api/house-rule-bundles/{table['id']}", json={}).status_code == 204
    assert local.get("/api/house-rule-bundles").json() == []

    types = [type for type, _ in published(app)]
    assert types.count("house_rules") == 7 and set(types) == {"house_rules"}
    assert published(app)[0] == ("house_rules", {"rule_id": lizard["id"]})

    calls = [
        ("GET", "/api/house-rules", None),
        ("POST", "/api/house-rules", RULE),
        ("GET", f"/api/house-rules/{lizard['id']}", None),
        ("PUT", f"/api/house-rules/{lizard['id']}", RULE),
        ("DELETE", f"/api/house-rules/{lizard['id']}", None),
        ("GET", "/api/house-rule-bundles", None),
        ("POST", "/api/house-rule-bundles", {"title": "x"}),
        ("GET", "/api/house-rule-bundles/hb_000000000000", None),
        ("PUT", "/api/house-rule-bundles/hb_000000000000", {"title": "x"}),
        ("DELETE", "/api/house-rule-bundles/hb_000000000000", None),
        ("GET", "/api/campaigns/cmp_000000000000/house-rules", None),
        ("PUT", "/api/campaigns/cmp_000000000000/house-rules", {"bundle_ids": [], "rule_ids": []}),
        ("POST", "/api/house-rules/import-example", None),
    ]
    for method, path, body in calls:
        response = lan.request(method, path, json=body if body is not None else {})
        assert response.status_code == 401, (method, path)
        assert "error" in response.json()
    assert local.get(f"/api/house-rules/{lizard['id']}").json()["title"] == "Lizard men"


def test_bad_rules_and_bundles_refused(local):
    for bad in ({"title": " "}, {"kind": "monster"}, {"phases": ["lunch"]}, {"enabled": "yes"}):
        response = local.post("/api/house-rules", json={**RULE, **bad})
        assert response.status_code == 422, bad
        assert "error" in response.json()
    for path in ("/api/house-rules/hr_000000000000", "/api/house-rule-bundles/hb_000000000000"):
        assert local.get(path).status_code == 404
        assert local.request("DELETE", path, json={}).status_code == 404
    assert local.put("/api/house-rules/hr_000000000000", json=RULE).status_code == 404
    unknown = local.post("/api/house-rule-bundles", json={"title": "x", "rule_ids": ["hr_000000000000"]})
    assert unknown.status_code == 422 and "hr_000000000000" in unknown.json()["error"]
    assert local.post("/api/house-rule-bundles", json={"title": " "}).status_code == 422
    assert local.get("/api/house-rule-bundles").json() == []


def test_campaign_house_rules_and_the_rules_in_effect(local, app):
    module = crypt_module(local)
    a = rule(local, title="Max HP", kind="general", subject=None, phases=["character-creation"])
    b = rule(local, title="Reroll HP", kind="general", subject=None, phases=["level-up"])
    tressym = rule(local, title="Tressym", kind="general", subject=None, phases=["always"], setting="forgotten-realms")
    off = rule(local, title="Off", kind="general", subject=None, phases=["always"], enabled=False)
    table = bundle(local, [a["id"], tressym["id"], off["id"]])

    created = local.post(
        "/api/campaigns",
        json={"name": "Tuesday", "module_id": module["id"], "bundle_ids": [table["id"]], "rule_ids": [b["id"]]},
    )
    assert created.status_code == 201
    cid = created.json()["id"]
    path = f"/api/campaigns/{cid}/house-rules"
    assert local.get(path).json() == {"bundle_ids": [table["id"]], "rule_ids": [b["id"]]}
    effective = hr.effective_rules(app.state.storage, cid)
    assert [r.title for r in effective] == ["Max HP", "Reroll HP"]
    assert effective[0].to_dict() == a

    put = local.put(path, json={"bundle_ids": [], "rule_ids": [tressym["id"], a["id"]]})
    assert put.status_code == 200 and put.json() == {"bundle_ids": [], "rule_ids": [tressym["id"], a["id"]]}
    assert [r.title for r in hr.effective_rules(app.state.storage, cid)] == ["Max HP"]
    assert ("house_rules", {"campaign_id": cid}) in published(app)

    refused = local.put(path, json={"bundle_ids": ["hb_000000000000"], "rule_ids": []})
    assert refused.status_code == 422 and "hb_000000000000" in refused.json()["error"]
    assert local.get(path).json()["rule_ids"] == [tressym["id"], a["id"]]
    for method in ("GET", "PUT"):
        missing = local.request(method, "/api/campaigns/cmp_000000000000/house-rules", json={})
        assert missing.status_code == 404, method


def test_create_campaign_without_house_rules_and_with_unknown_ones(local):
    module = crypt_module(local)
    plain = local.post("/api/campaigns", json={"name": "Plain", "module_id": module["id"]})
    assert plain.status_code == 201
    assert local.get(f"/api/campaigns/{plain.json()['id']}/house-rules").json() == {"bundle_ids": [], "rule_ids": []}
    refused = local.post(
        "/api/campaigns", json={"name": "Bad", "module_id": module["id"], "rule_ids": ["hr_000000000000"]}
    )
    assert refused.status_code == 422 and "hr_000000000000" in refused.json()["error"]
    assert [c["name"] for c in local.get("/api/campaigns").json()] == ["Plain"]  # nothing half-made


def test_seeded_bundle_can_be_chosen(local, storage):
    seeded = hr.import_house_rules(storage, hr.SEED_DIR)
    [listed] = local.get("/api/house-rule-bundles").json()
    assert listed["title"] == "My table (from ttrpg2)" and len(listed["rule_ids"]) == 4  # the homebrew is a pack's
    module = crypt_module(local)
    created = local.post(
        "/api/campaigns", json={"name": "Seeded", "module_id": module["id"], "bundle_ids": [seeded.id]}
    ).json()
    effective = hr.effective_rules(storage, created["id"])
    assert len(effective) == 4
    assert len([rule for rule in effective if "character-creation" in rule.phases]) == 2


def test_import_example_house_rules_once(local, app, storage):
    """Plan "Open fixes" Decision 7: the library starts empty, and "Import the example rules" runs the import that
    `delve house-rules import` runs. A second call answers the same bundle and changes nothing."""
    assert local.get("/api/house-rules").json() == [] and local.get("/api/house-rule-bundles").json() == []
    first = local.post("/api/house-rules/import-example", json={})
    assert first.status_code == 200, first.json()
    imported = first.json()
    assert imported["title"] == "My table (from ttrpg2)" and len(imported["rule_ids"]) == 4
    assert local.get("/api/house-rule-bundles").json() == [imported]
    assert published(app)[-1] == ("house_rules", {"bundle_id": imported["id"]})
    rules = local.get("/api/house-rules").json()

    again = local.post("/api/house-rules/import-example", json={})
    assert again.status_code == 200 and again.json() == imported
    assert local.get("/api/house-rules").json() == rules
    assert local.get("/api/house-rule-bundles").json() == [imported]


def test_import_example_keeps_the_rules_there_are(local, storage):
    """The owner's rules are never deleted or rewritten: once the example bundle is there, importing again answers it
    untouched, so an edited example rule keeps its edit, a deleted one stays deleted, and the owner's own rules and
    bundles stay as they are."""
    imported = local.post("/api/house-rules/import-example", json={}).json()
    example = local.get(f"/api/house-rules/{imported['rule_ids'][0]}").json()
    edited = local.put(f"/api/house-rules/{example['id']}", json={**example, "body_md": "Our way."}).json()
    gone = imported["rule_ids"][1]
    assert local.request("DELETE", f"/api/house-rules/{gone}", json={}).status_code == 204
    own = rule(local, title="Crits on 20", kind="general", phases=["combat"], subject="", ruleset="")
    mine = bundle(local, [own["id"]])
    example_bundle = local.get(f"/api/house-rule-bundles/{imported['id']}").json()
    assert gone not in example_bundle["rule_ids"]
    rules = local.get("/api/house-rules").json()

    again = local.post("/api/house-rules/import-example", json={})
    assert again.status_code == 200 and again.json() == example_bundle
    assert local.get("/api/house-rules").json() == rules
    assert local.get(f"/api/house-rules/{gone}").status_code == 404
    assert local.get(f"/api/house-rules/{example['id']}").json() == edited
    assert local.get(f"/api/house-rules/{own['id']}").json() == own
    assert local.get(f"/api/house-rule-bundles/{mine['id']}").json() == mine
    assert local.get(f"/api/house-rule-bundles/{imported['id']}").json() == example_bundle


def test_import_example_refuses_a_library_in_use(local, app):
    """A library with house rules but no example bundle is the owner's: importing is a 409 and changes nothing."""
    own = rule(local, title="Crits on 20", kind="general", phases=["combat"], subject="", ruleset="")
    seen = len(published(app))
    response = local.post("/api/house-rules/import-example", json={})
    assert response.status_code == 409
    assert response.json() == {"error": "The library already has house rules."}
    assert local.get("/api/house-rules").json() == [own]
    assert local.get("/api/house-rule-bundles").json() == []
    assert len(published(app)) == seen


def test_import_example_needs_json(local):
    response = local.post("/api/house-rules/import-example", content=b"", headers={"Content-Type": "text/plain"})
    assert response.status_code == 415 and "error" in response.json()
    assert local.get("/api/house-rules").json() == []
