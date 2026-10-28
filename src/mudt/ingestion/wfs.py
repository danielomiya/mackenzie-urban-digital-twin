from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

from mudt.ingestion.base import SourceFile, write_atomically
from mudt.ingestion.http import ensure_json, http_get

if TYPE_CHECKING:
    from pathlib import Path

    from mudt.config import DatasetConfig
    from mudt.schema.aoi import AreaOfInterest


def get_feature_params(
    type_names: str,
    *,
    srs_name: str,
    aoi: AreaOfInterest,
    output_format: str = "application/json",
) -> dict[str, Any]:
    """
    Build the query parameters of a WFS 2.0 `GetFeature` request limited to the AOI's bounds.

    The bounding box only narrows the download: the exact clip against the AOI polygon happens
    later, in `mudt.transformation`.
    """
    minx, miny, maxx, maxy = aoi.geometry.bounds
    return {
        "service": "WFS",
        "version": "2.0.0",
        "request": "GetFeature",
        "typeNames": type_names,
        "srsName": srs_name,
        "bbox": f"{minx},{miny},{maxx},{maxy}",
        "outputFormat": output_format,
    }


class Wfs:
    """Retrieves one GeoSampa WFS layer as GeoJSON."""

    suffix = ".geojson"

    def expand_tiles(self, config: DatasetConfig, aoi: AreaOfInterest) -> list[str]:
        """WFS layers are not tiled."""
        return []

    def fetch_source(
        self,
        config: DatasetConfig,
        destination: Path,
        *,
        aoi: AreaOfInterest,
        tile_id: str | None = None,
    ) -> SourceFile:
        retrieval = config.retrieval
        url = retrieval["endpoint"]
        params = get_feature_params(
            retrieval["type_names"],
            srs_name=retrieval["srs_name"],
            aoi=aoi,
            output_format=retrieval.get("output_format", "application/json"),
        )

        response = http_get(url, params)
        ensure_json(response)
        write_atomically(destination, response.content)

        return SourceFile(
            dataset_id=config.dataset_id,
            tile_id=tile_id,
            path=destination,
            retrieval_url=url,
            retrieval_params=params,
        )

    def read_native_crs(self, source: SourceFile) -> str | None:
        """Return the CRS named in the GeoJSON `crs` member, or `None` when there is none."""
        data = json.loads(source.path.read_bytes())
        crs = data.get("crs")
        if not isinstance(crs, dict):
            return None
        return crs.get("properties", {}).get("name")

    def read_vertical_datum(self, source: SourceFile) -> str | None:
        """Return `None`: a vector layer has no vertical coordinates."""
        return None
