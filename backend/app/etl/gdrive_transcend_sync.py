from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import html
import re
from typing import Any, Dict, List, Optional, Set, Tuple
import uuid

from app.etl.registry import TranscendMicroConnector

DRIVE_FOLDER_ID_RE = re.compile(r"/folders/([A-Za-z0-9_-]{15,})")
SAFE_ID_RE = re.compile(r"^[A-Za-z0-9_-]{10,}$")


def parse_drive_folder_id(raw_value: str) -> str:
    """Extract a Google Drive folder ID from either a full Drive URL or a raw folder ID."""
    cleaned = (raw_value or "").strip()
    if not cleaned:
        raise ValueError("Google Drive folder ID or URL is required.")
    m = DRIVE_FOLDER_ID_RE.search(cleaned)
    if m:
        return m.group(1)
    if SAFE_ID_RE.match(cleaned):
        return cleaned
    raise ValueError(f"Invalid Google Drive folder ID or URL: {raw_value!r}")


def parse_public_drive_folder_html(body: str, folder_id: str) -> List[Dict[str, str]]:
    """
    Extract file IDs and filenames from a public Google Drive folder HTML page
    when Drive API v3 is not enabled or lacks direct permission.
    """
    normalized = (
        body.replace("\\x22", '"')
        .replace("\\x5b", "[")
        .replace("\\x5d", "]")
        .replace("\\u003d", "=")
    )
    seen: Dict[str, str] = {}

    # 1. Exact DOM row pattern: data-id="<ID>" ... data-target="doc" ... aria-label="<filename>.pdf ..."
    for m in re.finditer(
        r'data-id="([A-Za-z0-9_-]{25,40})"[^>]*data-target="doc".*?aria-label="([^"]+\.(?:pdf|csv))\b',
        normalized,
        re.IGNORECASE | re.DOTALL,
    ):
        fid, fname = m.group(1), html.unescape(m.group(2).strip())
        if fid != folder_id and not fid.endswith("-0-16"):
            seen.setdefault(fid, fname)

    if seen:
        return [{"id": fid, "name": fname} for fid, fname in seen.items()]

    # 2. Structured Drive JSON tuple fallback: ["<fid>",["<folder_id>"]],"<filename>"
    tuple_re = re.compile(
        r'\["([A-Za-z0-9_-]{25,40})"\s*,\s*\["'
        + re.escape(folder_id)
        + r'"\][^\]]*\][,\s]+"([^"]+\.(?:pdf|csv))"',
        re.IGNORECASE,
    )
    for m in tuple_re.finditer(normalized):
        fid, fname = m.group(1), html.unescape(m.group(2).strip())
        if fid != folder_id:
            seen.setdefault(fid, fname)

    if seen:
        return [{"id": fid, "name": fname} for fid, fname in seen.items()]

    # 3. Quoted filename + quoted Drive ID proximity fallback
    for m in re.finditer(r'"([A-Za-z0-9._ -]+\.(?:pdf|csv))"', normalized, re.IGNORECASE):
        filename = html.unescape(m.group(1).strip())
        snippet = normalized[max(0, m.start() - 450) : m.end() + 200]
        ids = [
            fid
            for fid in re.findall(r'["\']([A-Za-z0-9_-]{25,40})["\']', snippet)
            if fid != folder_id and not fid.endswith("-0-16") and "." not in fid
        ]
        if ids:
            seen.setdefault(ids[-1], filename)
    return [{"id": fid, "name": fname} for fid, fname in seen.items()]


