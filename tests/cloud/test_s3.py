"""The S3-compatible store (cloud storage plan Task 3): SigV4 over httpx, against an `httpx.MockTransport` fake S3 that
checks every request's signature, keeps objects in a dict, honours `If-None-Match: *` and pages its listings at 2.

Review Focus 2: an error page echoing the request, its signature or the secret never reaches an exception message, a
log or a repr."""

import asyncio
import hashlib
import logging
import re
import traceback
from datetime import UTC, datetime
from urllib.parse import parse_qs, unquote, urlsplit

import httpx
import pytest

from delve.cloud import s3
from delve.cloud.s3 import S3Store, sign
from delve.cloud.store import Exists, Missing, Refused, StoreError, probe

ENDPOINT = "https://acct.r2.cloudflarestorage.com"
BUCKET = "delve-library"
KEY_ID = "TESTKEYID"
SECRET = "SECRET-XYZZY-s3cr3t/key+value"


def run(coro):
    return asyncio.run(coro)


class FakeS3:
    """A bucket in a dict. Refuses (403) a request whose signature doesn't check out, and whatever `allow` leaves out:
    `allow` holds "list", "get", "create", "put" and "delete"."""

    def __init__(self, *, allow=("list", "get", "create", "put", "delete"), page=2):
        self.objects: dict[str, bytes] = {}
        self.uploads: dict[str, dict[int, bytes]] = {}
        self.allow = set(allow)
        self.page = page
        self.calls: list[tuple[str, str]] = []
        self.fail_with: int | None = None
        self.fail_body = ""

    def client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(transport=httpx.MockTransport(self.handle))

    def store(self) -> S3Store:
        return S3Store(ENDPOINT, BUCKET, KEY_ID, SECRET, client=self.client())

    def _signed(self, request: httpx.Request) -> bool:
        auth = request.headers.get("authorization", "")
        match = re.search(r"SignedHeaders=([^,]+)", auth)
        if not match or request.headers.get("x-amz-content-sha256") != hashlib.sha256(request.content).hexdigest():
            return False
        own = {"host", "x-amz-date", "x-amz-content-sha256"}
        headers = {name: request.headers[name] for name in match.group(1).split(";") if name not in own}
        now = datetime.strptime(request.headers["x-amz-date"], "%Y%m%dT%H%M%SZ").replace(tzinfo=UTC)
        expected = sign(
            request.method, str(request.url), headers, request.headers["x-amz-content-sha256"], KEY_ID, SECRET,
            "auto", now,
        )
        return expected["authorization"] == auth

    def handle(self, request: httpx.Request) -> httpx.Response:
        url = urlsplit(str(request.url))
        query = {key: values[0] for key, values in parse_qs(url.query, keep_blank_values=True).items()}
        bucket, _, key = url.path.lstrip("/").partition("/")
        key = unquote(key)
        self.calls.append((request.method, url.query))
        if self.fail_with:
            return httpx.Response(self.fail_with, text=self.fail_body)
        if bucket != BUCKET or not self._signed(request):
            return httpx.Response(403, text="<Error><Code>SignatureDoesNotMatch</Code></Error>")
        method = request.method
        if method == "GET" and not key:
            return self._list(query) if "list" in self.allow else httpx.Response(403)
        if method in ("GET", "HEAD"):
            if "get" not in self.allow:
                return httpx.Response(403)
            if key not in self.objects:
                return httpx.Response(404)
            return httpx.Response(200, content=self.objects[key] if method == "GET" else b"")
        if method == "POST" and "uploads" in query:
            upload_id = f"up{len(self.uploads)}"
            self.uploads[upload_id] = {}
            return httpx.Response(200, text=f"<InitiateMultipartUploadResult><UploadId>{upload_id}</UploadId>"
                                            "</InitiateMultipartUploadResult>")
        if method == "PUT" and "uploadId" in query:
            self.uploads[query["uploadId"]][int(query["partNumber"])] = request.content
            return httpx.Response(200, headers={"ETag": f'"etag{query["partNumber"]}"'})
        if method == "POST" and "uploadId" in query:
            parts = self.uploads.pop(query["uploadId"])
            return self._write(request, key, b"".join(parts[number] for number in sorted(parts)))
        if method == "DELETE" and "uploadId" in query:
            self.uploads.pop(query["uploadId"], None)
            return httpx.Response(204)
        if method == "PUT":
            return self._write(request, key, request.content)
        if method == "DELETE":
            if "delete" not in self.allow:
                return httpx.Response(403)
            self.objects.pop(key, None)
            return httpx.Response(204)
        return httpx.Response(400)

    def _write(self, request, key, data):
        creating = request.headers.get("if-none-match") == "*"
        if ("create" if creating else "put") not in self.allow:
            return httpx.Response(403)
        if creating and key in self.objects:
            return httpx.Response(412)
        self.objects[key] = data
        return httpx.Response(200)

    def _list(self, query):
        prefix = query.get("prefix", "")
        names = sorted(name for name in self.objects if name.startswith(prefix))
        start = int(query.get("continuation-token", "0") or 0)
        chunk = names[start:start + self.page]
        more = start + self.page < len(names)
        contents = "".join(
            f"<Contents><Key>{name}</Key><Size>{len(self.objects[name])}</Size>"
            f"<LastModified>2026-10-26T04:00:00.000Z</LastModified></Contents>"
            for name in chunk
        )
        token = f"<NextContinuationToken>{start + self.page}</NextContinuationToken>" if more else ""
        body = (
            '<ListBucketResult xmlns="http://s3.amazonaws.com/doc/2006-03-01/">'
            f"<IsTruncated>{'true' if more else 'false'}</IsTruncated>{contents}{token}</ListBucketResult>"
        )
        return httpx.Response(200, text=body)


