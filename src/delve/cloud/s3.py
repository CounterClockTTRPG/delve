"""An S3-compatible store (cloud storage plan Task 3): Cloudflare R2, and also Backblaze B2, AWS S3 and MinIO, over
their S3 API with SigV4 signing on httpx, no SDK.

URLs are path-style, `{endpoint}/{bucket}/{key}`, and every request is signed with `x-amz-content-sha256` set. The
secret access key only ever goes into the HMAC: it is in no URL, no header, no message and no repr, and an answer's
body is never read into an error (an error page may quote the request). `label` is `{endpoint}/{bucket}`.

`create` is a PUT with `If-None-Match: *`, which R2 and S3 refuse with 412 when the key is there, and with 409 when
another conditional write races it: both are `Exists`. S3 answers 204 for a delete of a missing key, so `delete` asks
with HEAD first. A body over `MULTIPART_THRESHOLD` goes as a multipart upload of `PART_SIZE` parts; a create's
precondition goes on its `CompleteMultipartUpload`, and an upload that doesn't complete is aborted.
"""

from __future__ import annotations

import contextlib
import hashlib
import hmac
import xml.etree.ElementTree as ET
from collections.abc import Mapping
from datetime import UTC, datetime
from urllib.parse import parse_qsl, quote, urlencode, urlsplit

import httpx

from delve.cloud.store import TOO_LARGE, Exists, Listed, Missing, Refused, StoreError, read_within

MULTIPART_THRESHOLD = 64 * 1024 * 1024
PART_SIZE = 8 * 1024 * 1024

_ALGORITHM = "AWS4-HMAC-SHA256"
_NS = "{http://s3.amazonaws.com/doc/2006-03-01/}"
_EMPTY_SHA256 = hashlib.sha256(b"").hexdigest()


def _encode(text: str, safe: str = "-_.~") -> str:
    return quote(text, safe=safe)


def _hmac(key: bytes, text: str) -> bytes:
    return hmac.new(key, text.encode(), hashlib.sha256).digest()


def sign(
    method: str,
    url: str,
    headers: Mapping[str, str],
    payload_sha256: str,
    access_key_id: str,
    secret: str,
    region: str,
    now: datetime,
) -> dict[str, str]:
    """`headers` (names lowercased) with `host`, `x-amz-date`, `x-amz-content-sha256` and the SigV4 `authorization`
    for service `s3`. Every header given is signed. `url`'s path is taken as already percent-encoded."""
    parsed = urlsplit(url)
    target = httpx.URL(url)
    host = target.host if target.port is None else f"{target.host}:{target.port}"
    amz_date = now.astimezone(UTC).strftime("%Y%m%dT%H%M%SZ")
    day = amz_date[:8]
    signed = {name.lower(): " ".join(str(value).split()) for name, value in headers.items()}
    signed |= {"host": host, "x-amz-date": amz_date, "x-amz-content-sha256": payload_sha256}
    names = sorted(signed)
    query = "&".join(
        f"{_encode(key)}={_encode(value)}" for key, value in sorted(parse_qsl(parsed.query, keep_blank_values=True))
    )
    canonical = "\n".join([
        method.upper(),
        parsed.path or "/",
        query,
        "".join(f"{name}:{signed[name]}\n" for name in names),
        ";".join(names),
        payload_sha256,
    ])
    scope = f"{day}/{region}/s3/aws4_request"
    to_sign = "\n".join([_ALGORITHM, amz_date, scope, hashlib.sha256(canonical.encode()).hexdigest()])
    key = _hmac(_hmac(_hmac(_hmac(f"AWS4{secret}".encode(), day), region), "s3"), "aws4_request")
    signature = hmac.new(key, to_sign.encode(), hashlib.sha256).hexdigest()
    signed["authorization"] = (
        f"{_ALGORITHM} Credential={access_key_id}/{scope},SignedHeaders={';'.join(names)},Signature={signature}"
    )
    return signed