def list_drive_folder_files(
    folder_id: str,
    access_token: Optional[str] = None,
) -> Tuple[List[Dict[str, Any]], str]:
    """
    List supported PDF/CSV files in a Google Drive folder.
    Uses Google Drive API v3 first when an access token is provided, falling back to
    public folder HTML inspection for link-shared folders.
    """
    import httpx

    with httpx.Client(timeout=30.0, follow_redirects=True) as client:
        if access_token:
            api_url = "https://www.googleapis.com/drive/v3/files"
            files: List[Dict[str, Any]] = []
            page_token: Optional[str] = None
            api_ok = True
            while True:
                params: Dict[str, str] = {
                    "q": f"'{folder_id}' in parents and trashed = false",
                    "fields": "nextPageToken,files(id,name,mimeType,size,md5Checksum,modifiedTime)",
                    "pageSize": "100",
                    "supportsAllDrives": "true",
                    "includeItemsFromAllDrives": "true",
                }
                if page_token:
                    params["pageToken"] = page_token
                resp = client.get(
                    api_url,
                    params=params,
                    headers={"Authorization": f"Bearer {access_token}"},
                )
                if resp.status_code != 200:
                    api_ok = False
                    break
                payload = resp.json()
                for f in payload.get("files", []):
                    name = str(f.get("name", ""))
                    if name.lower().endswith((".pdf", ".csv")):
                        files.append(f)
                page_token = payload.get("nextPageToken")
                if not page_token:
                    break
            if api_ok:
                return files, "drive_api_v3"

        # Public link-shared folder fallback
        public_url = f"https://drive.google.com/drive/folders/{folder_id}"
        pub_resp = client.get(public_url, headers={"User-Agent": "Mozilla/5.0"})
        pub_resp.raise_for_status()
        parsed = parse_public_drive_folder_html(pub_resp.text, folder_id)
        return parsed, "public_folder_html"


def download_drive_file_bytes(
    file_id: str,
    access_token: Optional[str] = None,
) -> bytes:
    """Download file bytes from Google Drive API v3 or public share URL."""
    import httpx

    with httpx.Client(timeout=60.0, follow_redirects=True) as client:
        if access_token:
            resp = client.get(
                f"https://www.googleapis.com/drive/v3/files/{file_id}",
                params={"alt": "media", "supportsAllDrives": "true"},
                headers={"Authorization": f"Bearer {access_token}"},
            )
            if resp.status_code == 200 and resp.content:
                return resp.content

        dl_resp = client.get(
            f"https://drive.google.com/uc?export=download&id={file_id}",
            headers={"User-Agent": "Mozilla/5.0"},
        )
        dl_resp.raise_for_status()
        if dl_resp.headers.get("content-type", "").lower().startswith("text/html"):
            confirm_m = re.search(r"confirm=([0-9A-Za-z_-]+)", dl_resp.text)
            if confirm_m:
                dl_resp = client.get(
                    f"https://drive.google.com/uc?export=download&confirm={confirm_m.group(1)}&id={file_id}",
                    headers={"User-Agent": "Mozilla/5.0"},
                )
                dl_resp.raise_for_status()
        return dl_resp.content


