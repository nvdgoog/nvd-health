from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any, Dict, Iterable, List, Optional, Sequence, Tuple

if TYPE_CHECKING:
    from google.cloud import bigquery

from app.etl.csv_parser import rows_to_ndjson_bytes
from app.etl.schemas import CORE_HEALTH_TABLES, SYSTEM_TABLES, TableSchemaSpec


def build_schema_fields(columns: Dict[str, str]) -> List["bigquery.SchemaField"]:
    """Convert a {col_name: bq_type} dict into BigQuery SchemaField objects."""
    from google.cloud import bigquery

    return [
        bigquery.SchemaField(name=col_name, field_type=col_type, mode="NULLABLE")
        for col_name, col_type in columns.items()
    ]


def build_merge_sql(
    target_table_fqn: str,
    stage_table_fqn: str,
    spec: TableSchemaSpec,
    all_columns: Sequence[str],
) -> str:
    """
    Build an idempotent BigQuery MERGE statement from a deduplicated staging table.

    Deduplicates incoming stage rows per natural primary key (keeping latest
    order_by_column or _ingested_at) before merging into target.
    """
    pk_cols = list(spec.primary_keys) if spec.primary_keys else ["_row_hash"]
    # Ensure PKs exist in all_columns
    valid_pks = [pk for pk in pk_cols if pk in all_columns] or ["_row_hash"]

    order_parts: List[str] = []
    if spec.order_by_column and spec.order_by_column in all_columns:
        order_parts.append(f"`{spec.order_by_column}` DESC NULLS LAST")
    for fallback_col in ("_ingested_at", "updated_at", "ingested_at", "started_at"):
        if fallback_col in all_columns and fallback_col != spec.order_by_column:
            order_parts.append(f"`{fallback_col}` DESC NULLS LAST")
            break
    order_expr = ", ".join(order_parts) if order_parts else "1"
    partition_by = ", ".join(f"`{pk}`" for pk in valid_pks)

    dedup_source = (
        f"(\n"
        f"  SELECT * FROM `{stage_table_fqn}`\n"
        f"  QUALIFY ROW_NUMBER() OVER (PARTITION BY {partition_by} ORDER BY {order_expr}) = 1\n"
        f")"
    )

    on_clause = " AND ".join(
        f"T.`{pk}` IS NOT DISTINCT FROM S.`{pk}`" for pk in valid_pks
    )

    non_pk_cols = [c for c in all_columns if c not in valid_pks]
    update_clause = ""
    if non_pk_cols:
        assignments = ", ".join(f"`{c}` = S.`{c}`" for c in non_pk_cols)
        match_guard = ""
        if spec.table_name == "bronze_reacthealth_daily_usage":
            match_guard = (
                " AND (S.`report_generated_date` >= T.`report_generated_date`"
                " OR T.`report_generated_date` IS NULL)"
            )
        update_clause = f"WHEN MATCHED{match_guard} THEN\n  UPDATE SET {assignments}\n"

    insert_cols = ", ".join(f"`{c}`" for c in all_columns)
    insert_vals = ", ".join(f"S.`{c}`" for c in all_columns)

    return (
        f"MERGE `{target_table_fqn}` AS T\n"
        f"USING {dedup_source} AS S\n"
        f"ON {on_clause}\n"
        f"{update_clause}"
        f"WHEN NOT MATCHED THEN\n"
        f"  INSERT ({insert_cols})\n"
        f"  VALUES ({insert_vals});"
    )