def test_sign_matches_the_aws_example():
    headers = sign(
        "GET",
        "https://examplebucket.s3.amazonaws.com/test.txt",
        {"Range": "bytes=0-9"},
        hashlib.sha256(b"").hexdigest(),
        "AKIAIOSFODNN7EXAMPLE",
        "wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY",
        "us-east-1",
        datetime(2013, 5, 24, tzinfo=UTC),
    )
    assert headers["authorization"] == (
        "AWS4-HMAC-SHA256 Credential=AKIAIOSFODNN7EXAMPLE/20130524/us-east-1/s3/aws4_request,"
        "SignedHeaders=host;range;x-amz-content-sha256;x-amz-date,"
        "Signature=f0e8bdb87c964420e857bd35b5d6ed310bd44f0170aba48dd91039c6036bdb41"
    )
    assert headers["x-amz-date"] == "20130524T000000Z"
    assert headers["x-amz-content-sha256"] == hashlib.sha256(b"").hexdigest()


def test_round_trip_against_a_fake_s3():
    fake = FakeS3()
    store = fake.store()

    async def go():
        await store.create("lib/entry one/v1/module.dscn", b"zip bytes")
        await store.put("lib/entry one/entry.json", b"{}")
        await store.put("lib/entry one/entry.json", b'{"v": 2}')
        listed = await store.list("lib/")
        got = await store.get("lib/entry one/entry.json")
        await store.delete("lib/entry one/v1/module.dscn")
        with pytest.raises(Missing):
            await store.get("lib/entry one/v1/module.dscn")
        with pytest.raises(Missing):
            await store.delete("lib/entry one/v1/module.dscn")
        await store.aclose()
        return listed, got

    listed, got = run(go())
    assert [(item.name, item.size) for item in listed] == [
        ("lib/entry one/entry.json", 8),
        ("lib/entry one/v1/module.dscn", 9),
    ]
    assert listed[0].modified == "2026-10-26T04:00:00.000Z"
    assert got == b'{"v": 2}'
    assert list(fake.objects) == ["lib/entry one/entry.json"]


def test_create_over_an_existing_key_raises_exists():
    fake = FakeS3()
    store = fake.store()
    run(store.create("a", b"one"))
    with pytest.raises(Exists):
        run(store.create("a", b"two"))
    assert fake.objects["a"] == b"one"


def test_list_follows_the_continuation_token():
    fake = FakeS3(page=2)
    fake.objects = {f"k/{n}": b"x" for n in range(5)} | {"other": b"y"}
    listed = run(fake.store().list("k/"))
    assert [item.name for item in listed] == [f"k/{n}" for n in range(5)]
    assert sum(1 for method, query in fake.calls if method == "GET" and "list-type=2" in query) == 3


