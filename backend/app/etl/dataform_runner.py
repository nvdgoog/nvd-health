from __future__ import annotations

import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional

from google.cloud import dataform_v1beta1 as dataform


@dataclass
class DataformExecutionResult:
    """Result summary from a Dataform workspace sync, compile, and workflow invocation."""

    compilation_id: str
    invocation_id: str
    status: str
    compilation_errors: List[str] = field(default_factory=list)
    actions: List[Dict[str, str]] = field(default_factory=list)


class DataformRunner:
    """Synchronizes local .sqlx files to a GCP Dataform workspace and triggers execution."""

    def __init__(
        self,
        project_id: str,
        region: str,
        repository_id: str,
        workspace_id: str,
        dataform_dir: str,
        bq_location: str = "US",
        silver_dataset: str = "nvd_health_silver",
        service_account: Optional[str] = None,
    ) -> None:
        self.project_id = project_id
        self.region = region
        self.repository_id = repository_id
        self.workspace_id = workspace_id
        self.dataform_dir = Path(dataform_dir)
        self.bq_location = bq_location
        self.silver_dataset = silver_dataset
        self.service_account = (
            service_account
            or f"nvd-health-etl-sa@{project_id}.iam.gserviceaccount.com"
        )
        self.client = dataform.DataformClient()

    @property
    def repository_path(self) -> str:
        return (
            f"projects/{self.project_id}/locations/{self.region}"
            f"/repositories/{self.repository_id}"
        )

    @property
    def workspace_path(self) -> str:
        return f"{self.repository_path}/workspaces/{self.workspace_id}"

    def ensure_repository_and_workspace(self) -> None:
        """Create the Dataform repository and workspace if they do not exist."""
        parent = f"projects/{self.project_id}/locations/{self.region}"
        try:
            self.client.get_repository(name=self.repository_path)
        except Exception:
            self.client.create_repository(
                parent=parent,
                repository_id=self.repository_id,
                repository=dataform.Repository(),
            )

        try:
            self.client.get_workspace(name=self.workspace_path)
        except Exception:
            self.client.create_workspace(
                parent=self.repository_path,
                workspace_id=self.workspace_id,
                workspace=dataform.Workspace(),
            )

    def sync_workspace_files(self) -> List[str]:
        """Upload all local Dataform files from dataform_dir into the Dataform workspace."""
        if not self.dataform_dir.exists():
            raise FileNotFoundError(f"Dataform directory not found: {self.dataform_dir}")

        self.ensure_repository_and_workspace()
        for legacy_file in ("package.json", "package-lock.json", "dataform.json"):
            try:
                self.client.remove_file(
                    request=dataform.RemoveFileRequest(
                        workspace=self.workspace_path,
                        path=legacy_file,
                    )
                )
            except Exception:
                pass

        synced: List[str] = []
        for path in sorted(self.dataform_dir.rglob("*")):
            if path.is_dir():
                continue
            rel = path.relative_to(self.dataform_dir).as_posix()
            # Skip local-only creds, node_modules, or legacy package.json (workflow_settings.yaml uses dataformCoreVersion)
            if rel.startswith(".") or "node_modules/" in rel or rel in ("package.json", "package-lock.json", "dataform.json"):
                continue
            contents = path.read_bytes()
            self.client.write_file(
                request=dataform.WriteFileRequest(
                    workspace=self.workspace_path,
                    path=rel,
                    contents=contents,
                )
            )
            synced.append(rel)
        return synced

    def compile_and_run(
        self,
        sync_files: bool = True,
        poll_interval_sec: float = 3.0,
        timeout_sec: float = 900.0,
    ) -> DataformExecutionResult:
        """Sync workspace, compile Dataform DAG, invoke workflow, and wait for completion."""
        if sync_files:
            self.sync_workspace_files()
        else:
            self.ensure_repository_and_workspace()

        compilation = self.client.create_compilation_result(
            parent=self.repository_path,
            compilation_result=dataform.CompilationResult(
                workspace=self.workspace_path,
                code_compilation_config=dataform.CodeCompilationConfig(
                    default_database=self.project_id,
                    default_schema=self.silver_dataset,
                    default_location=self.bq_location,
                ),
            ),
        )
        compilation_errors = [
            f"{err.path}: {err.message}" for err in (compilation.compilation_errors or [])
        ]
        comp_id = compilation.name.rsplit("/", 1)[-1]
        if compilation_errors:
            return DataformExecutionResult(
                compilation_id=comp_id,
                invocation_id="",
                status="COMPILATION_FAILED",
                compilation_errors=compilation_errors,
            )

        invocation = self.client.create_workflow_invocation(
            parent=self.repository_path,
            workflow_invocation=dataform.WorkflowInvocation(
                compilation_result=compilation.name,
                invocation_config=dataform.InvocationConfig(
                    fully_refresh_incremental_tables_enabled=False,
                    service_account=self.service_account,
                ),
            ),
        )
        inv_id = invocation.name.rsplit("/", 1)[-1]

        deadline = time.monotonic() + timeout_sec
        current = invocation
        while True:
            state_name = dataform.WorkflowInvocation.State(current.state).name
            if state_name in ("SUCCEEDED", "FAILED", "CANCELLED"):
                break
            if time.monotonic() >= deadline:
                state_name = "TIMEOUT"
                break
            time.sleep(poll_interval_sec)
            current = self.client.get_workflow_invocation(name=invocation.name)

        actions: List[Dict[str, str]] = []
        try:
            for action in self.client.query_workflow_invocation_actions(
                name=invocation.name
            ):
                actions.append(
                    {
                        "target": f"{action.target.schema}.{action.target.name}",
                        "state": dataform.WorkflowInvocationAction.State(
                            action.state
                        ).name,
                        "failure_reason": action.failure_reason or "",
                    }
                )
        except Exception:
            pass

        return DataformExecutionResult(
            compilation_id=comp_id,
            invocation_id=inv_id,
            status=state_name,
            compilation_errors=[],
            actions=actions,
        )

    def get_invocation_status(self, invocation_id: str) -> Dict[str, object]:
        """Inspect status and per-action logs for an existing WorkflowInvocation."""
        name = f"{self.repository_path}/workflowInvocations/{invocation_id}"
        inv = self.client.get_workflow_invocation(name=name)
        state_name = dataform.WorkflowInvocation.State(inv.state).name
        actions = []
        for action in self.client.query_workflow_invocation_actions(name=name):
            actions.append(
                {
                    "target": f"{action.target.schema}.{action.target.name}",
                    "state": dataform.WorkflowInvocationAction.State(action.state).name,
                    "failure_reason": action.failure_reason or "",
                }
            )
        return {
            "invocation_id": invocation_id,
            "status": state_name,
            "actions": actions,
        }
