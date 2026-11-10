"""The Azure Blob store (cloud storage plan Task 2), against an `httpx.MockTransport` fake Azure: never a real call.
The fake keeps blobs in a dict, honours `If-None-Match: *`, pages its listing, and refuses with 403 what the SAS's
`sp` doesn't allow, as Azure does. A SAS echoed in an error page never reaches a message, a log or a repr."""

import asyncio
import base64
import logging
import traceback
import xml.etree.ElementTree as ET
from datetime import UTC, datetime
from email.utils import format_datetime
from urllib.parse import parse_qs

import httpx
import pytest

from delve.cloud import azure
from delve.cloud.azure import AzureBlobStore, parse_sas, sas_expiry
from delve.cloud.store import PROBE_PREFIX, Exists, Missing, Refused, StoreError, probe, probe_gap

CONTAINER = "https://delveacct.blob.core.windows.net/delve"
SIG = "SECRET-SIG%2Bxyzzy%3D"


def sas_url(sp: str = "racwdl", *, se: str = "2026-12-31T00:00:00Z") -> str:
    return f"{CONTAINER}?sv=2023-11-03&ss=b&srt=co&sp={sp}&se={se}&spr=https&sig={SIG}"


def run(coro):
    return asyncio.run(coro)


class FakeAzure:
    """Blob storage for one container. `sp` is the SAS's permissions: r read, a/c create, w write, d delete, l list."""

    def __init__(self, sp: str = "racwdl", *, page: int = 2) -> None:
        self.sp, self.page = sp, page
        self.blobs: dict[str, bytes] = {}
        self.blocks: dict[str, bytes] = {}
        self.requests: list[httpx.Request] = []
        self.fail: int | None = None

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        assert request.headers["x-ms-version"] == "2023-11-03"
        query = parse_qs(request.url.query.decode(), keep_blank_values=True)
        assert query["sig"] == ["SECRET-SIG+xyzzy="]
        if self.fail:
            return httpx.Response(self.fail, text=f"<Error><Message>Server busy for {request.url}</Message></Error>")
        path = request.url.path
        assert path.startswith("/delve")
        name = path.removeprefix("/delve").removeprefix("/")
        comp = query.get("comp", [""])[0]
        if request.method == "GET" and query.get("restype") == ["container"] and comp == "list":
            return self.list(query) if "l" in self.sp else self.refuse()
        if request.method in ("GET", "HEAD"):
            if "r" not in self.sp:
                return self.refuse()
            if name not in self.blobs:
                return httpx.Response(404)
            body = self.blobs[name] if request.method == "GET" else b""
            return httpx.Response(200, content=body, headers={"Content-Length": str(len(self.blobs[name]))})
        if request.method == "DELETE":
            if "d" not in self.sp:
                return self.refuse()
            if self.blobs.pop(name, None) is None:
                return httpx.Response(404)
            return httpx.Response(202)
        if request.method == "PUT" and comp == "block":
            if not {"c", "w"} & set(self.sp):
                return self.refuse()
            self.blocks[query["blockid"][0]] = request.content
            return httpx.Response(201)
        if request.method == "PUT" and comp == "blocklist":
            ids = [item.text for item in ET.fromstring(request.content).findall("Latest")]
            return self.write(request, name, b"".join(self.blocks.pop(i) for i in ids))
        if request.method == "PUT":
            assert request.headers["x-ms-blob-type"] == "BlockBlob"
            return self.write(request, name, request.content)
        return httpx.Response(400)

    def write(self, request: httpx.Request, name: str, data: bytes) -> httpx.Response:
        exists = name in self.blobs
        # `c` writes a new blob and never overwrites one; `w` does both.
        if "w" not in self.sp and not ("c" in self.sp and not exists):
            return self.refuse()
        if exists and request.headers.get("If-None-Match") == "*":
            return httpx.Response(409, text="<Error><Code>BlobAlreadyExists</Code></Error>")
        self.blobs[name] = data
        return httpx.Response(201)

    def list(self, query: dict[str, list[str]]) -> httpx.Response:
        prefix = query.get("prefix", [""])[0]
        names = sorted(name for name in self.blobs if name.startswith(prefix))
        marker = query.get("marker", [""])[0]
        start = names.index(marker) if marker else 0
        shown, rest = names[start : start + self.page], names[start + self.page :]
        modified = format_datetime(datetime(2026, 10, 26, 6, 0, tzinfo=UTC), usegmt=True)
        blobs = "".join(
            f"<Blob><Name>{name}</Name><Properties><Last-Modified>{modified}</Last-Modified>"
            f"<Content-Length>{len(self.blobs[name])}</Content-Length></Properties></Blob>"
            for name in shown
        )
        next_marker = rest[0] if rest else ""
        xml = (
            '<?xml version="1.0" encoding="utf-8"?>'
            f'<EnumerationResults ContainerName="{CONTAINER}"><Prefix>{prefix}</Prefix>'
            f"<Blobs>{blobs}</Blobs><NextMarker>{next_marker}</NextMarker></EnumerationResults>"
        )
        return httpx.Response(200, content=xml.encode(), headers={"Content-Type": "application/xml"})

    def refuse(self) -> httpx.Response:
        return httpx.Response(403, text="<Error><Code>AuthorizationPermissionMismatch</Code></Error>")


