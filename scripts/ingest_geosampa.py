"""
Download the GeoSampa datasets listed in `config/ingestion.yaml` into `data/raw/`.

Every source is saved exactly as received, next to a `<name>.provenance.json` recording where
it came from and its checksum. A source that is already on disk is not downloaded again unless
`--refresh` is given.

Usage:
    uv run scripts/ingest_geosampa.py
    uv run scripts/ingest_geosampa.py --dataset geoportal:edificacao --refresh
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated

import typer

from mudt.config import DatasetConfig, load_dataset_configs
from mudt.crs import same_crs
from mudt.exceptions import (
    AreaOfInterestMissingError,
    ConfigInvalidError,
    InconsistentCRSError,
    RetrievalError,
)
from mudt.ingestion.base import SourceAdapter, compute_checksum, source_name
from mudt.ingestion.point_cloud import PointCloudTile
from mudt.ingestion.provenance import (
    PROVENANCE_SUFFIX,
    ProvenanceRecord,
    read_provenance,
    write_provenance,
)
from mudt.ingestion.wfs import Wfs
from mudt.logging_config import configure_logging, get_logger
from mudt.schema.aoi import AreaOfInterest, load_area_of_interest

ADAPTERS: dict[str, SourceAdapter] = {
    "wfs": Wfs(),
    "point_cloud_tile": PointCloudTile(),
}


app = typer.Typer(add_completion=False)


def ingest_source(
    config: DatasetConfig,
    tile_id: str | None,
    aoi: AreaOfInterest,
    *,
    out_dir: Path,
    refresh: bool,
) -> None:
    """Download one source (a whole layer, or one tile) and write its provenance record."""
    logger = get_logger(dataset_id=config.dataset_id, tile_id=tile_id)
    adapter = ADAPTERS[config.adapter]
    name = source_name(config.dataset_id, tile_id)
    destination = out_dir / f"{name}{adapter.suffix}"
    provenance_path = out_dir / f"{name}{PROVENANCE_SUFFIX}"

    previous = read_provenance(provenance_path)
    if previous is not None and destination.is_file() and not refresh:
        logger.info("already_downloaded", path=str(destination))
        return

    logger.info("downloading")
    source = adapter.fetch_source(config, destination, aoi=aoi, tile_id=tile_id)

    native_crs = adapter.read_native_crs(source)
    if native_crs is None:
        raise InconsistentCRSError(f"{destination} declares no CRS")
    if not same_crs(native_crs, config.native_crs):
        raise InconsistentCRSError(
            f"{destination} declares CRS {native_crs!r}, but the configuration expects "
            f"{config.native_crs!r}"
        )

    checksum = compute_checksum(destination)
    if previous is not None and previous.checksum != checksum:
        logger.warning(
            "upstream_changed", previous_checksum=previous.checksum, current_checksum=checksum
        )

    record = ProvenanceRecord(
        dataset_id=config.dataset_id,
        tile_id=tile_id,
        raw_file=destination.name,
        retrieval_url=source.retrieval_url,
        retrieval_params=source.retrieval_params,
        retrieved_at=datetime.now(UTC),
        native_crs=native_crs,
        vertical_datum=adapter.read_vertical_datum(source),
        checksum=checksum,
        bytes=destination.stat().st_size,
    )
    write_provenance(record, provenance_path)
    logger.info("downloaded", path=str(destination), bytes=record.bytes)


def ingest_dataset(
    config: DatasetConfig, aoi: AreaOfInterest, *, out_dir: Path, refresh: bool
) -> bool:
    """Download every source of one dataset. Return `False` if any of them failed."""
    logger = get_logger(dataset_id=config.dataset_id)
    adapter = ADAPTERS[config.adapter]

    try:
        tile_ids: list[str | None] = [*adapter.expand_tiles(config, aoi)] or [None]
    except RetrievalError as exc:
        logger.error("tile_lookup_failed", error=str(exc))
        return False

    succeeded = True
    for tile_id in tile_ids:
        try:
            ingest_source(config, tile_id, aoi, out_dir=out_dir, refresh=refresh)
        except (RetrievalError, InconsistentCRSError) as exc:
            logger.error("ingestion_failed", tile_id=tile_id, error=str(exc))
            succeeded = False
    return succeeded


@app.command(help=__doc__.split("\n\n")[0])
def main(
    verbose: Annotated[
        bool, typer.Option("--verbose", "-v", help="Enable verbose logging.")
    ] = False,
    aoi_path: Annotated[Path, typer.Option("--aoi", help="Area of interest polygon.")] = Path(
        "config/aoi.yaml"
    ),
    config: Annotated[Path, typer.Option(help="Dataset ingestion configuration.")] = Path(
        "config/ingestion.yaml"
    ),
    out: Annotated[Path, typer.Option(help="Directory to download raw sources into.")] = Path(
        "data/raw"
    ),
    dataset_ids: Annotated[
        list[str] | None,
        typer.Option(
            "--dataset",
            help="Only ingest this dataset id (repeatable). Defaults to every configured dataset.",
        ),
    ] = None,
    refresh: Annotated[
        bool,
        typer.Option("--refresh", help="Download again even when the source is already on disk."),
    ] = False,
) -> None:
    configure_logging(verbose)
    logger = get_logger()

    try:
        aoi = load_area_of_interest(aoi_path)
    except AreaOfInterestMissingError:
        logger.error("aoi_missing", path=str(aoi_path))
        raise typer.Exit(2) from None

    try:
        datasets = load_dataset_configs(config)
    except (ConfigInvalidError, FileNotFoundError) as exc:
        logger.error("config_invalid", path=str(config), error=str(exc))
        raise typer.Exit(2) from None

    if dataset_ids:
        unknown = set(dataset_ids) - {dataset.dataset_id for dataset in datasets}
        if unknown:
            logger.error("unknown_dataset", dataset_ids=sorted(unknown))
            raise typer.Exit(2)
        datasets = [dataset for dataset in datasets if dataset.dataset_id in dataset_ids]

    out.mkdir(parents=True, exist_ok=True)
    failed = [
        dataset.dataset_id
        for dataset in datasets
        if not ingest_dataset(dataset, aoi, out_dir=out, refresh=refresh)
    ]

    if failed:
        logger.error("ingestion_finished_with_failures", failed=failed)
        raise typer.Exit(1)
    logger.info("ingestion_finished", datasets=len(datasets))


if __name__ == "__main__":
    app()
