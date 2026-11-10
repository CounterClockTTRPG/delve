"""The world map of the Reaches of Aun (DEL-354): a Delve map document and a picture in the manner of the old hex maps
(terrain drawn in every hex, realms in coloured borders, names lettered on), both made from the same shapes, so the
picture lies exactly under the grid.

    uv run python -I scripts/aun_map.py build <out dir>     # aun.geojson, aun.jpg, aun-preview.jpg
    uv run python -I scripts/aun_map.py store <out dir>     # into Delve as the setting aun's map `reaches`

The geography follows docs/settings/aun-bible.md: its coordinates are in miles, x west to east (0-1600), y south to
north (0-1000), and so are this file's. Everything is drawn from a fixed seed, so a build is the same every time. Back
up delve.db before `store`: it replaces the map `reaches`, and stores `hask-region` from its shipped file beside it.
"""

from __future__ import annotations

import json
import math
import sys
from dataclasses import dataclass, field
from itertools import pairwise
from pathlib import Path

import numpy as np
import shapely
from PIL import Image, ImageDraw, ImageFilter, ImageFont
from shapely.geometry import LineString, MultiPolygon, Polygon, box
from shapely.ops import unary_union

MILE_KM = 1.609344
W_MI, H_MI = 1600.0, 1000.0
R = 2.0  # raster cell, miles
NX, NY = int(W_MI / R), int(H_MI / R)
HEX_MI = 15.0
SEED = 1188

# ----------------------------------------------------------------------------------------------------------------------
# The geography (bible coordinates: miles, y north)
# ----------------------------------------------------------------------------------------------------------------------

# The main coast, west to east along the north, then back along the south. The far south-west (the Drowned Coast)
# is ragged on purpose; its isles come from ISLES and the noise.
COAST = [
    # west coast, south to north
    (-40, 230),
    (60, 300),
    (28, 345),
    (72, 405),
    (38, 462),
    (90, 520),
    (52, 585),
    (30, 640),
    (82, 690),
    (42, 735),
    (95, 762),
    # north coast of the steppe and the Wrackmoor
    (150, 772),
    (200, 800),
    (248, 778),
    (300, 808),
    (345, 792),
    (380, 840),
    (410, 885),
    (450, 905),
    # the Holds
    (500, 925),
    (560, 935),
    (640, 945),
    (700, 955),
    (760, 950),
    (840, 940),
    (900, 965),
    (935, 990),
    (960, 965),
    (1000, 930),
    (1060, 900),
    (1150, 880),
    (1250, 862),
    (1350, 872),
    (1450, 868),
    (1540, 880),
    (1640, 875),
    # east edge, then the Greenmaw coast east to west
    (1640, 18),
    (1560, 22),
    (1480, 12),
    (1400, 20),
    (1330, 14),
    (1260, 22),
    (1190, 30),
    (1140, 60),
    # the Sunder Sea's north shore, east to west
    (1110, 120),
    (1075, 150),
    (1040, 128),
    (1000, 138),
    (960, 165),
    (930, 140),
    (880, 150),
    (860, 148),
    (820, 155),
    (790, 138),
    (760, 165),
    (720, 180),
    (700, 150),
    (660, 132),
    (630, 155),
    (580, 140),
    (540, 158),
    (500, 150),
    (490, 185),
    (470, 212),
    (450, 216),
    (430, 210),
    (410, 185),
    (390, 150),
    (370, 118),
    (340, 140),
    (305, 145),
    (280, 125),
    (250, 95),
    (230, 60),
    (205, 30),
    (160, 10),
    (100, -40),
    (-40, -40),
]

# Islands: the Holds' western isles, Kaldvik's outer isles, the Drowned Coast's, and a few in the Sunder Sea.
ISLES = [
    [(150, 850), (210, 845), (240, 880), (200, 905), (150, 895)],
    [(255, 880), (300, 870), (330, 900), (300, 935), (260, 925)],
    [(190, 930), (230, 925), (245, 955), (205, 965)],
    [(340, 935), (380, 930), (400, 960), (360, 975)],
    [(590, 965), (640, 960), (665, 985), (620, 995), (585, 985)],
    [(680, 980), (710, 975), (720, 995), (690, 998)],
    [(1040, 940), (1080, 930), (1100, 955), (1060, 965)],
    [(60, 120), (110, 110), (130, 140), (90, 160), (55, 150)],
    [(20, 40), (70, 30), (85, 70), (40, 85)],
    [(150, 50), (190, 55), (185, 80), (150, 78)],
    [(560, 70), (610, 60), (640, 85), (600, 105), (560, 95)],
    [(900, 60), (940, 55), (950, 80), (915, 90)],
    [(1010, 80), (1035, 78), (1040, 95), (1015, 98)],
]

# The Holds' fjords, each from its mouth to its head.
FJORDS = [
    [(505, 960), (510, 925), (514, 895)],  # Skarnholm's
    [(598, 975), (592, 930), (586, 885)],
    [(665, 985), (668, 940), (672, 895)],
    [(742, 985), (738, 945), (733, 905)],
    [(792, 985), (796, 940), (800, 900)],
    [(850, 985), (842, 945), (836, 912), (832, 885)],  # Tarnfjord
    [(892, 1000), (888, 960), (880, 925)],
    [(985, 980), (976, 935), (968, 890)],
    [(1040, 940), (1030, 900), (1022, 865)],
]

# Land kept dry whatever the noise does (a city's ground, a peninsula's neck).
DRY = [
    ((800, 520), 12),
    ((450, 224), 5),
    ((180, 120), 8),
    ((858, 168), 6),
    ((520, 905), 8),
    ((930, 985), 6),
    ((1322, 44), 5),
    ((420, 880), 6),
    ((620, 975), 6),
]


@dataclass
class Area:
    """A terrain area: `kind` one of the terrain classes, a polygon or a buffered line (`width` miles each side)."""

    name: str
    kind: str
    shape: list[tuple[float, float]]
    width: float = 0.0
    description: str = ""
    reference: str = ""
    label: tuple[float, float, float, float] | None = None  # x, y, angle, size
    named: bool = True


AREAS = [
    Area(
        "Hornwall",
        "mountain",
        [
            (455, 742),
            (520, 752),
            (600, 760),
            (700, 764),
            (790, 762),
            (860, 760),
            (950, 758),
            (1050, 752),
            (1150, 748),
            (1250, 742),
        ],
        28,
        "The great mountain chain of the north, eight hundred miles from the moors north of Calder to the edge of "
        "the Margravate: grey peaks, snow nine months of the year, glaciers in the high valleys.",
        "Hornwall",
        (850, 775, 0, 30),
    ),
    Area(
        "Hornwall foothills",
        "hills",
        [(450, 738), (600, 752), (790, 755), (950, 750), (1150, 742), (1260, 738)],
        46,
        named=False,
    ),
    Area(
        "Smoking Hills",
        "hills",
        [(1180, 690), (1260, 700), (1340, 720), (1360, 780), (1330, 830), (1250, 840), (1190, 800), (1160, 740)],
        description="The broken eastern end of the Hornwall: black rock, hot springs and smoke, held by orc tribes "
        "who serve the Margrave.",
        label=(1270, 785, 0, 17),
    ),
    Area(
        "Calder Downs",
        "hills",
        [(425, 420), (500, 405), (580, 410), (625, 445), (610, 515), (540, 532), (470, 528), (420, 490)],
        description="Rolling chalk hills in Calder's heart, bare on top and wooded in the folds; barrows on the "
        "ridges, gnome burrow-villages, and the Hill That Listens.",
        label=(530, 485, 0, 15),
    ),
    Area(
        "Wrackmoor",
        "hills",
        [(380, 700), (440, 705), (480, 740), (470, 820), (440, 890), (400, 880), (375, 820)],
        description="The open moor of Calder's north, running up to the Iron Sea between the steppe and the "
        "Hornwall's western end. Longships come ashore here in raiding years.",
        label=(420, 810, 80, 14),
    ),
    Area(
        "Bleached Hills",
        "hills",
        [(370, 245), (450, 250), (520, 262), (610, 270), (640, 310), (560, 330), (470, 318), (390, 300)],
        description="The dry hills behind the Theocracy's coast, cut by the long valleys that run north into Calder.",
        label=(560, 300, 0, 15),
    ),
    Area(
        "Tessarine Hills",
        "hills",
        [(915, 250), (990, 240), (1070, 260), (1120, 320), (1100, 380), (1020, 385), (940, 350)],
        description="The dry eastern hills of the Lantern Principalities on the edge of the Glass Waste, House "
        "Tessarine's.",
        label=(1040, 345, 0, 15),
    ),
    Area(
        "Anvils",
        "hills",
        [(990, 640), (1060, 660), (1140, 650), (1200, 690), (1190, 735), (1100, 735), (1020, 715), (975, 690)],
        description="The Margravate's iron hills under the Hornwall: ash-grey heath, fast streams and mine-workings.",
        label=(1120, 715, 0, 14),
    ),
    Area(
        "Burning Hills",
        "hills",
        [(1470, 70), (1560, 60), (1600, 110), (1600, 230), (1520, 240), (1470, 180)],
        description="The eastern hills of the Greenmaw, where the Tree-Burners live and strangers are not welcome.",
        label=(1535, 170, 90, 14),
    ),
    Area(
        "Grandmother Frost",
        "arctic",
        [(660, 880), (720, 880), (750, 905), (720, 930), (670, 925)],
        description="The greatest glacier of the Holds, and a small god: she keeps the dead of the Hold-folk in her "
        "ice.",
        reference="Grandmother Frost",
        named=False,
    ),
    Area(
        "Thornwold",
        "forest",
        [
            (600, 485),
            (650, 478),
            (710, 490),
            (762, 505),
            (768, 560),
            (760, 620),
            (740, 670),
            (690, 685),
            (630, 675),
            (598, 630),
            (590, 560),
        ],
        description="The elves' forest between Calder and Hask, ruled by the Lady Ysmeine. The Thornway runs through "
        "it by day only.",
        reference="Thornwold",
        label=(680, 620, 0, 17),
    ),
    Area(
        "Glass Waste",
        "desert",
        [
            (1150, 262),
            (1250, 250),
            (1350, 245),
            (1450, 262),
            (1550, 285),
            (1565, 380),
            (1560, 470),
            (1550, 560),
            (1540, 650),
            (1460, 668),
            (1380, 660),
            (1300, 640),
            (1225, 620),
            (1210, 540),
            (1200, 470),
            (1160, 400),
            (1130, 330),
        ],
        description="Where Ishavel burned on the night of the Unmaking: dunes, ripples and ridges of glass, grey ash "
        "between, brass ruins, ghosts and thirst.",
        reference="Glass Waste",
    ),
    Area(
        "Greenmaw",
        "jungle",
        [(1110, 0), (1600, 0), (1600, 250), (1450, 262), (1300, 255), (1180, 250), (1120, 180), (1100, 100)],
        reference="Greenmaw",
        named=False,
    ),
    Area(
        "Drowned shallows",
        "swamp",
        [(0, 0), (250, 0), (280, 120), (300, 200), (270, 250), (150, 270), (0, 260)],
        named=False,
    ),
    Area(
        "Salt marshes",
        "swamp",
        [(270, 150), (320, 155), (345, 200), (330, 250), (290, 260), (270, 210)],
        description="The salt marshes between the Theocracy and the Drowned Coast.",
        named=False,
    ),
    Area("Ambre mouths", "swamp", [(835, 150), (885, 150), (890, 185), (860, 200), (835, 185)], named=False),
    Area(
        "Greenmaw mangroves",
        "swamp",
        [(1140, 20), (1600, 15), (1600, 45), (1450, 40), (1300, 45), (1180, 55), (1135, 70)],
        named=False,
    ),
    Area("Redmere fen", "swamp", [(870, 600), (930, 598), (948, 630), (920, 650), (880, 645)], named=False),
    Area(
        "Holds ice",
        "arctic",
        [(840, 940), (900, 950), (930, 990), (960, 990), (1000, 950), (960, 930), (900, 925)],
        named=False,
    ),
    Area("Iron coast tundra", "arctic", [(1250, 840), (1400, 845), (1640, 850), (1640, 880), (1250, 870)], named=False),
]

