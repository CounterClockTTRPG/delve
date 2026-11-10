"""The conversion API and drafts (plan 5 Task 5): a PDF or a request becomes a module in the background, and a draft
can't start a campaign until it's marked ready (Review Focus 4). A broken PDF fails its conversion with the reader's
message, and makes no module (Review Focus 5).

Claude is `FakeDM` with the runner tests' side handler. The test PDFs have only text pages, so no page needs OCR.

A thorough conversion (thorough conversion Task 8) is the default: these tests ask for the quick one (`upload`'s
`thorough=false`) unless they are about the thorough one, whose agents are `tests/fakes/fake_claude_agent.py`, a fake
`claude` on `PATH` that the app's agent runner (`run_agent`) runs for real in the job folder.
"""

import asyncio
import json
import os
import time
from dataclasses import replace
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from delve.conversions import runner
from delve.conversions.thorough.pieces import USAGE_LIMIT
from delve.conversions.thorough.workspace import DELVE_STOPPED, RECORDS, Workspace
from delve.dm.claude_cli import CLAUDE_CLI_CAPABILITIES
from delve.dm.claude_cli.agent import AGENT_TIMEOUT
from delve.dm.fake import FAKE_DM_CAPABILITIES, FakeDM
from delve.domain.backends import Registry
from delve.domain.settings import BackendChoice, Effort, Job
from delve.web.app import create_app
from delve.web.guard import PDF_LIMIT
from delve.web.routes import conversions as conversion_routes
from tests.conversions.test_runner import CAVES, Claude
from tests.conversions.thorough.test_pipeline import _answer as pipeline_answer
from tests.conversions.thorough.test_pipeline import _book as pipeline_book
from tests.fakes import fake_claude_agent
from tests.fakes.fake_claude_agent import COST
from tests.fixtures.pdfs import encrypted_pdf, pdf_bytes, text_page, truncated_pdf
from tests.web.conftest import BASE_URL, make_account, make_registries, session_for
from tests.web.test_campaigns_api import crypt_module
from tests.web.test_preferences_api import published

CONVERSION_FIELDS = {
    "id",
    "kind",
    "title",
    "mode",
    "status",
    "step",
    "steps",
    "done",
    "total",
    "module_id",
    "warnings",
    "error",
    "created_at",
    "updated_at",
    "target",
    "result",
    "questions",
    "cost_usd",
    "comments",
    "closed",
    "thorough",
    "paused",
}
CAVES_PDF = pdf_bytes([text_page(CAVES)])
PDF_HEADERS = {"Content-Type": "application/pdf"}
HOUSE_MAP_PAGE = '{"kind": "map", "title": "The Haunted House"}'


@pytest.fixture
def claude():
    return Claude()


@pytest.fixture
def registries(claude):
    """The web tests' registries, with a DM whose side calls the runner tests' Claude answers."""
    dm = Registry()
    dm.register(FAKE_DM_CAPABILITIES, lambda: FakeDM([], side_handler=claude))
    return replace(make_registries(), dm=dm)


def upload(local, data: bytes, *, title="The Kobold Caves", mode="ready", media_type="application/pdf", **more):
    """Upload `data` for a conversion: the quick one unless `more` says `thorough`."""
    params = {"title": title, "mode": mode, "thorough": "false", **more}
    return local.post("/api/conversions/pdf", params=params, content=data, headers={"Content-Type": media_type})


def ended(local, id: str, *, waiting=("running", "queued")) -> dict:
    """The conversion once it has ended (or paused)."""
    deadline = time.monotonic() + 20
    while time.monotonic() < deadline:
        conversion = local.get(f"/api/conversions/{id}").json()
        if conversion["status"] not in waiting:
            return conversion
        time.sleep(0.02)
    raise AssertionError(f"conversion {id} still running")


def uploads(config) -> list:
    root = config.data_dir / "uploads"
    return sorted(root.iterdir()) if root.exists() else []


# ----- a PDF -----


def test_a_pdf_upload_converts_into_a_module(local, app, config):
    response = upload(local, CAVES_PDF)

    assert response.status_code == 202, response.json()
    started = response.json()
    assert set(started) == CONVERSION_FIELDS
    assert started["id"].startswith("cnv_")
    assert (started["kind"], started["title"], started["mode"], started["status"]) == (
        "pdf",
        "The Kobold Caves",
        "ready",
        "running",
    )
    done = ended(local, started["id"])
    assert done["status"] == "done" and done["error"] is None and done["module_id"]
    assert done["step"] == "maps"
    assert "map-sketched" in [w["code"] for w in done["warnings"]]
    assert set(done["warnings"][0]) == {"code", "message", "ref"}

    module = local.get(f"/api/modules/{done['module_id']}").json()
    assert module["title"] == "The Kobold Caves" and module["draft"] is False
    assert [m["name"] for m in module["maps"]] == ["the-caves"]
    attachments = local.get(f"/api/modules/{module['id']}/source").json()["attachments"]
    assert [(a["id"], a["role"]) for a in attachments] == [("source-pdf", "source")]
    assert uploads(config) == [], "the uploaded file is gone when the job ends"

    events = [e.data for e in published(app) if e.type == "conversion"]
    assert events and all(set(e) == {"id", "status", "step", "done", "total", "steps", "cost_usd"} for e in events)
    assert events[-1]["status"] == "done"


@pytest.mark.parametrize(
    ("params", "drawn"), [({}, True), ({"book_maps": "true"}, True), ({"book_maps": "false"}, False)]
)
def test_book_maps_are_drawn_unless_asked_not_to(local, monkeypatch, params, drawn):
    asked = []

    async def draw(services, module_id):
        asked.append(module_id)
        return []

    monkeypatch.setattr(conversion_routes, "draw_book_maps", draw)
    done = ended(local, upload(local, CAVES_PDF, **params).json()["id"])

    deadline = time.monotonic() + 5
    while drawn and not asked and time.monotonic() < deadline:
        time.sleep(0.02)
    assert asked == ([done["module_id"]] if drawn else [])


def test_a_draft_upload_makes_a_draft_module(local):
    started = upload(local, CAVES_PDF, mode="draft").json()
    assert started["mode"] == "draft"
    done = ended(local, started["id"])
    module = local.get(f"/api/modules/{done['module_id']}").json()
    assert module["draft"] is True
    [listed] = local.get("/api/modules").json()
    assert listed["draft"] is True


