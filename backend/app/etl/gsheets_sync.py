from __future__ import annotations

import hashlib
import re
import uuid
from datetime import date, datetime, timezone
from typing import Any, Dict, List, Optional, Sequence, Tuple

from app.etl.pdf_parser import parse_mmddyy
from app.etl.schemas import CORE_HEALTH_TABLES

SHEET_DATE_ISO_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
SHEET_DATE_MDY_RE = re.compile(r"^\d{1,2}/\d{1,2}/\d{2,4}$")


def _clean_cell(val: Any) -> Optional[str]:
    if val is None:
        return None
    s = str(val).strip()
    if not s or s.lower() in {"n/a", "na", "null", "none", "-"}:
        return None
    return s


def _parse_sheet_date(raw: Optional[str]) -> Optional[str]:
    if not raw:
        return None
    s = raw.strip()
    if SHEET_DATE_ISO_RE.match(s):
        return s
    if SHEET_DATE_MDY_RE.match(s):
        return parse_mmddyy(s)
    return None


def _parse_float(raw: Optional[str]) -> Optional[float]:
    if not raw:
        return None
    cleaned = re.sub(r"[^0-9.-]", "", raw)
    if not cleaned:
        return None
    try:
        return float(cleaned)
    except ValueError:
        return None


def _parse_int(raw: Optional[str]) -> Optional[int]:
    if not raw:
        return None
    cleaned = re.sub(r"[^0-9-]", "", raw)
    if not cleaned:
        return None
    try:
        return int(cleaned)
    except ValueError:
        return None