def sync_transcend_drive_folder(
    folder_id_or_url: str,
    run_id: Optional[str] = None,
    trigger_dataform: bool = True,
    force_reload: bool = False,
) -> Dict[str, Any]:
    """
    Synchronize new Transcend Micro PDF/CSV exports from a Google Drive folder
    into GCS (`uploads/transcend_micro/drive/`), BigQuery Bronze, and Dataform Silver/Gold.

    Deduplicates strictly via SHA-256 content hashes in `bronze_ingestion_ledger` so
    only new files that do not already exist in BigQuery are ingested.
    """
    import google.auth
    from google.auth.transport.requests import Request
    from google.cloud import bigquery, storage

    from app.config import get_settings
    from app.etl.bq_loader import BigQueryBronzeLoader
    from app.etl.dataform_runner import DataformRunner

    settings = get_settings()
    folder_id = parse_drive_folder_id(folder_id_or_url or settings.transcend_drive_folder_id)
    eff_run_id = run_id or f"transcend-drive-{datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4().hex[:6]}"
    now_iso = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")

    token: Optional[str] = None
    try:
        creds, _ = google.auth.default(
            scopes=["https://www.googleapis.com/auth/drive.readonly"]
        )
        if not creds.valid:
            creds.refresh(Request())
        token = creds.token
    except Exception:
        token = None

    drive_files, list_mode = list_drive_folder_files(folder_id, access_token=token)

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

    existing_ledger = loader.fetch_ledger_hashes()
    existing_hashes: Set[str] = set(existing_ledger.values())

    storage_client = storage.Client(project=settings.gcp_project_id)
    bucket = storage_client.bucket(settings.gcs_raw_bucket)
    connector = TranscendMicroConnector()

    files_scanned = len(drive_files)
    files_loaded = 0
    files_skipped = 0
    files_failed = 0
    rows_staged = 0
    table_batches: Dict[str, Tuple[Any, List[Dict[str, Any]], Dict[str, str]]] = {}
    ledger_entries: List[Dict[str, Any]] = []
    warnings: List[str] = []
    processed_names: List[str] = []

    for df in drive_files:
        fid = str(df["id"])
        raw_name = str(df.get("name") or f"{fid}.pdf")
        safe_name = re.sub(r"[^A-Za-z0-9._-]+", "_", raw_name)
        gcs_path = f"uploads/transcend_micro/drive/{fid}_{safe_name}"

        try:
            raw_bytes = download_drive_file_bytes(fid, access_token=token)
            content_hash = hashlib.sha256(raw_bytes).hexdigest()

            if not force_reload and (
                content_hash in existing_hashes
                or existing_ledger.get(gcs_path) == content_hash
            ):
                files_skipped += 1
                continue

            # Archive raw export into GCS under uploads/transcend_micro/
            blob = bucket.blob(gcs_path)
            content_type = "application/pdf" if safe_name.lower().endswith(".pdf") else "text/csv"
            blob.upload_from_string(raw_bytes, content_type=content_type)

            parsed_items = connector.parse(
                blob_path=gcs_path,
                data=raw_bytes,
                run_id=eff_run_id,
                ingested_at_iso=now_iso,
            )
            file_rows = 0
            target_tables: List[str] = []
            for item in parsed_items:
                if item.warnings:
                    warnings.extend(item.warnings)
                if not item.rows:
                    continue
                tname = item.spec.table_name
                target_tables.append(tname)
                file_rows += len(item.rows)
                if tname not in table_batches:
                    table_batches[tname] = (item.spec, list(item.rows), dict(item.resolved_columns))
                else:
                    _, acc_rows, acc_cols = table_batches[tname]
                    acc_rows.extend(item.rows)
                    for k, v in item.resolved_columns.items():
                        acc_cols.setdefault(k, v)

            files_loaded += 1
            rows_staged += file_rows
            processed_names.append(raw_name)
            existing_hashes.add(content_hash)
            ledger_entries.append(
                {
                    "file_path": gcs_path,
                    "content_hash": content_hash,
                    "hash_type": "sha256",
                    "source_type": "transcend_micro",
                    "target_table": ",".join(target_tables) or "bronze_transcend_reports",
                    "file_size_bytes": len(raw_bytes),
                    "row_count": file_rows,
                    "status": "LOADED",
                    "error_message": None,
                    "last_run_id": eff_run_id,
                    "ingested_at": now_iso,
                }
            )
        except Exception as exc:
            files_failed += 1
            warnings.append(f"{raw_name}: {exc}")
            ledger_entries.append(
                {
                    "file_path": gcs_path,
                    "content_hash": hashlib.sha256(f"{fid}|{now_iso}".encode("utf-8")).hexdigest(),
                    "hash_type": "error",
                    "source_type": "transcend_micro",
                    "target_table": "transcend_cpap_daily_usage",
                    "file_size_bytes": 0,
                    "row_count": 0,
                    "status": "FAILED",
                    "error_message": str(exc)[:1000],
                    "last_run_id": eff_run_id,
                    "ingested_at": now_iso,
                }
            )

    merge_stats: Dict[str, Dict[str, int]] = {}
    for tname, (spec, rows_list, cols_map) in table_batches.items():
        merge_stats[tname] = loader.load_and_merge_rows(spec, rows_list, cols_map)

    if ledger_entries:
        loader.upsert_ledger_entries(ledger_entries)

    dataform_status = "NO_NEW_FILES"
    if files_loaded > 0 or force_reload:
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
                service_account=settings.dataform_service_account
                or f"nvd-health-etl-sa@{settings.gcp_project_id}.iam.gserviceaccount.com",
            )
            df_res = df_runner.compile_and_run(sync_files=True)
            dataform_status = df_res.status
            if df_res.status != "SUCCEEDED":
                detail = "; ".join(df_res.compilation_errors) if df_res.compilation_errors else df_res.error_message
                raise RuntimeError(f"Transcend Bronze loaded, but Dataform returned {df_res.status}: {detail}")

    return {
        "folder_id": folder_id,
        "list_mode": list_mode,
        "run_id": eff_run_id,
        "files_scanned": files_scanned,
        "files_loaded": files_loaded,
        "files_skipped": files_skipped,
        "files_failed": files_failed,
        "rows_staged": rows_staged,
        "loaded_files": processed_names,
        "merge_stats": merge_stats,
        "warnings": warnings,
        "dataform_status": dataform_status,
    }
