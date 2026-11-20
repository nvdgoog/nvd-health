from __future__ import annotations

import asyncio
import json
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, File, HTTPException, Query, Request, UploadFile
from fastapi.responses import StreamingResponse
from google.cloud import bigquery, storage
from pydantic import BaseModel, Field

from app.config import get_settings
from app.etl.bq_loader import BigQueryBronzeLoader
from app.etl.dataform_runner import DataformRunner
from app.etl.pdf_parser import parse_reacthealth_pdf_bytes
from app.etl.registry import ConnectorRegistry
from app.services.cloud_run_jobs import launch_etl_run
from app.services.gcs_signing import build_gcs_object_path, generate_direct_upload_url

router = APIRouter(prefix="/api/admin", tags=["admin"])


class SignedUrlItemRequest(BaseModel):
    relative_path: str
    content_type: str = "application/octet-stream"
    resumable: bool = True


class SignedUrlRequest(BaseModel):
    source_type: str
    relative_path: str
    content_type: str = "application/octet-stream"
    resumable: bool = True
    upload_batch_id: Optional[str] = None


class BatchSignedUrlRequest(BaseModel):
    source_type: str
    files: List[SignedUrlItemRequest] = Field(..., max_length=500)
    upload_batch_id: Optional[str] = None


class TriggerEtlRequest(BaseModel):
    mode: str = Field(
        default="existing_gcs",
        pattern="^(existing_gcs|zip|prefix|reacthealth_pdf)$",
    )
    prefixes: Optional[List[str]] = None
    zip_gcs_path: Optional[str] = None
    force_reload: bool = False


class ReactHealthPreviewRequest(BaseModel):
    gcs_path: str


class UpdateCpapStartDateRequest(BaseModel):
    cpap_start_date: Optional[str] = None
    use_auto_detected: bool = False


class GSheetsSyncRequest(BaseModel):
    spreadsheet_id: Optional[str] = None
    trigger_dataform: bool = True


def _bq_client() -> bigquery.Client:
    s = get_settings()
    return bigquery.Client(project=s.gcp_project_id, location=s.bq_location)


@router.post("/uploads/signed-url")
def create_signed_upload_url(
    payload: SignedUrlRequest, request: Request
) -> Dict[str, Any]:
    batch_id = payload.upload_batch_id or datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    try:
        object_path = build_gcs_object_path(
            source_type=payload.source_type,
            relative_path=payload.relative_path,
            upload_batch_id=batch_id,
        )
        origin = request.headers.get("origin")
        res = generate_direct_upload_url(
            object_path=object_path,
            content_type=payload.content_type,
            resumable=payload.resumable,
            origin=origin,
        )
        res["upload_batch_id"] = batch_id
        return res
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to sign GCS URL: {exc}") from exc


@router.post("/uploads/signed-urls-batch")
def create_batch_signed_upload_urls(
    payload: BatchSignedUrlRequest, request: Request
) -> Dict[str, Any]:
    batch_id = payload.upload_batch_id or datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    origin = request.headers.get("origin")
    items: List[Dict[str, Any]] = []
    try:
        for f in payload.files:
            object_path = build_gcs_object_path(
                source_type=payload.source_type,
                relative_path=f.relative_path,
                upload_batch_id=batch_id,
            )
            signed = generate_direct_upload_url(
                object_path=object_path,
                content_type=f.content_type,
                resumable=f.resumable,
                origin=origin,
            )
            signed["relative_path"] = f.relative_path
            items.append(signed)
        return {
            "upload_batch_id": batch_id,
            "prefix": f"{build_gcs_object_path(payload.source_type, '_marker', batch_id).rsplit('/', 1)[0]}/",
            "items": items,
        }
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Batch URL signing failed: {exc}") from exc


@router.post("/reacthealth/preview")
def preview_reacthealth_pdf(payload: ReactHealthPreviewRequest) -> Dict[str, Any]:
    """Download an uploaded ReactHealth PDF from GCS and return header + day counts preview."""
    settings = get_settings()
    try:
        storage_client = storage.Client(project=settings.gcp_project_id)
        bucket = storage_client.bucket(settings.gcs_raw_bucket)
        blob = bucket.blob(payload.gcs_path)
        if not blob.exists():
            raise HTTPException(status_code=404, detail=f"GCS object not found: {payload.gcs_path}")
        pdf_bytes = blob.download_as_bytes()
        parsed = parse_reacthealth_pdf_bytes(
            pdf_bytes=pdf_bytes,
            source_file=payload.gcs_path,
            run_id="preview",
            ingested_at_iso=datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        )
        return {
            "metadata": parsed.report_metadata,
            "valid_days_count": len(parsed.daily_rows),
            "no_data_days_count": len(parsed.no_data_dates),
            "no_data_dates_sample": parsed.no_data_dates[:15],
            "daily_rows_preview": parsed.daily_rows[:14],
            "warnings": parsed.warnings,
        }
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"PDF parse error: {exc}") from exc


