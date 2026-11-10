"""Comments on the PDF form, through the API (table voice and fixes Task F1): `comments=` on the upload is kept on the
job, at most `COMMENTS_MAX` characters (422 over, before the book is taken in), and the access log drops its value."""

import logging

from delve.conversions.runner import COMMENTS_MAX
from tests.web.test_conversions_api import (  # noqa: F401 (fixtures)
    CAVES_PDF,
    PDF_HEADERS,
    agents,
    book,
    claude,
    ended,
    owner,
    registries,
    thorough_app,
    thorough_registries,
    upload,
    uploads,
)

COMMENTS = "The room key starts on page 40; keep the book's spelling."


def test_comments_stored_on_the_job(local, storage):
    started = upload(local, CAVES_PDF, comments=COMMENTS)
    assert started.status_code == 202, started.json()
    assert started.json()["comments"] == COMMENTS
    done = ended(local, started.json()["id"])
    assert done["status"] == "done" and done["comments"] == COMMENTS
    assert storage.conversions.get(done["id"]).comments == COMMENTS


def test_no_comments_are_empty(local):
    done = ended(local, upload(local, CAVES_PDF).json()["id"])
    assert done["comments"] == ""


def test_comments_over_2000_is_422(local, config):
    assert COMMENTS_MAX == 2000
    assert upload(local, CAVES_PDF, comments="x" * COMMENTS_MAX).status_code == 202
    ended(local, local.get("/api/conversions").json()[0]["id"])
    refused = upload(local, CAVES_PDF, comments="x" * (COMMENTS_MAX + 1))
    assert refused.status_code == 422
    assert "2000" in refused.json()["error"]
    assert uploads(config) == [], "a refused start takes in no book"


def test_a_thorough_job_keeps_its_comments(owner, book):  # noqa: F811
    params = {"title": "Saltmarsh", "comments": COMMENTS}
    started = owner.post("/api/conversions/pdf", params=params, content=book, headers=PDF_HEADERS)
    assert started.status_code == 202, started.json()
    done = ended(owner, started.json()["id"])
    assert done["status"] == "done", done["error"]
    assert done["thorough"] is True and done["comments"] == COMMENTS


def test_access_log_drops_comments():
    from delve.web.app import AccessLogRedactor

    path = "/api/conversions/pdf?title=Caves&comments=Room%207%27s%20trap%20is%20a%20pit&mode=ready"
    args = ("1.2.3.4", "POST", path, "1.1", 202)
    record = logging.LogRecord("uvicorn.access", logging.INFO, "", 0, '%s - "%s %s HTTP/%s" %d', args, None)
    assert AccessLogRedactor().filter(record) is True
    message = record.getMessage()
    assert "trap" not in message and "comments=…" in message
    assert "title=Caves" in message and "mode=ready" in message
    last = logging.LogRecord("uvicorn.access", logging.INFO, "", 0, "%s %s", ("POST", "/x?comments=secret"), None)
    AccessLogRedactor().filter(last)
    assert last.getMessage() == "POST /x?comments=…"
