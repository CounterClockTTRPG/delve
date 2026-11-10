"""Azure Blob Storage as an object store (cloud storage plan Task 2), over the Blob REST API with `httpx`: no SDK.

The credential is a container SAS URL, `https://<account>.blob.core.windows.net/<container>?sv=…&sp=…&sig=…`. The
query string is the secret: it goes on every request and nowhere else. `label` and `repr` show the container URL
without it, errors are Delve's own words with the HTTP status (an Azure error page may quote the request URL), and a
log filter on `httpx`'s logger hides the query of any URL that carries a signature.

The storage enforces the SAS's permissions: read+list reads, `c` creates a new blob but never overwrites one, `w` and
`d` overwrite and delete. A create is a Put Blob with `If-None-Match: *`; a body over `BLOCK_THRESHOLD` goes as Put
Block calls of `BLOCK_SIZE` and a Put Block List, which carries the create's precondition.
"""

from __future__ import annotations

import base64
import contextlib
import logging
import re
import xml.etree.ElementTree as ET
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from urllib.parse import parse_qs, quote, urlsplit

import httpx

from delve.cloud.store import TOO_LARGE, Exists, Listed, Missing, Refused, StoreError, read_within

API_VERSION = "2023-11-03"
BLOCK_THRESHOLD = 64 * 1024 * 1024
BLOCK_SIZE = 4 * 1024 * 1024

# A URL's query holding a SAS signature: everything from `?` to the end of the URL.
_SIGNED_QUERY = re.compile(r"\?[^\s\"'<>]*\bsig=[^\s\"'<>]*")


def _hide_sas(text: str) -> str:
    return _SIGNED_QUERY.sub("?(SAS hidden)", text)


class _HideSas(logging.Filter):
    """Hides the SAS in `httpx`'s request log ("HTTP Request: PUT https://…?sv=…&sig=…")."""

    def filter(self, record: logging.LogRecord) -> bool:
        if isinstance(record.msg, str) and "sig=" in record.msg:
            record.msg = _hide_sas(record.msg)
        if isinstance(record.args, tuple):
            record.args = tuple(_hide_sas(str(arg)) if "sig=" in str(arg) else arg for arg in record.args)
        return True


logging.getLogger("httpx").addFilter(_HideSas())


def parse_sas(sas_url: str) -> tuple[str, str]:
    """`(container_url, query)` of a container SAS URL. ValueError, in words that hold no credential, unless it is
    https, has no user name or password before its host, names a container and carries a signature (`sv` and
    `sig`)."""
    try:
        parts = urlsplit(sas_url.strip())
    except ValueError:
        raise ValueError("That isn't a SAS URL.") from None
    if parts.scheme != "https" or not parts.netloc:
        raise ValueError("A SAS URL starts with https://.")
    if "@" in parts.netloc:
        raise ValueError("A SAS URL holds no user name before its host.")
    container = parts.path.strip("/")
    if not container:
        # The storage account's "Blob service SAS URL" (an account SAS, `ss=` and `srt=`) ends at the host.
        if "ss" in parse_qs(parts.query):
            raise ValueError(
                "This is an account SAS URL, which names no container: put your container's name after the host "
                "(https://<account>.blob.core.windows.net/<container>?sv=…), or make a SAS for the container itself."
            )
        raise ValueError("The SAS URL doesn't name a container.")
    query = parse_qs(parts.query)
    if not query.get("sv") or not query.get("sig"):
        raise ValueError("The SAS URL has no signature (sv and sig).")
    return f"https://{parts.netloc}/{container}", parts.query


def sas_expiry(sas_url: str) -> str | None:
    """When the SAS stops working: its `se=` time as an ISO UTC timestamp, or None when it has none Delve can read."""
    try:
        se = parse_qs(urlsplit(sas_url.strip()).query).get("se", [""])[0]
        when = datetime.fromisoformat(se)
    except ValueError:
        return None
    if when.tzinfo is None:
        when = when.replace(tzinfo=UTC)
    return when.astimezone(UTC).isoformat(timespec="seconds")


def _check_name(name: str) -> str:
    parts = name.split("/")
    if not name or name.startswith("/") or "\\" in name or any(part in ("", ".", "..") for part in parts):
        raise StoreError("That object name isn't allowed.")
    return quote(name, safe="/")


