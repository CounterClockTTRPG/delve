"""The Settings area's API and the Setting tab's (settings plan Task 8): organisers search, browse, read, add, override
and revert a setting's pages, keep its facts and decide the DM's proposals under `/api/settings`; a seat reads its
campaign's setting, read-only and without DM-only content, under `/api/campaigns/{id}/setting`. Greyhawk over the
tiny reference."""

from urllib.parse import quote

import pytest
from fastapi.testclient import TestClient

from delve.domain.backends import Registry
from delve.domain.modules import ModuleMap
from delve.domain.setting_content import Proposal, SettingAddition
from delve.play import seats
from delve.setting.catalog import register_settings
from delve.web.seats import SEAT_COOKIE, new_seat_token, token_hash
from tests.fixtures.rulesets import osric_catalogs
from tests.web.conftest import BASE_URL, make_registries

SECRET = "SECRET-XYZZY"


@pytest.fixture
def config(reference_config):
    return reference_config


@pytest.fixture
def lore(reference):
    return reference


@pytest.fixture
def registries():
    registries = make_registries()
    registries.settings_ = Registry()
    registries.catalogs = osric_catalogs()
    register_settings(registries.settings_, registries.catalogs.settings)
    return registries


def make_campaign(storage, setting="greyhawk", name="Tuesday"):
    module = storage.modules.create("The Crypt")
    storage.modules.put_map(module.id, ModuleMap("crypt", "map", "map crypt {}\n", is_default=True))
    revision = storage.revisions.snapshot(module.id)
    made = storage.campaigns.create(name, module.id, revision.number, setting=setting, ruleset="osric")
    seats.owner_seat(storage, made.id)
    return made


def seated(app, storage, campaign_id, role="player"):
    token = new_seat_token()
    storage.seats.create(campaign_id, "Ana", "en", role, token_hash=token_hash(token))
    client = TestClient(app, base_url=BASE_URL)
    client.__enter__()
    client.cookies.set(SEAT_COOKIE, token)
    return client


def delete(client, path):
    return client.request("DELETE", path, json={})


def page_path(title: str, setting: str = "greyhawk") -> str:
    return f"/api/settings/{setting}/pages/{quote(title, safe='')}"


def test_the_settings_list_and_one_setting(local, storage):
    listed = local.get("/api/settings")
    assert listed.status_code == 200
    assert listed.json() == [
        {"id": "aun", "title": "Aun"},
        {"id": "forgotten-realms", "title": "Forgotten Realms"},
        {"id": "greyhawk", "title": "Greyhawk"},
    ], "the fake only when alone"

    one = local.get("/api/settings/greyhawk").json()
    assert (one["id"], one["title"]) == ("greyhawk", "Greyhawk")
    assert "place" in one["kinds"] and one["counts"] == {"pages": 0, "facts": 0, "proposals": 0}
    assert one["maps_in_use"] == "built-in"
    assert one["built_in_maps"] == [{"name": "greyhawk-region", "title": "Greyhawk region"}]

    realms = local.get("/api/settings/forgotten-realms").json()
    assert (realms["title"], realms["built_in_maps"]) == ("Forgotten Realms", [])
    assert realms["kinds"][:2] == ["place", "realm"] and "archfiend" not in realms["kinds"]
    assert (realms["calendar"]["id"], realms["calendar"]["era"]) == ("harptos", "DR")
    calendar = one["calendar"]
    assert set(calendar) == {"id", "era", "months", "default_start"} and calendar["era"] == "CY"
    assert set(calendar["months"][0]) == {"name", "days", "season", "weather_season", "festival"}

    storage.setting_pages.put(SettingAddition("greyhawk", "Saltmarsh", text="A town."))
    local.post("/api/settings/greyhawk/facts", json={"text": "Iuz stirs."})
    cid = make_campaign(storage).id
    storage.proposals.add(Proposal(0, "greyhawk", cid, "fact", text="Vecna stirs."))
    rejected = storage.proposals.add(Proposal(0, "greyhawk", cid, "fact", text="Nobody.", status="rejected"))
    assert rejected.status == "rejected"
    counts = local.get("/api/settings/greyhawk").json()["counts"]
    assert counts == {"pages": 1, "facts": 1, "proposals": 1}

    unknown = local.get("/api/settings/narnia")
    assert unknown.status_code == 404 and unknown.json() == {"error": "There is no setting 'narnia'."}