@pytest.mark.parametrize("media_type", ["application/octet-stream", "application/json", "application/zip", ""])
def test_a_pdf_upload_of_another_type_is_415(local, media_type):
    response = upload(local, CAVES_PDF, media_type=media_type)
    assert response.status_code == 415
    assert "application/pdf" in response.json()["error"]
    assert local.get("/api/conversions").json() == []


def test_a_pdf_that_says_it_is_too_long_is_413(local):
    headers = {"Content-Type": "application/pdf", "Content-Length": str(PDF_LIMIT + 1)}
    params = {"title": "Big", "thorough": "false"}
    response = local.post("/api/conversions/pdf", params=params, content=b"%PDF-", headers=headers)
    assert response.status_code == 413
    assert "error" in response.json()


def test_a_pdf_that_streams_past_the_limit_is_413(local, config, monkeypatch):
    monkeypatch.setattr(conversion_routes, "PDF_LIMIT", 1024)
    response = upload(local, b"%PDF-1.4\n" + b"x" * 2048)
    assert response.status_code == 413
    assert "error" in response.json()
    assert uploads(config) == []
    assert local.get("/api/conversions").json() == []


def test_bytes_that_are_not_a_pdf_are_400(local, config):
    response = upload(local, b"PK\x03\x04 a zip, really")
    assert response.status_code == 400
    assert response.json() == {"error": "The file isn't a PDF."}
    assert uploads(config) == []
    assert local.get("/api/conversions").json() == []


def test_a_pdf_needs_a_title_and_a_mode(local, config):
    no_title = upload(local, CAVES_PDF, title="  ")
    assert no_title.status_code == 422 and no_title.json() == {"error": "A conversion needs a title."}
    bad_mode = upload(local, CAVES_PDF, mode="later")
    assert bad_mode.status_code == 422 and "error" in bad_mode.json()
    assert uploads(config) == []
    assert local.get("/api/conversions").json() == []


@pytest.mark.parametrize(("title", "mode"), [("  ", "ready"), ("The Kobold Caves", "later")])
def test_a_title_and_a_mode_are_checked_before_the_book_is_taken_in(local, monkeypatch, title, mode):
    async def never(request, folder):
        raise AssertionError("the body was taken in")

    monkeypatch.setattr(conversion_routes, "_receive_pdf", never)
    response = upload(local, CAVES_PDF, title=title, mode=mode)
    assert response.status_code == 422 and "error" in response.json()


@pytest.mark.parametrize(
    ("data", "message"),
    [
        (encrypted_pdf(), "The PDF is encrypted: it needs a password to open."),
        (truncated_pdf(), "The PDF can't be read"),
    ],
    ids=["encrypted", "corrupt"],
)
def test_a_broken_pdf_fails_its_conversion_and_makes_no_module(local, config, data, message):
    started = upload(local, data)
    assert started.status_code == 202, started.json()

    failed = ended(local, started.json()["id"])

    assert failed["status"] == "failed"
    assert failed["error"].startswith(message)
    assert failed["module_id"] is None
    assert local.get("/api/modules").json() == []
    assert uploads(config) == []


def test_one_conversion_at_a_time(local, app, claude):
    gate = asyncio.Event()
    handler = claude.__call__
    waiting = []

    # The first job waits in its first Claude call until the gate opens.
    async def held(prompt, choice, *, timeout=None, on_usage=None):
        waiting.append(prompt)
        await gate.wait()
        return handler(prompt)

    dm = app.state.registries.dm.get("fake")
    dm.side_call = held
    first = upload(local, CAVES_PDF).json()
    deadline = time.monotonic() + 10
    while not waiting and time.monotonic() < deadline:
        time.sleep(0.01)

    second = upload(local, CAVES_PDF, title="Another")
    generated = local.post("/api/conversions/generate", json={"request": "a dungeon with kobolds"})

    assert second.status_code == 202 and second.json()["status"] == "queued", "a book waits in the queue"
    assert generated.status_code == 202 and generated.json()["status"] == "queued", "so does a request (DEL-141)"
    local.portal.call(gate.set)
    assert ended(local, first["id"])["status"] == "done"
    assert ended(local, second.json()["id"])["status"] == "done", "it started when the slot freed"
    assert ended(local, generated.json()["id"])["status"] == "done"


# ----- a request -----


def test_a_request_generates_a_module(local):
    response = local.post("/api/conversions/generate", json={"request": "a dungeon with kobolds, no plot"})

    assert response.status_code == 202, response.json()
    started = response.json()
    assert set(started) == CONVERSION_FIELDS
    assert (started["kind"], started["title"], started["mode"]) == (
        "generate",
        "a dungeon with kobolds, no plot",
        "ready",
    )
    done = ended(local, started["id"])
    assert done["status"] == "done", done
    module = local.get(f"/api/modules/{done['module_id']}").json()
    assert module["draft"] is False and module["title"] == done["title"]


def test_a_request_may_make_a_draft(local):
    started = local.post("/api/conversions/generate", json={"request": "kobolds", "mode": "draft"}).json()
    done = ended(local, started["id"])
    assert local.get(f"/api/modules/{done['module_id']}").json()["draft"] is True


def test_the_app_paints_a_requests_pictures_and_serves_them(local, claude):
    claude.pictures = [{"subject": "Grik", "kind": "person", "brief": "A wiry kobold.", "description": "Grik: when met."}]
    started = local.post("/api/conversions/generate", json={"request": "kobolds", "pictures": 2}).json()
    done = ended(local, started["id"])
    assert done["status"] == "done", done
    source = local.get(f"/api/modules/{done['module_id']}/source").json()
    assert [(a["id"], a["audience"], a["description"]) for a in source["attachments"]] == [
        ("grik", "player", "Grik: when met.")
    ]
    picture = local.get(f"/api/modules/{done['module_id']}/assets/grik")
    assert picture.status_code == 200 and picture.headers["content-type"] == "image/png"


def test_pictures_within_the_limit_are_kept_on_the_job(local, storage):
    storage.conversions.set_queue_paused(True)
    response = local.post("/api/conversions/generate", json={"request": "kobolds", "pictures": 12})
    assert response.status_code == 202, response.json()
    assert response.json()["target"]["pictures"] == 12
    assert response.json()["steps"]["count"] == 3
    assert local.post("/api/conversions/generate", json={"request": "kobolds", "pictures": 13}).status_code == 422
    assert local.post("/api/conversions/generate", json={"request": "kobolds", "pictures": -1}).status_code == 422


