"""Aun (DEL-351): Delve's own setting, written for it, with no third-party material. The Reaches of Aun, twelve
centuries after the Unmaking ended the sorcerer-empire; gods great and small; the free city of Hask as the hub. Its
pages, lore facts and maps are files in `setting/data/aun` (`delve.setting.files`); the canon they follow is
`docs/settings/aun-bible.md`."""

from __future__ import annotations

from importlib import resources
from pathlib import Path

from delve.setting.calendar import RECKONING_CALENDAR
from delve.setting.files import FileSetting

DATA = Path(str(resources.files("delve.setting").joinpath("data", "aun")))

KINDS = ("realm", "place", "deity", "organization", "character", "people", "item", "holiday", "history", "lore")
"""The kinds of Aun's pages, in the order the DM is shown them."""


class AunSetting(FileSetting):
    """Aun over its folder of pages (the package's own unless `root` is given)."""

    id = "aun"
    title = "Aun"
    world = "aun"
    KINDS = KINDS
    CALENDAR = RECKONING_CALENDAR
    MAPS = (("reaches", "The Reaches"), ("hask-region", "Hask and the Ambre"))

    def __init__(self, root: Path | None = None) -> None:
        super().__init__(root or DATA)
