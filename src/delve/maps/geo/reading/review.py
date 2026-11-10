"""The review of a reading: what was read from a picture, the colour clusters the organiser maps to terrain once, and
the doubts, each with the reading and its alternatives.

A doubtful reading is never kept silently. Every doubt is listed, in `DOUBT_KINDS` order and then by position, and
its feature carries the id of its first open doubt in `props["doubt"]` until it is resolved. A cluster without a
terrain (nor `OUTSIDE`) keeps its cells `.`, which no mode crosses and no seat sees as land; `unmapped` lists those
clusters, and accept is refused while there are any (Task 12).

The geo map always shows the current choice: at first each doubt's reading (its likely alternative), then whatever
`apply_review` decided. A decision can be changed later, except after a feature was dropped."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field, replace
from typing import Any

from delve.maps.geo.model import GeoFeature, GeoMap
from delve.maps.geo.terrain import NO_TERRAIN, PLACE_KINDS, TERRAIN_CLASSES, TERRAIN_LETTERS

DOUBT_KINDS = (
    "cluster-unmapped",
    "water-kind-guessed",
    "river-flow-guessed",
    "label-unpaired",
    "symbol-unlabelled",
    "label-uncertain",
    "kind-guessed",
    "cell-mixed",
    "river-no-mouth",
)
"""The kinds of doubt, in the order the review lists them."""

OUTSIDE = "outside"
"""A cluster that isn't the map (the frame, the legend, the margin): its cells have no terrain. It counts as mapped."""

KEEP = "keep"
DROP = "drop"
REVERSE = "reverse"
_NOT_DROPPED = ("cluster-unmapped", "water-kind-guessed", "cell-mixed")
"""The doubts about colours and cells, which have nothing to drop."""
LABEL_CHOICES = ("place", "river-name", "region-name", DROP)
"""What an unpaired label can be: a place (at the nearest symbol, or at the label), a river's or a region's name, or
nothing."""


def river_id(n: int) -> str:
    """The id of the reading's `n`th river (from 0)."""
    return f"river-{n + 1}"


@dataclass(frozen=True)
class Doubt:
    id: str
    kind: str
    """One of `DOUBT_KINDS`."""
    ref: str
    """What it is about: a feature's id (an unpaired label's: the place or region it makes, or the river it names),
    a cluster's id as text, or `cell:<index>`."""
    message: str
    reading: str
    """What was read: a terrain, a kind, a label's text, or `keep` for a river's direction."""
    alternatives: list[str]
    """The choices it offers, the likely one first; `keep` is the reading."""
    resolved: bool = False
    choice: str | None = None
    """The decision taken, once resolved."""
    data: dict[str, Any] = field(default_factory=dict)
    """What the decision needs: `at` (its position, km), and per kind the label's text and where a place would go."""

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "kind": self.kind,
            "ref": self.ref,
            "message": self.message,
            "reading": self.reading,
            "alternatives": list(self.alternatives),
            "resolved": self.resolved,
            "choice": self.choice,
            "data": self.data,
        }

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any]) -> Doubt:
        return cls(
            id=str(raw["id"]),
            kind=str(raw["kind"]),
            ref=str(raw["ref"]),
            message=str(raw.get("message", "")),
            reading=str(raw.get("reading", "")),
            alternatives=[str(a) for a in raw.get("alternatives", [])],
            resolved=bool(raw.get("resolved", False)),
            choice=raw.get("choice"),
            data=dict(raw.get("data") or {}),
        )

    def offers(self, choice: str) -> bool:
        """One of its `alternatives`; else `keep` (its reading), where it has one, and `drop` for a doubt about a
        feature."""
        if choice in self.alternatives:
            return True
        if choice == KEEP:
            return self.kind != "cluster-unmapped" or bool(self.reading)
        return choice == DROP and self.kind not in _NOT_DROPPED


@dataclass(frozen=True)
class ClusterReading:
    id: int
    colour: tuple[int, int, int]
    cells: list[int]
    """The cells that take their terrain from it (the water bodies' cells take theirs from the water)."""
    suggestion: str | None
    """Claude's terrain class for it, or `OUTSIDE`."""
    terrain: str | None
    """The class it is mapped to, `OUTSIDE`, or None while it is unmapped."""

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "colour": list(self.colour),
            "cells": list(self.cells),
            "suggestion": self.suggestion,
            "terrain": self.terrain,
        }

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any]) -> ClusterReading:
        return cls(
            id=int(raw["id"]),
            colour=(int(raw["colour"][0]), int(raw["colour"][1]), int(raw["colour"][2])),
            cells=[int(c) for c in raw.get("cells", [])],
            suggestion=raw.get("suggestion"),
            terrain=raw.get("terrain"),
        )


