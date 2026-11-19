from __future__ import annotations

import json
import os
import threading
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from google.cloud import bigquery

from app.config import Settings, get_settings
from app.etl.bq_loader import BigQueryBronzeLoader
from app.etl.runner import DEFAULT_SCAN_PREFIXES, HealthEtlRunner, utc_now_iso


def launch_etl_run(
    mode: str,
    prefixes: Optional[List[str]] = None,
    zip_gcs_path: Optional[str] = None,
    force_reload: bool = False,
    settings: Optional[Settings] = None,
) -> Dict[str, Any]:
    """
    Create an initial QUEUED run record in bronze_etl_runs and trigger the
    Cloud Run Job ETL worker (or an in-process background thread in local dev).
    """
    cfg = settings or get_settings()
    run_id = f"run-{datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4().hex[:6]}"

    bq_client = bigquery.Client(project=cfg.gcp_project_id, location=cfg.bq_location)
    loader = BigQueryBronzeLoader(
        client=bq_client,
        project_id=cfg.gcp_project_id,
        bronze_dataset=cfg.bq_dataset_bronze,
        location=cfg.bq_location,
    )
    loader.ensure_datasets_and_core_tables(
        silver_dataset=cfg.bq_dataset_silver,
        gold_dataset=cfg.bq_dataset_gold,
        default_cpap_start_date=cfg.default_cpap_start_date,
    )

    now = utc_now_iso()
    effective_prefixes = prefixes or ([zip_gcs_path] if zip_gcs_path else list(DEFAULT_SCAN_PREFIXES))
    loader.upsert_etl_run(
        {
            "run_id": run_id,
            "trigger_mode": mode,
            "status": "QUEUED",
            "current_stage": "Dispatching ETL worker",
            "source_prefixes_json": json.dumps(effective_prefixes),
            "files_total": 0,
            "files_scanned": 0,
            "files_loaded": 0,
            "files_skipped": 0,
            "files_failed": 0,
            "rows_inserted": 0,
            "rows_updated": 0,
            "table_stats_json": json.dumps({}),
            "dataform_compilation_id": None,
            "dataform_invocation_id": None,
            "dataform_status": "PENDING",
            "error_message": None,
            "started_at": now,
            "updated_at": now,
            "completed_at": None,
        }
    )

    if os.environ.get("LOCAL_INPROCESS_ETL", "").lower() == "true":
        thread = threading.Thread(
            target=_run_inprocess,
            kwargs={
                "run_id": run_id,
                "mode": mode,
                "prefixes": prefixes,
                "zip_gcs_path": zip_gcs_path,
                "force_reload": force_reload,
                "settings": cfg,
            },
            daemon=True,
        )
        thread.start()
        return {
            "run_id": run_id,
            "status": "QUEUED",
            "execution_target": "local_thread",
        }

    from google.cloud import run_v2

    jobs_client = run_v2.JobsClient()
    job_name = (
        f"projects/{cfg.gcp_project_id}/locations/{cfg.gcp_region}"
        f"/jobs/{cfg.cloud_run_job_name}"
    )
    env_vars = [
        run_v2.EnvVar(name="ETL_RUN_ID", value=run_id),
        run_v2.EnvVar(name="ETL_MODE", value=mode),
        run_v2.EnvVar(name="ETL_PREFIXES", value=",".join(prefixes or [])),
        run_v2.EnvVar(name="ETL_ZIP_PATH", value=zip_gcs_path or ""),
        run_v2.EnvVar(name="ETL_FORCE_RELOAD", value="true" if force_reload else "false"),
    ]
    request = run_v2.RunJobRequest(
        name=job_name,
        overrides=run_v2.RunJobRequest.Overrides(
            container_overrides=[
                run_v2.RunJobRequest.Overrides.ContainerOverride(env=env_vars)
            ]
        ),
    )
    operation = jobs_client.run_job(request=request)
    execution_name = getattr(getattr(operation, "metadata", None), "name", "")
    return {
        "run_id": run_id,
        "status": "QUEUED",
        "execution_target": "cloud_run_job",
        "execution_name": execution_name,
    }


def _run_inprocess(
    run_id: str,
    mode: str,
    prefixes: Optional[List[str]],
    zip_gcs_path: Optional[str],
    force_reload: bool,
    settings: Settings,
) -> None:
    runner = HealthEtlRunner(settings=settings)
    try:
        runner.run(
            run_id=run_id,
            trigger_mode=mode,
            prefixes=prefixes,
            zip_gcs_path=zip_gcs_path,
            trigger_dataform=True,
            force_reload=force_reload,
        )
    except Exception:
        # Runner already records FAILED state in bronze_etl_runs
        pass
