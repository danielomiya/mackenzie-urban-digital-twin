from __future__ import annotations

from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, ValidationError

from mudt.exceptions import ConfigInvalidError


class DatasetConfig(BaseModel):
    """Committed configuration describing one retrievable source."""

    dataset_id: str
    adapter: Literal["wfs", "point_cloud_tile"]
    retrieval: dict[str, Any]
    native_crs: str


class ProjectReferenceSystem(BaseModel):
    """The project-wide CRS every staged artifact is reprojected to."""

    horizontal_crs: str


def _invalid_fields(exc: ValidationError, prefix: str = "") -> list[str]:
    return [prefix + ".".join(str(part) for part in error["loc"]) for error in exc.errors()]


def load_dataset_configs(path: Path) -> list[DatasetConfig]:
    """
    Load and validate every dataset in `config/ingestion.yaml`.

    Raises `ConfigInvalidError` naming every offending field, and rejects duplicate
    `dataset_id`s.
    """
    if not path.is_file():
        raise FileNotFoundError(f"Ingestion configuration file not found: {path}")
    with path.open("r") as handle:
        data = yaml.safe_load(handle)

    raw_datasets = data.get("datasets", [])
    invalid_fields: list[str] = []
    datasets: list[DatasetConfig] = []
    for index, raw_dataset in enumerate(raw_datasets):
        try:
            datasets.append(DatasetConfig.model_validate(raw_dataset))
        except ValidationError as exc:
            invalid_fields.extend(_invalid_fields(exc, prefix=f"dataset[{index}]."))

    seen_ids: set[str] = set()
    for index, dataset in enumerate(datasets):
        if dataset.dataset_id in seen_ids:
            invalid_fields.append(f"dataset[{index}].dataset_id (duplicate: {dataset.dataset_id})")
        seen_ids.add(dataset.dataset_id)

    if invalid_fields:
        raise ConfigInvalidError(
            f"Invalid ingestion configuration in {path}: {', '.join(invalid_fields)}",
            invalid_fields=invalid_fields,
        )
    return datasets


def load_project_reference_system(path: Path) -> ProjectReferenceSystem:
    """
    Load the project CRS from `config/default_crs.yaml`.

    Absence of the file is a hard failure — there is no default.
    """
    if not path.is_file():
        raise FileNotFoundError(f"Project reference system file not found: {path}")
    with path.open("r") as handle:
        data = yaml.safe_load(handle)

    try:
        return ProjectReferenceSystem.model_validate(data)
    except ValidationError as exc:
        invalid_fields = _invalid_fields(exc)
        raise ConfigInvalidError(
            f"Invalid project reference system in {path}: {', '.join(invalid_fields)}",
            invalid_fields=invalid_fields,
        ) from exc
