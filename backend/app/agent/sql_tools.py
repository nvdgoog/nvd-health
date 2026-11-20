from __future__ import annotations

from contextvars import ContextVar
import json
import re
from typing import Any, Dict, List, Optional

_EXECUTED_SQL_LOG: ContextVar[Optional[List[str]]] = ContextVar(
    "_EXECUTED_SQL_LOG", default=None
)


def start_sql_audit_log() -> List[str]:
    """Initialize a per-request SQL audit list in ContextVar."""
    buf: List[str] = []
    _EXECUTED_SQL_LOG.set(buf)
    return buf

FORBIDDEN_SQL_KEYWORDS = re.compile(
    r"\b(INSERT|UPDATE|DELETE|MERGE|DROP|ALTER|CREATE|TRUNCATE|GRANT|REVOKE|EXECUTE|CALL|EXPORT|LOAD|COPY)\b",
    re.IGNORECASE,
)
ALLOWED_DATASETS = ("nvd_health_gold", "nvd_health_silver", "nvd_health_bronze")


def strip_sql_comments(sql: str) -> str:
    """Remove -- single-line and /* ... */ block comments before validation."""
    no_block = re.sub(r"/\*.*?\*/", " ", sql, flags=re.DOTALL)
    no_line = re.sub(r"--[^\n]*", " ", no_block)
    return no_line.strip()


def validate_readonly_sql(sql: str) -> str:
    """
    Validate that an agent-generated SQL query is strictly a single read-only SELECT/WITH query
    against the allowed Medallion health datasets.
    """
    cleaned = strip_sql_comments(sql)
    if not cleaned:
        raise ValueError("SQL query cannot be empty.")

    # Allow at most one trailing semicolon
    without_trailing_semi = cleaned.rstrip(";").strip()
    if ";" in without_trailing_semi:
        raise ValueError("Multiple SQL statements are not allowed.")

    if not re.match(r"^(SELECT|WITH)\b", without_trailing_semi, re.IGNORECASE):
        raise ValueError("Only read-only SELECT or WITH queries are permitted.")

    if FORBIDDEN_SQL_KEYWORDS.search(without_trailing_semi):
        raise ValueError("Query contains forbidden DML/DDL keywords.")

    # Ensure query references at least one authorized dataset or INFORMATION_SCHEMA
    lowered = without_trailing_semi.lower()
    if not any(ds in lowered for ds in ALLOWED_DATASETS):
        raise ValueError(
            "Query must reference tables in nvd_health_gold, nvd_health_silver, or nvd_health_bronze."
        )

    return without_trailing_semi


def get_bq_client() -> Any:
    from google.cloud import bigquery
    from app.config import get_settings

    settings = get_settings()
    return bigquery.Client(
        project=settings.gcp_project_id,
        location=settings.bq_location,
    )


def list_health_tables() -> str:
    """List available tables and views across nvd_health_gold, nvd_health_silver, and nvd_health_bronze."""
    from app.config import get_settings

    settings = get_settings()
    client = get_bq_client()
    catalog: Dict[str, List[Dict[str, str]]] = {}
    for ds in (
        settings.bq_dataset_gold,
        settings.bq_dataset_silver,
        settings.bq_dataset_bronze,
    ):
        entries: List[Dict[str, str]] = []
        try:
            for item in client.list_tables(f"{settings.gcp_project_id}.{ds}"):
                entries.append(
                    {
                        "table_id": item.table_id,
                        "table_type": item.table_type,
                        "fqn": f"{settings.gcp_project_id}.{ds}.{item.table_id}",
                    }
                )
        except Exception as exc:
            entries.append({"error": str(exc)})
        catalog[ds] = entries
    return json.dumps(catalog, indent=2)


def describe_table_schema(dataset: str, table_name: str) -> str:
    """Return column names, BigQuery types, and descriptions for a Medallion table or view."""
    from app.config import get_settings

    if dataset not in ALLOWED_DATASETS:
        return json.dumps({"error": f"Dataset {dataset!r} is not in allowed datasets."})
    settings = get_settings()
    client = get_bq_client()
    fqn = f"{settings.gcp_project_id}.{dataset}.{table_name}"
    table = client.get_table(fqn)
    cols = [
        {
            "name": f.name,
            "type": f.field_type,
            "mode": f.mode,
            "description": f.description or "",
        }
        for f in table.schema
    ]
    return json.dumps(
        {
            "table": fqn,
            "table_type": table.table_type,
            "num_rows": table.num_rows,
            "columns": cols,
        },
        indent=2,
    )


def run_readonly_sql(sql: str, max_rows: int = 200) -> str:
    """
    Execute a validated read-only BigQuery SELECT query across nvd_health_gold,
    nvd_health_silver, or nvd_health_bronze and return JSON rows + row count.
    """
    from google.cloud import bigquery

    safe_sql = validate_readonly_sql(sql)
    audit_log = _EXECUTED_SQL_LOG.get()
    if audit_log is not None and safe_sql not in audit_log:
        audit_log.append(safe_sql)
    bounded_max = max(1, min(int(max_rows), 500))
    client = get_bq_client()
    job_config = bigquery.QueryJobConfig(
        maximum_bytes_billed=5 * 1024 * 1024 * 1024,  # 5 GiB safety guardrail
        use_legacy_sql=False,
    )
    job = client.query(safe_sql, job_config=job_config)
    rows_iter = job.result(max_results=bounded_max)
    records = [dict(r.items()) for r in rows_iter]
    return json.dumps(
        {
            "sql": safe_sql,
            "row_count": len(records),
            "total_rows": rows_iter.total_rows,
            "rows": records,
        },
        default=str,
    )