def test_search_and_browse_by_kind(local, storage):
    storage.setting_pages.put(SettingAddition("greyhawk", "Saltmarsh", kind="place", text="A town by Hardby's bay."))
    found = local.get("/api/settings/greyhawk/search", params={"q": "hardby"}).json()
    assert found["query"] == "hardby"
    titles = [hit["title"] for hit in found["results"]]
    assert titles[0] == "Saltmarsh" and "Hardby" in titles
    assert set(found["results"][0]) >= {"kind", "key", "title", "text", "origin"}
    assert found["results"][0]["origin"] == "addition"

    places = local.get("/api/settings/greyhawk/kinds/place").json()
    assert places["kind"] == "place"
    found = [(hit["title"], hit["origin"]) for hit in places["results"]]
    assert ("Hardby", "shipped") in found and ("Saltmarsh", "addition") in found
    assert found == sorted(found), "by title"
    assert [hit["title"] for hit in local.get("/api/settings/greyhawk/kinds/place?q=salt").json()["results"]] == [
        "Saltmarsh"
    ]
    assert local.get("/api/settings/greyhawk/kinds/dragon").status_code == 404
    assert local.get("/api/settings/greyhawk/kinds/place?limit=0").status_code == 422
    assert local.get("/api/settings/greyhawk/kinds/place?limit=501").status_code == 422


def test_search_takes_any_input(local, storage):
    storage.setting_pages.put(SettingAddition("greyhawk", "Ærdy", text="The Ūrnst border, near Ærdy."))
    for query in ('"', "*", "AND", "-", "%", "_", ""):
        response = local.get("/api/settings/greyhawk/search", params={"q": query})
        assert response.status_code == 200, query
        assert all(hit["title"] != "Ærdy" for hit in response.json()["results"]), query
    for words in ("Ærdy", "ūrnst"):
        assert [
            hit["title"] for hit in local.get("/api/settings/greyhawk/search", params={"q": words}).json()["results"]
        ] == ["Ærdy"]


def test_read_a_page_follows_a_redirect(local):
    page = local.get(page_path("Mordy"))
    assert page.status_code == 200, page.json()
    body = page.json()
    assert (body["title"], body["redirected_from"], body["origin"], body["revertible"]) == (
        "Mordenkainen",
        "Mordy",
        "shipped",
        False,
    )
    assert body["text"].startswith("**Mordenkainen** is an archmage"), "always Markdown"
    assert set(body) == {
        "title",
        "kind",
        "fields",
        "text",
        "categories",
        "origin",
        "dm_only",
        "campaign_id",
        "revertible",
        "redirected_from",
    }
    assert local.get(page_path("  hardby ")).json()["redirected_from"] is None
    missing = local.get(page_path("Nowhere"))
    assert missing.status_code == 404 and "error" in missing.json()


def test_add_override_and_revert_a_page(app, local, storage):
    events = []
    app.state.events.publish = lambda kind, data, **where: events.append((kind, data, where))

    made = local.put(page_path("Saltmarsh"), json={"kind": "place", "text": "A town.", "fields": {"size": "Small"}})
    assert made.status_code == 201, made.json()
    assert (made.json()["origin"], made.json()["revertible"], made.json()["fields"]) == (
        "addition",
        False,
        {"size": "Small"},
    )
    changed = local.put(page_path("saltmarsh"), json={"text": "A fishing town."})
    assert changed.status_code == 200 and changed.json()["title"] == "Saltmarsh", "the title keeps its spelling"

    overridden = local.put(page_path("Mordy"), json={"text": "The archmage, retired."})
    assert overridden.status_code == 201
    body = overridden.json()
    assert (body["title"], body["origin"], body["revertible"], body["redirected_from"]) == (
        "Mordenkainen",
        "override",
        True,
        "Mordy",
    )
    assert storage.setting_pages.get("greyhawk", "Mordenkainen").text == "The archmage, retired."

    assert delete(local, page_path("Mordy")).status_code == 204
    back = local.get(page_path("Mordenkainen")).json()
    assert (back["origin"], back["revertible"]) == ("shipped", False)
    assert delete(local, page_path("Mordenkainen")).status_code == 404
    assert delete(local, page_path("Saltmarsh")).status_code == 204
    assert local.get(page_path("Saltmarsh")).status_code == 404
    assert [kind for kind, _, _ in events] == ["setting"] * 5
    assert all(
        data == {"id": "greyhawk"} and where.get("scope", "organisers") == "organisers" for _, data, where in events
    )

    for bad in ({"text": ""}, {"text": "  "}, {"text": "x", "kind": "dragon"}):
        assert local.put(page_path("Saltmarsh"), json=bad).status_code == 422, bad
    assert local.put("/api/settings/greyhawk/pages/%20", json={"text": "x"}).status_code == 422
    assert local.put(page_path("Saltmarsh", "narnia"), json={"text": "x"}).status_code == 404