# Forest scattered by noise (woods in the folds, the pines of the fjords), per region: (polygon, share of the land).
WOODS = [
    ([(400, 380), (700, 380), (700, 720), (400, 720)], 0.22),  # Calder
    ([(480, 800), (1000, 800), (1000, 940), (480, 940)], 0.30),  # Holds valleys
    ([(690, 160), (1100, 160), (1100, 420), (690, 420)], 0.16),  # Lantern
    ([(950, 450), (1200, 450), (1200, 740), (950, 740)], 0.18),  # Margravate
    ([(1250, 680), (1640, 680), (1640, 840), (1250, 840)], 0.25),  # north-east
    ([(300, 160), (690, 160), (690, 370), (300, 370)], 0.06),  # Theocracy
]

LAKES = [
    (
        "Redmere",
        [(882, 612), (900, 606), (918, 612), (924, 622), (912, 632), (892, 632), (880, 624)],
        (
            "A marshy reed lake on the Calder–Margravate border, and the battlefield of 1110 RY. The border runs through "
            "the middle of it."
        ),
        "Redmere",
    ),
    (
        "Tarnwater",
        [(820, 865), (840, 860), (848, 876), (835, 886), (818, 880)],
        "The long lake at the head of Tarnfjord, where the dwarf-road comes down from the Hornwall.",
        "",
    ),
]


@dataclass
class River:
    name: str
    points: list[tuple[float, float]]
    description: str = ""
    reference: str = ""
    width: float = 1.0  # at its mouth, in the picture's river widths
    label_at: float = 0.5  # how far along its name sits


RIVERS = [
    River(
        "Ambre",
        [
            (806, 745),
            (802, 700),
            (795, 650),
            (798, 600),
            (796, 560),
            (800, 520),
            (812, 470),
            (828, 410),
            (836, 362),
            (848, 300),
            (855, 230),
            (858, 170),
            (860, 140),
        ],
        "The great river of the Reaches: from the Hornwall's southern flank past Hask and through the Lantern "
        "Principalities to the Sunder Sea. Hask's ferries are its only crossing for a hundred miles.",
        "Ambre",
        2.0,
        0.62,
    ),
    River(
        "Aldwater",
        [
            (570, 690),
            (555, 620),
            (543, 562),
            (532, 500),
            (520, 450),
            (518, 390),
            (512, 335),
            (480, 270),
            (455, 225),
            (451, 200),
            (452, 170),
        ],
        "Calder's river: down from the Wrackmoor's edge past Aldmoor, south through the long valleys and the "
        "Bleached Hills, to the sea at Candor.",
        "",
        1.5,
        0.45,
    ),
    River(
        "Thornbeck",
        [(670, 660), (705, 600), (745, 555), (775, 520), (802, 505)],
        "A dark stream out of the Thornwold that joins the Ambre below Hask. Woodcutters do not follow it in.",
        "",
        0.8,
        0.4,
    ),
    River(
        "Reedrun",
        [(892, 612), (870, 570), (840, 520), (816, 470)],
        "The slow stream from Redmere down to the Ambre below Hask, reed-choked and full of eels.",
        "",
        0.7,
        0.5,
    ),
    River(
        "Cinder",
        [(1150, 735), (1120, 690), (1085, 645), (1062, 603), (1090, 560), (1135, 520), (1170, 470), (1200, 430)],
        "The grey river of the Margravate, down from the Smoking Hills past Vaelholt, and east into the Glass Waste, "
        "where it sinks into the glass and is not seen again.",
        "",
        1.0,
        0.55,
    ),
    River(
        "Dulce",
        [(1060, 340), (1040, 280), (1020, 230), (1010, 200), (1012, 135)],
        "The Lantern river of the eastern hills, past Dulcamare to the Sunder Sea.",
        "",
        0.9,
        0.3,
    ),
    River(
        "Saltbeck",
        [(420, 335), (380, 290), (350, 240), (310, 185), (290, 150)],
        "A brackish river out of the Bleached Hills into the salt marshes at the Theocracy's western edge.",
        "",
        0.8,
        0.4,
    ),
    River(
        "Ashkai",
        [(370, 650), (300, 655), (230, 640), (160, 670), (110, 700), (60, 715)],
        "A shallow steppe river wandering west to the sea in a bed a mile wide. Hold raiders know its mouth.",
        "",
        1.0,
        0.45,
    ),
    River(
        "Mirrun",
        [(390, 460), (330, 445), (260, 420), (190, 395), (120, 380), (50, 370)],
        "The southern river of the Horse Steppe, its wells and fords the clans' law.",
        "",
        1.0,
        0.5,
    ),
    River(
        "Coil",
        [(1300, 262), (1330, 205), (1345, 160), (1352, 132), (1338, 85), (1325, 50), (1321, 10)],
        "The brown river of the Greenmaw, from the Waste's edge down past Zhaumal to Fevermouth on the coast. A "
        "Thaumarch army went up it once and did not come down.",
        "",
        1.3,
        0.25,
    ),
    River("", [(1480, 245), (1495, 180), (1490, 110), (1505, 50), (1500, 0)], width=1.0),
    River("", [(1210, 240), (1220, 170), (1205, 110), (1215, 40)], width=0.9),
    River("", [(620, 790), (612, 840), (600, 900), (598, 935)], width=0.7),
    River("", [(815, 785), (822, 840), (830, 870), (834, 900), (838, 935)], width=0.8),
    River("", [(920, 790), (930, 850), (925, 900), (935, 960)], width=0.7),
    River("", [(990, 705), (950, 660), (915, 628)], width=0.6),
    River("", [(330, 760), (290, 775), (250, 790)], width=0.6),
    River("", [(1380, 720), (1400, 790), (1390, 870)], width=0.6),
    River("", [(640, 320), (690, 250), (700, 160)], width=0.7),
]


@dataclass
class Place:
    id: str
    name: str
    x: float
    y: float
    kind: str  # city, town, village, castle, ruin, dungeon, port, other
    description: str
    rank: str = "town"  # capital, city, town, site
    reference: str = ""
    label: str = "e"  # where its name sits: e, w, n, s, ne, nw, se, sw
    tags: list[str] = field(default_factory=list)
    pop: int | None = None


