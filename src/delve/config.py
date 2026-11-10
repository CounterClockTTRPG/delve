"""Where Delve keeps its data and where it listens."""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass, replace
from pathlib import Path

DEFAULT_HOST = "0.0.0.0"
DEFAULT_PORT = 7810


@dataclass(frozen=True)
class Config:
    data_dir: Path
    host: str = DEFAULT_HOST
    port: int = DEFAULT_PORT

    @property
    def db_path(self) -> Path:
        return self.data_dir / "delve.db"

    @property
    def token_path(self) -> Path:
        return self.data_dir / "token"

    @property
    def packs_dir(self) -> Path:
        return self.data_dir / "packs"

    @classmethod
    def from_env(cls, env: Mapping[str, str] = os.environ, **overrides) -> Config:
        """Build the config from `DELVE_DATA_DIR`, then apply overrides; an override of None is ignored."""
        data_dir = env.get("DELVE_DATA_DIR")
        config = cls(data_dir=Path(data_dir) if data_dir else Path.home() / ".local/share/delve")
        return replace(config, **{k: v for k, v in overrides.items() if v is not None})


DATA_DIR_MODE = 0o700
"""The data directory holds the database, the owner token and the stores' credentials: its owner's alone."""


def private_data_dir(data_dir: Path) -> None:
    """Make `data_dir` if need be, and keep it 0700 (DEL-154, audit finding 13): an older Delve made it 0775, and
    `mkdir`'s mode is cut by the umask, so it is set again each time."""
    data_dir.mkdir(mode=DATA_DIR_MODE, parents=True, exist_ok=True)
    if data_dir.stat().st_uid == os.getuid() and data_dir.stat().st_mode & 0o777 != DATA_DIR_MODE:
        data_dir.chmod(DATA_DIR_MODE)