@dataclass(frozen=True)
class Reading:
    geo: GeoMap
    clusters: list[ClusterReading]
    doubts: list[Doubt]

    def to_dict(self) -> dict[str, Any]:
        """The review's JSON (the map's `reading`); the geo map is stored on its own, as the map's `geo`."""
        return {
            "clusters": [c.to_dict() for c in self.clusters],
            "doubts": [d.to_dict() for d in self.doubts],
        }

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any], geo: GeoMap) -> Reading:
        return cls(
            geo,
            [ClusterReading.from_dict(c) for c in raw.get("clusters", [])],
            [Doubt.from_dict(d) for d in raw.get("doubts", [])],
        )

    def doubt(self, doubt_id: str) -> Doubt | None:
        return next((d for d in self.doubts if d.id == doubt_id), None)


def unmapped(reading: Reading) -> list[int]:
    """The clusters with neither a terrain nor `OUTSIDE`."""
    return [c.id for c in reading.clusters if c.terrain is None]


def order_doubts(doubts: list[Doubt]) -> list[Doubt]:
    """By kind as `DOUBT_KINDS` lists them, then by position (top to bottom, left to right), then by what they are
    about; each gets its id from its place in that order, `<kind>-<n>`."""

    def key(d: Doubt) -> tuple[int, float, float, str]:
        at = d.data.get("at")
        y, x = (float(at[1]), float(at[0])) if at else (0.0, 0.0)
        return (DOUBT_KINDS.index(d.kind), y, x, d.ref)

    out: list[Doubt] = []
    count: dict[str, int] = {}
    for d in sorted(doubts, key=key):
        count[d.kind] = count.get(d.kind, 0) + 1
        out.append(replace(d, id=f"{d.kind}-{count[d.kind]}"))
    return out


def apply_review(
    reading: Reading,
    *,
    clusters: Mapping[int, str] | Mapping[str, str] = {},
    decisions: Mapping[str, str] = {},
    kinds: Mapping[str, str] = {},
) -> Reading:
    """The reading after the organiser's review.

    `clusters` maps a cluster to a terrain class or `OUTSIDE`, which re-derives its cells' terrain. A decision is one
    of a doubt's `alternatives`, `keep` (its reading) or `drop` (`Doubt.offers`), and marks it resolved. `kinds`
    decides all of a kind at once: the choice goes to every unresolved doubt of that kind that offers it, and the
    others are left for one by one. Anything that doesn't fit raises `ValueError`, and nothing changes."""
    review = _Review(reading)
    for cluster, terrain in clusters.items():
        review.map_cluster(int(cluster), terrain)
    for doubt_id, choice in decisions.items():
        doubt = review.doubts.get(doubt_id)
        if doubt is None:
            raise ValueError(f"There is no doubt {doubt_id!r}.")
        if not doubt.offers(choice):
            raise ValueError(f"{choice!r} isn't a choice for {doubt_id}: {', '.join(doubt.alternatives)}.")
        review.decide(doubt, choice)
    for kind, choice in kinds.items():
        if kind not in DOUBT_KINDS:
            raise ValueError(f"{kind!r} isn't a kind of doubt.")
        for doubt in list(review.doubts.values()):
            if doubt.kind == kind and not doubt.resolved and doubt.offers(choice):
                review.decide(review.doubts[doubt.id], choice)
    return review.result()


def initial(geo: GeoMap, clusters: list[ClusterReading], doubts: list[Doubt]) -> Reading:
    """The reading as read: every label doubt's likely alternative applied, and the terrain derived."""
    review = _Review(Reading(geo, clusters, doubts))
    for doubt in doubts:
        if doubt.kind == "label-unpaired":
            review.place_label(doubt, doubt.alternatives[0], fresh=True)
    return review.result()