PLACES = [
    Place(
        "hask",
        "Hask",
        800,
        520,
        "city",
        "Hask, the free city on Hask Ford: rich, crooked, loud, and without a "
        "bridge. About 38,000 souls on both banks of the Ambre.",
        "capital",
        "Hask",
        "e",
        ["walled"],
        38000,
    ),
    Place(
        "aldmoor",
        "Aldmoor",
        540,
        560,
        "city",
        "Aldmoor, the old royal city of Calder, by its river and its wool fairs.",
        "capital",
        "Aldmoor",
        "w",
        ["walled"],
        22000,
    ),
    Place(
        "candor",
        "Candor",
        450,
        222,
        "port",
        "Candor, the white city of the Hierarch, at the mouth of the Aldwater on the Sunder Sea.",
        "capital",
        "Candor",
        "e",
        ["walled"],
        30000,
    ),
    Place(
        "vaelholt",
        "Vaelholt",
        1060,
        600,
        "city",
        "Vaelholt, the Margrave's seat: a fortress city of black stone. Foreigners enter by the west gate only.",
        "capital",
        "Vaelholt",
        "e",
        ["walled"],
        15000,
    ),
    Place(
        "skarnholm",
        "Skarnholm",
        520,
        905,
        "port",
        "Skarnholm, chief port of the Holds, where the Moot gathers each spring.",
        "capital",
        "Skarnholm",
        "s",
        [],
        8000,
    ),
    Place(
        "gullhaven",
        "Gullhaven",
        180,
        120,
        "port",
        "Gullhaven, the pirates' port of the Drowned Coast, on its Thaumarch harbour mole.",
        "city",
        "Gullhaven",
        "e",
        [],
        6000,
    ),
    Place(
        "corvanne",
        "Corvanne",
        838,
        362,
        "city",
        "Corvanne, on the Ambre's east bluff, the Lantern city nearest Hask; it works the river chains.",
        "capital",
        "Corvanne",
        "e",
        ["walled"],
        18000,
    ),
    Place(
        "tessarine",
        "Tessarine",
        970,
        300,
        "city",
        "Tessarine, in the eastern hills, seat of the House of Tessarine and its glass trade.",
        "capital",
        "Tessarine",
        "e",
        ["walled"],
        14000,
    ),
    Place(
        "amaranthe",
        "Amaranthe",
        858,
        168,
        "port",
        "Amaranthe, built on the islands and mudbanks where the Ambre "
        "meets the Sunder Sea; its Lantern burns in the harbour tower on feast nights.",
        "capital",
        "Amaranthe",
        "w",
        ["walled"],
        12000,
    ),
    Place(
        "deephorn",
        "Deephorn",
        820,
        752,
        "castle",
        "Deephorn, the dwarves' hold under the Hornwall, above the "
        "source of the Ambre: a gate of carved stone in a cliff.",
        "capital",
        "Deephorn",
        "e",
        ["dwarven"],
        9000,
    ),
    # Calder
    Place(
        "wendlecote",
        "Wendlecote",
        522,
        448,
        "town",
        "A valley town of Calder on the Aldwater, where the Sun Road comes up from the south.",
        label="e",
    ),
    Place(
        "burnhollow",
        "Burnhollow",
        470,
        505,
        "village",
        "A downs village of Calder, gnome burrows on its hill.",
        label="w",
    ),
    Place(
        "stannick",
        "Stannick",
        398,
        600,
        "castle",
        "A border keep of Calder, watching the grass of the Horse Steppe.",
        label="e",
    ),
    Place(
        "morwick",
        "Morwick",
        418,
        872,
        "village",
        "A fishing village on the Wrackmoor coast, burned by Hold raiders more often than anyone has counted.",
        label="e",
    ),
    Place(
        "thanes-cross",
        "Thane's Cross",
        868,
        668,
        "town",
        "The chief town of the Calder march, north of the Thornwold; the Grey Legions sit across the border from it.",
        label="n",
    ),
    # The Theocracy
    Place(
        "whitmarsh",
        "Whitmarsh",
        335,
        205,
        "town",
        "The Theocracy's last town before the salt marshes and the Drowned Coast: inquisitors and smugglers both.",
        label="n",
    ),
    Place(
        "tirrow",
        "Tirrow",
        512,
        335,
        "town",
        "A whitewashed valley town of the Theocracy on the Aldwater, on the Sun Road north.",
        label="e",
    ),
    Place(
        "sollen",
        "Sollen",
        610,
        162,
        "port",
        "A port of the Theocracy on the Sunder Sea, where the coast road runs east toward the Lantern lands.",
        label="n",
    ),
    # The Lantern Principalities
    Place("sabrenne", "Sabrenne", 760, 250, "town", "Seat of the House of Sabrenne, small, proud and poor.", label="w"),
    Place("dulcamare", "Dulcamare", 1010, 200, "town", "Seat of the House of Dulcamare, on the Dulce.", label="e"),
    Place("orsolin", "Orsolin", 905, 250, "town", "Seat of the House of Orsolin.", label="s"),
    Place(
        "quillane",
        "Quillane",
        725,
        330,
        "town",
        "Seat of the House of Quillane, behind the hill forts on the Theocracy's border.",
        label="w",
    ),
    # The Margravate
    Place(
        "kettleburn",
        "Kettleburn",
        1130,
        680,
        "town",
        "A Margravate mining town in the Anvils; the forges never go out.",
        label="e",
    ),
    Place(
        "harl", "Harl", 985, 520, "town", "A Margravate district town and reeve's seat on the road south.", label="w"
    ),
    # The Holds
    Place(
        "kaldvik",
        "Kaldvik",
        625,
        975,
        "port",
        "Kaldvik, Skarnholm's rival: a whaling hold on the outer isles.",
        reference="",
        label="e",
    ),
    Place(
        "tarnfjord",
        "Tarnfjord",
        836,
        905,
        "town",
        "Tarnfjord, where the dwarf-road comes down from the Hornwall.",
        label="e",
    ),
    Place(
        "brennoy",
        "Brennoy",
        930,
        982,
        "village",
        "Brennoy, the farthest north of the Holds, where the sun does not rise for a month of the year.",
        label="e",
    ),
    # The south
    Place(
        "fevermouth",
        "Fevermouth",
        1322,
        44,
        "port",
        "Fevermouth: a stockade, a wharf, a temple of Marrah and a "
        "graveyard bigger than the town, at the mouth of the Coil.",
        label="e",
    ),
    Place(
        "old-calvey",
        "Old Calvey",
        92,
        182,
        "ruin",
        "Old Calvey, a Thaumarch harbour town that slid under the sea; its roofs show at the lowest tides.",
        label="e",
        tags=["ruined"],
    ),
    # Sites
    Place(
        "ishavel",
        "Ishavel",
        1350,
        450,
        "ruin",
        "The glass ruins of Ishavel, the Thaumarchy's capital, the "
        "Lantern of the World. From a distance it looks like a frozen sea breaking on a reef.",
        "site",
        "Ishavel",
        "s",
        ["ruined"],
    ),
    Place(
        "zhaumal",
        "Zhaumal",
        1352,
        132,
        "ruin",
        "Zhaumal, the ruined serpent-city at the heart of the Greenmaw, where the Serpent Oracle speaks.",
        "site",
        "Zhaumal",
        "e",
        ["ruined"],
    ),
    Place(
        "pale-tower",
        "Pale Tower",
        790,
        560,
        "dungeon",
        "The Pale Tower, a day upriver from Hask, leaning and whiter than bone; the Undercroft is below it.",
        "site",
        "Pale Tower",
        "w",
        ["ruined", "dungeon"],
    ),
    Place(
        "thousand-fires",
        "Thousand Fires",
        180,
        520,
        "other",
        "The Thousand Fires, the grass hollow where the steppe clans gather each summer.",
        "site",
        "Thousand Fires",
        "s",
    ),
    Place(
        "shardsend",
        "Shardsend",
        1135,
        310,
        "village",
        "Shardsend, the glass-pickers' camp-town on the Waste's south-west rim, three days from Tessarine.",
        "town",
        "Glass-Pickers",
        "e",
    ),
    Place(
        "vael-dig",
        "Vael Dig",
        1290,
        505,
        "other",
        "The Margrave's diggings in the Glass Waste, with an army camp "
        "to guard them. Locals say they have found something large.",
        "site",
        "Glass Waste",
        "n",
    ),
    Place(
        "redmere-field",
        "Redmere field",
        905,
        640,
        "other",
        "The field of Redmere, where the Seven Years' War ended in 1110 RY.",
        "site",
        "Redmere",
        "ne",
    ),
    Place(
        "hill-that-listens",
        "Hill That Listens",
        500,
        470,
        "other",
        "The Hill That Listens, a barrow in Calder's downs that answers one question a year for a secret.",
        "site",
        "Hill That Listens",
        "s",
    ),
    Place(
        "drowned-bell",
        "Drowned Bell",
        112,
        62,
        "other",
        "Where the Drowned Bell lies under the sea, and rings before wrecks.",
        "site",
        "Drowned Bell",
        "e",
    ),
    Place(
        "ambre-gate",
        "Ambre Gate",
        815,
        790,
        "other",
        "The Ambre Gate, the gorge under Deephorn, the one easy "
        "road from the Holds to the south; dwarf towers at each end take the toll.",
        "site",
        "Hornwall",
        "e",
    ),
    Place(
        "ketters-notch",
        "Ketter's Notch",
        560,
        770,
        "other",
        "Ketter's Notch, a high goat-path in the western Hornwall, open two months a year. Smugglers use it.",
        "site",
        "Hornwall",
        "w",
    ),
    Place(
        "red-stair",
        "Red Stair",
        1185,
        765,
        "other",
        "The Red Stair, the Thaumarchs' stepped road over the "
        "eastern Hornwall, held by orcs and used by the Margrave's patrols.",
        "site",
        "Hornwall",
        "e",
    ),
]


@dataclass
class Road:
    name: str
    stops: list  # place ids and (x, y) points
    kind: str  # road (paved), track, trail
    description: str = ""


ROADS = [
    Road(
        "Thornway",
        ["aldmoor", (600, 552), (680, 540), (760, 530), "hask"],
        "road",
        "The Thaumarch road from Aldmoor to Hask straight through the Thornwold: a hundred and sixty miles of pale "
        "stone, travelled by day only, under the elves' terms.",
    ),
    Road(
        "South road",
        ["aldmoor", (580, 480), (650, 455), (720, 452), (780, 478), "hask"],
        "track",
        "The long road round the south of the Thornwold, four days longer than the Thornway.",
    ),
    Road(
        "Old Road east",
        ["hask", (850, 548), (880, 585), (940, 600), (1000, 604), "vaelholt"],
        "road",
        "The Old Road east from Hask past Redmere to Vaelholt. Margravate toll-forts at the border.",
    ),
    Road(
        "River road",
        ["hask", (818, 440), "corvanne", (852, 280), (862, 210), "amaranthe"],
        "road",
        "The road down the Ambre's east bank from Hask through the Lantern Principalities to the sea.",
    ),
    Road(
        "Sun Road",
        ["candor", (470, 275), "tirrow", (518, 400), "wendlecote", (535, 510), "aldmoor"],
        "road",
        "The pilgrims' and soldiers' road from Candor north up the valleys to Calder.",
    ),
    Road(
        "Deephorn road",
        ["hask", (803, 600), (800, 680), "deephorn"],
        "track",
        "The road north up the Ambre to Deephorn's gates.",
    ),
    Road(
        "Dwarf-road",
        ["deephorn", "ambre-gate", (828, 850), "tarnfjord"],
        "trail",
        "Through the Ambre Gate and down to Tarnfjord: the one easy way between the Holds and the south.",
    ),
    Road(
        "Notch path",
        [(585, 700), "ketters-notch", (545, 830), "skarnholm"],
        "trail",
        "The goat-path over Ketter's Notch, open two months a year.",
    ),
    Road(
        "Steppe track",
        ["aldmoor", "stannick", (300, 560), "thousand-fires"],
        "track",
        "The drovers' track west onto the steppe.",
    ),
    Road(
        "March road",
        ["aldmoor", (600, 640), (660, 700), (770, 708), "thanes-cross"],
        "track",
        "Calder's road north of the Thornwold to its march and Redmere.",
    ),
    Road(
        "Moor road",
        ["aldmoor", (520, 650), (450, 760), "morwick"],
        "track",
        "The road north across the Wrackmoor to the coast.",
    ),
    Road(
        "Coast road",
        ["gullhaven", (260, 170), "whitmarsh", (400, 215), "candor"],
        "track",
        "The coast track from Gullhaven to Candor, smugglers' and inquisitors' both.",
    ),
    Road(
        "Lantern coast road",
        ["candor", (530, 190), "sollen", (690, 175), (780, 175), "amaranthe"],
        "road",
        "The coast road from Candor east past Sollen to Amaranthe, through the hill forts on the border.",
    ),
    Road(
        "Houses' road",
        ["corvanne", "orsolin", "tessarine"],
        "road",
        "The road from Corvanne east through Orsolin to Tessarine.",
    ),
    Road(
        "Dulce road",
        ["amaranthe", (940, 180), "dulcamare", (1000, 250), "tessarine"],
        "track",
        "From Amaranthe east to Dulcamare and up the Dulce to Tessarine.",
    ),
    Road(
        "Quillane road",
        ["corvanne", "quillane", "sabrenne", "amaranthe"],
        "track",
        "The western road of the Lantern lands, by the small Houses' seats.",
    ),
    Road(
        "Glass road",
        ["tessarine", (1060, 305), "shardsend"],
        "track",
        "Three days from Tessarine to Shardsend on the Waste's rim.",
    ),
    Road(
        "Diggers' track",
        ["vaelholt", (1150, 560), (1230, 530), "vael-dig"],
        "track",
        "The Margrave's diggers' track into the Glass Waste: timber, rope and convicts east, nothing west.",
    ),
    Road(
        "Red Stair road",
        ["vaelholt", "kettleburn", "red-stair"],
        "trail",
        "North through the Anvils and over the Red Stair.",
    ),
    Road(
        "Harl road",
        ["vaelholt", (1020, 560), "harl", (975, 420), "tessarine"],
        "track",
        "From Vaelholt south through Harl to the Lantern lands.",
    ),
]


@dataclass
class Realm:
    id: str
    name: str
    shape: list[tuple[float, float]]
    description: str
    reference: str
    colour: str
    label: tuple[float, float, float, float]  # x, y, angle, size
    kind: str = "realm"
    border: bool = True
    takes_mountains: bool = False


