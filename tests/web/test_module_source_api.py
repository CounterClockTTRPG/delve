"""The module source API (plan 3 Task 3): texts, entities, links and warnings, and the metadata check on PATCH."""

from tests.web.test_modules_api import ZIP, create, crypt_zip, put_source
from tests.web.test_preferences_api import published
from tests.web.test_seats_identity import campaign, join  # noqa: F401  (fixtures)

ROOMS_MAP = (
    'map "Gatehouse" {\n  grid { bounds 30 x 10 }\n}\n\n'
    'room "gate" {\n  rect 1,1 4 x 4\n  label "The Gate"\n}\n\n'
    'room "hall" {\n  rect 10,1 4 x 4\n  label "The Hall"\n}\n'
)


def imported(local) -> str:
    response = local.post("/api/modules/import", content=crypt_zip(), headers=ZIP)
    assert response.status_code == 201
    return response.json()["id"]


def rooms_module(local) -> str:
    mid = create(local)["id"]
    assert put_source(local, mid, "map", ROOMS_MAP).status_code == 200
    return mid


def delete(local, path):
    return local.request("DELETE", path, json={})


def test_source_of_an_imported_module(local):
    mid = imported(local)
    response = local.get(f"/api/modules/{mid}/source")
    assert response.status_code == 200
    source = response.json()
    assert set(source) == {"texts", "entities", "attachments", "keys", "worldmaps", "links", "warnings", "headings"}
    assert [t["id"] for t in source["texts"]] == ["intro", "crypt-key"]
    intro = source["texts"][0]
    assert set(intro) == {"id", "title", "audience", "map", "markdown"}
    assert intro["audience"] == "player" and intro["map"] is None
    assert [r["id"] for r in source["entities"]["npcs"]] == ["prior-anselm", "ritualist"]
    assert source["attachments"] == [
        {
            "id": "ritualist-token",
            "type": "image/png",
            "sha256": "78b972a7f365ee3e41ee6adbedeb4154f0f451fc3b32b6b50e2eb52fe6bc05a3",
            "size": 79,
            "description": "Cult ritualist token",
            "audience": "player",
            "role": "attachment",
            "cut": None,
        }
    ]
    assert [k["key"] for k in source["keys"]] == ["C1", "C2", "C3"]
    c2 = next(link for link in source["links"] if link["key"] == "C2")
    assert c2 == {
        "text_id": "crypt-key",
        "anchor": "c2",
        "key": "C2",
        "map": "crypt",
        "node": "room.throne_chamber",
        "label": "Throne Room",
        "explicit": True,
    }
    for warning in source["warnings"]:
        assert set(warning) == {"code", "message", "ref"}


def test_source_of_an_unknown_module_is_404(local):
    response = local.get("/api/modules/mod_000000000000/source")
    assert response.status_code == 404 and "error" in response.json()


def test_the_source_is_for_organisers(lan):
    assert lan.get("/api/modules/mod_000000000000/source").status_code in (401, 403)


def test_create_a_text(local):
    mid = rooms_module(local)
    response = local.post(f"/api/modules/{mid}/texts", json={"id": "gate-key", "title": "The gatehouse"})
    assert response.status_code == 201
    assert response.json() == {"id": "gate-key", "title": "The gatehouse", "audience": "gm", "map": None, "markdown": ""}
    player = local.post(
        f"/api/modules/{mid}/texts", json={"id": "letter", "title": "A letter", "audience": "player", "map": "map"}
    )
    assert player.status_code == 201 and player.json()["audience"] == "player" and player.json()["map"] == "map"
    texts = local.get(f"/api/modules/{mid}/source").json()["texts"]
    assert [t["id"] for t in texts] == ["gate-key", "letter"]


def test_create_a_text_refusals(local):
    mid = rooms_module(local)
    assert local.post(f"/api/modules/{mid}/texts", json={"id": "a", "title": "A"}).status_code == 201
    duplicate = local.post(f"/api/modules/{mid}/texts", json={"id": "a", "title": "Again"})
    assert duplicate.status_code == 409 and "error" in duplicate.json()
    for bad in ("Not A Slug", "-dash", "", "a/b"):
        response = local.post(f"/api/modules/{mid}/texts", json={"id": bad, "title": "B"})
        assert response.status_code == 422 and "error" in response.json(), bad
    assert local.post(f"/api/modules/{mid}/texts", json={"id": "b", "title": " "}).status_code == 422
    assert local.post(f"/api/modules/{mid}/texts", json={"id": "b", "title": "B", "map": "nowhere"}).status_code == 422
    assert local.post(f"/api/modules/{mid}/texts", json={"id": "b", "title": "B", "audience": "dm"}).status_code == 422
    assert local.post("/api/modules/mod_000000000000/texts", json={"id": "b", "title": "B"}).status_code == 404
    assert [t["id"] for t in local.get(f"/api/modules/{mid}/source").json()["texts"]] == ["a"]