class _Review:
    def __init__(self, reading: Reading) -> None:
        self.reading = reading
        self.features: dict[str, GeoFeature] = {f.id: f for f in reading.geo.features}
        self.terrain = list(reading.geo.terrain)
        self.clusters = {c.id: c for c in reading.clusters}
        self.doubts = {d.id: d for d in reading.doubts}

    # --- clusters and cells

    def map_cluster(self, cluster: int, terrain: str) -> None:
        if cluster not in self.clusters:
            raise ValueError(f"There is no colour {cluster}.")
        if terrain not in TERRAIN_CLASSES and terrain != OUTSIDE:
            raise ValueError(f"{terrain!r} isn't a terrain.")
        self.clusters[cluster] = replace(self.clusters[cluster], terrain=terrain)
        for d in self.doubts.values():
            if d.kind == "cluster-unmapped" and d.ref == str(cluster):
                self._resolve(d, terrain)

    # --- decisions

    def decide(self, doubt: Doubt, choice: str) -> None:
        kind = doubt.kind
        if doubt.choice == DROP and kind != "label-unpaired":
            raise ValueError(f"{doubt.id} was dropped.")
        if kind == "cluster-unmapped":
            self.map_cluster(int(doubt.ref), doubt.reading if choice == KEEP else choice)
            return
        if kind == "label-unpaired":
            self.place_label(doubt, choice)
        elif choice == DROP:
            self._drop(doubt.ref)
        elif kind == "water-kind-guessed":
            self._water_kind(doubt, doubt.reading if choice == KEEP else choice)
        elif kind in ("river-flow-guessed", "river-no-mouth"):
            if (doubt.choice == REVERSE) != (choice == REVERSE):
                self._reverse(doubt.ref)
        elif kind == "label-uncertain":
            self._edit(doubt.ref, name=doubt.reading if choice == KEEP else choice)
        elif kind == "kind-guessed":
            self._edit(doubt.ref, kind=doubt.reading if choice == KEEP else choice)
        # symbol-unlabelled `keep`, and cell-mixed: the choice itself is what counts (`_terrain`).
        self._resolve(doubt, choice)

    def place_label(self, doubt: Doubt, choice: str, *, fresh: bool = False) -> None:
        """An unpaired label made what `choice` says, after undoing what it was (nothing, when `fresh`)."""
        data = doubt.data
        text = data["text"]
        feature_id = data["feature"]
        river = self.features.get(data.get("river") or "")
        if not fresh:
            before = doubt.choice or doubt.alternatives[0]
            self.features.pop(feature_id, None)
            if before == "river-name" and river is not None and river.name == text:
                river = self.features[river.id] = replace(river, name=data.get("river_was", ""))
        if choice == "place":
            x, y = data["place_at"]
            self.features[feature_id] = GeoFeature(
                feature_id, "places", "town", text, {"type": "Point", "coordinates": [x, y]}
            )
        elif choice == "region-name":
            x0, y0, x1, y1 = data["box"]
            ring = [[x0, y0], [x1, y0], [x1, y1], [x0, y1], [x0, y0]]
            self.features[feature_id] = GeoFeature(
                feature_id, "regions", "region", text, {"type": "Polygon", "coordinates": [ring]}
            )
        elif choice == "river-name":
            if river is None:
                raise ValueError(f"There is no river for {doubt.id} to name.")
            self.features[river.id] = replace(river, name=text)

    def _resolve(self, doubt: Doubt, choice: str) -> None:
        self.doubts[doubt.id] = replace(doubt, resolved=True, choice=choice)

    def _drop(self, ref: str) -> None:
        if self.features.pop(ref, None) is None:
            raise ValueError(f"{ref} isn't on the map.")
        for d in list(self.doubts.values()):
            if d.ref == ref and not d.resolved:
                self._resolve(d, DROP)

    def _edit(self, ref: str, **changes: str) -> None:
        feature = self.features.get(ref)
        if feature is None:
            raise ValueError(f"{ref} isn't on the map.")
        if "kind" in changes and changes["kind"] not in PLACE_KINDS:
            raise ValueError(f"{changes['kind']!r} isn't a kind of place.")
        self.features[ref] = replace(feature, **changes)

    def _reverse(self, ref: str) -> None:
        feature = self.features.get(ref)
        if feature is None:
            raise ValueError(f"{ref} isn't on the map.")
        coordinates = list(reversed(feature.geometry["coordinates"]))
        self.features[ref] = replace(feature, geometry={**feature.geometry, "coordinates": coordinates})

    def _water_kind(self, doubt: Doubt, kind: str) -> None:
        letter = TERRAIN_LETTERS[kind]
        for cell in doubt.data.get("cells", []):
            self.terrain[cell] = letter
        for feature_id in doubt.data.get("features", []):
            feature = self.features.get(feature_id)
            if feature is not None:
                self.features[feature_id] = replace(feature, kind=kind)

    # --- the result

    def _terrain(self) -> str:
        overrides = {
            int(d.ref.split(":")[1]): d.choice
            for d in self.doubts.values()
            if d.kind == "cell-mixed" and d.resolved and d.choice not in (None, KEEP)
        }
        letters = self.terrain
        for cluster in self.clusters.values():
            letter = TERRAIN_LETTERS.get(cluster.terrain or "", NO_TERRAIN)
            for cell in cluster.cells:
                letters[cell] = letter
        for cell, choice in overrides.items():
            letters[cell] = TERRAIN_LETTERS.get(choice or "", NO_TERRAIN)
        return "".join(letters)

    def result(self) -> Reading:
        doubts = list(self.doubts.values())
        open_on: dict[str, str] = {}
        for d in doubts:
            if not d.resolved:
                target = d.ref
                if d.kind == "label-unpaired":
                    target = d.data.get("river") if d.alternatives[0] == "river-name" else d.data.get("feature")
                if target:
                    open_on.setdefault(target, d.id)
        features = []
        for f in self.features.values():
            props = {k: v for k, v in f.props.items() if k != "doubt"}
            if f.id in open_on:
                props["doubt"] = open_on[f.id]
            features.append(f if props == dict(f.props) else replace(f, props=props))
        geo = replace(self.reading.geo, terrain=self._terrain(), features=tuple(features))
        return Reading(geo, list(self.clusters.values()), doubts)