@router.post("/reacthealth/preview-local")
async def preview_reacthealth_pdf_local(file: UploadFile = File(...)) -> Dict[str, Any]:
    """Optional instant preview endpoint for small ReactHealth PDFs directly before/with GCS upload."""
    pdf_bytes = await file.read()
    try:
        parsed = parse_reacthealth_pdf_bytes(
            pdf_bytes=pdf_bytes,
            source_file=file.filename or "upload.pdf",
            run_id="preview",
            ingested_at_iso=datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        )
        return {
            "metadata": parsed.report_metadata,
            "valid_days_count": len(parsed.daily_rows),
            "no_data_days_count": len(parsed.no_data_dates),
            "no_data_dates_sample": parsed.no_data_dates[:15],
            "daily_rows_preview": parsed.daily_rows[:14],
            "warnings": parsed.warnings,
        }
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"PDF parse error: {exc}") from exc


@router.post("/etl/trigger")
def trigger_etl(payload: TriggerEtlRequest) -> Dict[str, Any]:
    try:
        return launch_etl_run(
            mode=payload.mode,
            prefixes=payload.prefixes,
            zip_gcs_path=payload.zip_gcs_path,
            force_reload=payload.force_reload,
        )
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to trigger ETL run: {exc}") from exc


@router.get("/etl/runs")
def list_etl_runs(limit: int = Query(default=20, ge=1, le=100)) -> Dict[str, Any]:
    settings = get_settings()
    client = _bq_client()
    sql = f"""
    SELECT *
    FROM `{settings.gcp_project_id}.{settings.bq_dataset_bronze}.bronze_etl_runs`
    ORDER BY started_at DESC
    LIMIT @limit
    """
    job_config = bigquery.QueryJobConfig(
        query_parameters=[bigquery.ScalarQueryParameter("limit", "INT64", limit)]
    )
    try:
        rows = [dict(r.items()) for r in client.query(sql, job_config=job_config).result()]
        for r in rows:
            r["table_stats"] = _safe_json_loads(r.get("table_stats_json"), {})
            r["source_prefixes"] = _safe_json_loads(r.get("source_prefixes_json"), [])
        return {"runs": rows}
    except Exception:
        return {"runs": []}


@router.get("/etl/runs/{run_id}")
def get_etl_run(run_id: str) -> Dict[str, Any]:
    settings = get_settings()
    client = _bq_client()
    sql = f"""
    SELECT *
    FROM `{settings.gcp_project_id}.{settings.bq_dataset_bronze}.bronze_etl_runs`
    WHERE run_id = @run_id
    LIMIT 1
    """
    job_config = bigquery.QueryJobConfig(
        query_parameters=[bigquery.ScalarQueryParameter("run_id", "STRING", run_id)]
    )
    rows = [dict(r.items()) for r in client.query(sql, job_config=job_config).result()]
    if not rows:
        raise HTTPException(status_code=404, detail=f"Run not found: {run_id}")
    run = rows[0]
    run["table_stats"] = _safe_json_loads(run.get("table_stats_json"), {})
    run["source_prefixes"] = _safe_json_loads(run.get("source_prefixes_json"), [])

    dataform_actions: List[Dict[str, Any]] = []
    if run.get("dataform_invocation_id"):
        try:
            df_runner = DataformRunner(
                project_id=settings.gcp_project_id,
                region=settings.gcp_region,
                repository_id=settings.dataform_repository_id,
                workspace_id=settings.dataform_workspace_id,
                dataform_dir=settings.dataform_dir,
                bq_location=settings.bq_location,
                silver_dataset=settings.bq_dataset_silver,
            )
            df_status = df_runner.get_invocation_status(run["dataform_invocation_id"])
            dataform_actions = df_status.get("actions", [])  # type: ignore[assignment]
        except Exception:
            pass
    run["dataform_actions"] = dataform_actions
    return run


@router.get("/etl/runs/{run_id}/stream")
async def stream_etl_run(run_id: str) -> StreamingResponse:
    """Server-Sent Events stream providing live ETL + Dataform progress updates."""

    async def event_generator():
        for _ in range(300):  # up to 10 minutes
            try:
                run = get_etl_run(run_id)
                yield f"data: {json.dumps(run, default=str)}\n\n"
                if run.get("status") in ("COMPLETED", "FAILED"):
                    break
            except HTTPException:
                yield f"data: {json.dumps({'run_id': run_id, 'status': 'PENDING'})}\n\n"
            await asyncio.sleep(2.0)

    return StreamingResponse(event_generator(), media_type="text/event-stream")


