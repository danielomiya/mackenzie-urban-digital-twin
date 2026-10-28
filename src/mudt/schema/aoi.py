from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

import yaml
from shapely.geometry import shape

from mudt.exceptions import AreaOfInterestMissingError

if TYPE_CHECKING:
    from shapely.geometry.base import BaseGeometry


@dataclass(frozen=True)
class AreaOfInterest:
    """The committed campus polygon and its derivation metadata."""

    name: str
    crs: str
    geometry: BaseGeometry


def load_area_of_interest(path: Path) -> AreaOfInterest:
    """
    Load the committed AOI GeoJSON.

    Raises `AreaOfInterestMissingError` when `path` is absent — there is no derived or
    default fallback.
    """
    if not path.is_file():
        raise AreaOfInterestMissingError(f"No area of interest at {path}")

    raw_bytes = path.read_bytes()
    data = yaml.safe_load(raw_bytes)

    crs = data["crs"]["type"]
    return AreaOfInterest(
        name=data["name"],
        geometry=shape(data["geometry"]),
        crs=crs,
    )
