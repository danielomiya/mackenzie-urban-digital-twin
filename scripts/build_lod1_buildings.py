"""
Give every building footprint in `data/staging/` a height, writing them to `data/out/`.

Run `scripts/clip_to_aoi.py` first. A height is measured on the 2020 LiDAR as the roof minus the
ground around the building: the roof is a high percentile of the surface (MDS) points classified
as building inside the footprint, and the ground is the median terrain (MDT) elevation in a ring
around it. When the LiDAR does not clearly see a building inside the footprint, GeoSampa's own
height attribute is used instead and, failing that, a one-storey default. `height_source` tells
which of the three each building got.

Buildings listed in `data/mapping/predio_mapping.csv` also get the Prédio number and name used on
campus. A footprint holding several Prédios carries them joined, as in `5/6`.

The buildings are written twice: as GeoJSON footprints carrying their height, and as a CityJSON
file of LOD1 blocks, each extruded from its ground elevation up to its roof. Convert the CityJSON
to CityGML with `citygml-tools from-cityjson` when a tool needs it.

Usage:
    uv run scripts/build_lod1_buildings.py
"""

from __future__ import annotations

import csv
import json
import math
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Annotated

import geopandas as gpd
import laspy
import numpy as np
import pandas as pd
import shapely
import typer
from pyproj import Transformer
from shapely.geometry.polygon import orient

from mudt.exceptions import InconsistentCRSError
from mudt.ingestion.base import source_name, write_atomically
from mudt.las import crs_of
from mudt.logging_config import configure_logging, get_logger

if TYPE_CHECKING:
    from collections.abc import Sequence

    from pyproj import CRS
    from shapely.geometry import Polygon
    from shapely.geometry.base import BaseGeometry

FOOTPRINTS_DATASET = "geoportal:edificacao"
SURFACE_DATASET = "mds_2020"
TERRAIN_DATASET = "mdt_2020"
KEY_ATTRIBUTE = "cd_identificador"
GEOSAMPA_HEIGHT_ATTRIBUTE = "qt_altura_edificacao"

#: ASPRS classification code of building points.
BUILDING_CLASS = 6
#: A footprint is measured on the LiDAR only when at least this share of the surface points
#: inside it are building points...
MIN_BUILDING_SHARE = 0.5
#: ...and there are at least this many of them.
MIN_BUILDING_POINTS = 10
#: The 3dfier convention: high enough to reach the roof, low enough to ignore antennas.
ROOF_PERCENTILE = 90
#: The ground ring starts this far out, clear of walls and eaves...
GROUND_RING_INNER_M = 0.5
#: ...and reaches the first of these that holds `MIN_GROUND_POINTS` terrain points. The wider
#: ones are for buildings at the AOI-clipped edge of the data.
GROUND_RING_OUTER_M = (3.0, 10.0, 25.0)
MIN_GROUND_POINTS = 3
#: One storey.
DEFAULT_HEIGHT_M = 3.0
#: CityJSON stores vertices as integers times this scale: millimetres, as in the LiDAR.
CITYJSON_SCALE = 0.001

app = typer.Typer(add_completion=False)


@dataclass(frozen=True)
class PointCloud:
    x: np.ndarray
    y: np.ndarray
    z: np.ndarray
    classification: np.ndarray


def load_point_cloud(staging_dir: Path, dataset_id: str, metric_crs: CRS) -> PointCloud:
    """Read every staged tile of a dataset into one point cloud, with x/y in `metric_crs`."""
    paths = sorted(staging_dir.glob(f"{source_name(dataset_id, '*')}.laz"))
    if not paths:
        raise FileNotFoundError(f"No staged tile of {dataset_id} found in {staging_dir}")

    tiles = []
    for path in paths:
        las = laspy.read(path)
        crs = crs_of(las.header)
        if crs is None:
            raise InconsistentCRSError(f"{path} declares no CRS")
        transformer = Transformer.from_crs(crs, metric_crs, always_xy=True)
        x, y = transformer.transform(np.asarray(las.x), np.asarray(las.y))
        tiles.append((x, y, np.asarray(las.z), np.asarray(las.classification)))
    return PointCloud(*(np.concatenate(column) for column in zip(*tiles, strict=True)))


def load_predio_mapping(path: Path) -> dict[int, dict]:
    """Return the Prédio number and name of every mapped footprint, by `cd_identificador`."""
    with path.open(encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle, delimiter=";"))
    return {
        int(row[KEY_ATTRIBUTE]): {
            "predio_number": row["predio_number"],
            "predio_name": row["predio_name"] or None,
        }
        for row in rows
        # Prédios with no footprint keep a row explaining why, under `unmapped_reason`.
        if row[KEY_ATTRIBUTE]
    }