def test_a_large_body_goes_in_parts(monkeypatch):
    monkeypatch.setattr(s3, "MULTIPART_THRESHOLD", 10)
    monkeypatch.setattr(s3, "PART_SIZE", 4)
    fake = FakeS3()
    store = fake.store()
    run(store.create("big", b"0123456789abcdef"))
    assert fake.objects["big"] == b"0123456789abcdef"
    assert sum(1 for method, query in fake.calls if method == "PUT" and "partNumber" in query) == 4
    with pytest.raises(Exists):
        run(store.create("big", b"another long body"))
    assert fake.objects["big"] == b"0123456789abcdef"
    assert fake.uploads == {}
    run(store.put("big", b"fedcba9876543210"))
    assert fake.objects["big"] == b"fedcba9876543210"


def test_refusals_and_errors_are_delves_own_words():
    fake = FakeS3(allow=("list",))
    store = fake.store()
    with pytest.raises(Refused):
        run(store.get("a"))
    fake.fail_with = 503
    with pytest.raises(StoreError, match=r"^The S3 store answered 503\.$"):
        run(store.list())

    def down(request):
        raise httpx.ConnectError("connection refused", request=request)

    offline = S3Store(ENDPOINT, BUCKET, KEY_ID, SECRET, client=httpx.AsyncClient(transport=httpx.MockTransport(down)))
    with pytest.raises(StoreError, match=r"^The S3 store isn't answering\.$") as caught:
        run(offline.get("a"))
    assert caught.value.__cause__ is None and caught.value.__suppress_context__


def test_the_secret_never_reaches_an_error_or_repr(caplog):
    caplog.set_level(logging.DEBUG)
    seen: list[str] = []

    def echo(request: httpx.Request) -> httpx.Response:
        seen.append(request.headers["authorization"])
        return httpx.Response(500, text=f"<Error>{request.url} {request.headers} {SECRET}</Error>")

    store = S3Store(ENDPOINT, BUCKET, KEY_ID, SECRET, client=httpx.AsyncClient(transport=httpx.MockTransport(echo)))
    with pytest.raises(StoreError) as caught:
        run(store.put("a", b"data"))
    error = caught.value
    assert str(error) == "The S3 store answered 500."
    signature = seen[0].rpartition("Signature=")[2]
    for text in (str(error), repr(error), repr(store), str(store), store.label, caplog.text):
        assert SECRET not in text
        assert signature not in text
    assert store.label == f"{ENDPOINT}/{BUCKET}"


@pytest.mark.parametrize(
    ("allow", "right"),
    [
        (("list", "get"), "read"),
        (("list", "get", "create", "delete"), "publish"),
        (("list", "get", "create", "put", "delete"), "manage"),
    ],
)
def test_probe_reads_the_right(allow, right):
    fake = FakeS3(allow=allow)
    assert run(probe(fake.store())) == right
    assert fake.objects == {}


def test_probe_of_a_bucket_it_cannot_list_is_none():
    assert run(probe(FakeS3(allow=()).store())) is None


def test_the_fake_checks_the_signature():
    fake = FakeS3()
    wrong = S3Store(ENDPOINT, BUCKET, KEY_ID, "not the secret", client=fake.client())
    with pytest.raises(Refused):
        run(wrong.list())
    fake.objects["a b/c+d"] = b"x"
    assert run(fake.store().get("a b/c+d")) == b"x"


def test_a_name_with_a_dot_segment_is_refused():
    with pytest.raises(StoreError, match="isn't allowed"):
        run(FakeS3().store().get("a/../b"))


def test_a_conditional_conflict_on_create_raises_exists():
    """Two conditional writes at once: S3 answers 409 ConditionalRequestConflict to one, which is "already there", so
    the library retries as the next version."""
    fake = FakeS3()
    store = S3Store(ENDPOINT, BUCKET, KEY_ID, SECRET, client=httpx.AsyncClient(transport=httpx.MockTransport(
        lambda request: httpx.Response(409, text="<Error><Code>ConditionalRequestConflict</Code></Error>")
    )))
    with pytest.raises(Exists):
        run(store.create("a", b"one"))
    with pytest.raises(StoreError) as error:
        run(store.put("a", b"one"))
    assert not isinstance(error.value, Exists), "a 409 on an overwrite is no create's conflict"
    assert fake.objects == {}


