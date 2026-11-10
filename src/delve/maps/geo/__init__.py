"""Geo world maps (plan 7): a frame in km, a grid of terrain cells, layers of features and an optional base picture.

A `GeoMap` (`model`) is stored as a Delve GeoJSON document (`geojson`): coordinates in km from the top left, y growing
down, plus a `delve` member with the frame, the grid, the terrain letters and the picture. `grid` measures the cells,
`terrain` names the classes and kinds, and `from_dsl` converts plateau 6's `.map` maps once. Beside them, the package
holds the routing, what the party knows and the seat's view, the tiles and the fog, and the reading of a picture.

Like `delve.maps.world`, it imports nothing of storage, play, dm or web: Claude and OCR are injected callables.
"""