def select_points_inside(geometry: BaseGeometry, x: np.ndarray, y: np.ndarray) -> np.ndarray:
    """Return the indices of the points inside `geometry`."""
    minx, miny, maxx, maxy = geometry.bounds
    candidates = np.flatnonzero((x >= minx) & (x <= maxx) & (y >= miny) & (y <= maxy))
    return candidates[shapely.contains_xy(geometry, x[candidates], y[candidates])]


def measure_ground(footprint: BaseGeometry, terrain: PointCloud) -> float | None:
    """Return the median terrain elevation around `footprint`, or `None` when there is too little."""
    inner = footprint.buffer(GROUND_RING_INNER_M)
    for outer in GROUND_RING_OUTER_M:
        ring = footprint.buffer(outer).difference(inner)
        inside = select_points_inside(ring, terrain.x, terrain.y)
        if len(inside) >= MIN_GROUND_POINTS:
            return float(np.median(terrain.z[inside]))
    return None


def measure_building(
    footprint: BaseGeometry,
    geosampa_height_m: float,
    *,
    surface: PointCloud,
    terrain: PointCloud,
) -> dict:
    """Pick one height for a footprint, preferring the LiDAR, and return its output properties."""
    inside = select_points_inside(footprint, surface.x, surface.y)
    building_z = surface.z[inside][surface.classification[inside] == BUILDING_CLASS]
    ground = measure_ground(footprint, terrain)
    seen_by_lidar = len(building_z) >= MIN_BUILDING_POINTS and len(
        building_z
    ) >= MIN_BUILDING_SHARE * len(inside)
    roof = float(np.percentile(building_z, ROOF_PERCENTILE)) if seen_by_lidar else None

    if roof is not None and ground is not None and roof > ground:
        height, height_source = roof - ground, "lidar"
    elif geosampa_height_m > 0:
        height, height_source = geosampa_height_m, "geosampa"
    else:
        height, height_source = DEFAULT_HEIGHT_M, "default"

    return {
        "height_m": round(height, 3),
        "height_source": height_source,
        "ground_elevation_m": None if ground is None else round(ground, 3),
        "roof_elevation_m": None if roof is None else round(roof, 3),
        "surface_points": len(inside),
        "building_points": len(building_z),
    }


def build_solid(polygon: Polygon, base_m: float, top_m: float) -> list:
    """
    Extrude `polygon` from `base_m` to `top_m` into a CityJSON solid of `(x, y, z)` points.

    Every surface is ordered counter-clockwise seen from outside the solid, as CityJSON requires,
    so the floor runs opposite to the roof.
    """
    polygon = orient(shapely.remove_repeated_points(polygon))
    rings = [
        [(x, y) for x, y, *_ in ring.coords[:-1]] for ring in [polygon.exterior, *polygon.interiors]
    ]
    floor = [[(x, y, base_m) for x, y in reversed(ring)] for ring in rings]
    roof = [[(x, y, top_m) for x, y in ring] for ring in rings]
    walls = [
        [[(*start, base_m), (*end, base_m), (*end, top_m), (*start, top_m)]]
        for ring in rings
        for start, end in zip(ring, ring[1:] + ring[:1], strict=True)
    ]
    return [[floor, roof, *walls]]


def write_cityjson(
    path: Path, buildings: list[dict], footprints: Sequence[BaseGeometry], crs: CRS
) -> None:
    """Write every building that has a ground elevation as a CityJSON LOD1 block."""
    logger = get_logger()
    minx, miny, *_ = shapely.total_bounds(footprints)
    translate = (math.floor(minx), math.floor(miny), 0)
    vertices: dict[tuple[int, ...], int] = {}

    def index_vertices(boundaries: list | tuple) -> list | int:
        if isinstance(boundaries, tuple):
            key = tuple(
                round((value - offset) / CITYJSON_SCALE)
                for value, offset in zip(boundaries, translate, strict=True)
            )
            return vertices.setdefault(key, len(vertices))
        return [index_vertices(item) for item in boundaries]

    city_objects = {}
    for building, footprint in zip(buildings, footprints, strict=True):
        key = building[KEY_ATTRIBUTE]
        base = building["ground_elevation_m"]
        if base is None:
            logger.warning("no_ground_elevation", **{KEY_ATTRIBUTE: key})
            continue

        solids = [
            build_solid(polygon, base, base + building["height_m"])
            for polygon in getattr(footprint, "geoms", [footprint])
        ]
        city_objects[f"bldg-edificacao-{key}"] = {
            "type": "Building",
            "attributes": {
                KEY_ATTRIBUTE: key,
                "measuredHeight": building["height_m"],
                "height_source": building["height_source"],
                **{
                    name: building[name]
                    for name in ("predio_number", "predio_name")
                    if building[name] is not None
                },
            },
            "geometry": [
                {
                    "type": "Solid" if len(solids) == 1 else "MultiSolid",
                    "lod": "1",
                    "boundaries": index_vertices(solids[0] if len(solids) == 1 else solids),
                }
            ],
        }

    document = {
        "type": "CityJSON",
        "version": "2.0",
        "transform": {"scale": [CITYJSON_SCALE] * 3, "translate": list(translate)},
        "metadata": {"referenceSystem": f"https://www.opengis.net/def/crs/EPSG/0/{crs.to_epsg()}"},
        "CityObjects": city_objects,
        "vertices": [list(vertex) for vertex in vertices],
    }
    write_atomically(path, json.dumps(document, ensure_ascii=False).encode("utf-8"))