def store_on(fake: FakeAzure, sp: str | None = None) -> AzureBlobStore:
    client = httpx.AsyncClient(transport=httpx.MockTransport(fake))
    return AzureBlobStore(sas_url(sp or fake.sp), client=client)


def test_round_trip_create_get_list_delete():
    fake = FakeAzure()
    store = store_on(fake)
    run(store.create("ins_1/modules/mod 1.dmod", b"module"))
    run(store.put("ins_1/index.json", b"{}"))
    assert run(store.get("ins_1/modules/mod 1.dmod")) == b"module"
    listed = run(store.list("ins_1/"))
    assert [(item.name, item.size) for item in listed] == [("ins_1/index.json", 2), ("ins_1/modules/mod 1.dmod", 6)]
    assert listed[0].modified == "2026-10-26T06:00:00+00:00"
    run(store.delete("ins_1/index.json"))
    assert [item.name for item in run(store.list())] == ["ins_1/modules/mod 1.dmod"]
    with pytest.raises(Missing):
        run(store.get("ins_1/index.json"))
    with pytest.raises(Missing):
        run(store.delete("ins_1/index.json"))
    assert store.label == CONTAINER


def test_create_over_an_existing_blob_raises_exists():
    fake = FakeAzure()
    store = store_on(fake)
    run(store.create("lib/e/v1/module.dscn", b"one"))
    with pytest.raises(Exists):
        run(store.create("lib/e/v1/module.dscn", b"two"))
    assert fake.blobs["lib/e/v1/module.dscn"] == b"one"
    run(store.put("lib/e/v1/module.dscn", b"two"))
    assert fake.blobs["lib/e/v1/module.dscn"] == b"two"


def test_create_over_an_existing_blob_with_a_create_sas_raises_exists():
    """A create-only SAS may get a 403 rather than a 409 for a blob that is there: Delve looks, and says Exists."""
    fake = FakeAzure("rcl")
    fake.blobs["lib/e/v1/module.dscn"] = b"one"
    store = store_on(fake)
    with pytest.raises(Exists):
        run(store.create("lib/e/v1/module.dscn", b"two"))
    with pytest.raises(Refused):
        run(store.put("lib/e/v1/module.dscn", b"two"))
    assert fake.blobs["lib/e/v1/module.dscn"] == b"one"


def test_list_follows_the_next_marker():
    fake = FakeAzure(page=2)
    for name in ("m/e", "m/a", "m/d", "m/b", "m/c", "n/z"):
        fake.blobs[name] = b"x"
    store = store_on(fake)
    assert [item.name for item in run(store.list("m/"))] == ["m/a", "m/b", "m/c", "m/d", "m/e"]
    pages = [r for r in fake.requests if "comp=list" in str(r.url)]
    assert len(pages) == 3
    assert "marker=m%2Fc" in str(pages[1].url) or "marker=m/c" in str(pages[1].url)


