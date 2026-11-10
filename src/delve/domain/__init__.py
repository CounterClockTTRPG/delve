"""Plain data types for modules, campaigns, characters, beats and so on. No I/O."""

from __future__ import annotations

import secrets


def new_id(prefix: str) -> str:
    """A fresh typed id, `<prefix>_<12 hex>`: `mod` for modules, `cmp` for campaigns, `chr` for characters."""
    return f"{prefix}_{secrets.token_hex(6)}"