class BigQueryBronzeLoader:
    """Manages Bronze datasets, schemas, ledger lookup, and atomic MERGE loads."""

    def __init__(
        self,
        client: bigquery.Client,
        project_id: str,
        bronze_dataset: str,
        location: str = "US",
    ) -> None:
        self.client = client
        self.project_id = project_id
        self.bronze_dataset = bronze_dataset
        self.location = location

    def fqn(self, table_name: str) -> str:
        return f"{self.project_id}.{self.bronze_dataset}.{table_name}"

    def ensure_datasets_and_core_tables(
        self,
        silver_dataset: str,
        gold_dataset: str,
        default_cpap_start_date: str = "2026-10-13",
    ) -> None:
        """Create Medallion datasets and empty typed core/system Bronze tables if absent."""
        from google.cloud import bigquery

        for ds_id in (self.bronze_dataset, silver_dataset, gold_dataset):
            ds_ref = bigquery.Dataset(f"{self.project_id}.{ds_id}")
            ds_ref.location = self.location
            self.client.create_dataset(ds_ref, exists_ok=True)

        for spec in list(SYSTEM_TABLES.values()) + list(CORE_HEALTH_TABLES.values()):
            self.ensure_table(spec, spec.columns)

        # Seed cpap_start_date setting if missing
        self.ensure_default_cpap_setting(default_cpap_start_date)

    def ensure_table(
        self,
        spec: TableSchemaSpec,
        resolved_columns: Dict[str, str],
    ) -> "bigquery.Table":
        """Ensure target Bronze table exists with partitioning, clustering, and evolved columns."""
        from google.cloud import bigquery

        table_id = self.fqn(spec.table_name)
        schema_fields = build_schema_fields(resolved_columns)
        try:
            existing = self.client.get_table(table_id)
            if spec.allow_schema_evolution:
                existing_names = {f.name for f in existing.schema}
                missing = [f for f in schema_fields if f.name not in existing_names]
                if missing:
                    existing.schema = list(existing.schema) + missing
                    existing = self.client.update_table(existing, ["schema"])
            return existing
        except Exception:
            table = bigquery.Table(table_id, schema=schema_fields)
            table.description = spec.description or None
            if spec.partition_field and spec.partition_field in resolved_columns:
                col_type = resolved_columns[spec.partition_field]
                if col_type in ("TIMESTAMP", "DATE", "DATETIME"):
                    table.time_partitioning = bigquery.TimePartitioning(
                        type_=bigquery.TimePartitioningType.DAY,
                        field=spec.partition_field,
                    )
            valid_clusters = [
                c for c in spec.clustering_fields if c in resolved_columns
            ]
            if valid_clusters:
                table.clustering_fields = valid_clusters[:4]
            return self.client.create_table(table, exists_ok=True)

    def load_and_merge_rows(
        self,
        spec: TableSchemaSpec,
        rows: List[Dict[str, Any]],
        resolved_columns: Dict[str, str],
    ) -> Dict[str, int]:
        """Load rows into a temporary staging table and execute 1 atomic MERGE."""
        if not rows:
            return {"staged": 0, "inserted": 0, "updated": 0}

        # Ensure all keys present across batch are represented in resolved_columns
        merged_cols = dict(resolved_columns)
        for row in rows:
            for k in row.keys():
                if k not in merged_cols:
                    merged_cols[k] = "STRING"

        target_table = self.ensure_table(spec, merged_cols)
        # Reconcile column order with existing BigQuery table schema
        final_col_types: Dict[str, str] = {
            f.name: f.field_type for f in target_table.schema
        }
        for k, v in merged_cols.items():
            if k not in final_col_types:
                final_col_types[k] = v

        from google.cloud import bigquery

        stage_name = f"_stage_{spec.table_name}_{uuid.uuid4().hex[:10]}"
        stage_fqn = self.fqn(stage_name)
        stage_schema = build_schema_fields(final_col_types)

        ndjson_bytes = rows_to_ndjson_bytes(rows)
        job_config = bigquery.LoadJobConfig(
            schema=stage_schema,
            source_format=bigquery.SourceFormat.NEWLINE_DELIMITED_JSON,
            write_disposition=bigquery.WriteDisposition.WRITE_TRUNCATE,
            ignore_unknown_values=True,
        )

        import io

        try:
            load_job = self.client.load_table_from_file(
                io.BytesIO(ndjson_bytes),
                stage_fqn,
                job_config=job_config,
                location=self.location,
            )
            load_job.result()

            merge_sql = build_merge_sql(
                target_table_fqn=self.fqn(spec.table_name),
                stage_table_fqn=stage_fqn,
                spec=spec,
                all_columns=list(final_col_types.keys()),
            )
            merge_job = self.client.query(merge_sql, location=self.location)
            merge_job.result()
            dml_stats = merge_job.dml_stats
            inserted = int(dml_stats.inserted_row_count) if dml_stats else len(rows)
            updated = int(dml_stats.updated_row_count) if dml_stats else 0
            return {
                "staged": len(rows),
                "inserted": inserted,
                "updated": updated,
            }
        finally:
            self.client.delete_table(stage_fqn, not_found_ok=True)

    def fetch_ledger_hashes(self) -> Dict[str, str]:
        """Return {file_path: content_hash} for all previously LOADED or IGNORED files."""
        sql = (
            f"SELECT file_path, content_hash "
            f"FROM `{self.fqn('bronze_ingestion_ledger')}` "
            f"WHERE status IN ('LOADED', 'IGNORED')"
        )
        rows = self.client.query(sql, location=self.location).result()
        return {r["file_path"]: r["content_hash"] for r in rows}

    def upsert_ledger_entries(self, entries: List[Dict[str, Any]]) -> None:
        if not entries:
            return
        spec = SYSTEM_TABLES["bronze_ingestion_ledger"]
        self.load_and_merge_rows(spec, entries, spec.columns)

    def upsert_etl_run(self, run_record: Dict[str, Any]) -> None:
        spec = SYSTEM_TABLES["bronze_etl_runs"]
        self.load_and_merge_rows(spec, [run_record], spec.columns)

    def ensure_default_cpap_setting(self, default_date: str) -> None:
        from google.cloud import bigquery

        sql = f"""
        MERGE `{self.fqn('bronze_app_settings')}` AS T
        USING (
          SELECT 'cpap_start_date' AS setting_key,
                 @default_date AS setting_value,
                 @default_date AS auto_detected_value,
                 FALSE AS is_manual_override,
                 CURRENT_TIMESTAMP() AS updated_at,
                 'system_bootstrap' AS updated_by
        ) AS S
        ON T.setting_key = S.setting_key
        WHEN NOT MATCHED THEN
          INSERT (setting_key, setting_value, auto_detected_value, is_manual_override, updated_at, updated_by)
          VALUES (S.setting_key, S.setting_value, S.auto_detected_value, S.is_manual_override, S.updated_at, S.updated_by);
        """
        job_config = bigquery.QueryJobConfig(
            query_parameters=[
                bigquery.ScalarQueryParameter("default_date", "STRING", default_date)
            ]
        )
        self.client.query(sql, job_config=job_config, location=self.location).result()

    def refresh_auto_detected_cpap_start_date(self, fallback_date: str) -> str:
        """
        Auto-detect the earliest non-zero CPAP usage night from bronze_reacthealth_daily_usage.
        Updates setting_value only if is_manual_override is FALSE.
        """
        from google.cloud import bigquery

        detect_sql = f"""
        SELECT CAST(MIN(usage_date) AS STRING) AS first_nonzero_date
        FROM `{self.fqn('bronze_reacthealth_daily_usage')}`
        WHERE usage_minutes > 0
        """
        rows = list(self.client.query(detect_sql, location=self.location).result())
        detected = (
            rows[0]["first_nonzero_date"]
            if rows and rows[0]["first_nonzero_date"]
            else fallback_date
        )

        merge_sql = f"""
        MERGE `{self.fqn('bronze_app_settings')}` AS T
        USING (SELECT 'cpap_start_date' AS setting_key, @detected AS detected) AS S
        ON T.setting_key = S.setting_key
        WHEN MATCHED THEN
          UPDATE SET
            auto_detected_value = S.detected,
            setting_value = IF(T.is_manual_override, T.setting_value, S.detected),
            updated_at = CURRENT_TIMESTAMP(),
            updated_by = 'auto_detect'
        WHEN NOT MATCHED THEN
          INSERT (setting_key, setting_value, auto_detected_value, is_manual_override, updated_at, updated_by)
          VALUES ('cpap_start_date', S.detected, S.detected, FALSE, CURRENT_TIMESTAMP(), 'auto_detect');
        """
        job_config = bigquery.QueryJobConfig(
            query_parameters=[
                bigquery.ScalarQueryParameter("detected", "STRING", detected)
            ]
        )
        self.client.query(merge_sql, job_config=job_config, location=self.location).result()
        return detected