class AzureBlobStore:
    """One container, reached with its SAS URL. The store owns its client, and `aclose` closes it."""

    def __init__(self, sas_url: str, *, client: httpx.AsyncClient) -> None:
        self._container, self._sas = parse_sas(sas_url)
        self._client = client
        self.label = self._container

    def __repr__(self) -> str:
        return f"AzureBlobStore({self.label!r})"

    def _blob_url(self, name: str, query: str = "") -> str:
        return f"{self._container}/{_check_name(name)}?{query}{self._sas}"

    async def _send(
        self, method: str, url: str, *, content: bytes | None = None, headers=None, stream: bool = False
    ) -> httpx.Response:
        """The answer to one request; with `stream`, its body unread, for the caller to read and close."""
        try:
            request = self._client.build_request(
                method, url, content=content, headers={"x-ms-version": API_VERSION, **(headers or {})}
            )
            response = await self._client.send(request, stream=stream)
        except Exception:  # noqa: BLE001 (httpx's errors, a closed client's RuntimeError: never the URL)
            raise StoreError("Azure isn't answering.") from None
        if response.status_code in (401, 403):
            raise Refused(f"Azure refused the credential ({response.status_code}).")
        return response

    @staticmethod
    def _fail(response: httpx.Response) -> StoreError:
        return StoreError(f"Azure answered {response.status_code}.")

    async def list(self, prefix: str = "") -> list[Listed]:
        listed: list[Listed] = []
        marker = ""
        seen: set[str] = set()
        while True:
            query = f"restype=container&comp=list&prefix={quote(prefix, safe='')}"
            if marker:
                query += f"&marker={quote(marker, safe='')}"
            response = await self._send("GET", f"{self._container}?{query}&{self._sas}")
            if response.status_code == 404:
                raise Missing("The container isn't there.")
            if response.status_code >= 400:
                raise self._fail(response)
            try:
                root = ET.fromstring(response.content)
                for blob in root.iter("Blob"):
                    modified = parsedate_to_datetime(blob.findtext("Properties/Last-Modified", ""))
                    listed.append(
                        Listed(
                            blob.findtext("Name", ""),
                            int(blob.findtext("Properties/Content-Length", "0")),
                            modified.astimezone(UTC).isoformat(timespec="seconds"),
                        )
                    )
            except (ET.ParseError, ValueError, TypeError):
                raise StoreError("Azure answered a listing Delve can't read.") from None
            marker = root.findtext("NextMarker") or ""
            if not marker:
                return sorted(listed, key=lambda item: item.name)
            if marker in seen:
                raise StoreError("Azure answered a listing Delve can't read.")
            seen.add(marker)

    async def get(self, name: str, *, limit: int | None = None) -> bytes:
        response = await self._send("GET", self._blob_url(name), stream=True)
        try:
            if response.status_code == 404:
                raise Missing("That object isn't there.")
            if response.status_code >= 400:
                raise self._fail(response)
            declared = response.headers.get("Content-Length", "")
            if limit is not None and declared.isdigit() and int(declared) > limit:
                raise StoreError(TOO_LARGE)
            try:
                return await read_within(response.aiter_bytes(), limit)
            except StoreError:
                raise
            except Exception:  # noqa: BLE001 (a body that broke while read)
                raise StoreError("Azure isn't answering.") from None
        finally:
            with contextlib.suppress(Exception):
                await response.aclose()

    async def create(self, name: str, data: bytes) -> None:
        try:
            await self._write(name, data, {"If-None-Match": "*"})
        except Refused:
            # A create-only SAS may be refused, rather than told 409, for a blob that is already there.
            if await self._exists(name):
                raise Exists("That object is already there.") from None
            raise

    async def put(self, name: str, data: bytes) -> None:
        await self._write(name, data, {})

    async def _write(self, name: str, data: bytes, precondition: dict[str, str]) -> None:
        if len(data) <= BLOCK_THRESHOLD:
            response = await self._send(
                "PUT", self._blob_url(name), content=data, headers={"x-ms-blob-type": "BlockBlob", **precondition}
            )
        else:
            ids = []
            for start in range(0, len(data), BLOCK_SIZE):
                block_id = base64.b64encode(f"{len(ids):08d}".encode()).decode()
                ids.append(block_id)
                url = self._blob_url(name, f"comp=block&blockid={quote(block_id, safe='')}&")
                block = await self._send("PUT", url, content=data[start : start + BLOCK_SIZE])
                if block.status_code >= 400:
                    raise self._fail(block)
            body = "".join(f"<Latest>{block_id}</Latest>" for block_id in ids)
            response = await self._send(
                "PUT",
                self._blob_url(name, "comp=blocklist&"),
                content=f'<?xml version="1.0" encoding="utf-8"?><BlockList>{body}</BlockList>'.encode(),
                headers={"Content-Type": "application/xml", **precondition},
            )
        if precondition and response.status_code in (409, 412):
            raise Exists("That object is already there.")
        if response.status_code >= 400:
            raise self._fail(response)

    async def _exists(self, name: str) -> bool:
        try:
            response = await self._send("HEAD", self._blob_url(name))
        except Refused:
            return False
        return response.status_code < 400

    async def delete(self, name: str) -> None:
        response = await self._send("DELETE", self._blob_url(name))
        if response.status_code == 404:
            raise Missing("That object isn't there.")
        if response.status_code >= 400:
            raise self._fail(response)

    async def aclose(self) -> None:
        await self._client.aclose()
