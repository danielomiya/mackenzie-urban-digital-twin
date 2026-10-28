from __future__ import annotations

import io
import zipfile
from typing import TYPE_CHECKING

import laspy

if TYPE_CHECKING:
    from pathlib import Path

#: GeoSampa declares the vertical datum in the `description` of a VLR with this `user_id`.
_VERTICAL_DATUM_VLR = "VertDatum-Geoid"


def _las_bytes(path: Path) -> bytes:
    """
    Return the LAS/LAZ bytes at `path`, unzipping them first when `path` is a zip archive.

    GeoSampa delivers each tile as a zip holding a single LAZ file. The zip is kept on disk
    exactly as received; it is only unzipped in memory, here.
    """
    raw = path.read_bytes()
    if not zipfile.is_zipfile(io.BytesIO(raw)):
        return raw
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        names = [name for name in archive.namelist() if name.lower().endswith((".laz", ".las"))]
        if not names:
            raise ValueError(f"No LAS/LAZ file found in archive {path}")
        return archive.read(names[0])


def read_las(path: Path) -> laspy.LasData:
    """Read every point of a LAS/LAZ file (zipped or not)."""
    return laspy.read(io.BytesIO(_las_bytes(path)))


def read_las_header(path: Path) -> laspy.LasHeader:
    """Read only the header of a LAS/LAZ file, which is much cheaper than reading the points."""
    with laspy.open(io.BytesIO(_las_bytes(path))) as reader:
        return reader.header


def crs_of(header: laspy.LasHeader) -> str | None:
    """Return the horizontal CRS declared in the header VLRs, or `None` when there is none."""
    crs = header.parse_crs()
    if crs is None:
        return None
    epsg = crs.to_epsg()
    return f"EPSG:{epsg}" if epsg is not None else crs.to_wkt()


def vertical_datum_of(header: laspy.LasHeader) -> str | None:
    """Return the vertical datum declared in the header VLRs, or `None` when there is none."""
    for vlr in header.vlrs:
        if vlr.user_id == _VERTICAL_DATUM_VLR:
            return vlr.description.strip()
    return None
