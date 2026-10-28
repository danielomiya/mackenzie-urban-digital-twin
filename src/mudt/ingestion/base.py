from __future__ import annotations

import hashlib
import os
import re
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from mudt.config import DatasetConfig
    from mudt.schema.aoi import AreaOfInterest

_UNSAFE_CHARACTERS = re.compile(r"[^A-Za-z0-9_.-]+")


@dataclass(frozen=True)
class SourceFile:
    """
    A source as retrieved by an adapter.

    Adapters populate `retrieval_url`/`retrieval_params` — the request that produced the
    bytes at `path` — but never compute the checksum themselves: checksumming is a generic
    pipeline concern. An adapter owns nothing else.
    """

    dataset_id: str
    tile_id: str | None
    path: Path
    retrieval_url: str
    retrieval_params: dict


class SourceAdapter(Protocol):
    """
    What a class must provide to retrieve a new kind of source.

    See `mudt.ingestion.wfs.Wfs` for the simplest example.
    """

    #: File extension of the downloaded file, e.g. `.geojson`.
    suffix: str

    def expand_tiles(self, config: DatasetConfig, aoi: AreaOfInterest) -> list[str]:
        """Return the ids of the tiles covering `aoi`, or `[]` for a source that is not tiled."""
        ...

    def fetch_source(
        self,
        config: DatasetConfig,
        destination: Path,
        *,
        aoi: AreaOfInterest,
        tile_id: str | None = None,
    ) -> SourceFile:
        """Download the source, writing the bytes exactly as received to `destination`."""
        ...

    def read_native_crs(self, source: SourceFile) -> str | None:
        """Return the CRS the downloaded file declares, or `None` when it declares none."""
        ...

    def read_vertical_datum(self, source: SourceFile) -> str | None:
        """Return the vertical datum the downloaded file declares, or `None`."""
        ...


def source_name(dataset_id: str, tile_id: str | None) -> str:
    """
    Return the file name stem used for one source, e.g. `geoportal_edificacao`.

    Characters that are awkward in file names (such as the `:` in `geoportal:edificacao`) are
    replaced with `_`. Tiled sources get the tile id appended: `mdt_2020.3314-211`.
    """
    name = _UNSAFE_CHARACTERS.sub("_", dataset_id)
    return name if tile_id is None else f"{name}.{tile_id}"


def compute_checksum(path: Path) -> str:
    """Return `sha256:<hex>` of the bytes at `path`."""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            digest.update(chunk)
    return f"sha256:{digest.hexdigest()}"


def write_atomically(destination: Path, content: bytes) -> None:
    """
    Write `content` to `destination` via a temporary file plus `os.replace`.

    An interrupted write never leaves a half-written file at `destination`.
    """
    destination.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(dir=destination.parent, prefix=f".{destination.name}.")
    temp_path = Path(temp_name)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(content)
        os.replace(temp_path, destination)
    except BaseException:
        temp_path.unlink(missing_ok=True)
        raise