def test_saving_a_text_relinks_its_headings(local):
    mid = imported(local)
    assert local.post(f"/api/modules/{mid}/texts", json={"id": "notes", "title": "Notes", "map": "crypt"}).status_code == 201
    response = local.put(f"/api/modules/{mid}/texts/notes", json={"markdown": "## 3. Vestry\n\nDusty robes.\n"})
    assert response.status_code == 200
    body = response.json()
    assert set(body) == {"text", "links", "warnings", "headings"}
    assert body["text"]["markdown"] == "## 3. Vestry\n\nDusty robes.\n"
    found = [link for link in body["links"] if link["text_id"] == "notes"]
    assert [(link["key"], link["node"], link["label"], link["explicit"]) for link in found] == [
        ("3", "room.vestry_alcove", "Vestry", False)
    ]
    assert local.get(f"/api/modules/{mid}/source").json()["links"] == body["links"]


def test_a_heading_without_a_room_warns(local):
    mid = rooms_module(local)
    local.post(f"/api/modules/{mid}/texts", json={"id": "key", "title": "Key"})
    markdown = "## 1. The Gate\n\nA gate.\n\n## 9. The Moon\n\nNowhere.\n\nSee [[npc:nobody]].\n"
    body = local.put(f"/api/modules/{mid}/texts/key", json={"markdown": markdown}).json()
    assert [(link["key"], link["node"]) for link in body["links"]] == [("1", "room.gate")]
    codes = sorted((w["code"], w["ref"]) for w in body["warnings"])
    assert codes == [
        ("key-without-room", "text:key#9"),
        ("missing-entity", "npc:nobody"),
        ("room-without-text", "map:map#room.hall"),
    ]


def test_update_a_texts_title_audience_and_map(local):
    mid = rooms_module(local)
    local.post(f"/api/modules/{mid}/texts", json={"id": "key", "title": "Key"})
    body = local.put(f"/api/modules/{mid}/texts/key", json={"title": "The key", "audience": "player", "map": "map"})
    assert body.status_code == 200
    assert body.json()["text"] == {"id": "key", "title": "The key", "audience": "player", "map": "map", "markdown": ""}
    assert local.put(f"/api/modules/{mid}/texts/key", json={"map": "nowhere"}).status_code == 422
    assert local.put(f"/api/modules/{mid}/texts/key", json={"title": ""}).status_code == 422
    assert local.put(f"/api/modules/{mid}/texts/nope", json={"title": "x"}).status_code == 404
    cleared = local.put(f"/api/modules/{mid}/texts/key", json={"map": None}).json()["text"]
    assert cleared["map"] is None and cleared["title"] == "The key"


def test_a_saved_text_reaches_the_dms_text(local, storage):
    mid = rooms_module(local)
    local.post(f"/api/modules/{mid}/texts", json={"id": "key", "title": "Key"})
    local.put(f"/api/modules/{mid}/texts/key", json={"markdown": "## 1. The Gate\n\nA rusty portcullis.\n"})
    text = storage.module_texts.get(mid)
    assert any("rusty portcullis" in s["markdown"] for s in text["sections"])
    assert [k["key"] for k in text["keys"]] == ["1"]


def test_delete_a_text(local):
    mid = imported(local)
    assert delete(local, f"/api/modules/{mid}/texts/crypt-key").status_code == 204
    source = local.get(f"/api/modules/{mid}/source").json()
    assert [t["id"] for t in source["texts"]] == ["intro"]
    # Its explicit keys go with it, so no link points into a text that isn't there.
    assert source["keys"] == [] and source["links"] == []
    assert delete(local, f"/api/modules/{mid}/texts/crypt-key").status_code == 404


def test_put_an_npc(local):
    mid = rooms_module(local)
    record = {
        "id": "warden",
        "name": "The Warden",
        "audience": "gm",
        "disposition": -20,
        "description": "Guards the [[npc:nobody]] gate.",
        "stats": {"adnd2e": {"ac": 5, "hd": 2, "hp": 11}},
    }
    response = local.put(f"/api/modules/{mid}/entities/npcs/warden", json=record)
    assert response.status_code == 200
    body = response.json()
    assert body["record"] == record
    assert [w["ref"] for w in body["warnings"] if w["code"] == "missing-entity"] == ["npc:nobody"]
    again = local.put(f"/api/modules/{mid}/entities/npcs/warden", json={**record, "name": "Old Warden"})
    assert again.status_code == 200
    npcs = local.get(f"/api/modules/{mid}/source").json()["entities"]["npcs"]
    assert [(n["id"], n["name"]) for n in npcs] == [("warden", "Old Warden")]


