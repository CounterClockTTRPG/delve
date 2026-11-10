"""The map language without a stored map: parse, render and check a source. Organisers only.

Includes resolve against a module's `library` maps first, then the built-in libraries, and nothing else: never a file
on disk (`delve.maps.sources`). `parse_map` is how every route turns a module's (or a revision's) map into a parsed
`DungeonMap`.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel
from starlette.concurrency import run_in_threadpool

from delve.domain.modules import Module
from delve.maps.dsl import (
    Diagnostic,
    DmapError,
    DungeonMap,
    build_graph,
    render,
    validate,
)
from delve.maps.sources import library_sources, parse_source
from delve.web.auth import Organiser

router = APIRouter()


# ----- answers -----


def parse_error(error: DmapError) -> HTTPException:
    return HTTPException(status_code=400, detail={"error": error.message, "line": error.line, "column": error.column})


def diagnostic_json(diagnostic: Diagnostic) -> dict[str, Any]:
    return {
        "severity": diagnostic.severity,
        "message": diagnostic.message,
        "line": diagnostic.line,
        "column": diagnostic.column,
        "end_line": diagnostic.end_line,
        "end_column": diagnostic.end_column,
    }


def render_json(dmap: DungeonMap, renderer: str | None) -> dict[str, Any]:
    """`{svg, diagnostics}` for a parsed map. Raises `HTTPException` 400 for an unknown renderer."""
    diagnostics = validate(dmap)
    try:
        svg = render(dmap, renderer)
    except KeyError as error:
        raise HTTPException(status_code=400, detail=str(error.args[0]) if error.args else "unknown renderer") from None
    except DmapError as error:
        raise parse_error(error) from None
    return {"svg": svg, "diagnostics": [diagnostic_json(d) for d in diagnostics]}


def connectivity_json(dmap: DungeonMap) -> dict[str, Any]:
    """Per node, whether a door touches it: an edge to another node or a boundary exit (dungml's pathing check)."""
    graph = build_graph(dmap)
    nodes = []
    for node_id, node in graph.nodes.items():
        connections = []
        # Every door touching the node (either side), so the far side of a one-way door still reads as connected.
        for edge in graph.edges:
            if node_id not in (edge.a, edge.b):
                continue
            direction = ("out" if node_id == edge.a else "in") if edge.one_way else "both"
            connections.append(
                {"to": edge.other(node_id), "type": edge.type, "state": edge.state, "direction": direction}
            )
        for exit in graph.boundary_exits(node_id):
            connections.append({"to": "(exterior)", "type": exit.type, "state": exit.state, "direction": "out"})
        nodes.append(
            {
                "id": node_id,
                "kind": node.kind,
                "name": node.name,
                "connected": bool(connections),
                "doors": len(connections),
                "connections": connections,
            }
        )
    return {"nodes": nodes}


# ----- routes -----


class SourceIn(BaseModel):
    source: str
    module_id: str | None = None


class RenderIn(SourceIn):
    renderer: str | None = None


def module_libraries(request: Request, module_id: str | None) -> dict[str, str]:
    if module_id is None:
        return {}
    module: Module | None = request.app.state.storage.modules.get(module_id)
    if module is None:
        raise HTTPException(status_code=404, detail="No such module.")
    return library_sources(module.maps)


async def parsed(source: str, libraries: Mapping[str, str]) -> DungeonMap:
    """`source` parsed off the event loop; a parse error becomes a 400."""
    try:
        return await run_in_threadpool(parse_source, source, libraries)
    except DmapError as error:
        raise parse_error(error) from None


@router.post("/api/dsl/parse")
async def parse_route(request: Request, principal: Organiser, body: SourceIn) -> dict:
    """The parsed model as JSON."""
    dmap = await parsed(body.source, module_libraries(request, body.module_id))
    return {"map": dmap.model_dump(mode="json")}


@router.post("/api/dsl/render")
async def render_route(request: Request, principal: Organiser, body: RenderIn) -> dict:
    dmap = await parsed(body.source, module_libraries(request, body.module_id))
    return await run_in_threadpool(render_json, dmap, body.renderer)


@router.post("/api/dsl/connectivity")
async def connectivity_route(request: Request, principal: Organiser, body: SourceIn) -> dict:
    dmap = await parsed(body.source, module_libraries(request, body.module_id))
    return await run_in_threadpool(connectivity_json, dmap)
