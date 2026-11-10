"""Scenario metadata (spec §3.1): title, authors, release, timestamps,
party size and levels, duration, licensing.

The schema allows short forms — an author as a plain name, a range as a
single number, a licence as a string — so authors can write the obvious
thing. `normalise()` turns any valid manifest into one canonical shape for
tools that list or display scenarios; `check()` covers what JSON Schema
can't: range ordering, real calendar dates, timestamp order, the cover
image.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timezone
from typing import Any

_RANGE_KEYS = (("party", "size"), ("party", "levels"), ("duration", "sessions"),
               ("duration", "hours"))

# Fields an earlier draft of the manifest used, and where they live now.
MOVED = {"levels": "party.levels", "revision": "release.version"}


def _range(v: Any) -> dict | None:
    if isinstance(v, bool) or v is None:
        return None
    if isinstance(v, (int, float)):
        return {"min": v, "max": v, "recommended": v}
    if isinstance(v, dict) and "min" in v and "max" in v:
        return {"min": v["min"], "max": v["max"],
                **({"recommended": v["recommended"]} if "recommended" in v else {})}
    return None


def _person(p: Any) -> dict | None:
    if isinstance(p, str):
        return {"name": p, "role": "author"}
    if isinstance(p, dict) and p.get("name"):
        return {**p, "role": p.get("role", "author")}
    return None


def _license(v: Any) -> dict | None:
    if isinstance(v, str):
        return {"name": v}
    return dict(v) if isinstance(v, dict) else None


def parse_timestamp(s: Any) -> datetime | None:
    """A manifest timestamp as an aware UTC datetime (a bare date is
    midnight UTC). None if it isn't a real date/time."""
    if not isinstance(s, str):
        return None
    try:
        if len(s) == 10:
            d = date.fromisoformat(s)
            return datetime(d.year, d.month, d.day, tzinfo=timezone.utc)
        dt = datetime.fromisoformat(s.replace("z", "Z"))
    except ValueError:
        return None
    if dt.tzinfo is None:
        return None
    return dt.astimezone(timezone.utc)


def normalise(manifest: dict) -> dict:
    """Canonical metadata view: every short form expanded, absent fields
    omitted. Never raises on a schema-valid manifest."""
    m = manifest
    out: dict[str, Any] = {"id": m.get("id"), "title": m.get("title")}
    for k in ("subtitle", "summary", "description", "system", "system_name", "setting",
              "language", "homepage", "cover", "created", "updated"):
        if m.get(k) not in (None, ""):
            out[k] = m[k]
    authors = [a for a in (_person(p) for p in m.get("authors") or []) if a]
    if authors:
        out["authors"] = authors
    if isinstance(m.get("publisher"), dict):
        out["publisher"] = m["publisher"]
    if isinstance(m.get("release"), dict):
        out["release"] = dict(m["release"])
    lic = _license(m.get("license"))
    if lic:
        out["license"] = lic
    for outer, inner in _RANGE_KEYS:
        r = _range((m.get(outer) or {}).get(inner) if isinstance(m.get(outer), dict) else None)
        if r:
            out.setdefault(outer, {})[inner] = r
    if isinstance(m.get("party"), dict) and m["party"].get("notes"):
        out.setdefault("party", {})["notes"] = m["party"]["notes"]
    for k in ("tags", "content_warnings"):
        if m.get(k):
            out[k] = list(m[k])
    return out


@dataclass(frozen=True)
class Finding:
    severity: str
    code: str
    message: str


def check(manifest: dict, *, asset_lookup=None) -> list[Finding]:
    """Semantic metadata checks. `asset_lookup(id) -> asset entry | None`
    lets the cover be checked against the bundle."""
    out: list[Finding] = []
    m = manifest

    for outer, inner in _RANGE_KEYS:
        block = m.get(outer)
        v = block.get(inner) if isinstance(block, dict) else None
        if not isinstance(v, dict) or not {"min", "max"} <= set(v):
            continue
        lo, hi, rec = v.get("min"), v.get("max"), v.get("recommended")
        if not all(isinstance(x, (int, float)) for x in (lo, hi)):
            continue
        if lo > hi:
            out.append(Finding("error", "metadata-range",
                               f"{outer}.{inner}: min {lo} is greater than max {hi}"))
        elif isinstance(rec, (int, float)) and not lo <= rec <= hi:
            out.append(Finding("error", "metadata-range",
                               f"{outer}.{inner}: recommended {rec} is outside {lo}–{hi}"))

    stamps = {}
    for k in ("created", "updated"):
        if k in m:
            ts = parse_timestamp(m[k])
            if ts is None:
                out.append(Finding("error", "metadata-timestamp",
                                   f"{k}: {m[k]!r} is not a real date or a date-time with an offset"))
            stamps[k] = ts
    if stamps.get("created") and stamps.get("updated") and stamps["updated"] < stamps["created"]:
        out.append(Finding("error", "metadata-timestamp", "updated is earlier than created"))
    now = datetime.now(timezone.utc)
    for k, ts in stamps.items():
        if ts and (ts - now).days > 1:
            out.append(Finding("warning", "metadata-timestamp", f"{k} is in the future"))
    rel = m.get("release")
    if isinstance(rel, dict) and "date" in rel and parse_timestamp(rel["date"]) is None:
        out.append(Finding("error", "metadata-timestamp",
                           f"release.date: {rel['date']!r} is not a real date"))

    cover = m.get("cover")
    if isinstance(cover, str) and cover.startswith("asset:") and asset_lookup is not None:
        a = asset_lookup(cover[6:])
        if a is None:
            out.append(Finding("error", "dangling-ref", f"cover: no asset {cover[6:]!r}"))
        else:
            if not str(a.get("type", "")).startswith("image/"):
                out.append(Finding("error", "metadata-cover", "cover is not an image asset"))
            if a.get("audience", "gm") != "player":
                out.append(Finding("warning", "audience-leak",
                                   "cover asset is GM-only but covers are shown to players"))

    for old, new in MOVED.items():
        if old in m:
            out.append(Finding("warning", "metadata-moved", f"`{old}` is now `{new}`"))
    return out
