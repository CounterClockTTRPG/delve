"""The QA tools' one rule on paths (thorough conversion Task 3): every path a `delve qa` command is given, to read or to
write, is inside the job folder, which is the working directory the agent runs in.

A path is resolved before it is checked, following symlinks, so `../../delve.db`, `/home/raf/x.md` and a symlink in the
folder that points out of it are all refused. The CLI answers a refusal with exit code 2.
"""

from __future__ import annotations

from pathlib import Path


class OutsideFolder(ValueError):
    """A path outside the job folder."""

    def __init__(self, given: str) -> None:
        super().__init__(f"outside the job folder: {given}")
        self.given = given


def inside(folder: Path, given: str) -> Path:
    """`given` (relative to `folder`, or absolute) resolved, following symlinks; `OutsideFolder` unless it is
    `folder` itself or under it."""
    root = folder.resolve()
    path = (root / given).resolve()
    if not path.is_relative_to(root):
        raise OutsideFolder(given)
    return path