@app.command(help=__doc__.split("\n\n")[0])
def main(
    verbose: Annotated[
        bool, typer.Option("--verbose", "-v", help="Enable verbose logging.")
    ] = False,
    staging: Annotated[
        Path, typer.Option(help="Directory of clipped sources, as written by clip_to_aoi.py.")
    ] = Path("data/staging"),
    out: Annotated[Path, typer.Option(help="GeoJSON file to write the buildings to.")] = Path(
        "data/out/buildings.geojson"
    ),
    cityjson: Annotated[
        Path, typer.Option(help="CityJSON file to write the LOD1 buildings to.")
    ] = Path("data/out/buildings.city.json"),
    predio_mapping: Annotated[
        Path, typer.Option(help="Table of the campus Prédio numbers of each footprint.")
    ] = Path("data/mapping/predio_mapping.csv"),
) -> None:
    configure_logging(verbose)
    logger = get_logger()

    try:
        predios = load_predio_mapping(predio_mapping)
    except (OSError, KeyError, ValueError) as exc:
        logger.error("predio_mapping_invalid", path=str(predio_mapping), error=str(exc))
        raise typer.Exit(2) from None

    footprints_path = staging / f"{source_name(FOOTPRINTS_DATASET, None)}.geojson"
    if not footprints_path.is_file():
        logger.error("input_missing", path=str(footprints_path))
        raise typer.Exit(2)

    footprints = gpd.read_file(footprints_path)
    # Clipping at the AOI boundary can leave slivers that are no longer polygons.
    footprints = footprints[footprints.geom_type.isin(["Polygon", "MultiPolygon"])]
    if footprints.empty:
        logger.error("no_footprints", path=str(footprints_path))
        raise typer.Exit(1)

    # Staged data may be in degrees, but the ground ring and the CityJSON solids are in metres.
    metric_crs = footprints.estimate_utm_crs("SIRGAS 2000")
    metric_footprints = footprints.to_crs(metric_crs).geometry.to_numpy()
    try:
        surface = load_point_cloud(staging, SURFACE_DATASET, metric_crs)
        terrain = load_point_cloud(staging, TERRAIN_DATASET, metric_crs)
    except (FileNotFoundError, InconsistentCRSError) as exc:
        logger.error("input_missing", error=str(exc))
        raise typer.Exit(2) from None

    geosampa_heights = pd.to_numeric(footprints[GEOSAMPA_HEIGHT_ATTRIBUTE], errors="coerce")
    buildings = [
        {
            KEY_ATTRIBUTE: key,
            **measure_building(footprint, geosampa_height_m, surface=surface, terrain=terrain),
            **predios.get(key, {"predio_number": None, "predio_name": None}),
        }
        for key, footprint, geosampa_height_m in zip(
            footprints[KEY_ATTRIBUTE],
            metric_footprints,
            geosampa_heights.fillna(0.0),
            strict=True,
        )
    ]
    missing = sorted(predios.keys() - set(footprints[KEY_ATTRIBUTE]))
    if missing:
        logger.warning("predio_footprints_missing", **{KEY_ATTRIBUTE: missing})

    output = gpd.GeoDataFrame(
        buildings, geometry=footprints.geometry.to_numpy(), crs=footprints.crs
    )
    out.parent.mkdir(parents=True, exist_ok=True)
    out.unlink(missing_ok=True)
    output.to_file(out, driver="GeoJSON")
    write_cityjson(cityjson, buildings, metric_footprints, metric_crs)
    logger.info(
        "buildings_written",
        paths=[str(out), str(cityjson)],
        building_count=len(output),
        height_sources=dict(Counter(output["height_source"])),
    )


if __name__ == "__main__":
    app()