@router.get("/ledger")
def get_ingestion_ledger() -> Dict[str, Any]:
    settings = get_settings()
    client = _bq_client()
    bronze_fqn = f"{settings.gcp_project_id}.{settings.bq_dataset_bronze}"
    silver_fqn = f"{settings.gcp_project_id}.{settings.bq_dataset_silver}"

    sources_sql = f"""
    SELECT
      source_type,
      COUNT(*) AS total_files,
      COUNTIF(status = 'LOADED') AS loaded_files,
      COUNTIF(status = 'IGNORED') AS ignored_files,
      COUNTIF(status = 'FAILED') AS failed_files,
      SUM(COALESCE(row_count, 0)) AS total_rows_ingested,
      MAX(ingested_at) AS last_ingested_at
    FROM `{bronze_fqn}.bronze_ingestion_ledger`
    GROUP BY source_type
    ORDER BY source_type
    """
    tables_sql = f"""
    SELECT
      table_id,
      row_count,
      ROUND(size_bytes / (1024 * 1024), 2) AS size_mb,
      TIMESTAMP_MILLIS(last_modified_time) AS last_modified_at
    FROM `{bronze_fqn}.__TABLES__`
    WHERE NOT STARTS_WITH(table_id, '_stage_')
    ORDER BY row_count DESC, table_id ASC
    """
    coverage_sql = f"""
    SELECT
      CAST(MIN(health_date) AS STRING) AS min_health_date,
      CAST(MAX(health_date) AS STRING) AS max_health_date,
      COUNT(*) AS total_silver_days,
      COUNTIF(cpap_usage_minutes IS NOT NULL) AS cpap_days_present,
      COUNTIF(total_sleep_minutes IS NOT NULL) AS google_sleep_days_present,
      CAST(MIN(IF(cpap_usage_minutes IS NOT NULL, health_date, NULL)) AS STRING) AS cpap_min_date,
      CAST(MAX(IF(cpap_usage_minutes IS NOT NULL, health_date, NULL)) AS STRING) AS cpap_max_date
    FROM `{silver_fqn}.daily_health_summary`
    """
    recent_files_sql = f"""
    SELECT file_path, source_type, target_table, row_count, status, error_message, last_run_id, ingested_at
    FROM `{bronze_fqn}.bronze_ingestion_ledger`
    ORDER BY ingested_at DESC
    LIMIT 50
    """

    def _table_exists(table_fqn: str) -> bool:
        try:
            client.get_table(table_fqn)
            return True
        except Exception:
            return False

    def safe_query(sql: str) -> List[Dict[str, Any]]:
        try:
            return [dict(r.items()) for r in client.query(sql).result()]
        except Exception:
            return []

    cov_rows = (
        safe_query(coverage_sql)
        if _table_exists(f"{silver_fqn}.daily_health_summary")
        else []
    )
    bronze_exists = _table_exists(f"{bronze_fqn}.bronze_ingestion_ledger")
    return {
        "sources": safe_query(sources_sql) if bronze_exists else [],
        "bronze_tables": safe_query(tables_sql),
        "coverage": cov_rows[0] if cov_rows else {},
        "recent_files": safe_query(recent_files_sql) if bronze_exists else [],
    }


@router.get("/settings")
def get_admin_settings() -> Dict[str, Any]:
    settings = get_settings()
    client = _bq_client()
    sql = f"""
    SELECT setting_key, setting_value, auto_detected_value, is_manual_override, updated_at, updated_by
    FROM `{settings.gcp_project_id}.{settings.bq_dataset_bronze}.bronze_app_settings`
    WHERE setting_key = 'cpap_start_date'
    LIMIT 1
    """
    try:
        rows = [dict(r.items()) for r in client.query(sql).result()]
        if rows:
            return rows[0]
    except Exception:
        pass
    return {
        "setting_key": "cpap_start_date",
        "setting_value": settings.default_cpap_start_date,
        "auto_detected_value": settings.default_cpap_start_date,
        "is_manual_override": False,
        "updated_at": None,
        "updated_by": "default",
    }