def test_every_form_kind_is_saved(local):
    mid = rooms_module(local)
    records = {
        "encounters": {"id": "gate-guards", "name": "Gate guards", "key": "key:1", "fixed": [{"count": "1d4", "creature": "monster:orc"}]},
        "factions": {"id": "wardens", "name": "Wardens", "goals": ["keep the gate"], "members": []},
        "quests": {"id": "open-gate", "name": "Open the gate", "stakes": "the town", "related": []},
    }
    for kind, record in records.items():
        response = local.put(f"/api/modules/{mid}/entities/{kind}/{record['id']}", json=record)
        assert response.status_code == 200, (kind, response.json())
    entities = local.get(f"/api/modules/{mid}/source").json()["entities"]
    assert {kind: [r["id"] for r in entities[kind]] for kind in records} == {
        kind: [r["id"]] for kind, r in records.items()
    }


def test_the_source_lists_every_keyed_heading(local):
    """Where offers every keyed heading (faithful modules Task 15): the source lists them, linked to a room or not."""
    mid = rooms_module(local)
    local.post(f"/api/modules/{mid}/texts", json={"id": "key", "title": "Key", "map": "map"})
    markdown = "## 1. The Gate\n\nA gate.\n\n## 19. Cellar Stair\n\nSteps.\n"
    saved = local.put(f"/api/modules/{mid}/texts/key", json={"markdown": markdown}).json()
    expected = [
        {"key": "1", "title": "The Gate", "text_id": "key", "anchor": "1"},
        {"key": "19", "title": "Cellar Stair", "text_id": "key", "anchor": "19"},
    ]
    assert saved["headings"] == expected
    assert local.get(f"/api/modules/{mid}/source").json()["headings"] == expected


def test_put_a_pregen_for_the_players_by_default(local):
    mid = rooms_module(local)
    record = {
        "id": "ned",
        "name": "Ned Shakeshaft",
        "race": "human",
        "class": "thief",
        "level": 3,
        "gear": ["short sword"],
        "stats": {"adnd2e": {"ability_scores": {"str": 11}, "hp_max": 12}},
    }
    response = local.put(f"/api/modules/{mid}/entities/pregens/ned", json=record)
    assert response.status_code == 200, response.json()
    pregens = local.get(f"/api/modules/{mid}/source").json()["entities"]["pregens"]
    assert pregens == [{**record, "audience": "player"}]
    nameless = local.put(f"/api/modules/{mid}/entities/pregens/x", json={"id": "x"})
    assert nameless.status_code == 422
    assert delete(local, f"/api/modules/{mid}/entities/pregens/ned").status_code == 204


def test_an_npc_with_a_bad_disposition_is_refused(local):
    mid = rooms_module(local)
    response = local.put(
        f"/api/modules/{mid}/entities/npcs/warden", json={"id": "warden", "name": "Warden", "disposition": [5]}
    )
    assert response.status_code == 422
    body = response.json()
    assert "error" in body
    assert [d["path"] for d in body["diagnostics"]] == ["disposition"]
    assert body["diagnostics"][0]["severity"] == "error"
    assert "npcs" not in local.get(f"/api/modules/{mid}/source").json()["entities"]


def test_entity_refusals(local):
    mid = rooms_module(local)
    missing_name = local.put(f"/api/modules/{mid}/entities/npcs/warden", json={"id": "warden"})
    assert missing_name.status_code == 422
    assert [d["path"] for d in missing_name.json()["diagnostics"]] == ["name"]
    # Records are the format's: their audience is `gm` or `player`.
    dm = local.put(f"/api/modules/{mid}/entities/npcs/warden", json={"id": "warden", "name": "W", "audience": "dm"})
    assert dm.status_code == 422 and [d["path"] for d in dm.json()["diagnostics"]] == ["audience"]
    other_id = local.put(f"/api/modules/{mid}/entities/npcs/warden", json={"id": "keeper", "name": "Keeper"})
    assert other_id.status_code == 422 and [d["path"] for d in other_id.json()["diagnostics"]] == ["id"]
    for kind in ("rumors", "secrets", "monsters"):
        response = local.put(f"/api/modules/{mid}/entities/{kind}/x", json={"id": "x", "name": "X"})
        assert response.status_code == 404, kind
    assert local.put("/api/modules/mod_000000000000/entities/npcs/x", json={"id": "x", "name": "X"}).status_code == 404