def test_a_large_body_goes_in_blocks(monkeypatch):
    monkeypatch.setattr(azure, "BLOCK_THRESHOLD", 10)
    monkeypatch.setattr(azure, "BLOCK_SIZE", 10)
    fake = FakeAzure()
    store = store_on(fake)
    data = b"0123456789abcdefghijKLMNO"
    run(store.create("big.dcmp", data))
    comps = [parse_qs(r.url.query.decode()).get("comp", [""])[0] for r in fake.requests if r.method == "PUT"]
    assert comps == ["block", "block", "block", "blocklist"]
    assert fake.blobs["big.dcmp"] == data
    ids = [parse_qs(r.url.query.decode())["blockid"][0] for r in fake.requests if "comp=block&" in str(r.url)]
    assert len({len(base64.b64decode(i)) for i in ids}) == 1
    blocklist = next(r for r in fake.requests if "comp=blocklist" in str(r.url))
    assert blocklist.headers["If-None-Match"] == "*"
    with pytest.raises(Exists):
        run(store.create("big.dcmp", data))
    run(store.put("big.dcmp", data[::-1]))
    assert fake.blobs["big.dcmp"] == data[::-1]


def test_a_small_body_is_one_put():
    fake = FakeAzure()
    run(store_on(fake).create("small", b"x"))
    (put,) = [r for r in fake.requests if r.method == "PUT"]
    assert put.headers["If-None-Match"] == "*" and "comp=" not in str(put.url)


def test_parse_sas_refuses_http_and_a_missing_signature():
    assert parse_sas(sas_url()) == (CONTAINER, sas_url().split("?", 1)[1])
    assert parse_sas(sas_url().replace("/delve?", "/delve/?"))[0] == CONTAINER
    refused = [
        sas_url().replace("https://", "http://"),
        f"{CONTAINER}?sv=2023-11-03&sp=rl",
        f"{CONTAINER}?sp=rl&sig={SIG}",
        f"https://delveacct.blob.core.windows.net/?sv=2023-11-03&sig={SIG}",
        sas_url().replace("https://", "https://someone@"),
        sas_url().replace("https://", "https://someone:SECRET-PW@"),
        "not a url",
    ]
    for url in refused:
        with pytest.raises(ValueError) as caught:
            parse_sas(url)
        assert "SECRET" not in str(caught.value) and "sig=" not in str(caught.value)


def test_parse_sas_explains_an_account_sas_url():
    # The storage account's "Blob service SAS URL" names no container: the words say how to fix it.
    with pytest.raises(ValueError) as caught:
        parse_sas(f"https://delveacct.blob.core.windows.net/?sv=2023-11-03&ss=b&srt=sco&sp=rwdlac&sig={SIG}")
    words = str(caught.value)
    assert "account SAS URL" in words and "container's name" in words
    assert "SECRET" not in words and "sig=" not in words


def test_sas_expiry_reads_se():
    assert sas_expiry(sas_url()) == "2026-12-31T00:00:00+00:00"
    assert sas_expiry(sas_url(se="2027-01-15")) == "2027-01-15T00:00:00+00:00"
    assert sas_expiry(sas_url(se="2026-12-31T10%3A30%3A00Z")) == "2026-12-31T10:30:00+00:00"
    assert sas_expiry(f"{CONTAINER}?sv=2023-11-03&sig={SIG}") is None
    assert sas_expiry(sas_url(se="whenever")) is None


