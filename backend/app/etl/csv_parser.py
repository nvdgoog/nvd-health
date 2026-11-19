from __future__ import annotations

import csv
import hashlib
import io
import json
import re
from datetime import date, datetime, timezone
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

from app.etl.schemas import TableSchemaSpec, to_snake_case

NAN_SENTINELS = {"nan", "na", "null", "none", "inf", "-inf", ""}

ISO_TS_WITH_Z_RE = re.compile(
    r"^\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:?\d{2})?$"
)
ISO_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
INT_RE = re.compile(r"^[+-]?\d+$")
FLOAT_RE = re.compile(r"^[+-]?(?:\d+\.?\d*|\.\d+)(?:[eE][+-]?\d+)?$")


def is_nan_or_empty(val: Optional[str]) -> bool:
    """Return True if a CSV cell represents missing data or NaN."""
    if val is None:
        return True
    return val.strip().lower() in NAN_SENTINELS


def parse_timestamp_utc(raw: str) -> Optional[str]:
    """Parse ISO-8601 date/timestamp string into a UTC ISO-8601 string for BigQuery TIMESTAMP."""
    s = raw.strip()
    if is_nan_or_empty(s):
        return None
    if ISO_DATE_RE.match(s):
        return f"{s}T00:00:00Z"
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    elif " " in s and "T" not in s:
        s = s.replace(" ", "T", 1)
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    else:
        dt = dt.astimezone(timezone.utc)
    return dt.isoformat().replace("+00:00", "Z")


def parse_date_value(raw: str) -> Optional[str]:
    """Parse ISO date or timestamp into YYYY-MM-DD for BigQuery DATE."""
    s = raw.strip()
    if is_nan_or_empty(s):
        return None
    if ISO_DATE_RE.match(s):
        return s
    if len(s) >= 10 and ISO_DATE_RE.match(s[:10]):
        return s[:10]
    try:
        return date.fromisoformat(s).isoformat()
    except ValueError:
        return None


def parse_bool_value(raw: str) -> Optional[bool]:
    s = raw.strip().lower()
    if s in {"true", "1", "yes", "t"}:
        return True
    if s in {"false", "0", "no", "f"}:
        return False
    return None


def coerce_value(raw: Optional[str], bq_type: str) -> Any:
    """Coerce a raw CSV string into a JSON-serializable value matching bq_type."""
    if raw is None:
        return None
    stripped = raw.strip()
    if stripped.lower() in NAN_SENTINELS:
        return None

    if bq_type == "INT64":
        try:
            return int(stripped)
        except ValueError:
            try:
                f = float(stripped)
                return int(f) if f.is_integer() else None
            except ValueError:
                return None
    if bq_type == "FLOAT64":
        try:
            val = float(stripped)
            # NaN / Inf guard
            if val != val or val in (float("inf"), float("-inf")):
                return None
            return val
        except ValueError:
            return None
    if bq_type == "BOOL":
        return parse_bool_value(stripped)
    if bq_type == "TIMESTAMP":
        return parse_timestamp_utc(stripped)
    if bq_type == "DATE":
        return parse_date_value(stripped)
    # Preserve raw multiline content (e.g. intervals) for STRING
    return raw if raw != "" else None


def infer_column_types(
    headers: Sequence[str], sample_rows: Sequence[Dict[str, Optional[str]]]
) -> Dict[str, str]:
    """Infer BigQuery types for previously unseen CSV columns."""
    inferred: Dict[str, str] = {}
    for col in headers:
        non_empty = [
            (r.get(col) or "").strip()
            for r in sample_rows
            if not is_nan_or_empty(r.get(col))
        ]
        if not non_empty:
            inferred[col] = "STRING"
            continue
        # ID-like columns should remain STRING to preserve precision
        if col == "id" or col.endswith("_id") or col.endswith("_sn"):
            inferred[col] = "STRING"
            continue
        if all(ISO_DATE_RE.match(v) for v in non_empty):
            inferred[col] = "DATE"
        elif all(ISO_TS_WITH_Z_RE.match(v) for v in non_empty):
            inferred[col] = "TIMESTAMP"
        elif all(v.lower() in {"true", "false"} for v in non_empty):
            inferred[col] = "BOOL"
        elif all(INT_RE.match(v) for v in non_empty):
            # Guard against >64-bit integer IDs
            if all(-9223372036854775808 <= int(v) <= 9223372036854775807 for v in non_empty):
                inferred[col] = "INT64"
            else:
                inferred[col] = "STRING"
        elif all(FLOAT_RE.match(v) for v in non_empty):
            inferred[col] = "FLOAT64"
        else:
            inferred[col] = "STRING"
    return inferred


