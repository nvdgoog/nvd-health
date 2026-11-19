from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
import re
from typing import Any, Dict, List, Optional, Tuple

from app.etl.csv_parser import parse_rfc4180_csv_bytes
from app.etl.pdf_parser import parse_reacthealth_pdf_bytes
from app.etl.schemas import (
    CORE_HEALTH_TABLES,
    TableSchemaSpec,
    get_spec_for_google_family,
    infer_google_takeout_family,
)


@dataclass
class ParsedBatchItem:
    """Normalized records destined for a single Bronze BigQuery table."""

    spec: TableSchemaSpec
    rows: List[Dict[str, Any]]
    resolved_columns: Dict[str, str]
    warnings: List[str] = field(default_factory=list)


class BaseConnector(ABC):
    """Abstract pluggable ingestion connector for a health data source."""

    name: str
    display_name: str
    supported_extensions: Tuple[str, ...]
    expected_prefixes: Tuple[str, ...]
    status: str = "active"
    description: str = ""

    @abstractmethod
    def can_handle(self, blob_path: str) -> bool:
        """Return True if this connector owns the given GCS object path."""

    def should_ignore(self, blob_path: str) -> bool:
        """Return True if the file is non-tabular documentation (e.g. README.txt)."""
        return False

    @abstractmethod
    def parse(
        self,
        blob_path: str,
        data: bytes,
        run_id: str,
        ingested_at_iso: str,
    ) -> List[ParsedBatchItem]:
        """Parse raw file bytes into one or more Bronze table payloads."""


class GoogleTakeoutConnector(BaseConnector):
    """Connector for Google Health Takeout CSV exports across all ~65+ schemas."""

    name = "google_takeout"
    display_name = "Google Health Takeout"
    supported_extensions = (".csv", ".txt")
    expected_prefixes = (
        "Health Fitness Data_GoogleData/",
        "Physical Activity_GoogleData/",
        "Stress Score/",
        "uploads/google_takeout/",
    )
    status = "active"
    description = (
        "Parses daily summaries, sleep sessions/scores/stages, exercises, stress scores, "
        "and sharded high-frequency sensor CSVs using strict RFC-4180 rules."
    )

    _TAKEOUT_ROOT_MARKERS = (
        "health fitness data_googledata/",
        "physical activity_googledata/",
        "stress score/",
        "uploads/google_takeout/",
    )

    def can_handle(self, blob_path: str) -> bool:
        low = blob_path.lower()
        if low.endswith(".pdf"):
            return False
        if any(marker in low for marker in self._TAKEOUT_ROOT_MARKERS):
            return low.endswith(".csv") or low.endswith("readme.txt")
        # Fallback: handle generic CSVs outside explicit other-connector prefixes
        if low.endswith(".csv") and not any(
            p in low for p in ("uploads/transcend_micro/", "uploads/zenplanner/")
        ):
            return True
        return False

    def should_ignore(self, blob_path: str) -> bool:
        filename = blob_path.rsplit("/", 1)[-1].lower()
        return filename == "readme.txt" or filename.endswith("_readme.txt") or filename.endswith(" readme.txt")

    def classify_spec(self, blob_path: str) -> TableSchemaSpec:
        family = infer_google_takeout_family(blob_path)
        return get_spec_for_google_family(family)

    def parse(
        self,
        blob_path: str,
        data: bytes,
        run_id: str,
        ingested_at_iso: str,
    ) -> List[ParsedBatchItem]:
        if self.should_ignore(blob_path):
            return []
        spec = self.classify_spec(blob_path)
        rows, resolved_cols = parse_rfc4180_csv_bytes(
            data=data,
            spec=spec,
            source_file=blob_path,
            run_id=run_id,
            ingested_at_iso=ingested_at_iso,
        )
        return [
            ParsedBatchItem(
                spec=spec,
                rows=rows,
                resolved_columns=resolved_cols,
            )
        ]