def test_delete_an_entity(local):
    mid = imported(local)
    assert delete(local, f"/api/modules/{mid}/entities/npcs/ritualist").status_code == 204
    source = local.get(f"/api/modules/{mid}/source").json()
    assert [n["id"] for n in source["entities"]["npcs"]] == ["prior-anselm"]
    assert "npc:ritualist" in {w["ref"] for w in source["warnings"] if w["code"] == "missing-entity"}
    assert delete(local, f"/api/modules/{mid}/entities/npcs/ritualist").status_code == 404
    assert delete(local, f"/api/modules/{mid}/entities/rumors/x").status_code == 404


def test_patch_validates_metadata(local):
    mid = create(local)["id"]
    good = {"authors": ["Me"], "party": {"levels": {"min": 1, "max": 3}, "size": 4}, "tags": ["dungeon"]}
    response = local.patch(f"/api/modules/{mid}", json={"metadata": good})
    assert response.status_code == 200 and response.json()["metadata"] == good

    bad_shape = local.patch(f"/api/modules/{mid}", json={"metadata": {"party": {"levels": "low"}}})
    assert bad_shape.status_code == 422
    assert [d["path"] for d in bad_shape.json()["diagnostics"]] == ["party/levels"]

    bad_range = local.patch(f"/api/modules/{mid}", json={"metadata": {"party": {"levels": {"min": 5, "max": 2}}}})
    assert bad_range.status_code == 422
    assert [d["code"] for d in bad_range.json()["diagnostics"]] == ["metadata-range"]

    for key in ("maps", "text", "entities", "assets", "keys", "format", "version"):
        structural = local.patch(f"/api/modules/{mid}", json={"metadata": {key: []}})
        assert structural.status_code == 422, key
        assert [d["path"] for d in structural.json()["diagnostics"]] == [key]
    assert local.get(f"/api/modules/{mid}").json()["metadata"] == good


def test_patch_metadata_cover_must_be_an_attachment(local):
    mid = imported(local)
    assert local.patch(f"/api/modules/{mid}", json={"metadata": {"cover": "asset:ritualist-token"}}).status_code == 200
    response = local.patch(f"/api/modules/{mid}", json={"metadata": {"cover": "asset:nothing"}})
    assert response.status_code == 422
    assert [d["code"] for d in response.json()["diagnostics"]] == ["dangling-ref"]


def test_source_changes_publish_modules(local, app):
    mid = rooms_module(local)
    local.post(f"/api/modules/{mid}/texts", json={"id": "key", "title": "Key"})
    local.put(f"/api/modules/{mid}/texts/key", json={"markdown": "x\n"})
    local.put(f"/api/modules/{mid}/entities/npcs/a", json={"id": "a", "name": "A"})
    delete(local, f"/api/modules/{mid}/entities/npcs/a")
    delete(local, f"/api/modules/{mid}/texts/key")
    events = [(event.type, event.data) for event in published(app)]
    assert events[-5:] == [("modules", {"id": mid})] * 5


def test_audiences_are_gm_or_player_everywhere(local):
    """Texts, attachments and entity records store the same two values (docs/data-dictionary.md): `dm` is refused."""
    mid = rooms_module(local)
    assert local.post(f"/api/modules/{mid}/texts", json={"id": "notes", "title": "N", "audience": "dm"}).status_code == 422
    local.post(f"/api/modules/{mid}/texts", json={"id": "notes", "title": "N"})
    assert local.put(f"/api/modules/{mid}/texts/notes", json={"audience": "dm"}).status_code == 422


def audiences(local, mid) -> dict[str, str]:
    """Every item's audience by its ref: texts, entity records and attachments."""
    source = local.get(f"/api/modules/{mid}/source").json()
    found = {f"text:{t['id']}": t["audience"] for t in source["texts"]}
    found |= {f"asset:{a['id']}": a["audience"] for a in source["attachments"]}
    for kind, records in source["entities"].items():
        found |= {f"{kind[:-1]}:{r['id']}": r.get("audience", "gm") for r in records}
    return found