class Chunks:
    """An object's body as a stream of chunks, counting how many were read."""

    def __init__(self, chunks: list[bytes]) -> None:
        self.chunks, self.read = chunks, 0

    async def __aiter__(self):
        for chunk in self.chunks:
            self.read += 1
            yield chunk


def streaming(body: Chunks, headers: dict[str, str] | None = None) -> S3Store:
    def answer(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=body, headers=headers)

    return S3Store(ENDPOINT, BUCKET, KEY_ID, SECRET, client=httpx.AsyncClient(transport=httpx.MockTransport(answer)))


def test_get_within_its_limit_reads_the_object():
    fake = FakeS3()
    store = fake.store()
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


def test_get_of_an_object_declared_too_large_reads_none_of_it():
    body = Chunks([b"x" * 6, b"x" * 6])
    with pytest.raises(StoreError) as caught:
        run(streaming(body, {"Content-Length": "12"}).get("a", limit=10))
    assert str(caught.value) == "It is larger than Delve takes."
    assert body.read == 0


def assert_unanswered(caught: pytest.ExceptionInfo, caplog: pytest.LogCaptureFixture) -> None:
    assert str(caught.value) == "The S3 store isn't answering."
    assert caught.value.__cause__ is None and caught.value.__suppress_context__
    rendered = "".join(traceback.format_exception(caught.value))
    for text in (rendered, caplog.text):
        assert SECRET not in text and "Signature=" not in text and "acct.r2" not in text


@pytest.mark.parametrize("error", [RuntimeError, ValueError, OSError, KeyError])
def test_any_failure_to_send_is_the_store_not_answering(caplog, error):
    caplog.set_level(logging.DEBUG)

    def broken(request: httpx.Request) -> httpx.Response:
        raise error(f"it broke on {request.url} {request.headers['authorization']} {SECRET}")

    store = S3Store(ENDPOINT, BUCKET, KEY_ID, SECRET, client=httpx.AsyncClient(transport=httpx.MockTransport(broken)))
    for call in (store.list(), store.get("a"), store.put("a", b"x"), store.delete("a")):
        with pytest.raises(StoreError) as caught:
            run(call)
        assert_unanswered(caught, caplog)


def test_a_closed_client_is_the_store_not_answering(caplog):
    caplog.set_level(logging.DEBUG)
    store = FakeS3().store()
    run(store.aclose())
    for call in (store.list(), store.get("a"), store.create("a", b"x")):
        with pytest.raises(StoreError) as caught:
            run(call)
        assert_unanswered(caught, caplog)


def test_a_body_that_breaks_while_read_is_the_store_not_answering(caplog):
    class Breaks:
        async def __aiter__(self):
            yield b"x"
            raise RuntimeError(f"stream broke, {ENDPOINT} {SECRET}")

    def answer(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=Breaks())

    store = S3Store(ENDPOINT, BUCKET, KEY_ID, SECRET, client=httpx.AsyncClient(transport=httpx.MockTransport(answer)))
    with pytest.raises(StoreError) as caught:
        run(store.get("a"))
    assert_unanswered(caught, caplog)


def test_a_listing_whose_token_repeats_stops():
    calls = []

    def loops(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        if len(calls) > 5:
            raise AssertionError("the listing never stopped")
        return httpx.Response(200, text=(
            '<ListBucketResult xmlns="http://s3.amazonaws.com/doc/2006-03-01/"><IsTruncated>true</IsTruncated>'
            "<NextContinuationToken>again</NextContinuationToken></ListBucketResult>"
        ))

    store = S3Store(ENDPOINT, BUCKET, KEY_ID, SECRET, client=httpx.AsyncClient(transport=httpx.MockTransport(loops)))
    with pytest.raises(StoreError) as caught:
        run(store.list())
    assert str(caught.value) == "The S3 store's answer couldn't be read."
    assert len(calls) == 2
