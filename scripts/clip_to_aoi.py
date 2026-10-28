"""
Clip every source in `data/raw/` to the area of interest and reproject it into `data/staging/`.

Run `scripts/ingest_geosampa.py` first. Vector layers are written as GeoJSON and point clouds as
LAZ, each next to a `<name>.meta.json` linking it back to the raw source it was made from.

Usage:
    uv run scripts/clip_to_aoi.py
    uv run scripts/clip_to_aoi.py --dataset mdt_2020
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Annotated

import typer

from mudt.config import DatasetConfig, load_dataset_configs, load_project_reference_system
from mudt.exceptions import AreaOfInterestMissingError, ConfigInvalidError, InconsistentCRSError
from mudt.ingestion.base import compute_checksum, source_name
from mudt.ingestion.provenance import ProvenanceRecord, list_provenance
from mudt.logging_config import configure_logging, get_logger
from mudt.schema.aoi import AreaOfInterest, load_area_of_interest
from mudt.transformation.clip import clip_point_cloud, clip_vector

app = typer.Typer(add_completion=False)


def clip_source(
    config: DatasetConfig,
    record: ProvenanceRecord,
    aoi: AreaOfInterest,
    *,
    raw_dir: Path,
    out_dir: Path,
    target_crs: str,
) -> None:
    """Clip and reproject one raw source, then write it with its `.meta.json` sidecar."""
    logger = get_logger(dataset_id=record.dataset_id, tile_id=record.tile_id)
    raw_path = raw_dir / record.raw_file
    if compute_checksum(raw_path) != record.checksum:
        raise ValueError(
            f"{raw_path} no longer matches the checksum in its provenance record; "
            f"run scripts/ingest_geosampa.py --refresh"
        )

    name = source_name(record.dataset_id, record.tile_id)
    if config.adapter == "wfs":
        geodataframe = clip_vector(raw_path, aoi, target_crs)
        destination = out_dir / f"{name}.geojson"
        destination.unlink(missing_ok=True)
        geodataframe.to_file(destination, driver="GeoJSON")
        feature_count = len(geodataframe)
    else:
        point_cloud = clip_point_cloud(raw_path, aoi, target_crs)
        destination = out_dir / f"{name}.laz"
        point_cloud.write(destination)
        feature_count = len(point_cloud.points)

    meta = {
        "dataset_id": record.dataset_id,
        "tile_id": record.tile_id,
        "source_file": record.raw_file,
        "source_checksum": record.checksum,
        "aoi": aoi.name,
        "crs": target_crs,
        "vertical_datum": record.vertical_datum,
        "feature_count": feature_count,
    }
    meta_path = out_dir / f"{name}.meta.json"
    meta_path.write_text(json.dumps(meta, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    if feature_count == 0:
        logger.warning("empty_extract", path=str(destination))
    else:
        logger.info("clipped", path=str(destination), feature_count=feature_count)


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
    crs_config: Annotated[
        Path, typer.Option(help="Project reference system to reproject into.")
    ] = Path("config/default_crs.yaml"),
    raw: Annotated[
        Path, typer.Option(help="Directory of raw sources and their provenance records.")
    ] = Path("data/raw"),
    out: Annotated[Path, typer.Option(help="Directory to write clipped sources into.")] = Path(
        "data/staging"
    ),
    dataset_ids: Annotated[
        list[str] | None,
        typer.Option(
            "--dataset",
            help="Only clip this dataset id (repeatable). Defaults to every configured dataset.",
        ),
    ] = None,
) -> None:
    configure_logging(verbose)
    logger = get_logger()

    try:
        aoi = load_area_of_interest(aoi_path)
    except AreaOfInterestMissingError:
        logger.error("aoi_missing", path=str(aoi_path))
        raise typer.Exit(2) from None

    try:
        datasets = {dataset.dataset_id: dataset for dataset in load_dataset_configs(config)}
        project_crs = load_project_reference_system(crs_config)
    except (ConfigInvalidError, FileNotFoundError) as exc:
        logger.error("config_invalid", error=str(exc))
        raise typer.Exit(2) from None

    records = [record for record in list_provenance(raw) if record.dataset_id in datasets]
    if dataset_ids:
        records = [record for record in records if record.dataset_id in dataset_ids]
    if not records:
        logger.error("nothing_to_clip", raw_dir=str(raw))
        raise typer.Exit(1)

    out.mkdir(parents=True, exist_ok=True)
    failed = False
    for record in records:
        try:
            clip_source(
                datasets[record.dataset_id],
                record,
                aoi,
                raw_dir=raw,
                out_dir=out,
                target_crs=project_crs.horizontal_crs,
            )
        except (InconsistentCRSError, OSError, ValueError) as exc:
            logger.error(
                "clip_failed", dataset_id=record.dataset_id, tile_id=record.tile_id, error=str(exc)
            )
            failed = True

    if failed:
        raise typer.Exit(1)


if __name__ == "__main__":
    app()