def test_an_error_page_echoing_the_sas_never_reaches_the_message(caplog):
    caplog.set_level(logging.DEBUG)
    fake = FakeAzure()
    store = store_on(fake)
    run(store.put("a", b"x"))
    fake.fail = 500
    with pytest.raises(StoreError) as caught:
        run(store.get("a"))
    error = caught.value
    assert str(error) == "Azure answered 500."
    rendered = "".join(traceback.format_exception(error))
    for text in (rendered, repr(error), repr(store), store.label, caplog.text):
        assert "sig=" not in text and "SECRET-SIG" not in text
    assert "HTTP Request" in caplog.text  # httpx did log the call, without its SAS


def test_an_unreachable_azure_never_names_the_sas(caplog):
    caplog.set_level(logging.DEBUG)

    def down(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError(f"Connection refused for {request.url}", request=request)

    store = AzureBlobStore(sas_url(), client=httpx.AsyncClient(transport=httpx.MockTransport(down)))
    with pytest.raises(StoreError) as caught:
        run(store.list())
    assert str(caught.value) == "Azure isn't answering."
    rendered = "".join(traceback.format_exception(caught.value))
    assert "SECRET-SIG" not in rendered and "SECRET-SIG" not in caplog.text


def test_refusals_and_a_missing_container():
    store = store_on(FakeAzure("r"))
    with pytest.raises(Refused):
        run(store.list())

    def gone(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404, text=f"ContainerNotFound {request.url}")

    store = AzureBlobStore(sas_url(), client=httpx.AsyncClient(transport=httpx.MockTransport(gone)))
    with pytest.raises(Missing) as caught:
        run(store.list())
    assert "SECRET" not in str(caught.value)
    # A container that isn't there isn't a refused List: the probe says which.
    store = AzureBlobStore(sas_url(), client=httpx.AsyncClient(transport=httpx.MockTransport(gone)))
    assert run(probe_gap(store)) == (None, "container")


def test_a_name_escaping_the_container_is_refused():
    fake = FakeAzure()
    store = store_on(fake)
    for name in ("../x", "/x", "a/../../x", ""):
        with pytest.raises(StoreError):
            run(store.put(name, b"x"))
    assert fake.requests == []


def test_probe_on_a_read_list_sas_is_read():
    fake = FakeAzure("rl")
    assert run(probe(store_on(fake))) == "read"
    assert fake.blobs == {}


def test_probe_on_a_create_sas_is_publish():
    fake = FakeAzure("rcl")
    assert run(probe(store_on(fake))) == "publish"
    # A create SAS can't delete, so its probe object stays: one small blob under the probe prefix.
    assert [name.startswith(PROBE_PREFIX) for name in fake.blobs] == [True]


def test_probe_on_a_full_sas_is_manage():
    fake = FakeAzure("racwdl")
    assert run(probe(store_on(fake))) == "manage"
    assert fake.blobs == {}


def test_probe_gap_names_what_the_sas_was_refused():
    assert run(probe_gap(store_on(FakeAzure("rl")))) == ("read", "create")
    assert run(probe_gap(store_on(FakeAzure("rcdl")))) == ("publish", "write")
    assert run(probe_gap(store_on(FakeAzure("rcwl")))) == ("publish", "delete")
    assert run(probe_gap(store_on(FakeAzure("racwdl")))) == ("manage", None)
    assert run(probe_gap(store_on(FakeAzure("rcw")))) == (None, "list")


def test_probe_on_a_sas_without_list_is_none():
    assert run(probe(store_on(FakeAzure("rcw")))) is None


def test_aclose_closes_its_client():
    """Each store owns the client `open_store` builds for it (lead's ruling for Task 4)."""
    client = httpx.AsyncClient(transport=httpx.MockTransport(FakeAzure()))
    store = AzureBlobStore(sas_url(), client=client)
    run(store.aclose())
    assert client.is_closed


class Chunks:
    """A blob's body as a stream of chunks, counting how many were read."""

    def __init__(self, chunks: list[bytes]) -> None:
        self.chunks, self.read = chunks, 0

    async def __aiter__(self):
        for chunk in self.chunks:
            self.read += 1
            yield chunk


def streaming(body: Chunks, headers: dict[str, str] | None = None) -> AzureBlobStore:
    def answer(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=body, headers=headers)

    return AzureBlobStore(sas_url(), client=httpx.AsyncClient(transport=httpx.MockTransport(answer)))


def test_get_within_its_limit_reads_the_blob():
    fake = FakeAzure()
    store = store_on(fake)
    run(store.put("a", b"x" * 10))
    assert run(store.get("a", limit=10)) == b"x" * 10
    with pytest.raises(Missing):
        run(store.get("b", limit=10))


def test_get_past_its_limit_stops_reading():
    body = Chunks([b"x" * 6, b"x" * 6, b"x" * 6, b"x" * 6])
    with pytest.raises(StoreError) as caught:
        run(streaming(body).get("a", limit=10))
    assert str(caught.value) == "It is larger than Delve takes."
    assert body.read == 2, "the rest is never read"


def test_get_of_a_blob_declared_too_large_reads_none_of_it():
    body = Chunks([b"x" * 6, b"x" * 6])
    with pytest.raises(StoreError) as caught:
        run(streaming(body, {"Content-Length": "12"}).get("a", limit=10))
    assert str(caught.value) == "It is larger than Delve takes."
    assert body.read == 0


def assert_unanswered(caught: pytest.ExceptionInfo, caplog: pytest.LogCaptureFixture) -> None:
    assert str(caught.value) == "Azure isn't answering."
    assert caught.value.__cause__ is None and caught.value.__suppress_context__
    rendered = "".join(traceback.format_exception(caught.value))
    for text in (rendered, caplog.text):
        assert "SECRET-SIG" not in text and "sig=" not in text and "delveacct" not in text


@pytest.mark.parametrize("error", [RuntimeError, ValueError, OSError, KeyError])
def test_any_failure_to_send_is_azure_not_answering(caplog, error):
    caplog.set_level(logging.DEBUG)

    def broken(request: httpx.Request) -> httpx.Response:
        raise error(f"it broke on {request.url}")

    store = AzureBlobStore(sas_url(), client=httpx.AsyncClient(transport=httpx.MockTransport(broken)))
    for call in (store.list(), store.get("a"), store.put("a", b"x"), store.delete("a")):
        with pytest.raises(StoreError) as caught:
            run(call)
        assert_unanswered(caught, caplog)


def test_a_closed_client_is_azure_not_answering(caplog):
    caplog.set_level(logging.DEBUG)
    store = store_on(FakeAzure())
    run(store.aclose())
    for call in (store.list(), store.get("a"), store.create("a", b"x")):
        with pytest.raises(StoreError) as caught:
            run(call)
        assert_unanswered(caught, caplog)


def test_a_body_that_breaks_while_read_is_azure_not_answering(caplog):
    class Breaks:
        async def __aiter__(self):
            yield b"x"
            raise RuntimeError(f"stream broke, {sas_url()}")

    def answer(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=Breaks())

    store = AzureBlobStore(sas_url(), client=httpx.AsyncClient(transport=httpx.MockTransport(answer)))
    with pytest.raises(StoreError) as caught:
        run(store.get("a"))
    assert_unanswered(caught, caplog)


def test_a_listing_whose_marker_repeats_stops():
    fake = FakeAzure(page=1)
    fake.blobs.update({"a": b"x", "b": b"x"})
    calls = []

    def loops(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        if len(calls) > 5:
            raise AssertionError("the listing never stopped")
        xml = ('<?xml version="1.0" encoding="utf-8"?><EnumerationResults><Blobs></Blobs>'
               "<NextMarker>again</NextMarker></EnumerationResults>")
        return httpx.Response(200, content=xml.encode())

    store = AzureBlobStore(sas_url(), client=httpx.AsyncClient(transport=httpx.MockTransport(loops)))
    with pytest.raises(StoreError) as caught:
        run(store.list())
    assert str(caught.value) == "Azure answered a listing Delve can't read."
    assert len(calls) == 2