def test_an_override_keeps_the_shipped_pages_kind(local, storage):
    """The Settings page's form sends a shipped page's own kind back (the reference's table, not a kind of the
    setting): the override is stored without a kind of its own, and keeps the shipped page's."""
    shipped = local.get(page_path("Hardby")).json()
    assert shipped["kind"] and shipped["kind"] not in local.get("/api/settings/greyhawk").json()["kinds"]
    overridden = local.put(page_path("Hardby"), json={"kind": shipped["kind"], "text": "A port, rebuilt."})
    assert overridden.status_code == 201, overridden.json()
    assert (overridden.json()["origin"], overridden.json()["kind"]) == ("override", shipped["kind"])
    assert storage.setting_pages.get("greyhawk", "Hardby").kind == ""
    again = local.put(page_path("Hardby"), json={"kind": shipped["kind"], "text": "A port, rebuilt twice."})
    assert again.status_code == 200 and again.json()["kind"] == shipped["kind"]
    assert local.put(page_path("Hardby"), json={"kind": "place", "text": "A place."}).json()["kind"] == "place"
    refused = local.put(page_path("Saltmarsh"), json={"kind": shipped["kind"], "text": "A town."})
    assert refused.status_code == 422, "a new page has no shipped kind to keep"
    assert local.put(page_path("Hardby"), json={"kind": "dragon", "text": "A port."}).status_code == 422


def test_a_title_with_slash_apostrophe_and_question_mark(local):
    title = "Ready'reat / Patchwall?"
    assert local.put(page_path(title), json={"text": "A strange place."}).status_code == 201
    assert local.get(page_path(title)).json()["title"] == title
    assert [hit["title"] for hit in local.get("/api/settings/greyhawk/search?q=strange").json()["results"]] == [title]
    assert delete(local, page_path(title)).status_code == 204
    assert local.get(page_path(title)).status_code == 404


def test_facts_crud(local, storage):
    facts = local.get("/api/settings/greyhawk/facts").json()
    assert facts["own"] == []
    assert {fact["text"] for fact in facts["shipped"]} == {
        "The Circle of Eight keeps any one power from ruling the Flanaess.",
        "Iuz is the son of Iggwilv.",
        "The Twin Cataclysms ended the Suel Imperium.",
    }, "only Greyhawk's own categories"
    assert all(set(fact) == {"id", "text", "category"} for fact in facts["shipped"])

    made = local.post("/api/settings/greyhawk/facts", json={"text": "Iuz stirs.", "category": "greyhawk"})
    assert made.status_code == 201
    fact = made.json()
    assert set(fact) == {"id", "text", "category", "dm_only", "created_at"} and fact["dm_only"] is False
    changed = local.put(f"/api/settings/greyhawk/facts/{fact['id']}", json={"text": "Iuz wakes.", "dm_only": True})
    assert changed.status_code == 200 and (changed.json()["text"], changed.json()["dm_only"]) == ("Iuz wakes.", True)
    assert [f["text"] for f in local.get("/api/settings/greyhawk/facts").json()["own"]] == ["Iuz wakes."]
    assert local.post("/api/settings/greyhawk/facts", json={"text": " "}).status_code == 422
    assert local.put(f"/api/settings/fake-setting/facts/{fact['id']}", json={"text": "x"}).status_code == 404
    assert delete(local, f"/api/settings/fake-setting/facts/{fact['id']}").status_code == 404
    assert delete(local, f"/api/settings/greyhawk/facts/{fact['id']}").status_code == 204
    assert delete(local, f"/api/settings/greyhawk/facts/{fact['id']}").status_code == 404
    assert local.get("/api/settings/greyhawk/facts").json()["own"] == []