def test_bulk_audience_sets_texts_entities_and_assets(local, app):
    """E6: texts, entities and attachments change audience together, in one save of the source."""
    mid = imported(local)
    before = audiences(local, mid)
    assert before["text:intro"] == "player" and before["npc:ritualist"] == "gm"
    assert before["asset:ritualist-token"] == "player"
    seen = len(published(app))
    head = local.get(f"/api/modules/{mid}").json()["head_revision"]
    refs =["text:intro", "npc:ritualist", "asset:ritualist-token"]
    response = local.post(f"/api/modules/{mid}/audience", json={"refs": refs, "audience": "gm"})
    assert response.status_code == 200 and response.json() == {"changed": 2}
    response = local.post(f"/api/modules/{mid}/audience", json={"refs": refs, "audience": "player"})
    assert response.status_code == 200 and response.json() == {"changed": 3}
    after = audiences(local, mid)
    assert {ref: after[ref] for ref in refs} == dict.fromkeys(refs, "player")
    assert {ref: a for ref, a in after.items() if ref not in refs} == {
        ref: a for ref, a in before.items() if ref not in refs
    }
    # One save each: one `modules` event per request, and the DM's text derived from the new audiences.
    assert [(e.type, e.data) for e in published(app)[seen:]] == [("modules", {"id": mid})] * 2
    assert local.get(f"/api/modules/{mid}").json()["head_revision"] == head


def test_bulk_audience_unknown_ref_changes_nothing(local, app):
    """Review Focus 4: all or nothing. An unknown ref is named in the 422, and nothing is saved."""
    mid = imported(local)
    before = audiences(local, mid)
    seen = len(published(app))
    response = local.post(
        f"/api/modules/{mid}/audience", json={"refs": ["npc:ritualist", "text:nope"], "audience": "player"}
    )
    assert response.status_code == 422
    body = response.json()
    assert "text:nope" in body["error"] and body["unknown"] == ["text:nope"]
    assert audiences(local, mid) == before and before["npc:ritualist"] == "gm"
    assert len(published(app)) == seen
    for refs in (["npc:prior-anselm", "asset:nothing", "monster:orc", "rumors:x", "intro"], ["text:intro#c1"]):
        refused = local.post(f"/api/modules/{mid}/audience", json={"refs": refs, "audience": "gm"})
        assert refused.status_code == 422, refs
        assert audiences(local, mid) == before
    assert local.post(f"/api/modules/{mid}/audience", json={"refs": ["text:intro"], "audience": "dm"}).status_code == 422
    assert local.post(f"/api/modules/{mid}/audience", json={"refs": [], "audience": "gm"}).json() == {"changed": 0}
    assert local.post("/api/modules/mod_000000000000/audience", json={"refs": [], "audience": "gm"}).status_code == 404
    text_plain = local.post(
        f"/api/modules/{mid}/audience", content=b'{"refs": [], "audience": "gm"}', headers={"Content-Type": "text/plain"}
    )
    assert text_plain.status_code == 415


def test_bulk_audience_keeps_every_record_valid(local, app):
    """A secret's audience is always `gm` in the schema: giving it to the players is a 422 that names it, nothing is
    saved, and the module still exports."""
    mid = imported(local)
    before = audiences(local, mid)
    seen = len(published(app))
    response = local.post(
        f"/api/modules/{mid}/audience", json={"refs": ["text:intro", "secret:prior-knew"], "audience": "player"}
    )
    assert response.status_code == 422
    body = response.json()
    assert "secret:prior-knew" in body["error"] and body["invalid"] == ["secret:prior-knew"]
    assert "text:intro" not in body["invalid"]
    assert audiences(local, mid) == before
    assert len(published(app)) == seen
    assert local.get(f"/api/modules/{mid}/export.dscn").status_code == 200


def test_bulk_audience_needs_an_organiser(join, campaign):  # noqa: F811  (the seat fixtures)
    _, ana = join(campaign.id)
    response = ana.post(
        f"/api/modules/{campaign.module_id}/audience", json={"refs": ["text:intro"], "audience": "player"}
    )
    assert response.status_code == 403 and response.json() == {"error": "This needs the organiser role."}


def test_saves_at_once_lose_nothing(local):
    """The source routes run in the threadpool (DEL-166): each reads, changes and saves the whole source, holding the
    module's edit lock, so texts created at once all stay."""
    from concurrent.futures import ThreadPoolExecutor

    mid = rooms_module(local)

    def create_text(n):
        return local.post(f"/api/modules/{mid}/texts", json={"id": f"text-{n}", "title": f"Text {n}"}).status_code

    with ThreadPoolExecutor(8) as pool:
        assert list(pool.map(create_text, range(8))) == [201] * 8
    texts = local.get(f"/api/modules/{mid}/source").json()["texts"]
    assert sorted(t["id"] for t in texts) == [f"text-{n}" for n in range(8)]