def test_pictures_on_a_paid_model_are_the_owners(app, lan, storage, monkeypatch):
    storage.conversions.set_queue_paused(True)
    monkeypatch.setattr("delve.web.routes.conversions.image_paid", lambda app, job: True)
    session_for(storage, make_account(storage, "otto", organiser=True), lan)
    assert lan.get("/api/conversions/options").json()["pictures"] == {"paid": True, "allowed": False}
    refused = lan.post("/api/conversions/generate", json={"request": "kobolds", "pictures": 4})
    assert refused.status_code == 422 and "owner" in refused.text
    assert lan.post("/api/conversions/generate", json={"request": "kobolds"}).status_code == 202, "without pictures"

    monkeypatch.setattr("delve.web.routes.conversions.image_paid", lambda app, job: False)
    assert lan.get("/api/conversions/options").json()["pictures"] == {"paid": False, "allowed": True}
    free = lan.post("/api/conversions/generate", json={"request": "kobolds", "pictures": 4})
    assert free.status_code == 202 and free.json()["target"]["owner"] is False


def test_the_owner_may_ask_for_pictures_on_a_paid_model(local, storage, monkeypatch):
    storage.conversions.set_queue_paused(True)
    monkeypatch.setattr("delve.web.routes.conversions.image_paid", lambda app, job: True)
    assert local.get("/api/conversions/options").json()["pictures"] == {"paid": True, "allowed": True}
    started = local.post("/api/conversions/generate", json={"request": "kobolds", "pictures": 4})
    assert started.status_code == 202 and started.json()["target"]["owner"] is True


def test_an_empty_request_is_422(local):
    response = local.post("/api/conversions/generate", json={"request": "  \n "})
    assert response.status_code == 422
    assert response.json() == {"error": "Describe the module you want."}
    assert local.post("/api/conversions/generate", json={}).status_code == 422
    assert local.post("/api/conversions/generate", json={"request": "x", "mode": "later"}).status_code == 422
    assert local.get("/api/conversions").json() == []


# ----- reading and cancelling -----


def test_the_last_twenty_newest_first(local, storage):
    for n in range(22):
        conversion = storage.conversions.create("generate", f"job {n}", "ready")
        storage.conversions.save(replace(conversion, status="done"))
    listed = local.get("/api/conversions").json()
    assert [c["title"] for c in listed] == [f"job {n}" for n in range(21, 1, -1)]
    assert all(set(c) == CONVERSION_FIELDS for c in listed)


def test_an_unknown_conversion_is_404(local):
    assert local.get("/api/conversions/cnv_nope").status_code == 404
    response = local.post("/api/conversions/cnv_nope/cancel", json={})
    assert response.status_code == 404 and "error" in response.json()


def test_cancel_stops_a_conversion_and_makes_no_module(local, app, claude):
    gate = asyncio.Event()

    async def held(prompt, choice, *, timeout=None, on_usage=None):
        await gate.wait()
        return claude(prompt)

    app.state.registries.dm.get("fake").side_call = held
    started = upload(local, CAVES_PDF).json()

    response = local.post(f"/api/conversions/{started['id']}/cancel", json={})

    assert response.status_code == 200
    cancelled = response.json()
    assert cancelled["status"] == "cancelled" and cancelled["module_id"] is None
    assert local.get(f"/api/conversions/{started['id']}").json() == cancelled
    assert local.post(f"/api/conversions/{started['id']}/cancel", json={}).json() == cancelled
    assert local.get("/api/modules").json() == []


def test_cancel_needs_json(local, storage):
    conversion = storage.conversions.create("generate", "job", "ready")
    assert local.post(f"/api/conversions/{conversion.id}/cancel").status_code == 415


def test_orphans_are_closed_at_startup(config, storage, registries, static_dir):
    from fastapi.testclient import TestClient

    from delve.web.app import create_app
    from tests.web.conftest import BASE_URL

    left = storage.conversions.create("pdf", "Left running", "ready")
    with TestClient(create_app(config, storage, registries, static_dir=static_dir), base_url=BASE_URL):
        assert storage.conversions.get(left.id).status == "failed"
        assert storage.conversions.get(left.id).error == "Delve stopped during the conversion."


def test_leftover_uploads_are_removed_at_startup(config, storage, registries, static_dir):
    from fastapi.testclient import TestClient

    from delve.web.app import create_app
    from tests.web.conftest import BASE_URL

    folder = config.data_dir / "uploads"
    folder.mkdir(parents=True)
    left = folder / "conversion-abc123.pdf"
    left.write_bytes(CAVES_PDF)
    other = folder / "notes.txt"
    other.write_text("not an upload")
    with TestClient(create_app(config, storage, registries, static_dir=static_dir), base_url=BASE_URL):
        assert not left.exists(), "no running job owns it"
        assert other.exists()


def test_the_running_jobs_upload_is_kept(app, storage, tmp_path):
    folder = app.state.config.data_dir / "uploads"
    folder.mkdir(parents=True, exist_ok=True)
    owned, left = folder / "conversion-owned.pdf", folder / "conversion-left.pdf"
    for path in (owned, left):
        path.write_bytes(CAVES_PDF)
    services = conversion_routes.conversions(app)
    services.live["cnv_x"] = runner._Live(storage.conversions.create("pdf", "Running", "ready"), upload=owned)

    assert conversion_routes.remove_leftover_uploads(app) == [left]
    assert owned.exists() and not left.exists()


def test_the_routes_are_for_organisers(lan, storage):
    conversion = storage.conversions.create("generate", "job", "ready")
    assert lan.get("/api/conversions").status_code == 401
    assert lan.get(f"/api/conversions/{conversion.id}").status_code == 401
    assert lan.post("/api/conversions/generate", json={"request": "kobolds"}).status_code == 401
    assert lan.post(f"/api/conversions/{conversion.id}/cancel", json={}).status_code == 401
    pdf = lan.post("/api/conversions/pdf", params={"title": "x"}, content=CAVES_PDF, headers={"Content-Type": "application/pdf"})
    assert pdf.status_code == 401


# ----- drafts -----


def _draft(local, storage) -> dict:
    module = crypt_module(local)
    storage.modules.set_draft(module["id"], True)
    return local.get(f"/api/modules/{module['id']}").json()