class S3Store:
    """A bucket on an S3-compatible endpoint."""

    def __init__(
        self,
        endpoint: str,
        bucket: str,
        access_key_id: str,
        secret_access_key: str,
        *,
        region: str = "auto",
        client: httpx.AsyncClient,
    ) -> None:
        self._endpoint = endpoint.rstrip("/")
        self._bucket = bucket
        self._access_key_id = access_key_id
        self._secret = secret_access_key
        self._region = region
        self._client = client
        self.label = f"{self._endpoint}/{bucket}"

    def __repr__(self) -> str:
        return f"S3Store({self.label!r})"

    def _url(self, name: str = "", query: str = "") -> str:
        url = f"{self._endpoint}/{_encode(self._bucket)}"
        if name:
            # httpx resolves dot segments, so a name with one would reach (and sign) another key.
            if name.startswith("/") or any(part in ("", ".", "..") for part in name.split("/")):
                raise StoreError("That object name isn't allowed.")
            url += "/" + _encode(name, safe="/-_.~")
        return f"{url}?{query}" if query else url

    async def _send(
        self, method: str, url: str, *, body: bytes = b"", headers: Mapping[str, str] | None = None,
        stream: bool = False,
    ) -> httpx.Response:
        """The answer to one request; with `stream`, its body unread, for the caller to read and close."""
        try:
            signed = sign(
                method, url, headers or {}, hashlib.sha256(body).hexdigest() if body else _EMPTY_SHA256,
                self._access_key_id, self._secret, self._region, datetime.now(UTC),
            )
            request = self._client.build_request(method, url, content=body, headers=signed)
            return await self._client.send(request, stream=stream)
        except Exception:  # noqa: BLE001 (httpx's errors, a closed client's RuntimeError: never the URL)
            raise StoreError("The S3 store isn't answering.") from None

    @staticmethod
    def _check(response: httpx.Response, *, missing: bool = False, exists: bool = False) -> None:
        status = response.status_code
        if status < 400:
            return
        if status in (401, 403):
            raise Refused("The S3 store refused the credential.")
        if missing and status == 404:
            raise Missing("That object isn't there.")
        # 412 when the key is there; 409 (ConditionalRequestConflict) when another conditional write races this one.
        if exists and status in (409, 412):
            raise Exists("That object is already there.")
        raise StoreError(f"The S3 store answered {status}.")

    @staticmethod
    def _xml(response: httpx.Response) -> ET.Element:
        try:
            return ET.fromstring(response.content)
        except ET.ParseError:
            raise StoreError("The S3 store's answer couldn't be read.") from None

    @staticmethod
    def _text(element: ET.Element, tag: str) -> str:
        found = element.find(_NS + tag)
        if found is None:
            found = element.find(tag)
        return (found.text or "") if found is not None else ""

    async def list(self, prefix: str = "") -> list[Listed]:
        listed: list[Listed] = []
        token = ""
        seen: set[str] = set()
        while True:
            params = {"list-type": "2", "prefix": prefix}
            if token:
                params["continuation-token"] = token
            query = urlencode(sorted(params.items()), quote_via=quote, safe="-_.~")
            response = await self._send("GET", self._url(query=query))
            self._check(response)
            root = self._xml(response)
            for item in [*root.findall(_NS + "Contents"), *root.findall("Contents")]:
                try:
                    size = int(self._text(item, "Size") or 0)
                except ValueError:
                    raise StoreError("The S3 store's answer couldn't be read.") from None
                listed.append(Listed(self._text(item, "Key"), size, self._text(item, "LastModified")))
            token = self._text(root, "NextContinuationToken")
            if self._text(root, "IsTruncated") != "true" or not token:
                break
            if token in seen:
                raise StoreError("The S3 store's answer couldn't be read.")
            seen.add(token)
        return sorted(listed, key=lambda item: item.name)

    async def get(self, name: str, *, limit: int | None = None) -> bytes:
        response = await self._send("GET", self._url(name), stream=True)
        try:
            self._check(response, missing=True)
            declared = response.headers.get("content-length", "")
            if limit is not None and declared.isdigit() and int(declared) > limit:
                raise StoreError(TOO_LARGE)
            try:
                return await read_within(response.aiter_bytes(), limit)
            except StoreError:
                raise
            except Exception:  # noqa: BLE001 (a body that broke while read)
                raise StoreError("The S3 store isn't answering.") from None
        finally:
            with contextlib.suppress(Exception):
                await response.aclose()

    async def create(self, name: str, data: bytes) -> None:
        await self._write(name, data, {"if-none-match": "*"})

    async def put(self, name: str, data: bytes) -> None:
        await self._write(name, data, {})

    async def _write(self, name: str, data: bytes, condition: dict[str, str]) -> None:
        url = self._url(name)
        if len(data) <= MULTIPART_THRESHOLD:
            response = await self._send("PUT", url, body=data, headers=condition)
            self._check(response, exists=bool(condition))
            return
        response = await self._send("POST", self._url(name, "uploads"))
        self._check(response)
        upload_id = self._text(self._xml(response), "UploadId")
        if not upload_id:
            raise StoreError("The S3 store's answer couldn't be read.")
        upload = urlencode({"uploadId": upload_id}, quote_via=quote, safe="-_.~")
        completed = False
        try:
            parts = []
            for number, start in enumerate(range(0, len(data), PART_SIZE), start=1):
                part = urlencode({"partNumber": number, "uploadId": upload_id}, quote_via=quote, safe="-_.~")
                response = await self._send("PUT", self._url(name, part), body=data[start:start + PART_SIZE])
                self._check(response)
                parts.append(f"<Part><PartNumber>{number}</PartNumber><ETag>{response.headers.get('etag', '')}"
                             "</ETag></Part>")
            body = f"<CompleteMultipartUpload>{''.join(parts)}</CompleteMultipartUpload>".encode()
            response = await self._send("POST", self._url(name, upload), body=body, headers=condition)
            self._check(response, exists=bool(condition))
            # S3 can answer 200 to a CompleteMultipartUpload and put its error in the body.
            if response.content.strip() and self._xml(response).tag.endswith("Error"):
                raise StoreError("The S3 store didn't finish the upload.")
            completed = True
        finally:
            if not completed:
                with contextlib.suppress(StoreError):
                    await self._send("DELETE", self._url(name, upload))

    async def delete(self, name: str) -> None:
        url = self._url(name)
        self._check(await self._send("HEAD", url), missing=True)
        self._check(await self._send("DELETE", url), missing=True)

    async def aclose(self) -> None:
        await self._client.aclose()