REALMS = [
    Realm(
        "free-city-of-hask",
        "Free City of Hask",
        [(768, 470), (835, 462), (845, 520), (832, 578), (786, 585), (766, 540)],
        "The Free City of Hask and the farms, mills and ferry-hamlets it owns a day up and down the Ambre. A free "
        "city since the Bought Freedom of 901 RY.",
        "Free City of Hask",
        "#b8860b",
        (806, 492, 0, 8),
    ),
    Realm(
        "deephorn-hold",
        "Deephorn",
        [(770, 735), (860, 735), (880, 775), (840, 800), (775, 795), (755, 765)],
        "The dwarven hold of Deephorn and the high valleys around it, King Barrek Stonesong's.",
        "Deephorn",
        "#6b5b45",
        (820, 808, 0, 11),
        takes_mountains=True,
    ),
    Realm(
        "calder",
        "Kingdom of Calder",
        [
            (395, 368),
            (520, 358),
            (640, 382),
            (720, 418),
            (790, 452),
            (768, 470),
            (766, 540),
            (786, 585),
            (790, 640),
            (840, 650),
            (884, 618),
            (902, 640),
            (900, 705),
            (870, 728),
            (780, 728),
            (620, 718),
            (500, 725),
            (470, 745),
            (470, 1000),
            (380, 1000),
            (380, 700),
            (390, 520),
        ],
        "The Kingdom of Calder: castles, downs and sheep; an old king without an heir and barons who count the days.",
        "Kingdom of Calder",
        "#2e6b2e",
        (500, 625, 0, 24),
    ),
    Realm(
        "margravate",
        "Margravate",
        [
            (880, 470),
            (905, 612),
            (902, 640),
            (900, 705),
            (905, 740),
            (1000, 745),
            (1150, 732),
            (1220, 700),
            (1232, 600),
            (1205, 470),
            (1120, 440),
            (1000, 440),
            (930, 452),
        ],
        "The Margravate: iron, ash and gallows. Three hundred years under the Undying Margrave, Teodric Vael.",
        "Margravate",
        "#8a2a2a",
        (1080, 520, 0, 22),
    ),
    Realm(
        "lantern-principalities",
        "Lantern Principalities",
        [
            (690, 170),
            (820, 150),
            (950, 135),
            (1100, 140),
            (1125, 300),
            (1112, 385),
            (1000, 422),
            (930, 440),
            (845, 462),
            (790, 452),
            (720, 418),
            (680, 350),
            (668, 250),
        ],
        "The Lantern Principalities: seven princely Houses of Thaumarch blood, three of them strong (Corvanne, "
        "Tessarine, Amaranthe), all of them quarrelling.",
        "Lantern Principalities",
        "#6a3d8a",
        (890, 410, -8, 19),
    ),
    Realm(
        "sunward-theocracy",
        "Sunward Theocracy",
        [
            (300, 150),
            (420, 135),
            (560, 140),
            (670, 160),
            (690, 250),
            (690, 362),
            (640, 382),
            (520, 358),
            (395, 368),
            (330, 340),
            (305, 240),
        ],
        "The Sunward Theocracy of Aurel: whitewashed towns, sun-temples, inquisitors, burnt shrines. Ruled from "
        "Candor by the Hierarch.",
        "Sunward Theocracy",
        "#c9a227",
        (500, 350, 0, 20),
    ),
    Realm(
        "drowned-coast",
        "Drowned Coast",
        [(-40, -40), (300, -40), (305, 150), (305, 260), (180, 290), (-40, 290)],
        "The Drowned Coast: smugglers' coves, pirate isles, and Thaumarch towns that show their roofs at low tide.",
        "Drowned Coast",
        "#1f6f7a",
        (160, 225, 0, 17),
    ),
    Realm(
        "horse-steppe",
        "Horse Steppe",
        [(-40, 290), (180, 290), (305, 260), (330, 340), (395, 368), (390, 520), (380, 700), (380, 800), (-40, 800)],
        "The Horse Steppe: a sea of grass under Ulagh Khan's clans; horse archers, sky-burials, raids and trade "
        "with Calder.",
        "Horse Steppe",
        "#9a7b2a",
        (215, 600, 0, 24),
    ),
    Realm(
        "northern-holds",
        "Northern Holds",
        [
            (470, 790),
            (600, 782),
            (800, 790),
            (1000, 782),
            (1070, 870),
            (1080, 1040),
            (470, 1040),
            (470, 800),
            (380, 800),
            (380, 1040),
            (100, 1040),
            (100, 815),
        ],
        "The Northern Holds: fjords, longships and feuds. Jarls under the yearly Moot at Skarnholm, and no king.",
        "Northern Holds",
        "#3a5f8a",
        (720, 830, 0, 22),
        takes_mountains=True,
    ),
    Realm(
        "glass-waste",
        "Glass Waste",
        [
            (1150, 262),
            (1350, 245),
            (1555, 285),
            (1565, 470),
            (1545, 655),
            (1380, 662),
            (1225, 622),
            (1205, 470),
            (1130, 330),
        ],
        "The Glass Waste, where Ishavel burned on the night of the Unmaking. Nobody rules it.",
        "Glass Waste",
        "#7a7a5a",
        (1400, 560, 0, 24),
        kind="wilds",
        border=False,
    ),
    Realm(
        "greenmaw",
        "Greenmaw",
        [(1100, -40), (1640, -40), (1640, 250), (1450, 262), (1180, 252), (1100, 150)],
        "The Greenmaw: jungle, fever and serpent-temples older than the Thaumarchy. Tribes heed the Serpent Oracle "
        "of Zhaumal.",
        "Greenmaw",
        "#2a5a2a",
        (1250, 175, 0, 24),
        kind="wilds",
        border=False,
    ),
]

SEAS = [
    (
        "Iron Sea",
        "The Iron Sea: cold, grey, the Hold-folk's road to everywhere. Frozen along the shore in winter.",
        [(830, 985, 0, 26), (1400, 945, 0, 26), (25, 600, 90, 22)],
    ),
    (
        "Sunder Sea",
        (
            "The Sunder Sea: warm, busy, pirate-haunted. The ports of the Theocracy and the Lantern "
            "Principalities trade across it with the Southron coast."
        ),
        [(760, 90, 0, 26), (14, 300, 90, 18)],
    ),
]
SEA_SPLIT_Y = 330  # on the west coast: north of it is the Iron Sea

NOTES = [  # small lettering in the wilds
    ("orc tribes", 1265, 760, 0, 11),
    ("the Thousand Fires", 0, 0, 0, 0),
]


# ----------------------------------------------------------------------------------------------------------------------
# Rasters
# ----------------------------------------------------------------------------------------------------------------------


def to_px(x: float, y: float, scale: float = 1.0 / R) -> tuple[float, float]:
    """Bible miles to raster cells (y down)."""
    return x * scale, (H_MI - y) * scale


def coverage(polys: list[list[tuple[float, float]]], width: float = 0.0, line: bool = False, ss: int = 4) -> np.ndarray:
    """The share of each raster cell the polygons (or the lines, `width` miles each side) cover."""
    img = Image.new("L", (NX * ss, NY * ss), 0)
    d = ImageDraw.Draw(img)
    s = ss / R
    for p in polys:
        pts = [to_px(x, y, s) for x, y in p]
        if line:
            geom = LineString(p).buffer(width, cap_style="round", join_style="round")
            for g in getattr(geom, "geoms", [geom]):
                d.polygon([to_px(x, y, s) for x, y in g.exterior.coords], fill=255)
        else:
            d.polygon(pts, fill=255)
    small = img.resize((NX, NY), Image.BOX)
    return np.asarray(small, dtype=np.float32) / 255.0


def value_noise(rng: np.random.Generator, cell: float) -> np.ndarray:
    """Smooth value noise in [0, 1] over the raster, features about `cell` miles across."""
    c = cell / R
    gh, gw = int(NY / c) + 3, int(NX / c) + 3
    grid = rng.random((gh, gw)).astype(np.float32)
    ys = (np.arange(NY) + 0.5) / c
    xs = (np.arange(NX) + 0.5) / c
    y0 = np.floor(ys).astype(int)
    x0 = np.floor(xs).astype(int)
    ty = ys - y0
    tx = xs - x0
    ty = ty * ty * (3 - 2 * ty)
    tx = tx * tx * (3 - 2 * tx)
    a = grid[y0][:, x0]
    b = grid[y0][:, x0 + 1]
    cc = grid[y0 + 1][:, x0]
    dd = grid[y0 + 1][:, x0 + 1]
    top = a + (b - a) * tx[None, :]
    bot = cc + (dd - cc) * tx[None, :]
    return top + (bot - top) * ty[:, None]


def fbm(rng: np.random.Generator, cell: float, octaves: int = 5, gain: float = 0.5) -> np.ndarray:
    total = np.zeros((NY, NX), np.float32)
    amp, norm = 1.0, 0.0
    for _ in range(octaves):
        total += amp * value_noise(rng, cell)
        norm += amp
        amp *= gain
        cell /= 2.0
        if cell < R * 1.5:
            break
    # stretched to its full range, so that an amplitude means what it says
    lo, hi = np.quantile(total, [0.02, 0.98])
    return np.clip((total - lo) / (hi - lo), 0, 1)


def blur(a: np.ndarray, radius: int, passes: int = 3) -> np.ndarray:
    """A box blur `passes` times: close to a gaussian."""
    out = a.astype(np.float32)
    for _ in range(passes):
        for axis in (0, 1):
            pad = [(0, 0), (0, 0)]
            pad[axis] = (radius + 1, radius)
            p = np.pad(out, pad, mode="edge")
            cs = np.cumsum(p, axis=axis)
            n = 2 * radius + 1
            if axis == 0:
                out = (cs[n:, :] - cs[:-n, :]) / n
            else:
                out = (cs[:, n:] - cs[:, :-n]) / n
    return out


def warp(a: np.ndarray, wx: np.ndarray, wy: np.ndarray) -> np.ndarray:
    """`a` sampled at each cell displaced by (wx, wy) miles."""
    jj, ii = np.meshgrid(np.arange(NX), np.arange(NY))
    j = np.clip(np.round(jj + wx / R).astype(int), 0, NX - 1)
    i = np.clip(np.round(ii - wy / R).astype(int), 0, NY - 1)
    return a[i, j]


def cell_xy() -> tuple[np.ndarray, np.ndarray]:
    """Each raster cell's centre, in bible miles."""
    xs = (np.arange(NX) + 0.5) * R
    ys = H_MI - (np.arange(NY) + 0.5) * R
    return np.meshgrid(xs, ys)


def disc(cx: float, cy: float, r: float) -> np.ndarray:
    X, Y = cell_xy()
    return (X - cx) ** 2 + (Y - cy) ** 2 <= r * r


@dataclass
class World:
    land: np.ndarray  # bool
    lake: np.ndarray  # bool
    terrain: np.ndarray  # class index per cell (CLASSES)
    realm: np.ndarray  # REALMS index, -1 none
    shade: np.ndarray  # float noise for the picture's texture


CLASSES = ["plains", "forest", "hills", "mountain", "swamp", "desert", "arctic", "jungle", "sea", "lake"]
CI = {c: i for i, c in enumerate(CLASSES)}


def fill_pools(land: np.ndarray) -> np.ndarray:
    """`land` with the water that doesn't reach the map's edge filled in: pools the noise left inland."""
    water = ~land
    seen = np.zeros_like(water)
    seen[0, :], seen[-1, :], seen[:, 0], seen[:, -1] = water[0, :], water[-1, :], water[:, 0], water[:, -1]
    while True:
        grown = seen.copy()
        grown[1:, :] |= seen[:-1, :]
        grown[:-1, :] |= seen[1:, :]
        grown[:, 1:] |= seen[:, :-1]
        grown[:, :-1] |= seen[:, 1:]
        grown &= water
        if (grown == seen).all():
            return land | (water & ~seen)
        seen = grown


