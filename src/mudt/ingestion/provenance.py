from __future__ import annotations

import json
from datetime import datetime
from typing import TYPE_CHECKING

from pydantic import BaseModel, ValidationError

if TYPE_CHECKING:
    from pathlib import Path

#: Appended to a source's file name stem to name its provenance record.
PROVENANCE_SUFFIX = ".provenance.json"


class ProvenanceRecord(BaseModel):
    """
    Where one raw source file came from, written next to it.

    `raw_file` is the source's file name, relative to the directory holding this record.
    """

    dataset_id: str
    tile_id: str | None = None
    raw_file: str
    retrieval_url: str
    retrieval_params: dict
    retrieved_at: datetime
    native_crs: str
    vertical_datum: str | None
    checksum: str
    bytes: int


def write_provenance(record: ProvenanceRecord, path: Path) -> None:
    """Write `record` as readable JSON: sorted keys, and accented text left unescaped."""
    payload = json.dumps(
        record.model_dump(mode="json"), sort_keys=True, ensure_ascii=False, indent=2
    )
    path.write_text(payload + "\n", encoding="utf-8")


def read_provenance(path: Path) -> ProvenanceRecord | None:
    """Read the provenance record at `path`, or return `None` when it is absent or unreadable."""
    if not path.is_file():
        return None
    try:
        return ProvenanceRecord.model_validate_json(path.read_text(encoding="utf-8"))
    except ValidationError:
        return None


def list_provenance(directory: Path) -> list[ProvenanceRecord]:
    """Read every provenance record in `directory`, sorted by dataset and tile."""
    records = [read_provenance(path) for path in directory.glob(f"*{PROVENANCE_SUFFIX}")]
    return sorted(
        (record for record in records if record is not None),
        key=lambda record: (record.dataset_id, record.tile_id or ""),
    )