def test_a_draft_cannot_start_a_campaign(local, storage):
    module = _draft(local, storage)
    assert module["draft"] is True

    response = local.post("/api/campaigns", json={"name": "Tuesday", "module_id": module["id"]})

    assert response.status_code == 409
    assert response.json() == {"error": "This module is a draft: mark it ready first."}
    assert local.get("/api/campaigns").json() == []
    assert storage.revisions.latest(module["id"]) is None


def test_a_draft_marked_ready_starts_a_campaign(local, app, storage):
    module = _draft(local, storage)

    response = local.patch(f"/api/modules/{module['id']}", json={"draft": False})

    assert response.status_code == 200 and response.json()["draft"] is False
    assert ("modules", {"id": module["id"]}) in [(e.type, e.data) for e in published(app)]
    created = local.post("/api/campaigns", json={"name": "Tuesday", "module_id": module["id"]})
    assert created.status_code == 201, created.json()


def test_a_module_cannot_become_a_draft_again(local):
    module = crypt_module(local)
    assert module["draft"] is False

    response = local.patch(f"/api/modules/{module['id']}", json={"draft": True})

    assert response.status_code == 422
    assert response.json() == {"error": "A module can't become a draft again."}
    assert local.get(f"/api/modules/{module['id']}").json()["draft"] is False


# ----- questions while making a module (plateau 7 Task 20) -----


def _asked(storage) -> tuple[str, str]:
    """A module made by a job that asked one question: (module id, conversion id)."""
    module = storage.modules.create("The Kobold Caves")
    made = storage.conversions.create("generate", "kobolds", "ready")
    question = {"id": "q1", "text": "Should Grik bargain?", "default": "He bargains.", "answer": None}
    storage.conversions.save(
        replace(made, status="done", module_id=module.id, questions={"questions": [question], "remarks": []})
    )
    return module.id, made.id


def test_a_modules_questions_and_their_answers(local, app, storage):
    module_id, conversion_id = _asked(storage)
    for n in range(21):
        later = storage.conversions.create("generate", f"Module {n}", "ready")
        storage.conversions.save(replace(later, status="done"))

    [entry] = local.get(f"/api/modules/{module_id}/questions").json()
    assert entry["conversion_id"] == conversion_id and entry["questions"][0]["answer"] is None

    body = {"answers": {"q1": "No, he fights."}, "remarks": ["Add a second level."]}
    answered = local.put(f"/api/conversions/{conversion_id}/questions", json=body)
    assert answered.status_code == 200, answered.json()
    assert answered.json()["questions"][0]["answer"] == "No, he fights."
    assert answered.json()["remarks"] == ["Add a second level."]
    texts = local.get(f"/api/modules/{module_id}/source").json()["texts"]
    notes = next(t for t in texts if t["id"] == "making-notes")
    assert notes["audience"] == "gm" and "No, he fights." in notes["markdown"]
    assert [(e.type, e.data) for e in published(app)] == [("modules", {"id": module_id})]


def test_answering_questions_is_refused_when_it_cant_be(local, storage):
    _, conversion_id = _asked(storage)
    asked_nothing = storage.conversions.create("generate", "plain", "ready")
    assert local.get("/api/modules/mod_missing/questions").status_code == 404
    assert local.put("/api/conversions/cnv_missing/questions", json={"answers": {}}).status_code == 404
    assert local.put(f"/api/conversions/{asked_nothing.id}/questions", json={"answers": {}}).status_code == 404
    unknown = local.put(f"/api/conversions/{conversion_id}/questions", json={"answers": {"q7": "?"}})
    assert unknown.status_code == 422 and "q7" in unknown.json()["error"]


def test_the_questions_routes_are_for_organisers(lan, storage):
    module_id, conversion_id = _asked(storage)
    assert lan.get(f"/api/modules/{module_id}/questions").status_code == 401
    assert lan.put(f"/api/conversions/{conversion_id}/questions", json={"answers": {}}).status_code == 401


# ----- thorough (thorough conversion Task 8) -----


@pytest.fixture
def agents(tmp_path, monkeypatch):
    """The fake agent first on `PATH` as `claude`; answers `(configure, calls)`: `configure(**config)` sets its plan,
    `calls()` the `{piece, step, cwd}` of the sessions it ran, in order."""
    log = tmp_path / "agent-log.jsonl"

    def configure(**config):
        path = fake_claude_agent.install(tmp_path / "agent-bin", {"log": str(log), **config})
        monkeypatch.setenv("FAKE_AGENT_CONFIG", str(path))

    def calls() -> list[dict]:
        return [json.loads(line) for line in log.read_text().splitlines()] if log.exists() else []

    monkeypatch.setenv("PATH", f"{tmp_path / 'agent-bin'}:{os.environ['PATH']}")
    monkeypatch.setenv("DELVE_OCR", "off")
    configure()
    return configure, calls


def thorough_registries():
    """The web tests' registries with the Claude CLI there, as `delve serve` registers it when `claude` is on `PATH`:
    its side calls and looks are a `FakeDM` with the pipeline tests' answers; its agents are the fake agent's."""
    dm = Registry()
    fake = lambda: FakeDM([], side_handler=pipeline_answer, vision_handler=lambda *_: HOUSE_MAP_PAGE)
    dm.register(CLAUDE_CLI_CAPABILITIES, fake)
    dm.register(FAKE_DM_CAPABILITIES, fake)
    return replace(make_registries(), dm=dm)


@pytest.fixture
def thorough_app(config, storage, static_dir, agents):
    return create_app(config, storage, thorough_registries(), static_dir=static_dir)


@pytest.fixture
def owner(thorough_app):
    """A browser on this machine, on the app with the Claude CLI."""
    with TestClient(thorough_app, base_url=BASE_URL, client=("127.0.0.1", 50000)) as client:
        yield client


@pytest.fixture
def book(tmp_path) -> bytes:
    """The fake agent's book: the house and the ship, keyed 1, 2, 3 each, the house's map on page 3."""
    return pipeline_book(tmp_path).read_bytes()