def test_proposals_list_edit_accept_reject(local, storage):
    campaign = make_campaign(storage)
    page = storage.proposals.add(Proposal(0, "greyhawk", campaign.id, "page", title="Saltmarsh", text="A town."))
    fact = storage.proposals.add(Proposal(0, "greyhawk", campaign.id, "fact", text="Iuz stirs."))
    edit = storage.proposals.add(Proposal(0, "greyhawk", campaign.id, "edit", title="Hardby", text="It fell."))

    listed = local.get("/api/settings/greyhawk/proposals", params={"status": "pending"}).json()
    assert [p["id"] for p in listed] == [page.id, fact.id, edit.id]
    assert set(listed[0]) == {
        "id",
        "campaign_id",
        "campaign_title",
        "kind",
        "title",
        "text",
        "mode",
        "page_kind",
        "category",
        "dm_only",
        "status",
        "created_at",
        "decided_at",
    }
    assert listed[0]["campaign_title"] == "Tuesday"

    edited = local.put(
        f"/api/settings/greyhawk/proposals/{page.id}", json={"text": "A fishing town.", "page_kind": "place"}
    )
    assert edited.status_code == 200 and (edited.json()["text"], edited.json()["page_kind"]) == (
        "A fishing town.",
        "place",
    )

    accepted = local.post(f"/api/settings/greyhawk/proposals/{page.id}/accept", json={})
    assert accepted.status_code == 200, accepted.json()
    assert accepted.json()["proposal"]["status"] == "accepted"
    assert (accepted.json()["page"]["title"], accepted.json()["page"]["origin"]) == ("Saltmarsh", "addition")
    accepted_fact = local.post(f"/api/settings/greyhawk/proposals/{fact.id}/accept", json={}).json()
    assert accepted_fact["fact"]["text"] == "Iuz stirs." and "page" not in accepted_fact
    again = local.post(f"/api/settings/greyhawk/proposals/{page.id}/accept", json={})
    assert again.status_code == 409 and "error" in again.json()

    rejected = local.post(f"/api/settings/greyhawk/proposals/{edit.id}/reject", json={})
    assert rejected.status_code == 200 and rejected.json()["status"] == "rejected"
    assert local.put(f"/api/settings/greyhawk/proposals/{edit.id}", json={"text": "x"}).status_code == 409
    assert local.get("/api/settings/greyhawk/proposals?status=pending").json() == []
    assert len(local.get("/api/settings/greyhawk/proposals").json()) == 3
    assert local.post(f"/api/settings/fake-setting/proposals/{edit.id}/reject", json={}).status_code == 404
    assert local.post("/api/settings/greyhawk/proposals/999/accept", json={}).status_code == 404


def test_organisers_only(app, storage):
    campaign = make_campaign(storage)
    proposal = storage.proposals.add(Proposal(0, "greyhawk", campaign.id, "fact", text="Iuz stirs."))
    ana = seated(app, storage, campaign.id)
    try:
        reads = (
            "/api/settings",
            "/api/settings/greyhawk",
            "/api/settings/greyhawk/search?q=hardby",
            "/api/settings/greyhawk/kinds/place",
            page_path("Hardby"),
            "/api/settings/greyhawk/facts",
            "/api/settings/greyhawk/proposals",
        )
        for path in reads:
            response = ana.get(path)
            assert response.status_code == 403 and response.json() == {"error": "This needs the organiser role."}, path
        writes = (
            ("put", page_path("Hardby"), {"text": "x"}),
            ("delete", page_path("Hardby"), {}),
            ("post", "/api/settings/greyhawk/facts", {"text": "x"}),
            ("put", "/api/settings/greyhawk/facts/1", {"text": "x"}),
            ("delete", "/api/settings/greyhawk/facts/1", {}),
            ("put", f"/api/settings/greyhawk/proposals/{proposal.id}", {"text": "x"}),
            ("post", f"/api/settings/greyhawk/proposals/{proposal.id}/accept", {}),
            ("post", f"/api/settings/greyhawk/proposals/{proposal.id}/reject", {}),
        )
        for method, path, body in writes:
            response = ana.request(method, path, json=body)
            assert response.status_code == 403, (method, path)
        assert storage.proposals.get(proposal.id).status == "pending"
    finally:
        ana.__exit__(None, None, None)