def make_world() -> World:
    rng = np.random.default_rng(SEED)
    X, Y = cell_xy()

    # --- land: the coast and isles, warped and roughened by noise; fjords cut into the Holds ---
    sw = np.clip((330 - X) / 160, 0, 1) * np.clip((320 - Y) / 160, 0, 1)  # the Drowned Coast breaks up
    cwx = (fbm(rng, 170, 5, 0.6) - 0.5) * 80 + (fbm(rng, 50, 3) - 0.5) * 30
    cwy = (fbm(rng, 170, 5, 0.6) - 0.5) * 80 + (fbm(rng, 50, 3) - 0.5) * 30
    coast = warp(blur(coverage([COAST]), 2), cwx * (1 - 0.6 * sw), cwy * (1 - 0.6 * sw))
    isles = warp(blur(coverage(ISLES), 2), cwx * 0.5, cwy * 0.5) + 0.35 * (fbm(rng, 14, 3) - 0.5)
    fine = fbm(rng, 28, 5, 0.6) - 0.5
    v = np.maximum(coast, isles) + 0.55 * fine * (1 + 1.6 * sw)
    land = v > 0.5
    fjords = coverage([meander(f, rng, 0.18, 4) for f in FJORDS], 2.6, line=True) > 0.35
    land &= ~fjords
    for (cx, cy), r in DRY:
        land |= disc(cx, cy, r)
    # the sea around Amaranthe and the Ambre's mouth stays open for the river
    land &= ~(((X - 860) ** 2 / 9 + (Y - 140) ** 2 / 64) <= 1.0)
    land = fill_pools(land)

    # --- terrain ---
    wx = (fbm(rng, 60, 4) - 0.5) * 40
    wy = (fbm(rng, 60, 4) - 0.5) * 40
    terrain = np.full((NY, NX), CI["plains"], np.int8)

    def put(mask: np.ndarray, cls: str) -> None:
        terrain[mask & land] = CI[cls]

    # scattered woods first; the named areas paint over them
    woods_noise = fbm(rng, 40, 5, 0.55)
    for poly, share in WOODS:
        region = coverage([poly]) > 0.5
        if not region.any():
            continue
        thr = np.quantile(woods_noise[region & land], 1 - share) if (region & land).any() else 1
        put(region & (woods_noise > thr), "forest")
    # the steppe and the Waste have no woods
    order = ["jungle", "desert", "forest", "swamp", "arctic", "hills", "mountain"]
    hills_noise = fbm(rng, 30, 4)
    edge_noise = fbm(rng, 22, 4, 0.6)
    for cls in order:
        for a in AREAS:
            if a.kind != cls:
                continue
            cov = blur(coverage([a.shape], a.width, line=a.width > 0), 3)
            rough = 0.8 if cls in ("mountain", "hills") else 0.5
            mask = warp(cov, wx, wy) + rough * (edge_noise - 0.5) > 0.5
            if a.name == "Hornwall":
                # the west is lower: hills more than peaks
                lower = (X < 580) & (hills_noise > 0.45)
                put(mask & ~lower, "mountain")
                put(mask & lower, "hills")
                continue
            if a.name == "Smoking Hills":
                put(mask, "hills")
                put(mask & (hills_noise > 0.62), "mountain")
                continue
            if a.name == "Glass Waste":
                put(mask, "desert")
                continue
            if cls == "hills":
                put(mask & (hills_noise > 0.28), "hills")
                continue
            put(mask, cls)
    # the Holds: fells between the fjords, ice on the heights
    holds_area = [(470, 805), (560, 795), (700, 802), (860, 798), (1000, 805), (1040, 870), (1060, 1000), (470, 1000)]
    holds = warp(blur(coverage([holds_area]), 4), wx, wy) + 0.6 * (edge_noise - 0.5) > 0.5
    fells = fbm(rng, 34, 5, 0.55)
    put(holds & (fells > 0.6), "hills")
    put(holds & (fells > 0.72), "mountain")
    put(holds & (Y > 935) & (fells > 0.66), "arctic")

    lake = np.zeros((NY, NX), bool)
    for _, poly, _, _ in LAKES:
        lake |= blur(coverage([poly]), 2) + 0.3 * (edge_noise - 0.5) > 0.5
    lake &= land
    terrain[lake] = CI["lake"]
    terrain[~land] = CI["sea"]

    # --- realms: each realm's shape, roughened, in order; mountains stay unclaimed unless a realm takes them ---
    rx = (fbm(rng, 90, 4) - 0.5) * 44 + (fbm(rng, 28, 3) - 0.5) * 18
    ry = (fbm(rng, 90, 4) - 0.5) * 44 + (fbm(rng, 28, 3) - 0.5) * 18
    realm = np.full((NY, NX), -1, np.int8)
    thornwold = terrain == CI["forest"]
    thornwold &= warp(coverage([next(a.shape for a in AREAS if a.name == "Thornwold")]), wx, wy) > 0.5
    for k, r in enumerate(REALMS):
        mask = warp(coverage([r.shape]), rx, ry) > 0.5
        if r.id == "free-city-of-hask":
            mask = warp(coverage([r.shape]), rx * 0.3, ry * 0.3) > 0.5
        mask &= land & (realm < 0) & ~thornwold
        if not r.takes_mountains and r.kind == "realm":
            mask &= terrain != CI["mountain"]
        realm[mask] = k
    shade = fbm(rng, 12, 3)
    return World(land, lake, terrain, realm, shade)


# ----------------------------------------------------------------------------------------------------------------------
# Raster to shapes
# ----------------------------------------------------------------------------------------------------------------------


def mask_shape(mask: np.ndarray, simplify: float = 1.2, smooth: float = 1.5) -> shapely.Geometry:
    """The mask as polygons in bible miles: its rows' runs as boxes, joined, simplified and softened."""
    boxes = []
    for i in range(NY):
        row = mask[i]
        if not row.any():
            continue
        d = np.diff(np.concatenate([[0], row.astype(np.int8), [0]]))
        starts = np.where(d == 1)[0]
        ends = np.where(d == -1)[0]
        y1 = H_MI - i * R
        y0 = y1 - R
        for s, e in zip(starts, ends, strict=True):
            boxes.append(box(s * R, y0, e * R, y1))
    if not boxes:
        return Polygon()
    shape = unary_union(boxes)
    shape = shape.buffer(smooth, join_style="round").buffer(-smooth, join_style="round")
    return shape.simplify(simplify)


def polys(geom: shapely.Geometry, min_area: float = 0.0) -> list[Polygon]:
    if geom.is_empty:
        return []
    out = list(geom.geoms) if isinstance(geom, MultiPolygon | shapely.GeometryCollection) else [geom]
    return [p for p in out if isinstance(p, Polygon) and p.area >= min_area]


def meander(points: list[tuple[float, float]], rng: np.random.Generator, amp: float = 0.12, depth: int = 4):
    """A line through `points`, its segments bent by midpoint displacement."""
    pts = [np.array(p, float) for p in points]
    for _ in range(depth):
        out = [pts[0]]
        for a, b in pairwise(pts):
            m = (a + b) / 2
            d = b - a
            n = np.array([-d[1], d[0]])
            m = m + n * rng.uniform(-amp, amp)
            out += [m, b]
        pts = out
        amp *= 0.85
    return [tuple(p) for p in pts]


# ----------------------------------------------------------------------------------------------------------------------
# The hex grid
# ----------------------------------------------------------------------------------------------------------------------


def grid_spec() -> dict:
    size_km = HEX_MI * MILE_KM
    r = size_km / math.sqrt(3)
    w_km, h_km = W_MI * MILE_KM, H_MI * MILE_KM
    cols = math.ceil((w_km - 2 * r) / (1.5 * r)) + 1
    rows = math.ceil(h_km / size_km)
    return {"kind": "hex", "size_km": size_km, "cols": cols, "rows": rows, "origin": [0.0, 0.0], "orientation": "flat"}


def hex_centre_mi(g: dict, col: int, row: int) -> tuple[float, float]:
    """A hex's centre in bible miles (y north)."""
    s = g["size_km"]
    r = s / math.sqrt(3)
    x_km = r + 1.5 * r * col
    y_km = s * (row + 0.5 + 0.5 * (col & 1))
    return x_km / MILE_KM, H_MI - y_km / MILE_KM


def hex_terrain(world: World, g: dict) -> list[str]:
    """Each hex's class: the commonest among the raster cells under it, sea when most of it is sea."""
    r_mi = HEX_MI / math.sqrt(3)
    offs = [(0, 0)] + [
        (0.6 * r_mi * math.cos(math.radians(a)), 0.6 * r_mi * math.sin(math.radians(a))) for a in range(0, 360, 30)
    ]
    out = []
    for row in range(g["rows"]):
        for col in range(g["cols"]):
            cx, cy = hex_centre_mi(g, col, row)
            votes: dict[int, int] = {}
            for dx, dy in offs:
                j = int((cx + dx) / R)
                i = int((H_MI - (cy + dy)) / R)
                if 0 <= i < NY and 0 <= j < NX:
                    t = int(world.terrain[i, j])
                    votes[t] = votes.get(t, 0) + 1
            if not votes:
                out.append("sea")
                continue
            sea = votes.get(CI["sea"], 0)
            if sea * 2 > sum(votes.values()):
                out.append("sea")
                continue
            land_votes = {k: v for k, v in votes.items() if k != CI["sea"]}
            # mountains and hills show when a third of the hex is high
            pick = max(land_votes, key=lambda k: land_votes[k] * (1.6 if k in (CI["mountain"], CI["hills"]) else 1))
            out.append(CLASSES[pick])
    return out


def hex_land_class(world: World, g: dict) -> list[str]:
    """Each hex's commonest land class (for the land part of a coast hex), plains when it has none."""
    r_mi = HEX_MI / math.sqrt(3)
    offs = [(0, 0)] + [
        (0.7 * r_mi * math.cos(math.radians(a)), 0.7 * r_mi * math.sin(math.radians(a))) for a in range(0, 360, 30)
    ]
    out = []
    for row in range(g["rows"]):
        for col in range(g["cols"]):
            cx, cy = hex_centre_mi(g, col, row)
            votes: dict[int, int] = {}
            for dx, dy in offs:
                j, i = int((cx + dx) / R), int((H_MI - (cy + dy)) / R)
                if 0 <= i < NY and 0 <= j < NX and world.land[i, j]:
                    t = int(world.terrain[i, j])
                    if t != CI["lake"]:
                        votes[t] = votes.get(t, 0) + 1
            out.append(CLASSES[max(votes, key=votes.get)] if votes else "plains")
    return out


# ----------------------------------------------------------------------------------------------------------------------
# Features: the Delve document
# ----------------------------------------------------------------------------------------------------------------------


def km(x: float, y: float) -> list[float]:
    return [round(x * MILE_KM, 3), round((H_MI - y) * MILE_KM, 3)]


def ring_km(p: Polygon) -> list[list[list[float]]]:
    rings = [p.exterior] + list(p.interiors)
    return [[km(x, y) for x, y in r.coords] for r in rings]


def slug(name: str) -> str:
    return "".join(c if c.isalnum() else "-" for c in name.lower().replace("'", "")).strip("-")


def feature(fid, layer, kind, name, geometry, description="", reference="", tags=None, **props) -> dict:
    p = {
        "layer": layer,
        "kind": kind,
        "name": name,
        "description": description,
        "dm_notes": "",
        "tags": tags or [],
        "hidden": False,
    }
    if reference:
        p["reference"] = reference
    p.update({k: v for k, v in props.items() if v is not None})
    return {"type": "Feature", "id": fid, "geometry": geometry, "properties": p}