def compute_row_hash(row: Dict[str, Any]) -> str:
    """Compute a deterministic SHA-256 hash over canonical business columns."""
    payload = {
        k: v for k, v in sorted(row.items()) if not k.startswith("_")
    }
    encoded = json.dumps(payload, sort_keys=True, default=str).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def parse_rfc4180_csv_bytes(
    data: bytes,
    spec: TableSchemaSpec,
    source_file: str,
    run_id: str,
    ingested_at_iso: str,
) -> Tuple[List[Dict[str, Any]], Dict[str, str]]:
    """
    Strictly parse RFC-4180 multi-line CSV bytes into typed row dicts.

    Handles embedded newlines/tabs inside double-quoted fields (e.g., UserExercises.intervals,
    daily_sleep_breathing_quality intervals), converts NaN strings to None (SQL NULL),
    and preserves -1 sentinel values in Bronze.
    """
    text = data.decode("utf-8-sig", errors="replace")
    if not text.strip():
        return [], dict(spec.columns)

    buf = io.StringIO(text, newline="")
    reader = csv.reader(buf, dialect="excel")
    try:
        raw_headers = next(reader)
    except StopIteration:
        return [], dict(spec.columns)

    if not raw_headers:
        return [], dict(spec.columns)

    # Deduplicate normalized headers if a CSV ever repeats a name
    norm_headers: List[str] = []
    seen_counts: Dict[str, int] = {}
    for h in raw_headers:
        nh = to_snake_case(h)
        if nh in seen_counts:
            seen_counts[nh] += 1
            nh = f"{nh}_{seen_counts[nh]}"
        else:
            seen_counts[nh] = 0
        norm_headers.append(nh)

    raw_records: List[Dict[str, Optional[str]]] = []
    for row_vals in reader:
        if not row_vals or all((c or "").strip() == "" for c in row_vals):
            continue
        rec: Dict[str, Optional[str]] = {}
        for idx, col in enumerate(norm_headers):
            rec[col] = row_vals[idx] if idx < len(row_vals) else None
        raw_records.append(rec)

    if not raw_records:
        return [], dict(spec.columns)

    resolved_columns = dict(spec.columns)
    unknown_cols = [c for c in norm_headers if c not in resolved_columns]
    if unknown_cols:
        inferred = infer_column_types(unknown_cols, raw_records[:200])
        resolved_columns.update(inferred)

    parsed_rows: List[Dict[str, Any]] = []
    for rec in raw_records:
        typed: Dict[str, Any] = {}
        for col in norm_headers:
            bq_type = resolved_columns.get(col, "STRING")
            typed[col] = coerce_value(rec.get(col), bq_type)
        # Ensure primary keys exist even if missing from sparse file
        for pk in spec.primary_keys:
            if pk not in typed and not pk.startswith("_"):
                typed[pk] = None
        typed["_ingested_at"] = ingested_at_iso
        typed["_source_file"] = source_file
        typed["_run_id"] = run_id
        typed["_row_hash"] = compute_row_hash(typed)
        parsed_rows.append(typed)

    return parsed_rows, resolved_columns


def rows_to_ndjson_bytes(rows: Iterable[Dict[str, Any]]) -> bytes:
    """Serialize parsed Bronze rows to UTF-8 newline-delimited JSON bytes."""
    lines = [json.dumps(r, ensure_ascii=False, separators=(",", ":")) for r in rows]
    return ("\n".join(lines) + ("\n" if lines else "")).encode("utf-8")
