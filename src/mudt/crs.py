from __future__ import annotations

from pyproj import CRS


def same_crs(first: str, second: str) -> bool:
    """
    Tell whether two CRS strings name the same CRS.

    Sources spell the same CRS differently (`EPSG:31983`, `urn:ogc:def:crs:EPSG::31983`, a WKT
    string), so they are compared through `pyproj` rather than as plain strings.
    """
    return CRS.from_user_input(first) == CRS.from_user_input(second)