def place_xy(stop) -> tuple[float, float]:
    if isinstance(stop, str):
        p = next(p for p in PLACES if p.id == stop)
        return (p.x, p.y)
    return stop


@dataclass
class Lines:
    rivers: list[tuple[River, list[tuple[float, float]]]]
    roads: list[tuple[Road, list[tuple[float, float]]]]
    land_shape: shapely.Geometry
    realm_shapes: list[list[Polygon]]


def make_lines(world: World) -> Lines:
    rng = np.random.default_rng(SEED + 1)
    land_shape = mask_shape(world.land | world.lake, 0.8, 1.0)
    land_plus = land_shape.buffer(1.0)
    rivers = []
    for r in RIVERS:
        line = LineString(meander(r.points, rng, 0.16, 5))
        clipped = line.intersection(land_plus)
        parts = [g for g in getattr(clipped, "geoms", [clipped]) if isinstance(g, LineString) and not g.is_empty]
        if not parts:
            continue
        best = max(parts, key=lambda g: g.length)
        coords = list(best.coords)
        # keep source to mouth
        if math.dist(coords[0], r.points[0]) > math.dist(coords[-1], r.points[0]):
            coords.reverse()
        rivers.append((r, coords))
    roads = []
    for rd in ROADS:
        pts = [place_xy(s) for s in rd.stops]
        roads.append((rd, meander(pts, rng, 0.05, 3)))
    realm_shapes = [polys(mask_shape(world.realm == k, 1.0, 2.0), 40.0) for k in range(len(REALMS))]
    return Lines(rivers, roads, land_shape, realm_shapes)


def make_features(world: World, lines: Lines) -> list[dict]:
    feats: list[dict] = []
    # seas
    frame = box(-1, -1, W_MI + 1, H_MI + 1)
    sea = frame.difference(lines.land_shape)
    north = sea.intersection(box(-1, SEA_SPLIT_Y, W_MI + 1, H_MI + 1))
    south = sea.intersection(box(-1, -1, W_MI + 1, SEA_SPLIT_Y))
    for (name, desc, _), geom in zip(SEAS, (north, south), strict=True):
        for n, p in enumerate(sorted(polys(geom, 1.0), key=lambda p: -p.area)):
            feats.append(
                feature(
                    f"{slug(name)}-{n + 1}" if n else slug(name),
                    "water",
                    "sea",
                    name,
                    {"type": "Polygon", "coordinates": ring_km(p)},
                    desc if n == 0 else "",
                    tags=[] if n == 0 else ["part"],
                )
            )
    # lakes
    lake_shape = mask_shape(world.lake, 0.5, 0.8)
    for p in polys(lake_shape, 4.0):
        c = p.centroid
        name, _, desc, ref = min(LAKES, key=lambda lk: Polygon(lk[1]).centroid.distance(c))
        feats.append(
            feature(slug(name), "water", "lake", name, {"type": "Polygon", "coordinates": ring_km(p)}, desc, ref)
        )
    # rivers
    unnamed = 0
    for r, coords in lines.rivers:
        if r.name:
            fid, name = slug(r.name), r.name
        else:
            unnamed += 1
            fid, name = f"stream-{unnamed}", ""
        feats.append(
            feature(
                fid,
                "water",
                "river",
                name,
                {"type": "LineString", "coordinates": [km(*c) for c in coords]},
                r.description,
                r.reference,
            )
        )
    # realms
    for k, r in enumerate(REALMS):
        parts = sorted(lines.realm_shapes[k], key=lambda p: -p.area)
        for n, p in enumerate(parts):
            feats.append(
                feature(
                    r.id if n == 0 else f"{r.id}-{n + 1}",
                    "regions",
                    r.kind,
                    r.name,
                    {"type": "Polygon", "coordinates": ring_km(p)},
                    r.description if n == 0 else "",
                    r.reference,
                )
            )
    # named terrain areas
    kinds = {
        "mountain": "mountains",
        "hills": "hills",
        "forest": "forest",
        "desert": "desert",
        "jungle": "jungle",
        "swamp": "swamp",
        "arctic": "glacier",
    }
    for a in AREAS:
        if not a.named:
            continue
        near = coverage([a.shape], a.width + 25 if a.width else 25, line=True) > 0.3
        near |= coverage([a.shape]) > 0.5
        cls = a.kind
        mask = near & (world.terrain == CI[cls])
        if a.name == "Hornwall":
            mask = (
                near
                & np.isin(world.terrain, [CI["mountain"], CI["hills"]])
                & (coverage([a.shape], a.width + 8, line=True) > 0.3)
            )
        if a.name == "Smoking Hills":
            mask = near & np.isin(world.terrain, [CI["mountain"], CI["hills"]])
        parts = sorted(polys(mask_shape(mask, 1.2, 2.0), 30.0), key=lambda p: -p.area)
        for n, p in enumerate(parts[:6]):
            fid = f"{slug(a.name)}-{kinds[cls]}"
            feats.append(
                feature(
                    fid if n == 0 else f"{fid}-{n + 1}",
                    "regions",
                    kinds[cls],
                    a.name,
                    {"type": "Polygon", "coordinates": ring_km(p)},
                    a.description if n == 0 else "",
                    a.reference,
                )
            )
    # roads
    for rd, pts in lines.roads:
        feats.append(
            feature(
                slug(rd.name),
                "routes",
                rd.kind,
                rd.name,
                {"type": "LineString", "coordinates": [km(*c) for c in pts]},
                rd.description,
                surface={"road": "paved", "track": "dirt", "trail": "trail"}[rd.kind],
            )
        )
    # places
    for p in PLACES:
        feats.append(
            feature(
                p.id,
                "places",
                p.kind,
                p.name,
                {"type": "Point", "coordinates": km(p.x, p.y)},
                p.description,
                p.reference,
                list(p.tags),
                population=p.pop,
                rank=p.rank,
            )
        )
    return feats


def make_doc(world: World) -> tuple[dict, Lines]:
    g = grid_spec()
    lines = make_lines(world)
    classes = hex_terrain(world, g)
    from delve.maps.geo.terrain import TERRAIN_LETTERS

    letters = "".join(TERRAIN_LETTERS["swamp" if c == "swamp" else c] for c in classes)
    doc = {
        "type": "FeatureCollection",
        "delve": {
            "version": 1,
            "frame": {"width_km": W_MI * MILE_KM, "height_km": H_MI * MILE_KM, "units": "miles"},
            "grid": g,
            "terrain": letters,
        },
        "features": make_features(world, lines),
    }
    return doc, lines


# ----------------------------------------------------------------------------------------------------------------------
# The picture
# ----------------------------------------------------------------------------------------------------------------------

FINAL_PX = 3  # pixels per mile in the stored picture
SS = 2  # drawn at this many times that, then shrunk
P = FINAL_PX * SS
PW, PH = int(W_MI * P), int(H_MI * P)

FONT_DIR = "/usr/share/fonts/truetype/freefont/"
FONTS = {
    "regular": "FreeSerif.ttf",
    "bold": "FreeSerifBold.ttf",
    "italic": "FreeSerifItalic.ttf",
    "bolditalic": "FreeSerifBoldItalic.ttf",
}

PAPER = (244, 238, 214)
SEA = (171, 205, 226)
SEA_LINE = (120, 160, 192)
COAST_LINE = (58, 100, 140)
HEX_FILL = {
    "plains": (233, 232, 190),
    "forest": (196, 222, 160),
    "hills": (232, 212, 160),
    "mountain": (214, 186, 140),
    "swamp": (196, 220, 196),
    "desert": (226, 218, 182),
    "arctic": (244, 246, 246),
    "jungle": (170, 206, 140),
    "sea": SEA,
    "lake": (120, 170, 210),
}
STEPPE = (236, 228, 168)
RIVER = (46, 104, 168)
ROAD = (150, 50, 30)
BORDER = (170, 30, 30)
INK = (34, 28, 22)


def px(x: float, y: float) -> tuple[float, float]:
    return x * P, (H_MI - y) * P


def font(kind: str, size: float) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(FONT_DIR + FONTS[kind], max(6, int(size)))


def upmask(a: np.ndarray, soften: float = 2.0) -> Image.Image:
    """A raster mask at the picture's size, its stair-steps smoothed away."""
    img = Image.fromarray((a * 255).astype(np.uint8)).resize((PW, PH), Image.BILINEAR)
    img = img.filter(ImageFilter.GaussianBlur(soften * SS))
    return img.point(lambda v: 255 if v >= 128 else 0)


def hex_px(g: dict, i: int) -> tuple[tuple[float, float], list[tuple[float, float]]]:
    from delve.maps.geo.grid import cell_centre, cell_polygon
    from delve.maps.geo.model import Grid

    grid = Grid("hex", g["size_km"], g["cols"], g["rows"], tuple(g["origin"]), "flat")
    k = P / MILE_KM
    cx, cy = cell_centre(grid, i)
    return (cx * k, cy * k), [(x * k, y * k) for x, y in cell_polygon(grid, i)]


def dashed(d: ImageDraw.ImageDraw, pts, fill, width, pattern) -> None:
    """A polyline in dashes: `pattern` is [on, off, on, off, ...] in pixels."""
    seg = 0
    left = pattern[0]
    on = True
    for a, b in pairwise(pts):
        ax, ay = a
        bx, by = b
        length = math.hypot(bx - ax, by - ay)
        pos = 0.0
        while pos < length:
            step = min(left, length - pos)
            t0, t1 = pos / length, (pos + step) / length
            if on:
                d.line(
                    [(ax + (bx - ax) * t0, ay + (by - ay) * t0), (ax + (bx - ax) * t1, ay + (by - ay) * t1)],
                    fill=fill,
                    width=width,
                )
            pos += step
            left -= step
            if left <= 1e-6:
                seg = (seg + 1) % len(pattern)
                left = pattern[seg]
                on = seg % 2 == 0


