from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from app.config import get_settings
from app.etl.dataform_runner import DataformRunner


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Sync local dataform/ .sqlx files to GCP Dataform workspace and compile/run."
    )
    parser.add_argument(
        "--compile-only",
        action="store_true",
        help="Sync and compile Dataform DAG without executing WorkflowInvocation.",
    )
    args = parser.parse_args()

    settings = get_settings()
    if not settings.gcp_project_id:
        raise SystemExit(
            "ERROR: GCP_PROJECT_ID (or GOOGLE_CLOUD_PROJECT) must be set."
        )
    runner = DataformRunner(
        project_id=settings.gcp_project_id,
        region=settings.gcp_region,
        repository_id=settings.dataform_repository_id,
        workspace_id=settings.dataform_workspace_id,
        dataform_dir=settings.dataform_dir,
        bq_location=settings.bq_location,
        silver_dataset=settings.bq_dataset_silver,
        service_account=settings.dataform_service_account,
    )

    synced = runner.sync_workspace_files()
    print(f"Synced {len(synced)} Dataform files: {synced}")

    if args.compile_only:
        from google.cloud import dataform_v1beta1 as dataform

        comp = runner.client.create_compilation_result(
            parent=runner.repository_path,
            compilation_result=dataform.CompilationResult(
                workspace=runner.workspace_path,
                code_compilation_config=dataform.CodeCompilationConfig(
                    default_database=settings.gcp_project_id,
                    default_schema=settings.bq_dataset_silver,
                    default_location=settings.bq_location,
                ),
            ),
        )
        errors = [f"{e.path}: {e.message}" for e in (comp.compilation_errors or [])]
        print(json.dumps({"compilation": comp.name, "errors": errors}, indent=2))
        return 1 if errors else 0

    res = runner.compile_and_run(sync_files=False)
    print(
        json.dumps(
            {
                "compilation_id": res.compilation_id,
                "invocation_id": res.invocation_id,
                "status": res.status,
                "compilation_errors": res.compilation_errors,
                "actions": res.actions,
            },
            indent=2,
        )
    )
    return 0 if res.status == "SUCCEEDED" else 1


if __name__ == "__main__":
    raise SystemExit(main())