def test_a_pdf_converts_thoroughly_by_default(owner, thorough_app, config, book, agents, monkeypatch):
    _, calls = agents
    drawn = []

    async def draw(services, module_id):
        drawn.append(module_id)
        return []

    monkeypatch.setattr(conversion_routes, "draw_book_maps", draw)
    params = {"title": "Saltmarsh", "mode": "ready", "book_maps": "true"}
    response = owner.post("/api/conversions/pdf", params=params, content=book, headers=PDF_HEADERS)

    assert response.status_code == 202, response.json()
    started = response.json()
    assert started["thorough"] is True and started["paused"] is None
    assert started["target"] == {"thorough": True, "folder": str(config.data_dir / "conversions" / started["id"])}
    done = ended(owner, started["id"])
    assert done["status"] == "done", done["error"]
    assert done["steps"] == {"index": 10, "count": 10} and done["cost_usd"] == pytest.approx(5 * COST)
    assert [c["piece"] for c in calls()] == ["sort", "clean-1", "sort-orphans", "trace-house", "describe"]
    assert {c["cwd"] for c in calls()} == {started["target"]["folder"]}, "every agent ran in the job folder"
    module = owner.get(f"/api/modules/{done['module_id']}").json()
    assert [m["name"] for m in module["maps"]] == ["house", "ship"]
    assert drawn == [], "tracing the book's maps is part of a thorough conversion: book_maps is ignored"
    assert uploads(config) == []
    events = [e.data for e in published(thorough_app) if e.type == "conversion"]
    assert events[-1]["cost_usd"] == pytest.approx(5 * COST), "the cost so far travels with the progress"


def test_the_quick_conversion_is_unchanged(owner, agents):
    done = ended(owner, upload(owner, CAVES_PDF).json()["id"])
    _, calls = agents
    assert done["status"] == "done" and done["thorough"] is False and done["step"] == "maps"
    assert calls() == [], "no agent ran"


def test_thorough_is_unavailable_without_the_claude_cli(local, config):
    assert local.get("/api/conversions/options").json()["thorough"] == {"available": False, "reason": conversion_routes.NO_CLAUDE}
    response = local.post("/api/conversions/pdf", params={"title": "Saltmarsh"}, content=CAVES_PDF, headers=PDF_HEADERS)

    assert response.status_code == 409
    assert response.json() == {"error": conversion_routes.NO_CLAUDE, "code": "thorough_unavailable"}
    assert local.get("/api/conversions").json() == [] and uploads(config) == []


def test_thorough_is_unavailable_on_another_provider(owner, thorough_app, monkeypatch):
    chosen = replace(
        conversion_routes.current_preferences(thorough_app),
        choices={Job.CONVERSION_THOROUGH: BackendChoice("fake", "fake-large")},
    )
    monkeypatch.setattr(conversion_routes, "current_preferences", lambda app: chosen)

    assert owner.get("/api/conversions/options").json()["thorough"] == {
        "available": False,
        "reason": conversion_routes.NOT_CLAUDE,
    }
    response = owner.post("/api/conversions/pdf", params={"title": "Saltmarsh"}, content=CAVES_PDF, headers=PDF_HEADERS)
    assert response.status_code == 409 and response.json()["code"] == "thorough_unavailable"


def test_the_options_say_thorough_is_available(owner):
    assert owner.get("/api/conversions/options").json()["thorough"] == {"available": True, "reason": None}


def test_the_agents_run_on_the_thorough_choice(thorough_app, config, monkeypatch, tmp_path):
    ran = []

    async def recorded(prompt, folder, choice, **options):
        ran.append((prompt, folder, choice, options))
        return "run"

    monkeypatch.setattr(conversion_routes, "run_agent", recorded)
    services = conversion_routes.conversions(thorough_app)
    _, choice = services.thorough()

    assert choice == BackendChoice("claude-cli", "opus", Effort.HIGH), "Preferences' conversion.thorough default"
    assert asyncio.run(services.agent("PIECE: sort", tmp_path, choice)) == "run"
    [(prompt, folder, given, options)] = ran
    assert (prompt, folder, given) == ("PIECE: sort", tmp_path, choice)
    qa = config.data_dir / "bin" / "qa"
    assert options == {
        "timeout": AGENT_TIMEOUT,
        "repo": conversion_routes.REPOSITORY,
        "data_dir": config.data_dir,
        "qa": qa,
        "records": RECORDS,
    }
    assert {"state.json", "book.json", "warnings.json", "drafted/**"} <= set(RECORDS)
    assert os.access(qa, os.X_OK), "each session installs the qa wrapper for this Delve"
    assert (conversion_routes.REPOSITORY / "pyproject.toml").is_file(), "the agents may not read Delve's source"


def test_without_the_claude_cli_there_is_no_agent(app):
    assert conversion_routes.conversions(app).agent is None


def _limited(owner, agents, book) -> dict:
    """A thorough job paused at the usage limit, in its sort; its scheduled resume dropped."""
    configure, _ = agents
    configure(plan={"sort": ["limit"]})
    started = owner.post("/api/conversions/pdf", params={"title": "Saltmarsh"}, content=book, headers=PDF_HEADERS)
    return ended(owner, started.json()["id"])


def test_a_paused_job_says_why_and_resumes(owner, thorough_app, agents, book):
    paused = _limited(owner, agents, book)

    assert paused["status"] == "paused" and paused["thorough"] is True
    assert paused["paused"] == {"reason": USAGE_LIMIT, "resets_at": "2026-10-23T09:00:00+00:00"}
    assert paused["id"] in conversion_routes.conversions(thorough_app).resumes, "it resumes by itself after the reset"

    response = owner.post(f"/api/conversions/{paused['id']}/resume", json={})
    assert response.status_code == 202, response.json()
    assert response.json()["status"] == "running" and response.json()["paused"] is None
    assert paused["id"] not in conversion_routes.conversions(thorough_app).resumes
    done = ended(owner, paused["id"])
    assert done["status"] == "done", done["error"]
    assert done["cost_usd"] == pytest.approx(6 * COST), "the limited session's cost counts once"


def test_a_resume_is_refused_when_it_cant_be(owner, thorough_app, storage, agents, book):
    paused = _limited(owner, agents, book)
    done = storage.conversions.save(replace(storage.conversions.create("generate", "Kobolds", "ready"), status="done"))

    not_paused = owner.post(f"/api/conversions/{done.id}/resume", json={})
    assert not_paused.status_code == 409 and "isn't paused" in not_paused.json()["error"]
    assert owner.post("/api/conversions/cnv_missing/resume", json={}).status_code == 404
    assert owner.post(f"/api/conversions/{paused['id']}/resume").status_code == 415
    owner.post(f"/api/conversions/{paused['id']}/cancel", json={})


