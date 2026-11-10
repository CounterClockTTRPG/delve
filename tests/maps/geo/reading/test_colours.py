"""Clustering the cells' colours: one cluster per flat terrain colour, and the cell of mixed colour."""

from collections import defaultdict

import pytest

from delve.maps.geo.reading.colours import MAX_CLUSTERS, cluster_cells
from delve.maps.geo.reading.grid_detect import find_grid
from tests.maps.geo.pictures import hex_map, square_map


def _water_as_one(terrain):
    return "water" if terrain in ("sea", "lake") else terrain


@pytest.mark.parametrize(
    "make", [hex_map, square_map, lambda: hex_map(orientation="flat")], ids=["hex", "square", "flat"]
)
def test_every_cell_takes_its_terrains_cluster_and_the_mixed_cell_is_mixed(make):
    synthetic = make()
    truth = synthetic.truth
    clusters = cluster_cells(synthetic.image, find_grid(synthetic.image, truth.grid.kind))
    assert len(clusters.palette) <= MAX_CLUSTERS
    assert len(clusters.cell_cluster) == truth.grid.cells
    by_terrain = defaultdict(set)
    for i, cluster in enumerate(clusters.cell_cluster):
        if i not in truth.mixed:
            by_terrain[_water_as_one(truth.terrain[i])].add(cluster)
    assert set(by_terrain) == {"plains", "forest", "hills", "mountain", "water"}
    assert all(len(found) == 1 for found in by_terrain.values()), dict(by_terrain)
    assert len({next(iter(found)) for found in by_terrain.values()}) == 5
    assert clusters.mixed == list(truth.mixed)


def test_the_same_picture_read_twice_gives_the_same_clusters():
    synthetic = hex_map()
    grid = find_grid(synthetic.image, "hex")
    assert cluster_cells(synthetic.image, grid) == cluster_cells(synthetic.image.copy(), grid)
