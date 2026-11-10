"""A module's attachments (plan 3 Task 4, spec §8.2): upload, describe, delete and serve their bytes. Organisers only.

An attachment's entry is in the module's source and its bytes are in the blob store, by sha256, linked to the module
as `attachment`. Deleting one takes it out of the working source only: its bytes stay, since a pinned revision may
still show them, and the refs to it become `missing-attachment` warnings. Every change publishes `modules` with
`{id}`.

The upload's body is the file. The guard has let only `ATTACHMENT_TYPES` through; the bytes must also be what the type
says (`type_matches`), and an SVG must have no active content (`svg_is_active`), else 400. Nothing is stored for a
refused upload.

A picture can be cut (DEL-40): turned by 90° steps and cut to a box, or split into pieces, each a box of it. The
attachment keeps its original in its `cut`; the cut picture is its own bytes, all the players are ever served. Every
cut is taken from the original, so cutting again doesn't compound, and Reset gives the original back. A split's first
piece keeps the id; the others are new attachments after it. Only the organiser's `?original=true` serves the original.
"""

from __future__ import annotations

import dataclasses
from typing import Literal

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field
from starlette.concurrency import run_in_threadpool
from starlette.responses import Response

from delve.images.thumbs import THUMB_TYPE, card_thumbnail
from delve.modules.cuts import CUTTABLE, CutRefused, cut_picture
from delve.modules.dscn import ALLOWED_TYPES, slugify
from delve.modules.dscn.media import svg_is_active, type_matches
from delve.modules.source import ATTACHMENT, Attachment, Audience, Cut, ModuleSource, load_source, save_source
from delve.web.guard import ATTACHMENT_TYPES, UPLOAD_LIMIT
from delve.web.routes.module_source import editing, save, source_of
from delve.web.routes.modules import Organiser, changed, get_module

router = APIRouter()

SVG = "image/svg+xml"


def attachment_response(data: bytes, media_type: str) -> Response:
    """An attachment's bytes as served, here and to the players: with `nosniff`, so the browser keeps to the type, and
    for an SVG a sandboxing CSP, so it runs nothing even when opened on its own."""
    headers = {"X-Content-Type-Options": "nosniff"}
    if media_type == SVG:
        headers["Content-Security-Policy"] = "sandbox"
    return Response(data, media_type=media_type, headers=headers)


BannerSize = Literal["card"]
"""A banner asked for a card's list (DEL-234): its small copy, not the picture."""


async def banner_picture(request: Request, blob: str | None, mime: str | None, size: BannerSize | None) -> Response:
    """A banner's picture by its blob: the picture, or with `size` its card's copy (the picture itself while none can
    be made). Read again on every view, as painting again replaces it, but its ETag (the blob, and the size) answers
    304 to a browser that has it. 404 for none."""
    if blob is None:
        raise HTTPException(status_code=404, detail="No banner.")
    tag = f'"{blob}{"-" + size if size else ""}"'
    if tag in {t.strip() for t in request.headers.get("if-none-match", "").split(",")}:
        return Response(status_code=304, headers={"ETag": tag, "Cache-Control": "no-cache"})
    data = request.app.state.storage.blobs.get(blob)
    if data is None:
        raise HTTPException(status_code=404, detail="No banner.")
    media_type = mime or "image/png"
    if size == "card":
        small = await run_in_threadpool(card_thumbnail, request.app.state.config.data_dir, blob, data)
        if small is not None:
            data, media_type = small, THUMB_TYPE
    response = attachment_response(data, media_type)
    response.headers["Cache-Control"] = "no-cache"
    response.headers["ETag"] = tag
    return response


class AttachmentPatch(BaseModel):
    description: str | None = None
    audience: Literal["gm", "player"] | None = None
    reviewed: bool = False
    """True: the organiser has looked at a conversion's proposed cut, which is no longer marked `proposed`."""


class PieceIn(BaseModel):
    box: tuple[float, float, float, float] | None = None
    """`[x, y, w, h]` in fractions of the turned original; None for all of it."""
    id: str | None = None
    """A new piece's id, made unique; the first piece's is always the attachment's."""
    description: str | None = None
    audience: Literal["gm", "player"] | None = None


