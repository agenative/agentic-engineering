# /// script
# requires-python = ">=3.11"
# dependencies = ["pandas>=2.2", "pyarrow>=15", "pyyaml>=6"]
# ///
"""Prepare the upload file for one ADA e2e case.

A .parquet source is read as is; a .csv source is converted (ISO date columns become DATE).
Transforms from the case are applied in order, then the file is written to <out>/upload/ and
<out>/prepared.json records its path and schema for run_ui_case.py.

Usage: uv run make_parquet.py --case <id> --out <run_dir>/<id> [--cases cases.yaml]
"""

from __future__ import annotations

import argparse
import shutil
from pathlib import Path
from typing import Any

import pandas as pd
import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.parquet as pq
from _common import DEFAULT_CASES, PREPARED_FILE, load_case, repo_root, write_json


def read_source(path: Path, infer_dates: bool) -> pa.Table:
    """Load a parquet or CSV source as an Arrow table."""
    if path.suffix == ".parquet":
        return pq.read_table(path)
    if path.suffix != ".csv":
        raise SystemExit(f"unsupported source type {path.suffix}; use .parquet or .csv")
    frame = pd.read_csv(path)
    if infer_dates:
        for column in frame.columns:
            if not pd.api.types.is_string_dtype(frame[column]):
                continue
            values = frame[column].dropna().astype(str)
            if values.empty or not values.str.fullmatch(r"\d{4}-\d{2}-\d{2}").all():
                continue
            frame[column] = pd.to_datetime(frame[column], format="%Y-%m-%d").dt.date
    return pa.Table.from_pandas(frame, preserve_index=False)


def apply_transform(table: pa.Table, step: dict[str, Any]) -> tuple[pa.Table, str | None]:
    """Apply one transform; returns the table and an optional special upload format."""
    if "head" in step:
        return table.slice(0, int(step["head"])), None
    if step.get("zero_rows"):
        return table.slice(0, 0), None
    if "rename" in step:
        mapping = step["rename"]
        missing = [old for old in mapping if old not in table.column_names]
        if missing:
            raise SystemExit(f"rename: columns not in source: {missing}")
        return table.rename_columns([mapping.get(n, n) for n in table.column_names]), None
    if "decimal" in step:
        spec = step["decimal"]
        decimal_type = pa.decimal128(int(spec.get("precision", 18)), int(spec.get("scale", 2)))
        for name in spec["columns"]:
            index = table.column_names.index(name)
            rounded = pa.array(
                [None if v is None else round(float(v), decimal_type.scale) for v in table[name].to_pylist()],
                type=pa.float64(),
            )
            table = table.set_column(index, name, pc.cast(rounded, decimal_type))
        return table, None
    if "boolean_column" in step:
        spec = step["boolean_column"]
        source = table[spec["from"]].to_pandas()
        flags = (source > source.median()).tolist()
        return table.append_column(spec["name"], pa.array(flags, type=pa.bool_())), None
    if "format" in step:
        if step["format"] not in ("not_parquet", "empty"):
            raise SystemExit(f"unknown format {step['format']!r}")
        return table, step["format"]
    raise SystemExit(f"unknown transform {step}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--cases", type=Path, default=DEFAULT_CASES)
    parser.add_argument("--case", required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()

    case = load_case(args.cases, args.case)
    root = repo_root()
    source = (root / case["source"]).resolve()
    if not source.is_file():
        raise SystemExit(f"source not found: {source}")

    upload_dir = args.out / "upload"
    upload_dir.mkdir(parents=True, exist_ok=True)
    table = read_source(source, infer_dates=case.get("infer_dates", True))
    special: str | None = None
    for step in case.get("transforms") or []:
        table, fmt = apply_transform(table, step)
        special = fmt or special

    if special == "not_parquet":
        upload = upload_dir / f"{case['id']}.csv"
        shutil.copyfile(source, upload)
    elif special == "empty":
        upload = upload_dir / f"{case['id']}.parquet"
        upload.write_bytes(b"")
    else:
        upload = upload_dir / f"{case['id']}.parquet"
        pq.write_table(table, upload)

    prepared = {
        "case_id": case["id"],
        "source": str(source),
        "upload_path": str(upload),
        "bytes": upload.stat().st_size,
        "rows": table.num_rows if special is None else None,
        "schema": {f.name: str(f.type) for f in table.schema} if special is None else None,
    }
    write_json(args.out / PREPARED_FILE, prepared)
    print(f"[ok] {case['id']}: {upload} ({prepared['bytes']} bytes, rows={prepared['rows']})")
    if prepared["schema"]:
        for name, kind in prepared["schema"].items():
            print(f"       {name}: {kind}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
