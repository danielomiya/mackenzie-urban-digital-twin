from __future__ import annotations

from typing import TYPE_CHECKING

from mudt.ingestion.base import SourceFile, write_atomically
from mudt.ingestion.http import ensure_json, ensure_zip_attachment, http_get
from mudt.ingestion.wfs import get_feature_params
from mudt.las import crs_of, read_las_header, vertical_datum_of

if TYPE_CHECKING:
    from pathlib import Path

    from mudt.config import DatasetConfig
    from mudt.schema.aoi import AreaOfInterest

#: Where the tile index layer (`retrieval.tile_index_layer`) is published.
_TILE_INDEX_ENDPOINT = "https://wfs.geosampa.prefeitura.sp.gov.br/geoserver/geoportal/wfs"
#: The tile index attribute holding the tile id, e.g. `3314-211`.
_TILE_ID_ATTRIBUTE = "cd_quadricula"


class PointCloudTile:
    """
    Retrieves GeoSampa MDT/MDS LiDAR point clouds, one tile at a time.

    Each tile is delivered as a zip archive holding one LAZ file, and is kept exactly as
    received.
    """

    suffix = ".zip"

    def expand_tiles(self, config: DatasetConfig, aoi: AreaOfInterest) -> list[str]:
        """Look up which tiles intersect the AOI by querying the published tile index layer."""
        params = get_feature_params(
            config.retrieval["tile_index_layer"],
            srs_name=config.native_crs,
            aoi=aoi,
        )
        response = http_get(_TILE_INDEX_ENDPOINT, params)
        ensure_json(response)
        features = response.json()["features"]
        return sorted({feature["properties"][_TILE_ID_ATTRIBUTE] for feature in features})

    def fetch_source(
        self,
        config: DatasetConfig,
        destination: Path,
        *,
        aoi: AreaOfInterest,
        tile_id: str | None = None,
    ) -> SourceFile:
        if tile_id is None:
            raise ValueError(f"Dataset {config.dataset_id!r} is tiled and requires a tile_id")

        retrieval = config.retrieval
        url = retrieval["endpoint"]
        params = {
            "orig": retrieval["orig"],
            "arq": retrieval["arq_template"].format(tile=tile_id),
            "arqTipo": retrieval["arq_tipo"],
        }

        response = http_get(url, params, timeout=120.0)
        ensure_zip_attachment(response)
        write_atomically(destination, response.content)

        return SourceFile(
            dataset_id=config.dataset_id,
            tile_id=tile_id,
            path=destination,
            retrieval_url=url,
            retrieval_params=params,
        )

    def read_native_crs(self, source: SourceFile) -> str | None:
        """Return the CRS declared in the LAZ header, or `None` when there is none."""
        return crs_of(read_las_header(source.path))

    def read_vertical_datum(self, source: SourceFile) -> str | None:
        """Return the vertical datum declared in the LAZ header, or `None` when there is none."""
        return vertical_datum_of(read_las_header(source.path))