def _left(storage, config, tmp_path, title: str, *, status: str, reason: str | None = None, resets_at=None):
    """A thorough job with its folder, as a Delve that stopped left it: `running`, or `paused` for `reason`."""
    job = storage.conversions.create("pdf", title, "ready", target={"thorough": True})
    folder = config.data_dir / "conversions" / job.id
    job = storage.conversions.save(replace(job, target={"thorough": True, "folder": str(folder)}))
    workspace = Workspace.create(job.id, config.data_dir, pipeline_book(tmp_path), options={"mode": "ready"})
    if status == "paused":
        workspace.pause(reason, resets_at)
        job = storage.conversions.save(replace(job, status="paused"))
    return job


def test_the_jobs_delve_stopped_resume_at_start_through_the_queue(config, storage, static_dir, agents, tmp_path):
    older = _left(storage, config, tmp_path, "Older", status="paused", reason=DELVE_STOPPED)
    limited = _left(storage, config, tmp_path, "Limited", status="paused", reason=USAGE_LIMIT, resets_at="3am (UTC)")
    errored = _left(storage, config, tmp_path, "Errored", status="paused", reason="list index out of range")
    stopped = _left(storage, config, tmp_path, "Stopped", status="running")
    app = create_app(config, storage, thorough_registries(), static_dir=static_dir)

    with TestClient(app, base_url=BASE_URL, client=("127.0.0.1", 50000)) as client:
        services = conversion_routes.conversions(app)
        assert set(services.resumes) == {limited.id}, "the usage limit's resume is scheduled again"
        resumed = ended(client, older.id)
        assert resumed["status"] == "done", resumed["error"]
        after = ended(client, stopped.id)
        assert after["status"] == "done", "one at a time, through the queue: the older first, then the stopped one"
        assert after["updated_at"] > resumed["updated_at"]
        assert storage.conversions.get(errored.id).status == "paused", "an error waits for a resume by hand"
        for job in (limited, errored):
            client.post(f"/api/conversions/{job.id}/cancel", json={})


def test_the_start_removes_the_folders_no_unfinished_job_owns(config, storage, static_dir, tmp_path):
    """Review finding 11: a folder left by a Delve that stopped between the module's making and the folder's removal
    (its job done), by a cancel, or by a job whose row is gone, is removed at the start; a paused or a queued job's
    stays."""
    done = _left(storage, config, tmp_path, "Done", status="paused", reason=DELVE_STOPPED)
    storage.conversions.save(replace(done, status="done"))
    cancelled = _left(storage, config, tmp_path, "Cancelled", status="paused", reason=DELVE_STOPPED)
    storage.conversions.save(replace(cancelled, status="cancelled"))
    paused = _left(storage, config, tmp_path, "Paused", status="paused", reason="paused by the organiser")
    queued = _left(storage, config, tmp_path, "Queued", status="paused", reason="paused by the organiser")
    storage.conversions.save(replace(queued, status="queued"))
    storage.conversions.set_queue_paused(True)
    orphan = config.data_dir / "conversions" / "cnv_nobody"
    (orphan / "pages").mkdir(parents=True)
    app = create_app(config, storage, thorough_registries(), static_dir=static_dir)

    with TestClient(app, base_url=BASE_URL, client=("127.0.0.1", 50000)):
        left = sorted(path.name for path in (config.data_dir / "conversions").iterdir())
    assert left == sorted([paused.id, queued.id])


def test_a_folder_delve_cant_read_leaves_the_job_paused(config, storage, static_dir, agents, tmp_path):
    broken = _left(storage, config, tmp_path, "Broken", status="paused", reason=DELVE_STOPPED)
    (config.data_dir / "conversions" / broken.id / "state.json").write_text("{not json")
    app = create_app(config, storage, thorough_registries(), static_dir=static_dir)

    with TestClient(app, base_url=BASE_URL, client=("127.0.0.1", 50000)) as client:
        [listed] = client.get("/api/conversions").json()
        assert (listed["status"], listed["paused"]) == ("paused", None), "Delve starts, and lists it"
        assert storage.conversions.get(broken.id).status == "paused"
        client.post(f"/api/conversions/{broken.id}/cancel", json={})


def test_the_thorough_routes_are_for_organisers(lan, storage):
    conversion = storage.conversions.create("pdf", "Saltmarsh", "ready", target={"thorough": True})
    assert lan.get("/api/conversions/options").status_code == 401
    assert lan.post(f"/api/conversions/{conversion.id}/resume", json={}).status_code == 401
    assert lan.post(f"/api/conversions/{conversion.id}/tell-dm", json={}).status_code == 401


def test_the_doubts_and_the_cost_on_the_module_and_tell_the_dm(owner, thorough_app, book):
    started = owner.post("/api/conversions/pdf", params={"title": "Saltmarsh"}, content=book, headers=PDF_HEADERS)
    done = ended(owner, started.json()["id"])
    module_id = done["module_id"]

    [entry] = owner.get(f"/api/modules/{module_id}/questions").json()
    assert entry["conversion_id"] == done["id"] and entry["told"] is False
    assert entry["cost_usd"] == pytest.approx(5 * COST)
    assert {(d["piece"], d["kind"]) for d in entry["doubts"]} >= {("clean-1", "checker-flag"), ("describe", "picture-unsure")}
    assert set(entry["doubts"][0]) == {"piece", "part", "pages", "kind", "text"}
    texts = owner.get(f"/api/modules/{module_id}/source").json()["texts"]
    assert "making-notes" not in [t["id"] for t in texts], "the doubts are the organiser's until told"

    told = owner.post(f"/api/conversions/{done['id']}/tell-dm", json={})
    assert told.status_code == 200, told.json()
    assert told.json()["told"] is True
    notes = next(t for t in owner.get(f"/api/modules/{module_id}/source").json()["texts"] if t["id"] == "making-notes")
    assert notes["audience"] == "gm" and "## Doubts from the conversion" in notes["markdown"]
    assert "- **ship** (page 2; checker-flag): Key 3 covers 80%: the layer runs on." in notes["markdown"]
    assert {"type": "modules", "data": {"id": module_id}} in [{"type": e.type, "data": e.data} for e in published(thorough_app)]

    owner.put(f"/api/conversions/{done['id']}/questions", json={"answers": {}, "remarks": ["Check the cellar."]})
    notes = next(t for t in owner.get(f"/api/modules/{module_id}/source").json()["texts"] if t["id"] == "making-notes")
    assert "Check the cellar." in notes["markdown"] and "## Doubts from the conversion" in notes["markdown"]


