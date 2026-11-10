"""Serving the built single-page app: its files, and `index.html` for every client route.

The SPA answers whatever no route does, so it is the app's 404 handler: an `/api` path, or anything but a GET, stays a
JSON 404, and routes added later never sit behind a catch-all. A build file that isn't there (`/assets/…`, one an
older build named, asked for by a page open since before a deploy) is a plain 404, not `index.html`: a script that
comes back as HTML fails as a confusing MIME error, and the page reloads itself on a clean failure (`staleBuild.ts`).

A build file's name carries its content's hash, so it is cached for a year as immutable (DEL-167); a script, style
sheet or other text file goes gzipped to a browser that takes it, compressed once per file; and an `If-None-Match`
naming its ETag gets a 304. `index.html` is never cached, so a deploy's new file names reach the next page load.
"""

from __future__ import annotations

import gzip
from functools import lru_cache
from mimetypes import guess_type
from pathlib import Path

from fastapi import FastAPI, Request
from starlette.exceptions import HTTPException
from starlette.responses import FileResponse, HTMLResponse, JSONResponse, Response

DEFAULT_STATIC_DIR = Path(__file__).parent / "static"

MISSING_BUILD = """<!doctype html>
<meta charset="utf-8">
<title>Delve</title>
<p>Delve is running, but its web app has not been built. Run <code>make build</code>, then reload this page.</p>
"""


IMMUTABLE = "public, max-age=31536000, immutable"
COMPRESSIBLE = frozenset({".js", ".mjs", ".css", ".svg", ".json", ".map", ".html", ".txt", ".wasm"})
"""The build files worth gzipping; pictures and fonts are compressed already."""


def is_api(path: str) -> bool:
    return path == "/api" or path.startswith("/api/")


def is_asset(path: str) -> bool:
    return path.startswith("/assets/")


def install_spa(app: FastAPI, static_dir: Path, error_response) -> None:
    root = static_dir.resolve()

    @app.exception_handler(404)
    async def not_found(request: Request, exc: HTTPException) -> Response:
        if "endpoint" in request.scope:  # a route said 404 itself
            return error_response(request, exc)
        if is_api(request.url.path) or request.method not in ("GET", "HEAD"):
            return JSONResponse({"error": "not found"}, status_code=404)
        return _file_or_index(request, root, request.url.path)


@lru_cache(maxsize=256)
def _gzipped(path: Path, mtime_ns: int) -> bytes:
    """`path`'s bytes gzipped; the file's modification time in the key makes a rebuilt file compress again."""
    return gzip.compress(path.read_bytes(), compresslevel=6, mtime=0)


def _asset(request: Request, path: Path) -> Response:
    info = path.stat()
    etag = f'"{info.st_mtime_ns:x}-{info.st_size:x}"'
    headers = {"Cache-Control": IMMUTABLE, "ETag": etag, "Vary": "Accept-Encoding"}
    if etag in request.headers.get("if-none-match", ""):
        return Response(status_code=304, headers=headers)
    if request.method == "GET" and path.suffix in COMPRESSIBLE and "gzip" in request.headers.get("accept-encoding", ""):
        headers["Content-Encoding"] = "gzip"
        media_type = guess_type(path.name)[0] or "application/octet-stream"
        return Response(_gzipped(path, info.st_mtime_ns), media_type=media_type, headers=headers)
    return FileResponse(path, headers=headers)


def _file_or_index(request: Request, root: Path, path: str) -> Response:
    candidate = (root / path.lstrip("/")).resolve()
    if candidate.is_relative_to(root) and candidate.is_file():
        return _asset(request, candidate) if is_asset(path) else FileResponse(candidate)
    if is_asset(path):
        return Response("Not found", status_code=404, media_type="text/plain")
    index = root / "index.html"
    if index.is_file():
        return FileResponse(index, headers={"Cache-Control": "no-cache"})
    return HTMLResponse(MISSING_BUILD)