def symbol(
    d: ImageDraw.ImageDraw, cls: str, c: tuple[float, float], r: float, rng: np.random.Generator, steppe: bool
) -> None:
    """The terrain drawn in one hex, centred at `c`, the hex `r` pixels from centre to corner."""
    cx, cy = c
    j = lambda s: rng.uniform(-s, s)
    lw = max(1, int(SS * 1.1))
    if cls == "mountain":
        for dx, dy, s in ((-0.38, 0.2, 0.42), (0.38, 0.22, 0.4), (0.0, 0.05, 0.62)):
            x, y, h = cx + (dx + j(0.05)) * r, cy + (dy + j(0.04)) * r, s * r
            top, left, right, foot = (
                (x, y - h),
                (x - h * 0.85, y + h * 0.45),
                (x + h * 0.85, y + h * 0.45),
                (x + h * 0.1, y + h * 0.45),
            )
            d.polygon([top, left, foot], fill=(226, 200, 156))
            d.polygon([top, foot, right], fill=(150, 104, 60))
            d.line([left, top, right], fill=(92, 58, 28), width=lw + 1)
            d.line([top, (x + h * 0.05, y + h * 0.05)], fill=(92, 58, 28), width=lw)
    elif cls == "hills":
        for dx, dy, s in ((-0.32, 0.18, 0.3), (0.3, 0.2, 0.28), (0.0, -0.12, 0.34)):
            x, y, h = cx + (dx + j(0.06)) * r, cy + (dy + j(0.05)) * r, s * r
            d.arc([x - h, y - h * 0.7, x + h, y + h * 0.7], 200, 340, fill=(120, 86, 40), width=lw + 1)
            d.arc([x - h * 0.55, y - h * 0.25, x + h * 0.25, y + h * 0.35], 210, 300, fill=(150, 112, 60), width=lw)
    elif cls in ("forest", "jungle"):
        crown = (52, 112, 52) if cls == "forest" else (30, 90, 46)
        edge = (28, 70, 30) if cls == "forest" else (16, 56, 26)
        spots = [(-0.35, 0.15), (0.32, 0.18), (0.0, -0.22), (-0.05, 0.38), (0.4, -0.2), (-0.4, -0.2)]
        n = 4 if cls == "forest" else 6
        for dx, dy in spots[:n]:
            x, y, s = cx + (dx + j(0.06)) * r, cy + (dy + j(0.06)) * r, r * (0.17 + j(0.02))
            d.line([(x, y + s * 0.6), (x, y + s * 1.5)], fill=(90, 64, 34), width=lw)
            d.ellipse([x - s, y - s * 1.05, x + s, y + s * 0.85], fill=crown, outline=edge, width=lw)
    elif cls == "swamp":
        col = (52, 104, 92)
        for dx, dy in ((-0.32, 0.05), (0.28, 0.1), (-0.02, -0.28), (0.05, 0.38)):
            x, y = cx + (dx + j(0.06)) * r, cy + (dy + j(0.05)) * r
            for a in (-30, 0, 30):
                t = math.radians(a - 90)
                d.line([(x, y), (x + math.cos(t) * r * 0.2, y + math.sin(t) * r * 0.2)], fill=col, width=lw)
            d.line([(x - r * 0.18, y + r * 0.04), (x + r * 0.18, y + r * 0.04)], fill=(70, 130, 170), width=lw)
    elif cls == "desert":
        for _ in range(7):
            x, y = cx + j(0.62) * r, cy + j(0.55) * r
            d.ellipse([x - SS * 1.1, y - SS * 1.1, x + SS * 1.1, y + SS * 1.1], fill=(150, 130, 90))
        for _ in range(3):
            x, y, s = cx + j(0.45) * r, cy + j(0.4) * r, r * 0.16
            d.polygon(
                [(x, y - s), (x + s * 0.6, y + s * 0.2), (x - s * 0.1, y + s * 0.7), (x - s * 0.55, y)],
                fill=(122, 160, 150),
                outline=(60, 90, 84),
            )
    elif cls == "arctic":
        for _ in range(3):
            x, y, s = cx + j(0.5) * r, cy + j(0.45) * r, r * 0.14
            d.line([(x - s, y), (x + s, y)], fill=(130, 165, 190), width=lw)
            d.line([(x - s * 0.5, y + s * 0.5), (x + s * 0.5, y + s * 0.5)], fill=(130, 165, 190), width=lw)
    elif cls == "plains" and steppe:
        for _ in range(3):
            x, y = cx + j(0.5) * r, cy + j(0.45) * r
            for a in (-25, 0, 25):
                t = math.radians(a - 90)
                d.line(
                    [(x, y), (x + math.cos(t) * r * 0.12, y + math.sin(t) * r * 0.12)], fill=(150, 140, 70), width=lw
                )