def test_tell_the_dm_needs_doubts(local, storage):
    _, asked_only = _asked(storage)
    assert local.post(f"/api/conversions/{asked_only}/tell-dm", json={}).status_code == 404
    assert local.post("/api/conversions/cnv_missing/tell-dm", json={}).status_code == 404


# ----- the queue (thorough conversion, owner addition 2026-10-23) -----


def _queue(client) -> dict:
    return client.get("/api/conversions/queue").json()


def _until_status(client, id: str, status: str, *, step: str | None = None) -> dict:
    deadline = time.monotonic() + 20
    while time.monotonic() < deadline:
        conversion = client.get(f"/api/conversions/{id}").json()
        if conversion["status"] == status and (step is None or conversion["step"] == step):
            return conversion
        time.sleep(0.02)
    raise AssertionError(f"conversion {id} never {status} {step or ''}")


def test_uploads_while_a_job_runs_queue_and_the_queue_lists_them_in_order(owner, agents, book):
    configure, _ = agents
    configure(plan={"sort": ["slow"]}, slow_seconds=30)
    first = owner.post("/api/conversions/pdf", params={"title": "Saltmarsh"}, content=book, headers=PDF_HEADERS).json()
    _until_status(owner, first["id"], "running", step="sorting")
    second = upload(owner, CAVES_PDF, title="Danger at Dunwater")
    third = owner.post("/api/conversions/pdf", params={"title": "The Final Enemy"}, content=book, headers=PDF_HEADERS)

    assert second.status_code == third.status_code == 202
    assert (second.json()["status"], third.json()["status"]) == ("queued", "queued")
    assert set(second.json()) == CONVERSION_FIELDS
    queue = _queue(owner)
    assert queue["paused"] is False
    assert [(j["title"], j["status"]) for j in queue["jobs"]] == [
        ("Saltmarsh", "running"),
        ("Danger at Dunwater", "queued"),
        ("The Final Enemy", "queued"),
    ]
    assert queue["jobs"][0]["steps"]["index"] == 4 and "cost_usd" in queue["jobs"][0]
    assert queue["jobs"][2]["thorough"] is True

    paused = owner.post(f"/api/conversions/{first['id']}/pause", json={})
    assert paused.status_code == 200, paused.json()
    assert ended(owner, second.json()["id"])["status"] == "done", "the pause started the next queued job"
    for job in (first, third.json()):
        owner.post(f"/api/conversions/{job['id']}/cancel", json={})


def test_a_pause_by_hand_stops_the_agent_and_the_resume_finishes_without_paying_twice(
    owner, thorough_app, storage, agents, book
):
    configure, calls = agents
    configure(plan={"clean-1": ["slow"]}, slow_seconds=30)
    started = owner.post("/api/conversions/pdf", params={"title": "Saltmarsh"}, content=book, headers=PDF_HEADERS)
    id = started.json()["id"]
    running = _until_status(owner, id, "running", step="cleaning")
    deadline = time.monotonic() + 10
    while [c["piece"] for c in calls()][-1:] != ["clean-1"] and time.monotonic() < deadline:
        time.sleep(0.02)

    paused = owner.post(f"/api/conversions/{id}/pause", json={})

    assert paused.status_code == 200, paused.json()
    assert paused.json()["status"] == "paused" and paused.json()["error"] is None
    assert paused.json()["paused"] == {"reason": "paused by the organiser", "resets_at": None}
    assert paused.json()["cost_usd"] == pytest.approx(running["cost_usd"]), "the stopped session added no cost"
    ws = Workspace(Path(storage.conversions.get(id).target["folder"]))
    assert ws.piece("clean-1") is None, "neither done nor a failed attempt"
    assert id not in conversion_routes.conversions(thorough_app).resumes

    resumed = owner.post(f"/api/conversions/{id}/resume", json={})
    assert resumed.status_code == 202 and resumed.json()["status"] == "running"
    done = ended(owner, id)
    assert done["status"] == "done", done["error"]
    assert done["cost_usd"] == pytest.approx(5 * COST), "each finished session paid once"
    pieces = [c["piece"] for c in calls()]
    assert pieces.count("sort") == 1 and pieces.count("clean-1") == 2, "only the stopped piece ran again"


def test_only_a_running_thorough_job_can_be_paused(owner, local, storage):
    done = storage.conversions.save(replace(storage.conversions.create("generate", "Kobolds", "ready"), status="done"))
    refused = owner.post(f"/api/conversions/{done.id}/pause", json={})
    assert refused.status_code == 409 and "only one can be paused" in refused.json()["error"]
    assert owner.post("/api/conversions/cnv_missing/pause", json={}).status_code == 404
    assert owner.post(f"/api/conversions/{done.id}/pause").status_code == 415


def test_a_quick_job_cannot_be_paused(local, app, claude):
    gate = asyncio.Event()
    handler = claude.__call__

    async def held(prompt, choice, *, timeout=None, on_usage=None):
        await gate.wait()
        return handler(prompt)

    app.state.registries.dm.get("fake").side_call = held
    started = upload(local, CAVES_PDF).json()
    refused = local.post(f"/api/conversions/{started['id']}/pause", json={})
    assert refused.status_code == 409 and "error" in refused.json()
    local.portal.call(gate.set)
    assert ended(local, started["id"])["status"] == "done"


def test_a_resume_while_another_job_runs_is_queued(owner, thorough_app, storage, agents, book):
    paused = _limited(owner, agents, book)
    configure, _ = agents
    configure(plan={"sort": ["slow"]}, slow_seconds=30)
    other = owner.post("/api/conversions/pdf", params={"title": "Other"}, content=book, headers=PDF_HEADERS).json()
    _until_status(owner, other["id"], "running", step="sorting")

    response = owner.post(f"/api/conversions/{paused['id']}/resume", json={})

    assert response.status_code == 202, response.json()
    assert response.json()["status"] == "queued" and response.json()["paused"] is None
    owner.post(f"/api/conversions/{other['id']}/cancel", json={})
    assert ended(owner, paused["id"])["status"] == "done"