def parse_sheet_observations(
    data_values: Sequence[Sequence[Any]],
    notes_values: Sequence[Sequence[Any]],
    spreadsheet_id: str,
    run_id: str,
    ingested_at_iso: str,
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """
    Extract ONLY subjective activities, morning coffee, wake-up observations, and
    baseline habit notes from the Google Sheet, leaving Google Health & CPAP metrics
    sourced exclusively from official exports.
    """
    source_label = f"gsheet://{spreadsheet_id}"
    obs_rows: List[Dict[str, Any]] = []

    if data_values:
        headers = [str(h).strip().lower() for h in data_values[0]]

        def _find_col(*candidates: str) -> Optional[int]:
            for idx, h in enumerate(headers):
                for cand in candidates:
                    if cand in h:
                        return idx
            return None

        idx_night = _find_col("night")
        idx_date = _find_col("date")
        idx_activity = _find_col("activity notes")
        idx_coffee = _find_col("coffee")
        idx_wake = _find_col("self observation", "sleeping experience", "wake-up", "observation")

        if idx_date is not None:
            for row in data_values[1:]:
                raw_date = _clean_cell(row[idx_date]) if idx_date < len(row) else None
                obs_date = _parse_sheet_date(raw_date)
                if not obs_date:
                    continue

                night_num = (
                    _parse_int(_clean_cell(row[idx_night]))
                    if idx_night is not None and idx_night < len(row)
                    else None
                )
                activity = (
                    _clean_cell(row[idx_activity])
                    if idx_activity is not None and idx_activity < len(row)
                    else None
                )
                coffee = (
                    _parse_float(_clean_cell(row[idx_coffee]))
                    if idx_coffee is not None and idx_coffee < len(row)
                    else None
                )
                wake_notes = (
                    _clean_cell(row[idx_wake])
                    if idx_wake is not None and idx_wake < len(row)
                    else None
                )

                # Keep row if any anecdotal/activity/coffee observation was entered
                if activity is None and coffee is None and wake_notes is None:
                    continue

                row_hash = hashlib.sha256(
                    f"{obs_date}|{night_num}|{activity}|{coffee}|{wake_notes}".encode("utf-8")
                ).hexdigest()
                obs_rows.append(
                    {
                        "observation_date": obs_date,
                        "night_number": night_num,
                        "activity_notes": activity,
                        "morning_coffee_cups": coffee,
                        "wake_up_observations": wake_notes,
                        "_ingested_at": ingested_at_iso,
                        "_source_file": f"{source_label}/Data",
                        "_run_id": run_id,
                        "_row_hash": row_hash,
                    }
                )

    note_rows: List[Dict[str, Any]] = []
    current_category = "General Routines"
    for row in notes_values:
        cells = [str(c).strip() for c in row if c is not None and str(c).strip()]
        if not cells:
            continue
        # Category header rows sit in column A (non-empty col 0 when col 1 is empty)
        first = str(row[0]).strip() if len(row) > 0 and row[0] is not None else ""
        if first and len(cells) == 1 and first.endswith(":"):
            current_category = first.rstrip(":")
            continue
        text = " — ".join(cells)
        note_id = hashlib.sha256(f"{current_category}|{text}".encode("utf-8")).hexdigest()[:24]
        note_rows.append(
            {
                "note_id": note_id,
                "note_category": current_category,
                "note_text": text,
                "_ingested_at": ingested_at_iso,
                "_source_file": f"{source_label}/Notes",
                "_run_id": run_id,
                "_row_hash": note_id,
            }
        )

    return obs_rows, note_rows


def fetch_and_sync_google_sheet(
    spreadsheet_id: str,
    run_id: Optional[str] = None,
    trigger_dataform: bool = True,
) -> Dict[str, Any]:
    """Fetch Data & Notes tabs from Google Sheets via ADC credentials and merge into Bronze."""
    import google.auth
    from google.auth.transport.requests import Request
    from google.cloud import bigquery
    import httpx

    from app.config import get_settings
    from app.etl.bq_loader import BigQueryBronzeLoader
    from app.etl.dataform_runner import DataformRunner

    settings = get_settings()
    sid = spreadsheet_id or settings.google_sheet_id
    eff_run_id = run_id or f"gsheet-{datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4().hex[:6]}"
    now_iso = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")

    creds, _ = google.auth.default(
        scopes=["https://www.googleapis.com/auth/spreadsheets.readonly"]
    )
    if not creds.valid:
        creds.refresh(Request())

    headers = {"Authorization": f"Bearer {creds.token}"}
    base_url = f"https://sheets.googleapis.com/v4/spreadsheets/{sid}/values"

    with httpx.Client(timeout=30.0) as client:
        data_resp = client.get(f"{base_url}/Data!A1:AA1000", headers=headers)
        if data_resp.status_code in (401, 403, 404):
            raise PermissionError(
                f"Google Sheets API returned {data_resp.status_code}. "
                f"Please share spreadsheet {sid} (Viewer access) with "
                f"nvd-health-web-sa@{settings.gcp_project_id}.iam.gserviceaccount.com and "
                f"nvd-health-etl-sa@{settings.gcp_project_id}.iam.gserviceaccount.com."
            )
        data_resp.raise_for_status()
        data_values = data_resp.json().get("values", [])

        notes_resp = client.get(f"{base_url}/Notes!A1:Z200", headers=headers)
        notes_values = notes_resp.json().get("values", []) if notes_resp.status_code == 200 else []

    obs_rows, note_rows = parse_sheet_observations(
        data_values=data_values,
        notes_values=notes_values,
        spreadsheet_id=sid,
        run_id=eff_run_id,
        ingested_at_iso=now_iso,
    )

    bq_client = bigquery.Client(project=settings.gcp_project_id, location=settings.bq_location)
    loader = BigQueryBronzeLoader(
        client=bq_client,
        project_id=settings.gcp_project_id,
        bronze_dataset=settings.bq_dataset_bronze,
        location=settings.bq_location,
    )
    loader.ensure_datasets_and_core_tables(
        silver_dataset=settings.bq_dataset_silver,
        gold_dataset=settings.bq_dataset_gold,
        default_cpap_start_date=settings.default_cpap_start_date,
    )

    obs_stats = loader.load_and_merge_rows(
        CORE_HEALTH_TABLES["bronze_journal_daily_observations"],
        obs_rows,
        CORE_HEALTH_TABLES["bronze_journal_daily_observations"].columns,
    )
    notes_stats = loader.load_and_merge_rows(
        CORE_HEALTH_TABLES["bronze_journal_baseline_notes"],
        note_rows,
        CORE_HEALTH_TABLES["bronze_journal_baseline_notes"].columns,
    )

    dataform_status = "SKIPPED"
    if trigger_dataform:
        df_runner = DataformRunner(
            project_id=settings.gcp_project_id,
            region=settings.gcp_region,
            repository_id=settings.dataform_repository_id,
            workspace_id=settings.dataform_workspace_id,
            dataform_dir=settings.dataform_dir,
            bq_location=settings.bq_location,
            silver_dataset=settings.bq_dataset_silver,
            service_account=settings.dataform_service_account,
        )
        df_res = df_runner.compile_and_run(sync_files=True)
        dataform_status = df_res.status
        if df_res.status != "SUCCEEDED":
            err = "; ".join(df_res.compilation_errors) or f"Dataform {df_res.status}"
            raise RuntimeError(err)

    return {
        "spreadsheet_id": sid,
        "run_id": eff_run_id,
        "observations": obs_stats,
        "baseline_notes": notes_stats,
        "dataform_status": dataform_status,
    }
