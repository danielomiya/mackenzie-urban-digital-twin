from __future__ import annotations

from typing import TYPE_CHECKING

import geopandas as gpd
import laspy
import numpy as np
import shapely
from pyproj import CRS, Transformer

from mudt.crs import same_crs
from mudt.exceptions import InconsistentCRSError
from mudt.las import crs_of, read_las

if TYPE_CHECKING:
    from pathlib import Path

    from shapely.geometry.base import BaseGeometry

    from mudt.schema.aoi import AreaOfInterest

#: Coordinate resolution used for point clouds reprojected to a geographic CRS: 1e-7 degrees is
#: about 1 cm on the ground, matching the millimetre-to-centimetre precision of the source tiles.
_GEOGRAPHIC_SCALE = 1e-7


def aoi_in_crs(aoi: AreaOfInterest, crs: str) -> BaseGeometry:
    """Return the AOI polygon expressed in `crs`, so it can be compared with data in that CRS."""
    return gpd.GeoSeries([aoi.geometry], crs=aoi.crs).to_crs(crs).iloc[0]


def clip_vector(path: Path, aoi: AreaOfInterest, target_crs: str) -> gpd.GeoDataFrame:
    """
    Read a vector file, keep only what lies inside the AOI polygon, and reproject it.

    Features crossing the AOI boundary are cut at the boundary.
    """
    geodataframe = gpd.read_file(path)
    if geodataframe.crs is None:
        raise InconsistentCRSError(f"{path} declares no CRS")

    clipped = geodataframe.clip(aoi_in_crs(aoi, geodataframe.crs), keep_geom_type=False)
    return clipped.to_crs(target_crs)


def clip_point_cloud(path: Path, aoi: AreaOfInterest, target_crs: str) -> laspy.LasData:
    """
    Read a point cloud, keep only the points inside the AOI polygon, and reproject them.

    Only x and y are reprojected. Heights are kept as they are: no vertical transformation is
    available for the source's vertical datum (Imbituba/MAPGEO2015).
    """
    las = read_las(path)
    native_crs = crs_of(las.header)
    if native_crs is None:
        raise InconsistentCRSError(f"{path} declares no CRS")

    inside = shapely.contains_xy(aoi_in_crs(aoi, native_crs), las.x, las.y)
    clipped = laspy.LasData(header=las.header, points=las.points[inside].copy())

    if same_crs(native_crs, target_crs):
        return clipped
    return _reproject_points(clipped, native_crs, target_crs)


def _reproject_points(las: laspy.LasData, source_crs: str, target_crs: str) -> laspy.LasData:
    """
    Reproject the x/y of `las` into a new point cloud declaring `target_crs`.

    LAS files store coordinates as integers multiplied by a per-file scale (0.001 for GeoSampa).
    That scale suits metres but not degrees, so a new header is built with a scale and offset
    that fit the target CRS. Every other attribute (z, intensity, classification, ...) and every
    non-CRS VLR (such as the vertical datum declaration) is carried over unchanged.
    """
    source_header = las.header
    transformer = Transformer.from_crs(source_crs, target_crs, always_xy=True)
    x, y = transformer.transform(np.asarray(las.x), np.asarray(las.y))

    target = CRS.from_user_input(target_crs)
    xy_scale = _GEOGRAPHIC_SCALE if target.is_geographic else source_header.scales[0]

    header = laspy.LasHeader(version=source_header.version, point_format=source_header.point_format)
    header.vlrs.extend(source_header.vlrs)
    header.add_crs(target)  # Also removes the CRS VLRs copied from the source.
    header.scales = np.array([xy_scale, xy_scale, source_header.scales[2]])
    header.offsets = np.array(
        [
            np.floor(x.min()) if len(x) else 0.0,
            np.floor(y.min()) if len(y) else 0.0,
            source_header.offsets[2],
        ]
    )

    reprojected = laspy.LasData(header)
    reprojected.points = laspy.ScaleAwarePointRecord.zeros(len(las.points), header=header)
    for name in source_header.point_format.dimension_names:
        if name not in {"X", "Y", "Z"}:
            reprojected[name] = las[name]
    reprojected.x = x
    reprojected.y = y
    reprojected.z = las.z
    return reprojected