def test_the_table_routes_are_scoped_and_filtered(app, local, storage):
    campaign, other, plain = make_campaign(storage), make_campaign(storage, name="Friday"), make_campaign(storage, None)
    storage.setting_pages.put(SettingAddition("greyhawk", "Saltmarsh", kind="place", text="A town."))
    storage.proposals.add(Proposal(0, "greyhawk", campaign.id, "page", title="Ours", text="This table's own."))
    storage.proposals.add(Proposal(0, "greyhawk", other.id, "page", title="Theirs", text="Another table's."))
    ana = seated(app, storage, campaign.id)
    try:
        base = f"/api/campaigns/{campaign.id}/setting"
        about = ana.get(base).json()
        assert set(about) == {"id", "title", "kinds", "calendar"} and about["id"] == "greyhawk"

        hardby = ana.get(f"{base}/pages/Hardby")
        assert hardby.status_code == 200 and hardby.json()["title"] == "Hardby"
        assert hardby.json()["text"].startswith("**Hardby**")
        assert ana.get(f"{base}/pages/Mordy").json()["redirected_from"] == "Mordy"
        ours = ana.get(f"{base}/pages/Ours").json()
        assert (ours["origin"], ours["campaign_id"]) == ("proposal", campaign.id)
        assert ana.get(f"{base}/pages/Theirs").status_code == 404, "a proposal is its campaign's until accepted"

        hits = ana.get(f"{base}/search", params={"q": "table's"}).json()["results"]
        assert [(h["title"], h["origin"], h.get("campaign_id")) for h in hits] == [("Ours", "proposal", campaign.id)]
        places = ana.get(f"{base}/kinds/place").json()["results"]
        assert {"Hardby", "Saltmarsh"} <= {h["title"] for h in places}
        assert ana.get(f"{base}/kinds/dragon").status_code == 404

        storage.proposals.add(Proposal(0, "greyhawk", campaign.id, "fact", text="Iuz stirs."))
        local.post("/api/settings/greyhawk/facts", json={"text": "Vecna stirs."})
        facts = ana.get(f"{base}/facts").json()["facts"]
        assert {"text": "Iuz is the son of Iggwilv.", "category": "greyhawk", "origin": "shipped"} in facts
        assert facts[-2:] == [
            {"text": "Iuz stirs.", "category": "", "origin": "campaign"},
            {"text": "Vecna stirs.", "category": "", "origin": "install"},
        ]

        for path in ("", "/search?q=hardby", "/kinds/place", "/pages/Hardby", "/facts"):
            refused = ana.get(f"/api/campaigns/{other.id}/setting{path}")
            assert refused.status_code == 403, path
        none = local.get(f"/api/campaigns/{plain.id}/setting")
        assert none.status_code == 404 and none.json() == {"error": "This campaign has no setting."}
        assert local.get(f"/api/campaigns/{plain.id}/setting/pages/Hardby").status_code == 404
    finally:
        ana.__exit__(None, None, None)


def test_the_owners_seat_reads_the_tab_as_a_player_does(local, storage):
    """Decision 11: the tab's routes filter for every caller, the owner's own seat too."""
    campaign = make_campaign(storage)
    storage.setting_pages.put(SettingAddition("greyhawk", "Saltmarsh", text=f"A town.\n\n::: dm\n{SECRET}\n:::"))
    storage.setting_pages.put(SettingAddition("greyhawk", "Hideout", text=SECRET, dm_only=True))
    storage.proposals.add(Proposal(0, "greyhawk", campaign.id, "fact", text=SECRET, dm_only=True))
    base = f"/api/campaigns/{campaign.id}/setting"
    assert local.get(f"{base}/pages/Saltmarsh").json()["text"] == "A town."
    assert local.get(f"{base}/pages/Hideout").status_code == 404
    assert SECRET not in local.get(f"{base}/facts").text
    assert local.get(f"{base}/search", params={"q": SECRET}).json()["results"] == []
    assert SECRET in local.get(page_path("Hideout")).text, "the area shows it to organisers"