class CutIn(BaseModel):
    rotate: int
    pieces: list[PieceIn] = Field(min_length=1, max_length=12)
    proposed: bool = False
    """True: the cut is proposed (a crop pass over the module's pictures, DEL-293), until the organiser's Looks right."""


def _attachment(source: ModuleSource, asset_id: str) -> Attachment:
    found = source.attachment(asset_id)
    if found is None:
        raise HTTPException(status_code=404, detail="No such attachment.")
    return found


def _new_id(source: ModuleSource, name: str) -> str:
    """The file name's slug without its extension, made unique with `-2`, `-3`…"""
    stem = name.rpartition(".")[0] if name.rfind(".") > 0 else name
    return _unique(slugify(stem), {a.id for a in source.attachments})


def _unique(base: str, taken: set[str]) -> str:
    candidate, n = base, 1
    while candidate in taken:
        n += 1
        candidate = f"{base}-{n}"
    return candidate


@router.post("/api/modules/{module_id}/assets", status_code=201)
async def upload_attachment(request: Request, principal: Organiser, module_id: str, name: str) -> dict:
    get_module(request, module_id)
    media_type = request.headers.get("content-type", "").split(";")[0].strip().lower()
    if media_type not in ATTACHMENT_TYPES or media_type not in ALLOWED_TYPES:
        raise HTTPException(status_code=415, detail="This kind of file can't be an attachment.")
    data = bytearray()
    async for chunk in request.stream():
        data.extend(chunk)
        if len(data) > UPLOAD_LIMIT:
            raise HTTPException(status_code=413, detail=f"An attachment may be at most {UPLOAD_LIMIT} bytes.")
    if not type_matches(media_type, bytes(data)):
        raise HTTPException(status_code=400, detail=f"The file isn't the {media_type} it says it is.")
    if media_type == SVG and svg_is_active(bytes(data)):
        raise HTTPException(status_code=400, detail="An SVG with scripts, event handlers or links outside is refused.")

    storage = request.app.state.storage
    source = source_of(request, module_id)
    sha = storage.blobs.put(bytes(data), media_type)
    attachment = Attachment(_new_id(source, name), media_type, sha, len(data), "", "gm")
    with storage.transaction():
        storage.blobs.link(module_id, ATTACHMENT, sha)
        save_source(storage, module_id, dataclasses.replace(source, attachments=[*source.attachments, attachment]))
    changed(request, module_id)
    return dataclasses.asdict(attachment)


@router.patch("/api/modules/{module_id}/assets/{asset_id}")
def describe_attachment(
    request: Request, principal: Organiser, module_id: str, asset_id: str, body: AttachmentPatch
) -> dict:
    source = source_of(request, module_id)
    attachment = _attachment(source, asset_id)
    attachment = dataclasses.replace(
        attachment,
        description=attachment.description if body.description is None else body.description,
        audience=body.audience or attachment.audience,
        cut=dataclasses.replace(attachment.cut, proposed=False) if body.reviewed and attachment.cut else attachment.cut,
    )
    attachments = [attachment if a.id == asset_id else a for a in source.attachments]
    save(request, module_id, dataclasses.replace(source, attachments=attachments))
    return dataclasses.asdict(attachment)


@router.delete("/api/modules/{module_id}/assets/{asset_id}", status_code=204)
def delete_attachment(request: Request, principal: Organiser, module_id: str, asset_id: str) -> Response:
    source = source_of(request, module_id)
    _attachment(source, asset_id)
    attachments = [a for a in source.attachments if a.id != asset_id]
    save(request, module_id, dataclasses.replace(source, attachments=attachments))
    return Response(status_code=204)


@router.get("/api/modules/{module_id}/assets/{asset_id}")
def attachment_bytes(
    request: Request, principal: Organiser, module_id: str, asset_id: str, original: bool = False
) -> Response:
    """The attachment's bytes, or with `original` the original a cut picture is cut from (its own when it has none)."""
    attachment = _attachment(source_of(request, module_id), asset_id)
    sha, media_type = attachment.sha256, attachment.type
    if original and attachment.cut is not None:
        sha, media_type = attachment.cut.original, attachment.cut.original_type
    data = request.app.state.storage.blobs.get(sha)
    if data is None:
        raise HTTPException(status_code=404, detail="No such attachment.")
    return attachment_response(data, media_type)


