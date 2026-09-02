"""Reads the four source CSVs as raw dict rows. No validation, no
normalization here — this stage only knows how to read a file."""
from __future__ import annotations

import csv
import hashlib
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class RawFile:
    path: Path
    content_hash: str
    rows: list[dict]  # each row tagged with __source_line__ (1-indexed, header = line 1)


def read_csv(path: str | Path) -> RawFile:
    path = Path(path)
    content = path.read_bytes()
    content_hash = hashlib.sha256(content).hexdigest()

    rows: list[dict] = []
    text = content.decode("utf-8-sig")
    reader = csv.DictReader(text.splitlines())
    for line_no, row in enumerate(reader, start=2):  # header is line 1
        tagged = dict(row)
        tagged["__source_line__"] = line_no
        rows.append(tagged)

    return RawFile(path=path, content_hash=content_hash, rows=rows)
