from __future__ import annotations

import argparse
import json
import os
import sys
from typing import List, Optional

from app.etl.runner import HealthEtlRunner


def parse_args(argv: Optional[List[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Cloud Run Job ETL Worker for GCS raw health bucket -> BigQuery Bronze + Dataform."
    )
    parser.add_argument(
        "--run-id",
        default=os.environ.get("ETL_RUN_ID"),
        help="Deterministic ETL run identifier.",
    )
    parser.add_argument(
        "--mode",
        default=os.environ.get("ETL_MODE", "existing_gcs"),
        choices=["existing_gcs", "zip", "prefix", "reacthealth_pdf"],
        help="Trigger mode.",
    )
    parser.add_argument(
        "--prefixes",
        default=os.environ.get("ETL_PREFIXES", ""),
        help="Comma-separated GCS prefixes to ingest.",
    )
    parser.add_argument(
        "--zip-path",
        default=os.environ.get("ETL_ZIP_PATH", ""),
        help="GCS object path to uploaded Takeout .zip archive.",
    )
    parser.add_argument(
        "--skip-dataform",
        action="store_true",
        default=os.environ.get("ETL_SKIP_DATAFORM", "").lower() == "true",
        help="Skip triggering Dataform after Bronze completion.",
    )
    parser.add_argument(
        "--force-reload",
        action="store_true",
        default=os.environ.get("ETL_FORCE_RELOAD", "").lower() == "true",
        help="Ignore bronze_ingestion_ledger hashes and reprocess matching blobs.",
    )
    return parser.parse_args(argv)


def main(argv: Optional[List[str]] = None) -> int:
    args = parse_args(argv)
    prefixes = [p.strip() for p in args.prefixes.split(",") if p.strip()] or None
    runner = HealthEtlRunner()
    result = runner.run(
        run_id=args.run_id,
        trigger_mode=args.mode,
        prefixes=prefixes,
        zip_gcs_path=args.zip_path or None,
        trigger_dataform=not args.skip_dataform,
        force_reload=args.force_reload,
    )
    print(json.dumps(result, indent=2, default=str))
    return 0 if result.get("status") == "COMPLETED" else 1


if __name__ == "__main__":
    sys.exit(main())