@router.post("/api/modules/{module_id}/assets/{asset_id}/cut")
async def cut_attachment(request: Request, principal: Organiser, module_id: str, asset_id: str, body: CutIn) -> dict:
    """Cut the picture into `pieces`, each a box of its original turned by `rotate`; the answer is the pieces, the first
    being the attachment itself. 422 for a cut that can't be made, and nothing is stored."""
    storage = request.app.state.storage
    source = source_of(request, module_id)
    attachment = _attachment(source, asset_id)
    previous = attachment.cut
    if previous is not None:
        original, original_type, original_size = previous.original, previous.original_type, previous.original_size
    else:
        original, original_type, original_size = attachment.sha256, attachment.type, attachment.size
    if original_type not in CUTTABLE:
        raise HTTPException(status_code=422, detail="Only a PNG, JPEG, WebP or GIF picture can be cut.")
    data = storage.blobs.get(original)
    if data is None:
        raise HTTPException(status_code=404, detail="No such attachment.")
    try:
        made = [await run_in_threadpool(cut_picture, data, original_type, body.rotate, p.box) for p in body.pieces]
    except CutRefused as refused:
        raise HTTPException(status_code=422, detail=str(refused)) from None
    shas = [storage.blobs.put(cut_bytes, cut_type) for cut_bytes, cut_type in made]
    cut = Cut(original, original_type, original_size, body.rotate, proposed=body.proposed)
    # Decoding took a while: the source is read again to save, under the module's edit lock, so an edit made
    # meanwhile is kept (DEL-166).
    pieces = await run_in_threadpool(_save_cut, request, module_id, asset_id, cut, body.pieces, made, shas)
    changed(request, module_id)
    return {"attachments": [dataclasses.asdict(p) for p in pieces]}


def _save_cut(
    request: Request,
    module_id: str,
    asset_id: str,
    cut: Cut,
    asked: list[PieceIn],
    made: list[tuple[bytes, str]],
    shas: list[str],
) -> list[Attachment]:
    """Save the pieces of `asset_id` cut from `cut.original`, in the source as it is now; 404 if the attachment went."""
    storage = request.app.state.storage
    with editing(module_id):
        source = load_source(storage, module_id)
        attachment = source.attachment(asset_id)
        current = attachment and (attachment.cut.original if attachment.cut else attachment.sha256)
        if attachment is None or current != cut.original:
            raise HTTPException(status_code=404, detail="That picture changed while it was being cut.")
        taken = {a.id for a in source.attachments}
        pieces: list[Attachment] = []
        for n, (piece, (cut_bytes, cut_type), sha) in enumerate(zip(asked, made, shas, strict=True)):
            if n == 0:
                id = asset_id
            else:
                id = _unique(slugify(piece.id) if piece.id else asset_id, taken)
                taken.add(id)
            audience: Audience = piece.audience or attachment.audience
            pieces.append(
                dataclasses.replace(
                    attachment,
                    id=id,
                    type=cut_type,
                    sha256=sha,
                    size=len(cut_bytes),
                    description=attachment.description if piece.description is None else piece.description,
                    audience=audience,
                    cut=dataclasses.replace(cut, box=piece.box),
                )
            )
        attachments: list[Attachment] = []
        for a in source.attachments:
            attachments.extend(pieces if a.id == asset_id else [a])
        with storage.transaction():
            for sha in {cut.original, *shas}:
                storage.blobs.link(module_id, ATTACHMENT, sha)
            save_source(storage, module_id, dataclasses.replace(source, attachments=attachments))
    return pieces


@router.delete("/api/modules/{module_id}/assets/{asset_id}/cut")
def reset_cut(request: Request, principal: Organiser, module_id: str, asset_id: str) -> dict:
    """The picture back to its whole original; the other pieces of a split stay as they are. 404 for one not cut."""
    source = source_of(request, module_id)
    attachment = _attachment(source, asset_id)
    if attachment.cut is None:
        raise HTTPException(status_code=404, detail="That picture isn't cut.")
    cut = attachment.cut
    attachment = dataclasses.replace(
        attachment, type=cut.original_type, sha256=cut.original, size=cut.original_size, cut=None
    )
    attachments = [attachment if a.id == asset_id else a for a in source.attachments]
    save(request, module_id, dataclasses.replace(source, attachments=attachments))
    return dataclasses.asdict(attachment)