class ReactHealthPdfConnector(BaseConnector):
    """Connector for ReactHealth Sleep Therapy CPAP multi-page PDF reports."""

    name = "reacthealth_pdf"
    display_name = "ReactHealth CPAP PDF"
    supported_extensions = (".pdf",)
    expected_prefixes = ("uploads/reacthealth_pdf/", "")
    status = "active"
    description = (
        "Extracts Page 1 adherence summaries and Pages 2-N nightly CPAP therapy rows "
        "(ignoring 'No data received', preserving 00:00 sessions)."
    )

    def can_handle(self, blob_path: str) -> bool:
        low = blob_path.lower()
        if not low.endswith(".pdf"):
            return False
        if "uploads/transcend_micro/" in low or "uploads/zenplanner/" in low:
            return False
        return True

    def parse(
        self,
        blob_path: str,
        data: bytes,
        run_id: str,
        ingested_at_iso: str,
    ) -> List[ParsedBatchItem]:
        parsed = parse_reacthealth_pdf_bytes(
            pdf_bytes=data,
            source_file=blob_path,
            run_id=run_id,
            ingested_at_iso=ingested_at_iso,
        )
        items: List[ParsedBatchItem] = [
            ParsedBatchItem(
                spec=CORE_HEALTH_TABLES["bronze_reacthealth_reports"],
                rows=[parsed.report_metadata],
                resolved_columns=dict(
                    CORE_HEALTH_TABLES["bronze_reacthealth_reports"].columns
                ),
                warnings=parsed.warnings,
            )
        ]
        if parsed.daily_rows:
            items.append(
                ParsedBatchItem(
                    spec=CORE_HEALTH_TABLES["bronze_reacthealth_daily_usage"],
                    rows=parsed.daily_rows,
                    resolved_columns=dict(
                        CORE_HEALTH_TABLES["bronze_reacthealth_daily_usage"].columns
                    ),
                )
            )
        return items


class TranscendMicroConnector(BaseConnector):
    """Pluggable connector scaffold for future Transcend Micro travel CPAP exports."""

    name = "transcend_micro"
    display_name = "Transcend Micro Travel CPAP"
    supported_extensions = (".csv", ".pdf")
    expected_prefixes = ("uploads/transcend_micro/",)
    status = "ready_for_drop"
    description = (
        "Extensible connector slot for Transcend Micro travel CPAP therapy exports. "
        "Drops into nvd_health_bronze.transcend_cpap_daily_usage and joins to Silver."
    )

    def can_handle(self, blob_path: str) -> bool:
        return "uploads/transcend_micro/" in blob_path.lower() and blob_path.lower().endswith(".csv")

    def parse(
        self,
        blob_path: str,
        data: bytes,
        run_id: str,
        ingested_at_iso: str,
    ) -> List[ParsedBatchItem]:
        spec = CORE_HEALTH_TABLES["transcend_cpap_daily_usage"]
        rows, resolved_cols = parse_rfc4180_csv_bytes(
            data=data,
            spec=spec,
            source_file=blob_path,
            run_id=run_id,
            ingested_at_iso=ingested_at_iso,
        )
        return [ParsedBatchItem(spec=spec, rows=rows, resolved_columns=resolved_cols)]


class ZenPlannerConnector(BaseConnector):
    """Pluggable connector scaffold for future ZenPlanner CrossFit workout exports."""

    name = "zenplanner"
    display_name = "ZenPlanner CrossFit"
    supported_extensions = (".csv",)
    expected_prefixes = ("uploads/zenplanner/",)
    status = "ready_for_drop"
    description = (
        "Extensible connector slot for ZenPlanner WOD & strength exports. "
        "Drops into nvd_health_bronze.zenplanner_workouts and joins to Silver."
    )

    def can_handle(self, blob_path: str) -> bool:
        return "uploads/zenplanner/" in blob_path.lower() and blob_path.lower().endswith(".csv")

    def parse(
        self,
        blob_path: str,
        data: bytes,
        run_id: str,
        ingested_at_iso: str,
    ) -> List[ParsedBatchItem]:
        spec = CORE_HEALTH_TABLES["zenplanner_workouts"]
        rows, resolved_cols = parse_rfc4180_csv_bytes(
            data=data,
            spec=spec,
            source_file=blob_path,
            run_id=run_id,
            ingested_at_iso=ingested_at_iso,
        )
        return [ParsedBatchItem(spec=spec, rows=rows, resolved_columns=resolved_cols)]


class ConnectorRegistry:
    """Ordered registry dispatching GCS objects to the matching source connector."""

    def __init__(self, connectors: Optional[List[BaseConnector]] = None) -> None:
        self._connectors: List[BaseConnector] = connectors or [
            TranscendMicroConnector(),
            ZenPlannerConnector(),
            ReactHealthPdfConnector(),
            GoogleTakeoutConnector(),
        ]

    def register(self, connector: BaseConnector, prepend: bool = False) -> None:
        if prepend:
            self._connectors.insert(0, connector)
        else:
            self._connectors.append(connector)

    def resolve(self, blob_path: str) -> Optional[BaseConnector]:
        for conn in self._connectors:
            if conn.can_handle(blob_path):
                return conn
        return None

    def list_connectors(self) -> List[Dict[str, Any]]:
        return [
            {
                "name": c.name,
                "display_name": c.display_name,
                "supported_extensions": list(c.supported_extensions),
                "expected_prefixes": list(c.expected_prefixes),
                "status": c.status,
                "description": c.description,
            }
            for c in self._connectors
        ]