@router.put("/settings/cpap-start-date")
def update_cpap_start_date(payload: UpdateCpapStartDateRequest) -> Dict[str, Any]:
    settings = get_settings()
    client = _bq_client()
    loader = BigQueryBronzeLoader(
        client=client,
        project_id=settings.gcp_project_id,
        bronze_dataset=settings.bq_dataset_bronze,
        location=settings.bq_location,
    )
    loader.ensure_datasets_and_core_tables(
        silver_dataset=settings.bq_dataset_silver,
        gold_dataset=settings.bq_dataset_gold,
        default_cpap_start_date=settings.default_cpap_start_date,
    )
    if payload.use_auto_detected:
        sql = f"""
        UPDATE `{loader.fqn('bronze_app_settings')}`
        SET is_manual_override = FALSE,
            setting_value = auto_detected_value,
            updated_at = CURRENT_TIMESTAMP(),
            updated_by = 'admin_reset_auto'
        WHERE setting_key = 'cpap_start_date'
        """
        client.query(sql).result()
        loader.refresh_auto_detected_cpap_start_date(settings.default_cpap_start_date)
    else:
        if not payload.cpap_start_date:
            raise HTTPException(status_code=400, detail="cpap_start_date is required unless use_auto_detected=true.")
        try:
            datetime.strptime(payload.cpap_start_date, "%Y-%m-%d")
        except ValueError as exc:
            raise HTTPException(status_code=400, detail="cpap_start_date must be YYYY-MM-DD.") from exc
        sql = f"""
        MERGE `{loader.fqn('bronze_app_settings')}` AS T
        USING (SELECT 'cpap_start_date' AS setting_key, @val AS val) AS S
        ON T.setting_key = S.setting_key
        WHEN MATCHED THEN
          UPDATE SET setting_value = S.val, is_manual_override = TRUE, updated_at = CURRENT_TIMESTAMP(), updated_by = 'admin_manual_override'
        WHEN NOT MATCHED THEN
          INSERT (setting_key, setting_value, auto_detected_value, is_manual_override, updated_at, updated_by)
          VALUES ('cpap_start_date', S.val, @default_val, TRUE, CURRENT_TIMESTAMP(), 'admin_manual_override')
        """
        job_config = bigquery.QueryJobConfig(
            query_parameters=[
                bigquery.ScalarQueryParameter("val", "STRING", payload.cpap_start_date),
                bigquery.ScalarQueryParameter("default_val", "STRING", settings.default_cpap_start_date),
            ]
        )
        client.query(sql, job_config=job_config).result()

    return get_admin_settings()


@router.get("/connectors")
def list_connectors() -> Dict[str, Any]:
    registry = ConnectorRegistry()
    return {"connectors": registry.list_connectors()}


@router.get("/gsheets/status")
def get_gsheets_status() -> Dict[str, Any]:
    settings = get_settings()
    client = _bq_client()
    bronze_fqn = f"{settings.gcp_project_id}.{settings.bq_dataset_bronze}"
    obs_fqn = f"{bronze_fqn}.bronze_journal_daily_observations"
    notes_fqn = f"{bronze_fqn}.bronze_journal_baseline_notes"

    obs_count = 0
    notes_count = 0
    min_date = None
    max_date = None
    try:
        client.get_table(obs_fqn)
        row = list(
            client.query(
                f"SELECT COUNT(*) AS cnt, CAST(MIN(observation_date) AS STRING) AS mn, CAST(MAX(observation_date) AS STRING) AS mx FROM `{obs_fqn}`"
            ).result()
        )[0]
        obs_count = int(row["cnt"] or 0)
        min_date = row["mn"]
        max_date = row["mx"]
    except Exception:
        pass
    try:
        client.get_table(notes_fqn)
        row = list(client.query(f"SELECT COUNT(*) AS cnt FROM `{notes_fqn}`").result())[0]
        notes_count = int(row["cnt"] or 0)
    except Exception:
        pass

    return {
        "spreadsheet_id": settings.google_sheet_id,
        "web_service_account": f"nvd-health-web-sa@{settings.gcp_project_id}.iam.gserviceaccount.com",
        "etl_service_account": f"nvd-health-etl-sa@{settings.gcp_project_id}.iam.gserviceaccount.com",
        "observation_rows": obs_count,
        "baseline_note_rows": notes_count,
        "min_date": min_date,
        "max_date": max_date,
    }


@router.post("/gsheets/sync")
def sync_google_sheet_observations(payload: Optional[GSheetsSyncRequest] = None) -> Dict[str, Any]:
    from app.etl.gsheets_sync import fetch_and_sync_google_sheet

    settings = get_settings()
    req = payload or GSheetsSyncRequest()
    try:
        return fetch_and_sync_google_sheet(
            spreadsheet_id=req.spreadsheet_id or settings.google_sheet_id,
            trigger_dataform=req.trigger_dataform,
        )
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Google Sheet sync failed: {exc}") from exc


def _safe_json_loads(raw: Optional[str], fallback: Any) -> Any:
    if not raw:
        return fallback
    try:
        return json.loads(raw)
    except Exception:
        return fallback
