from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import gc
import hashlib
import json
import os
import tempfile
import uuid
import zipfile
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

from google.cloud import bigquery, storage

from app.config import Settings, get_settings
from app.etl.bq_loader import BigQueryBronzeLoader
from app.etl.dataform_runner import DataformRunner
from app.etl.registry import ConnectorRegistry, ParsedBatchItem
from app.etl.schemas import SYSTEM_TABLES, TableSchemaSpec, normalize_logical_path

DEFAULT_SCAN_PREFIXES = [
    "Health Fitness Data_GoogleData/",
    "Physical Activity_GoogleData/",
    "Stress Score/",
    "uploads/",
]

# Bounded chunk & flush limit (disk-backed NDJSON + 8Gi RAM safely handles 100k-row batches)
BATCH_ROW_FLUSH_LIMIT = 100000
PREFETCH_WINDOW_SIZE = 50
CHECKPOINT_FILE_INTERVAL = 400


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def compute_bytes_md5_hex(data: bytes) -> str:
    return hashlib.md5(data).hexdigest()


class HealthEtlRunner:
    """Orchestrates GCS discovery/unzipping, Bronze MERGE loading, and Dataform ELT."""

    def __init__(
        self,
        settings: Optional[Settings] = None,
        storage_client: Optional[storage.Client] = None,
        bq_client: Optional[bigquery.Client] = None,
        registry: Optional[ConnectorRegistry] = None,
    ) -> None:
        self.settings = settings or get_settings()
        self.storage_client = storage_client or storage.Client(
            project=self.settings.gcp_project_id
        )
        self.bq_client = bq_client or bigquery.Client(
            project=self.settings.gcp_project_id,
            location=self.settings.bq_location,
        )
        self.registry = registry or ConnectorRegistry()
        self.loader = BigQueryBronzeLoader(
            client=self.bq_client,
            project_id=self.settings.gcp_project_id,
            bronze_dataset=self.settings.bq_dataset_bronze,
            location=self.settings.bq_location,
        )

    def _record_run(self, state: Dict[str, Any]) -> None:
        state["updated_at"] = utc_now_iso()
        self.loader.upsert_etl_run(state)

    def run(
        self,
        run_id: Optional[str] = None,
        trigger_mode: str = "existing_gcs",
        prefixes: Optional[List[str]] = None,
        zip_gcs_path: Optional[str] = None,
        trigger_dataform: bool = True,
        force_reload: bool = False,
    ) -> Dict[str, Any]:
        """Execute an end-to-end Bronze + Dataform Silver/Gold pipeline run."""
        run_id = run_id or f"run-{datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4().hex[:6]}"
        started_at = utc_now_iso()

        self.loader.ensure_datasets_and_core_tables(
            silver_dataset=self.settings.bq_dataset_silver,
            gold_dataset=self.settings.bq_dataset_gold,
            default_cpap_start_date=self.settings.default_cpap_start_date,
        )

        scan_prefixes = prefixes or list(DEFAULT_SCAN_PREFIXES)
        if zip_gcs_path and trigger_mode == "zip":
            scan_prefixes = [zip_gcs_path]

        run_state: Dict[str, Any] = {
            "run_id": run_id,
            "trigger_mode": trigger_mode,
            "status": "SCANNING",
            "current_stage": "Initializing & scanning GCS objects",
            "source_prefixes_json": json.dumps(scan_prefixes),
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
            "started_at": started_at,
            "updated_at": started_at,
            "completed_at": None,
        }
        self._record_run(run_state)

        bucket = self.storage_client.bucket(self.settings.gcs_raw_bucket)
        table_stats: Dict[str, Dict[str, int]] = defaultdict(
            lambda: {"staged": 0, "inserted": 0, "updated": 0, "files": 0}
        )

        try:
            # Step 1: If zip mode, stream & extract Takeout zip in GCS first
            if trigger_mode == "zip" and zip_gcs_path:
                run_state["status"] = "UNZIPPING"
                run_state["current_stage"] = f"Streaming & unzipping {zip_gcs_path}"
                self._record_run(run_state)
                extracted_prefix = self._unzip_gcs_archive(
                    bucket=bucket,
                    zip_blob_path=zip_gcs_path,
                    run_id=run_id,
                )
                scan_prefixes = [extracted_prefix]
                run_state["source_prefixes_json"] = json.dumps(scan_prefixes)

            # Step 2: Discover GCS blobs (including root PDFs if existing_gcs)
            blobs = self._collect_blobs(
                bucket=bucket,
                scan_prefixes=scan_prefixes,
                include_root_pdfs=(trigger_mode == "existing_gcs"),
            )
            run_state["files_total"] = len(blobs)
            run_state["status"] = "LOADING_BRONZE"
            run_state["current_stage"] = f"Found {len(blobs)} objects; checking ledger"
            self._record_run(run_state)

            ledger_hashes = {} if force_reload else self.loader.fetch_ledger_hashes()
            logical_hash_pairs: Set[Tuple[str, str]] = {
                (normalize_logical_path(fp), h)
                for fp, h in ledger_hashes.items()
                if h
            }

            # Group pending rows by target Bronze table to execute 1 MERGE per table per batch
            pending_rows: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
            pending_specs: Dict[str, TableSchemaSpec] = {}
            pending_cols: Dict[str, Dict[str, str]] = {}
            ledger_buffer: List[Dict[str, Any]] = []
            readme_buffer: List[Dict[str, Any]] = []

            def _checkpoint(stage_label: str) -> None:
                for tbl_name, tbl_rows in list(pending_rows.items()):
                    if tbl_rows:
                        self._flush_table(
                            tbl_name,
                            pending_specs[tbl_name],
                            tbl_rows,
                            pending_cols[tbl_name],
                            table_stats,
                            run_state,
                        )
                        tbl_rows.clear()
                if readme_buffer:
                    doc_spec = SYSTEM_TABLES["bronze_schema_docs"]
                    self.loader.load_and_merge_rows(
                        doc_spec, readme_buffer, doc_spec.columns
                    )
                    readme_buffer.clear()
                if ledger_buffer:
                    self.loader.upsert_ledger_entries(ledger_buffer)
                    ledger_buffer.clear()
                run_state["current_stage"] = stage_label
                run_state["table_stats_json"] = json.dumps(table_stats)
                self._record_run(run_state)
                gc.collect()

            # Pre-filter blobs against ledger before downloading bytes
            to_process: List[Tuple[int, storage.Blob, Any, str]] = []
            for idx, blob in enumerate(blobs, start=1):
                blob_path = blob.name
                if blob_path.endswith("/") or blob.size == 0:
                    continue
                connector = self.registry.resolve(blob_path)
                if connector is None:
                    run_state["files_scanned"] += 1
                    run_state["files_skipped"] += 1
                    continue
                blob_hash = blob.md5_hash or blob.crc32c or str(blob.etag or "")
                logical_key = (normalize_logical_path(blob_path), blob_hash)
                if not force_reload and (
                    ledger_hashes.get(blob_path) == blob_hash
                    or (blob_hash and logical_key in logical_hash_pairs)
                ):
                    run_state["files_scanned"] += 1
                    run_state["files_skipped"] += 1
                    continue
                to_process.append((idx, blob, connector, blob_hash))

            if run_state["files_skipped"] > 0:
                run_state["current_stage"] = (
                    f"Skipped {run_state['files_skipped']} unchanged files; "
                    f"processing {len(to_process)} objects"
                )
                self._record_run(run_state)

            processed_since_checkpoint = 0
            with ThreadPoolExecutor(max_workers=8) as download_pool:
                for win_start in range(0, len(to_process), PREFETCH_WINDOW_SIZE):
                    window = to_process[win_start : win_start + PREFETCH_WINDOW_SIZE]
                    futures = {
                        item[1].name: download_pool.submit(item[1].download_as_bytes)
                        for item in window
                    }

                    for idx, blob, connector, blob_hash in window:
                        blob_path = blob.name
                        try:
                            raw_bytes = futures[blob_path].result()
                            content_hash = blob_hash or compute_bytes_md5_hex(raw_bytes)
                            hash_type = (
                                "MD5"
                                if blob.md5_hash
                                else ("CRC32C" if blob.crc32c else "MD5_COMPUTED")
                            )

                            if connector.should_ignore(blob_path):
                                readme_buffer.append(
                                    {
                                        "doc_path": blob_path,
                                        "content_hash": content_hash,
                                        "doc_text": raw_bytes.decode(
                                            "utf-8-sig", errors="replace"
                                        )[:50000],
                                        "ingested_at": utc_now_iso(),
                                    }
                                )
                                ledger_buffer.append(
                                    self._ledger_entry(
                                        blob_path=blob_path,
                                        content_hash=content_hash,
                                        hash_type=hash_type,
                                        source_type=connector.name,
                                        target_table="bronze_schema_docs",
                                        file_size_bytes=len(raw_bytes),
                                        row_count=1,
                                        status="IGNORED",
                                        error_message=None,
                                        run_id=run_id,
                                    )
                                )
                                run_state["files_scanned"] += 1
                                run_state["files_skipped"] += 1
                            else:
                                total_file_rows = 0
                                target_names: List[str] = []
                                seen_tables_in_file: Set[str] = set()
                                file_size = len(raw_bytes)
                                for item in connector.parse_chunks(
                                    blob_path=blob_path,
                                    data=raw_bytes,
                                    run_id=run_id,
                                    ingested_at_iso=utc_now_iso(),
                                    chunk_size=BATCH_ROW_FLUSH_LIMIT,
                                ):
                                    tname = item.spec.table_name
                                    if tname not in seen_tables_in_file:
                                        seen_tables_in_file.add(tname)
                                        target_names.append(tname)
                                        table_stats[tname]["files"] += 1
                                    pending_specs[tname] = item.spec
                                    if tname not in pending_cols:
                                        pending_cols[tname] = dict(item.resolved_columns)
                                    else:
                                        pending_cols[tname].update(item.resolved_columns)
                                    pending_rows[tname].extend(item.rows)
                                    total_file_rows += len(item.rows)

                                    if len(pending_rows[tname]) >= BATCH_ROW_FLUSH_LIMIT:
                                        self._flush_table(
                                            tname,
                                            pending_specs[tname],
                                            pending_rows[tname],
                                            pending_cols[tname],
                                            table_stats,
                                            run_state,
                                        )
                                        pending_rows[tname].clear()
                                        gc.collect()

                                del raw_bytes
                                ledger_buffer.append(
                                    self._ledger_entry(
                                        blob_path=blob_path,
                                        content_hash=content_hash,
                                        hash_type=hash_type,
                                        source_type=connector.name,
                                        target_table=",".join(target_names) or "none",
                                        file_size_bytes=file_size,
                                        row_count=total_file_rows,
                                        status="LOADED",
                                        error_message=None,
                                        run_id=run_id,
                                    )
                                )
                                run_state["files_scanned"] += 1
                                run_state["files_loaded"] += 1

                        except Exception as exc:
                            run_state["files_scanned"] += 1
                            run_state["files_failed"] += 1
                            ledger_buffer.append(
                                self._ledger_entry(
                                    blob_path=blob_path,
                                    content_hash=blob_hash,
                                    hash_type="MD5" if blob.md5_hash else "UNKNOWN",
                                    source_type=connector.name,
                                    target_table="error",
                                    file_size_bytes=int(blob.size or 0),
                                    row_count=0,
                                    status="FAILED",
                                    error_message=str(exc)[:1000],
                                    run_id=run_id,
                                )
                            )

                        processed_since_checkpoint += 1
                        if processed_since_checkpoint >= CHECKPOINT_FILE_INTERVAL:
                            _checkpoint(
                                f"Checkpointed {run_state['files_scanned']}/{len(blobs)} objects"
                            )
                            processed_since_checkpoint = 0

            # Final flush of remaining buffered Bronze tables & ledger
            _checkpoint(f"Flushed {run_state['files_scanned']}/{len(blobs)} objects")

            # Auto-detect cpap_start_date from earliest non-zero CPAP usage night
            self.loader.refresh_auto_detected_cpap_start_date(
                fallback_date=self.settings.default_cpap_start_date
            )

            run_state["table_stats_json"] = json.dumps(table_stats)

            # Step 3: Programmatically trigger Dataform Silver & Gold build
            if trigger_dataform:
                run_state["status"] = "RUNNING_DATAFORM"
                run_state["current_stage"] = "Compiling & running Dataform Silver/Gold models"
                self._record_run(run_state)

                df_runner = DataformRunner(
                    project_id=self.settings.gcp_project_id,
                    region=self.settings.gcp_region,
                    repository_id=self.settings.dataform_repository_id,
                    workspace_id=self.settings.dataform_workspace_id,
                    dataform_dir=self.settings.dataform_dir,
                    bq_location=self.settings.bq_location,
                    silver_dataset=self.settings.bq_dataset_silver,
                    service_account=self.settings.dataform_service_account,
                )
                df_result = df_runner.compile_and_run(sync_files=True)
                run_state["dataform_compilation_id"] = df_result.compilation_id
                run_state["dataform_invocation_id"] = df_result.invocation_id
                run_state["dataform_status"] = df_result.status
                if df_result.status != "SUCCEEDED":
                    err_detail = "; ".join(df_result.compilation_errors) or (
                        f"Dataform workflow ended with state {df_result.status}"
                    )
                    raise RuntimeError(err_detail)
            else:
                run_state["dataform_status"] = "SKIPPED"

            run_state["status"] = "COMPLETED"
            run_state["current_stage"] = "Completed Bronze + Silver/Gold pipeline"
            run_state["completed_at"] = utc_now_iso()
            self._record_run(run_state)
            return run_state

        except Exception as exc:
            run_state["status"] = "FAILED"
            run_state["current_stage"] = "Pipeline failed"
            run_state["error_message"] = str(exc)[:2000]
            run_state["completed_at"] = utc_now_iso()
            self._record_run(run_state)
            raise

    def _flush_table(
        self,
        table_name: str,
        spec: TableSchemaSpec,
        rows: List[Dict[str, Any]],
        cols: Dict[str, str],
        table_stats: Dict[str, Dict[str, int]],
        run_state: Dict[str, Any],
    ) -> None:
        stats = self.loader.load_and_merge_rows(spec, rows, cols)
        table_stats[table_name]["staged"] += stats["staged"]
        table_stats[table_name]["inserted"] += stats["inserted"]
        table_stats[table_name]["updated"] += stats["updated"]
        run_state["rows_inserted"] += stats["inserted"]
        run_state["rows_updated"] += stats["updated"]

    def _collect_blobs(
        self,
        bucket: storage.Bucket,
        scan_prefixes: List[str],
        include_root_pdfs: bool,
    ) -> List[storage.Blob]:
        seen: Dict[str, storage.Blob] = {}
        for prefix in scan_prefixes:
            clean_prefix = prefix.lstrip("/")
            if clean_prefix.endswith(".zip"):
                continue
            if clean_prefix and not clean_prefix.endswith("/") and "." in clean_prefix.rsplit("/", 1)[-1]:
                blob = bucket.get_blob(clean_prefix)
                if blob is not None:
                    seen[blob.name] = blob
                continue
            for blob in self.storage_client.list_blobs(bucket, prefix=clean_prefix):
                if blob.name.lower().endswith(".zip"):
                    continue
                seen[blob.name] = blob

        if include_root_pdfs:
            # Also capture root-level PDFs like gs://nvd-health-raw-data/8.21.26-11.18.26.pdf
            for blob in self.storage_client.list_blobs(bucket, delimiter="/"):
                if blob.name.lower().endswith(".pdf"):
                    seen[blob.name] = blob

        return [seen[k] for k in sorted(seen.keys())]

    def _unzip_gcs_archive(
        self,
        bucket: storage.Bucket,
        zip_blob_path: str,
        run_id: str,
    ) -> str:
        """Download >400 MB Takeout zip to ephemeral temp storage and extract relevant folders to GCS."""
        extract_prefix = f"uploads/google_takeout/unzipped/{run_id}/"
        zip_blob = bucket.blob(zip_blob_path)
        with tempfile.NamedTemporaryFile(suffix=".zip", delete=True) as tmp:
            zip_blob.download_to_filename(tmp.name)
            with zipfile.ZipFile(tmp.name, "r") as zf:
                for info in zf.infolist():
                    if info.is_dir():
                        continue
                    # Strip common Takeout/ prefix if present
                    member_path = info.filename.lstrip("/")
                    if member_path.startswith("Takeout/"):
                        member_path = member_path[len("Takeout/") :]
                    low = member_path.lower()
                    if not (
                        low.endswith(".csv")
                        or low.endswith("readme.txt")
                        or low.endswith(".pdf")
                    ):
                        continue
                    dest_path = f"{extract_prefix}{member_path}"
                    dest_blob = bucket.blob(dest_path)
                    with zf.open(info, "r") as member_fp:
                        dest_blob.upload_from_file(member_fp, rewind=False)
        return extract_prefix

    @staticmethod
    def _ledger_entry(
        blob_path: str,
        content_hash: str,
        hash_type: str,
        source_type: str,
        target_table: str,
        file_size_bytes: int,
        row_count: int,
        status: str,
        error_message: Optional[str],
        run_id: str,
    ) -> Dict[str, Any]:
        return {
            "file_path": blob_path,
            "content_hash": content_hash,
            "hash_type": hash_type,
            "source_type": source_type,
            "target_table": target_table,
            "file_size_bytes": file_size_bytes,
            "row_count": row_count,
            "status": status,
            "error_message": error_message,
            "last_run_id": run_id,
            "ingested_at": utc_now_iso(),
        }