def text_img(text: str, f: ImageFont.FreeTypeFont, fill, halo, spacing: float = 0.0, halo_w: int = 3) -> Image.Image:
    """`text` on a transparent image, letter-spaced by `spacing` ems, with a halo."""
    chars = list(text)
    widths = [f.getlength(ch) for ch in chars]
    gap = spacing * f.size
    w = int(sum(widths) + gap * (len(chars) - 1) + 4 * halo_w + 4)
    asc, desc = f.getmetrics()
    h = asc + desc + 4 * halo_w
    img = Image.new("RGBA", (max(1, w), h), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    x = 2 * halo_w
    for ch, cw in zip(chars, widths, strict=True):
        d.text(
            (x, 2 * halo_w),
            ch,
            font=f,
            fill=fill,
            stroke_width=halo_w if halo else 0,
            stroke_fill=halo if halo else None,
        )
        x += cw + gap
    return img


def put_text(
    canvas: Image.Image,
    text: str,
    at: tuple[float, float],
    f,
    fill,
    halo=PAPER,
    spacing=0.0,
    angle=0.0,
    anchor="c",
    halo_w=None,
) -> tuple[float, float, float, float]:
    hw = halo_w if halo_w is not None else max(2, int(f.size * 0.12))
    img = text_img(text, f, fill, halo, spacing, hw)
    if angle:
        img = img.rotate(angle, resample=Image.BICUBIC, expand=True)
    w, h = img.size
    x, y = at
    ox = {"c": w / 2, "e": 0, "w": w}[anchor[-1] if anchor[-1] in "ew" else "c"]
    oy = h / 2
    if anchor.startswith("n"):
        oy = h
    elif anchor.startswith("s"):
        oy = 0
    left, top = int(x - ox), int(y - oy)
    canvas.alpha_composite(img, (left, top)) if canvas.mode == "RGBA" else canvas.paste(img, (left, top), img)
    return left, top, left + w, top + h


def render(world: World, doc: dict, lines: Lines) -> Image.Image:
    g = doc["delve"]["grid"]
    letters = doc["delve"]["terrain"]
    from delve.maps.geo.terrain import TERRAIN_OF_LETTER

    classes = [TERRAIN_OF_LETTER.get(ch, "plains") for ch in letters]
    land_cls = hex_land_class(world, g)
    rng = np.random.default_rng(SEED + 2)
    hexes = [hex_px(g, i) for i in range(g["cols"] * g["rows"])]
    r_hex = HEX_MI / math.sqrt(3) * P
    steppe_k = next(k for k, r in enumerate(REALMS) if r.id == "horse-steppe")

    def realm_at(c) -> int:
        j, i = int(c[0] / P / R), int(c[1] / P / R)
        return int(world.realm[i, j]) if 0 <= i < NY and 0 <= j < NX else -1

    # --- land, hex by hex, inside a smooth coast ---
    canvas = Image.new("RGB", (PW, PH), SEA)
    land_layer = Image.new("RGB", (PW, PH), HEX_FILL["plains"])
    d = ImageDraw.Draw(land_layer)
    for i, (c, poly) in enumerate(hexes):
        cls = classes[i] if classes[i] not in ("sea", "lake") else land_cls[i]
        fill = HEX_FILL.get(cls, HEX_FILL["plains"])
        if cls == "plains" and realm_at(c) == steppe_k:
            fill = STEPPE
        d.polygon(poly, fill=fill)
    land_mask = upmask(world.land.astype(np.float32))
    canvas.paste(land_layer, (0, 0), land_mask)
    lake_mask = upmask(world.lake.astype(np.float32), 1.0)
    canvas.paste(Image.new("RGB", (PW, PH), HEX_FILL["lake"]), (0, 0), lake_mask)

    # --- coast: a dark line, and a pale ripple off it ---
    ripple = land_mask.filter(ImageFilter.MaxFilter(13 * SS + 1))
    ripple_in = land_mask.filter(ImageFilter.MaxFilter(11 * SS + 1))
    ring = Image.fromarray(((np.asarray(ripple) > 0) & ~(np.asarray(ripple_in) > 0)).astype(np.uint8) * 255)
    canvas.paste(Image.new("RGB", (PW, PH), (150, 188, 214)), (0, 0), ring)
    for m in (land_mask, lake_mask):
        grown = m.filter(ImageFilter.MaxFilter(2 * SS + 1))
        edge = Image.fromarray(((np.asarray(grown) > 0) & ~(np.asarray(m) > 0)).astype(np.uint8) * 255)
        canvas.paste(Image.new("RGB", (PW, PH), COAST_LINE), (0, 0), edge)
    canvas = canvas.convert("RGBA")

    # --- the hex grid ---
    grid_layer = Image.new("RGBA", (PW, PH), (0, 0, 0, 0))
    gd = ImageDraw.Draw(grid_layer)
    for _, poly in hexes:
        gd.line(poly, fill=(96, 86, 66, 70), width=SS)
    canvas.alpha_composite(grid_layer)

    # --- terrain drawn in the hexes ---
    sym = Image.new("RGBA", (PW, PH), (0, 0, 0, 0))
    sd = ImageDraw.Draw(sym)
    for i, (c, _) in enumerate(hexes):
        cls = classes[i]
        if cls in ("sea", "lake"):
            continue
        symbol(sd, cls, c, r_hex, rng, realm_at(c) == steppe_k)
    sym_mask = land_mask.filter(ImageFilter.MinFilter(3 * SS + 1))
    sym.putalpha(Image.fromarray(np.minimum(np.asarray(sym.getchannel("A")), np.asarray(sym_mask))))
    canvas.alpha_composite(sym)

    # --- realm borders: a band of the realm's colour inside, a dashed line on the border ---
    sea_shape = box(-5, -5, W_MI + 5, H_MI + 5).difference(lines.land_shape).buffer(3.0)
    band = Image.new("RGBA", (PW, PH), (0, 0, 0, 0))
    border = Image.new("RGBA", (PW, PH), (0, 0, 0, 0))
    bd = ImageDraw.Draw(border)
    for k, r in enumerate(REALMS):
        if not r.border:
            continue
        rgb = tuple(int(r.colour[n : n + 2], 16) for n in (1, 3, 5))
        layer = Image.new("RGBA", (PW, PH), (0, 0, 0, 0))
        ld = ImageDraw.Draw(layer)
        for p in lines.realm_shapes[k]:
            edge = p.exterior.difference(sea_shape)
            for e in getattr(edge, "geoms", [edge]):
                if e.is_empty or not hasattr(e, "coords"):
                    continue
                pts = [px(x, y) for x, y in e.coords]
                ld.line(pts, fill=(*rgb, 150), width=int(6 * SS * 2), joint="curve")
                dashed(bd, pts, (*BORDER, 255), int(1.8 * SS), [8 * SS, 3 * SS, 2 * SS, 3 * SS])
        inside = upmask((world.realm == k).astype(np.float32), 1.5)
        layer.putalpha(Image.fromarray(np.minimum(np.asarray(layer.getchannel("A")), np.asarray(inside))))
        band.alpha_composite(layer)
    canvas.alpha_composite(band)
    canvas.alpha_composite(border)

    # --- rivers, roads ---
    water = Image.new("RGBA", (PW, PH), (0, 0, 0, 0))
    wd = ImageDraw.Draw(water)
    for r, coords in lines.rivers:
        n = len(coords)
        for a in range(n - 1):
            t = (a + 1) / n
            w = max(1.0, (0.6 + r.width * t) * SS * 1.2)
            wd.line([px(*coords[a]), px(*coords[a + 1])], fill=(*RIVER, 255), width=round(w), joint="curve")
    water.putalpha(
        Image.fromarray(
            np.minimum(
                np.asarray(water.getchannel("A")), np.asarray(land_mask.filter(ImageFilter.MaxFilter(2 * SS + 1)))
            )
        )
    )
    canvas.alpha_composite(water)
    rd_layer = Image.new("RGBA", (PW, PH), (0, 0, 0, 0))
    rdd = ImageDraw.Draw(rd_layer)
    for rd, pts in lines.roads:
        ppts = [px(*p) for p in pts]
        if rd.kind == "road":
            rdd.line(ppts, fill=(*ROAD, 235), width=int(1.6 * SS), joint="curve")
        elif rd.kind == "track":
            dashed(rdd, ppts, (*ROAD, 230), int(1.4 * SS), [6 * SS, 3 * SS])
        else:
            dashed(rdd, ppts, (*ROAD, 220), int(1.3 * SS), [2 * SS, 3 * SS])
    canvas.alpha_composite(rd_layer)

    # --- places ---
    pd = ImageDraw.Draw(canvas)
    for p in PLACES:
        x, y = px(p.x, p.y)
        s = SS
        if p.rank == "capital":
            pd.rectangle([x - 5 * s, y - 5 * s, x + 5 * s, y + 5 * s], fill=(200, 30, 30), outline=INK, width=s)
            pd.ellipse([x - 1.6 * s, y - 1.6 * s, x + 1.6 * s, y + 1.6 * s], fill=PAPER)
        elif p.rank == "city":
            pd.ellipse([x - 4.5 * s, y - 4.5 * s, x + 4.5 * s, y + 4.5 * s], fill=(200, 30, 30), outline=INK, width=s)
        elif p.kind == "castle":
            pd.rectangle([x - 3.5 * s, y - 3.5 * s, x + 3.5 * s, y + 3.5 * s], fill=INK)
            pd.rectangle([x - 1.5 * s, y - 6 * s, x + 1.5 * s, y - 3.5 * s], fill=INK)
        elif p.kind in ("ruin", "dungeon"):
            pd.polygon(
                [(x, y - 5 * s), (x + 4.5 * s, y + 3.5 * s), (x - 4.5 * s, y + 3.5 * s)],
                fill=PAPER,
                outline=INK,
                width=s,
            )
            pd.line([(x - 2 * s, y + 1 * s), (x + 2 * s, y + 1 * s)], fill=INK, width=s)
        elif p.kind == "other":
            pd.polygon(
                [(x, y - 4 * s), (x + 4 * s, y), (x, y + 4 * s), (x - 4 * s, y)],
                fill=(200, 30, 30),
                outline=INK,
                width=s,
            )
        elif p.kind == "village":
            pd.ellipse([x - 2.5 * s, y - 2.5 * s, x + 2.5 * s, y + 2.5 * s], fill=INK)
        else:  # town, port
            pd.ellipse([x - 3.5 * s, y - 3.5 * s, x + 3.5 * s, y + 3.5 * s], fill=PAPER, outline=INK, width=s + 1)
            pd.ellipse([x - 1.3 * s, y - 1.3 * s, x + 1.3 * s, y + 1.3 * s], fill=INK)

    # --- lettering ---
    L = SS  # label sizes below are in final pixels
    for r in REALMS:
        x, y, ang, size = r.label
        put_text(canvas, r.name.upper(), px(x, y), font("bold", size * 1.3 * L), (122, 28, 28), spacing=0.28, angle=ang)
    for a in AREAS:
        if a.label is None:
            continue
        x, y, ang, size = a.label
        put_text(
            canvas, a.name.upper(), px(x, y), font("italic", size * 1.2 * L), (80, 54, 28), spacing=0.22, angle=ang
        )
    for name, _, spots in SEAS:
        for x, y, ang, size in spots:
            put_text(
                canvas,
                name.upper(),
                px(x, y),
                font("italic", size * 1.3 * L),
                (36, 82, 130),
                halo=None,
                spacing=0.5,
                angle=ang,
            )
    for r, coords in lines.rivers:
        if not r.name:
            continue
        line = LineString(coords)
        a = line.interpolate(r.label_at, normalized=True)
        b = line.interpolate(min(1.0, r.label_at + 0.06), normalized=True)
        ang = -math.degrees(math.atan2(b.y - a.y, b.x - a.x))
        if ang > 90:
            ang -= 180
        elif ang < -90:
            ang += 180
        nx, ny = -(b.y - a.y), (b.x - a.x)
        nl = math.hypot(nx, ny) or 1
        off = 7.0  # miles off the river
        put_text(
            canvas,
            r.name,
            px(a.x + nx / nl * off, a.y + ny / nl * off),
            font("italic", 15 * L),
            RIVER,
            angle=ang,
            halo_w=int(1.5 * SS),
        )
    for x, y, name, size in (
        (1265, 755, "orc tribes", 11),
        (695, 905, "Grandmother Frost", 10),
        (902, 600, "Redmere", 10),
        (834, 858, "Tarnwater", 9),
    ):
        put_text(canvas, name, px(x, y), font("italic", size * L), (80, 54, 28))
    for p in PLACES:
        x, y = px(p.x, p.y)
        f = font(
            "bold" if p.rank == "capital" else ("italic" if p.rank == "site" else "regular"),
            (17 if p.rank == "capital" else 15 if p.rank == "city" else 13) * L,
        )
        gap = 8 * SS
        at, anchor = {
            "e": ((x + gap, y), "e"),
            "w": ((x - gap, y), "w"),
            "n": ((x, y - gap), "n"),
            "s": ((x, y + gap), "s"),
            "ne": ((x + gap * 0.7, y - gap * 0.7), "ne"),
            "nw": ((x - gap * 0.7, y - gap * 0.7), "nw"),
            "se": ((x + gap * 0.7, y + gap * 0.7), "se"),
            "sw": ((x - gap * 0.7, y + gap * 0.7), "sw"),
        }[p.label]
        put_text(canvas, p.name, at, f, INK, anchor=anchor)

    # --- the title, the scale, the frame ---
    cart(canvas)
    d = ImageDraw.Draw(canvas)
    d.rectangle([2 * SS, 2 * SS, PW - 2 * SS, PH - 2 * SS], outline=INK, width=3 * SS)
    d.rectangle([7 * SS, 7 * SS, PW - 7 * SS, PH - 7 * SS], outline=INK, width=SS)
    return canvas.convert("RGB").resize((int(W_MI * FINAL_PX), int(H_MI * FINAL_PX)), Image.LANCZOS)


def cart(canvas: Image.Image) -> None:
    """The title cartouche and the scale, in the Iron Sea off the north-east."""
    d = ImageDraw.Draw(canvas)
    left, top = px(1185, 992)
    right, bottom = px(1585, 905)
    d.rectangle([left, top, right, bottom], fill=PAPER, outline=INK, width=2 * SS)
    d.rectangle([left + 5 * SS, top + 5 * SS, right - 5 * SS, bottom - 5 * SS], outline=INK, width=SS)
    cx = (left + right) / 2
    put_text(
        canvas, "THE REACHES OF AUN", (cx, top + 48 * SS), font("bold", 56 * SS), (122, 28, 28), halo=None, spacing=0.18
    )
    put_text(
        canvas,
        "as known in the year 1188 of the Reckoning",
        (cx, top + 104 * SS),
        font("italic", 26 * SS),
        INK,
        halo=None,
    )
    # scale bar: 0-150 miles
    sx0 = cx - 75 * P
    sy = top + 150 * SS
    for n in range(10):
        a, b = sx0 + n * 15 * P, sx0 + (n + 1) * 15 * P
        d.rectangle([a, sy, b, sy + 8 * SS], fill=INK if n % 2 == 0 else PAPER, outline=INK, width=SS)
    for n in (0, 2, 4, 6, 8, 10):
        put_text(canvas, str(n * 15), (sx0 + n * 15 * P, sy + 24 * SS), font("regular", 18 * SS), INK, halo=None)
    put_text(canvas, "miles  ·  one hex is fifteen miles", (cx, sy + 52 * SS), font("italic", 18 * SS), INK, halo=None)
    # a compass in the north-west sea
    cxp, cyp = px(48, 945)
    s = 60 * SS
    d.polygon([(cxp, cyp - s), (cxp + s * 0.25, cyp), (cxp, cyp + s * 0.6), (cxp - s * 0.25, cyp)], fill=INK)
    d.polygon([(cxp, cyp - s), (cxp + s * 0.25, cyp), (cxp, cyp)], fill=(200, 30, 30))
    d.polygon([(cxp - s * 0.6, cyp), (cxp, cyp - s * 0.12), (cxp + s * 0.6, cyp), (cxp, cyp + s * 0.12)], fill=INK)
    put_text(canvas, "N", (cxp, cyp - s - 16 * SS), font("bold", 30 * SS), INK, halo=None)


# ----------------------------------------------------------------------------------------------------------------------
# Commands
# ----------------------------------------------------------------------------------------------------------------------


def build(out: Path) -> None:
    out.mkdir(parents=True, exist_ok=True)
    world = make_world()
    doc, lines = make_doc(world)
    from delve.maps.geo.geojson import from_geojson
    from delve.maps.geo.model import water_from_areas

    geo = from_geojson(doc).geo
    assert geo is not None
    geo = water_from_areas(geo)
    doc["delve"]["terrain"] = geo.terrain
    picture = render(world, doc, lines)
    picture.save(out / "aun.jpg", quality=88, optimize=True)
    picture.resize((1600, 1000), Image.LANCZOS).save(out / "aun-preview.jpg", quality=85)
    (out / "aun.geojson").write_text(json.dumps(doc, ensure_ascii=False))
    counts: dict[str, int] = {}
    for f in doc["features"]:
        counts[f["properties"]["kind"]] = counts.get(f["properties"]["kind"], 0) + 1
    print("built", out, picture.size, len(doc["features"]), "features", counts)


def store(out: Path) -> None:
    from delve.config import Config
    from delve.domain.world import WorldMapSource
    from delve.maps.geo import pictures
    from delve.maps.geo.geojson import from_geojson
    from delve.setting.aun import DATA
    from delve.storage import open_storage

    doc = json.loads((out / "aun.geojson").read_text())
    data = (out / "aun.jpg").read_bytes()
    storage = open_storage(Config.from_env())
    pic = pictures.store(storage, data, "image/jpeg")
    doc["delve"]["picture"] = {
        "id": pic.id,
        "width_px": pic.width_px,
        "height_px": pic.height_px,
        "km_per_px": W_MI * MILE_KM / pic.width_px,
        "asset": None,
    }
    assert from_geojson(doc).geo is not None
    saved = storage.setting_maps.put(
        "aun",
        WorldMapSource(name="reaches", title="The Reaches of Aun", dsl="", geo=doc, picture=pic.id, status="ready"),
    )
    # A setting's stored maps replace its shipped ones at the table, so the shipped close map is stored beside it.
    if storage.setting_maps.get("aun", "hask-region") is None:
        from delve.maps.geo.from_dsl import from_view
        from delve.maps.geo.geojson import to_geojson
        from delve.maps.world.compile import compile_view
        from delve.maps.world.parse import parse

        region = to_geojson(from_view(compile_view(parse((DATA / "hask-region.map").read_text("utf-8")))).geo)
        storage.setting_maps.put(
            "aun", WorldMapSource(name="hask-region", title="Hask and the Ambre", dsl="", geo=region, status="ready")
        )
    (out / "stored.geojson").write_text(json.dumps(doc, ensure_ascii=False))
    print(saved.name, saved.status, pic.id, pic.width_px, pic.height_px, len(doc["features"]))


if __name__ == "__main__":
    {"build": build, "store": store}[sys.argv[1]](Path(sys.argv[2]))