def test_a_resume_of_a_job_whose_state_cant_be_read_is_a_json_409(owner, storage, config, tmp_path):
    broken = _left(storage, config, tmp_path, "Broken", status="paused", reason="list index out of range")
    (config.data_dir / "conversions" / broken.id / "state.json").write_text("{not json")

    response = owner.post(f"/api/conversions/{broken.id}/resume", json={})

    assert response.status_code == 409
    assert response.json() == {"error": f"The conversion {broken.id} can't be resumed: its folder's state can't be read."}
    assert storage.conversions.get(broken.id).status == "paused"


def test_the_queue_switch_holds_the_queue_and_survives_a_restart(config, storage, static_dir, agents, tmp_path):
    app = create_app(config, storage, thorough_registries(), static_dir=static_dir)
    with TestClient(app, base_url=BASE_URL, client=("127.0.0.1", 50000)) as client:
        put = client.put("/api/conversions/queue", json={"paused": True})
        assert put.status_code == 200 and put.json() == {"paused": True, "jobs": []}
        queued = upload(client, CAVES_PDF, title="At night").json()
        assert queued["status"] == "queued", "with the queue paused, a free slot starts nothing"
        assert [e.data for e in published(app) if e.type == "conversion-queue"] == [{"paused": True}]
    stopped = _left(storage, config, tmp_path, "Stopped", status="running")

    app = create_app(config, storage, thorough_registries(), static_dir=static_dir)
    with TestClient(app, base_url=BASE_URL, client=("127.0.0.1", 50000)) as client:
        queue = _queue(client)
        assert queue["paused"] is True, "the switch survives a restart"
        assert [(j["id"], j["status"]) for j in queue["jobs"]] == [(queued["id"], "queued"), (stopped.id, "queued")]
        assert uploads(config) != [], "a queued job's book is kept at the start"
        time.sleep(0.1)
        assert storage.conversions.get(queued["id"]).status == "queued", "no auto-resume, no queued job starts"

        unpaused = client.put("/api/conversions/queue", json={"paused": False})
        assert unpaused.json()["paused"] is False
        assert ended(client, queued["id"])["status"] == "done", "oldest first"
        assert ended(client, stopped.id)["status"] == "done"
        assert client.put("/api/conversions/queue", json={"paused": "later"}).status_code == 422
        assert client.put("/api/conversions/queue", content=b"{}", headers=PDF_HEADERS).status_code == 415


def test_a_queued_job_cancelled_leaves_the_queue(owner, agents, book, config):
    configure, _ = agents
    configure(plan={"sort": ["slow"]}, slow_seconds=30)
    first = owner.post("/api/conversions/pdf", params={"title": "Saltmarsh"}, content=book, headers=PDF_HEADERS).json()
    queued = upload(owner, CAVES_PDF, title="Next").json()
    cancelled = owner.post(f"/api/conversions/{queued['id']}/cancel", json={})
    assert cancelled.status_code == 200 and cancelled.json()["status"] == "cancelled"
    assert [j["id"] for j in _queue(owner)["jobs"]] == [first["id"]]
    owner.post(f"/api/conversions/{first['id']}/cancel", json={})
    assert uploads(config) == []


def test_the_queue_routes_are_for_organisers(lan, storage):
    conversion = storage.conversions.create("pdf", "Saltmarsh", "ready", target={"thorough": True})
    assert lan.get("/api/conversions/queue").status_code == 401
    assert lan.put("/api/conversions/queue", json={"paused": True}).status_code == 401
    assert lan.post(f"/api/conversions/{conversion.id}/pause", json={}).status_code == 401
    assert storage.conversions.queue_paused() is False


def test_delve_stopping_mid_piece_records_the_stopped_session(config, storage, static_dir, agents, book):
    """U1: Delve stopped during tracing; the sessions it stopped must be in the folder's `stopped`, so the job's
    doubts say the cost leaves them out (review finding 7)."""
    configure, calls = agents
    configure(plan={"clean-1": ["stall"]}, slow_seconds=60)
    app = create_app(config, storage, thorough_registries(), static_dir=static_dir)
    with TestClient(app, base_url=BASE_URL, client=("127.0.0.1", 50000)) as client:
        started = client.post("/api/conversions/pdf", params={"title": "Saltmarsh"}, content=book, headers=PDF_HEADERS)
        folder = Path(started.json()["target"]["folder"])
        for _ in range(300):
            if any(c["piece"] == "clean-1" for c in calls()):
                break
            time.sleep(0.05)
        time.sleep(1.0)  # the stalled session has said its message
    stopped = json.loads((folder / "state.json").read_text())["stopped"]
    assert [s["piece"] for s in stopped] == ["clean-1"]
    assert stopped[0]["tokens"]


# ----- generate in steps (DEL-134) -----


def test_a_request_is_scoped_before_it_is_generated(local, claude):
    claude.scope = {"scale": "campaign", "questions": [{"text": "How many levels?", "default": "Five."}]}

    response = local.post("/api/conversions/generate/scope", json={"request": "a sprawling dungeon"})

    assert response.status_code == 200, response.json()
    assert response.json() == {
        "scale": "campaign",
        "questions": [{"id": "s1", "text": "How many levels?", "default": "Five."}],
    }
    assert local.get("/api/conversions").json() == [], "scoping starts no job"
    assert local.post("/api/conversions/generate/scope", json={"request": " "}).status_code == 422


def test_a_scope_call_that_fails_is_502(local, claude):
    claude.fail_on = "scope"

    response = local.post("/api/conversions/generate/scope", json={"request": "a sprawling dungeon"})

    assert response.status_code == 502
    assert "couldn't be scoped" in str(response.json())


def test_a_request_goes_with_its_scale_and_answers(local):
    body = {
        "request": "a dungeon with kobolds",
        "scale": "module",
        "answers": [{"text": "Should Grik bargain?", "default": "He bargains.", "answer": "He fights."}],
    }
    started = local.post("/api/conversions/generate", json=body).json()

    done = ended(local, started["id"])
    assert done["status"] == "done", done
    assert done["questions"]["questions"][0] == {
        "id": "q1",
        "text": "Should Grik bargain?",
        "default": "He bargains.",
        "answer": "He fights.",
    }
    assert local.post("/api/conversions/generate", json={**body, "scale": "huge"}).status_code == 422
