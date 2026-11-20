from __future__ import annotations

from dataclasses import dataclass, field
import re
from typing import Dict, List, Optional, Tuple


@dataclass(frozen=True)
class TableSchemaSpec:
    """Definition of a Bronze BigQuery target table and its deduplication rules."""

    table_name: str
    columns: Dict[str, str] = field(default_factory=dict)
    primary_keys: Tuple[str, ...] = ()
    order_by_column: Optional[str] = None
    partition_field: Optional[str] = None
    clustering_fields: Tuple[str, ...] = ()
    allow_schema_evolution: bool = True
    description: str = ""


METADATA_COLUMNS: Dict[str, str] = {
    "_ingested_at": "TIMESTAMP",
    "_source_file": "STRING",
    "_run_id": "STRING",
    "_row_hash": "STRING",
}


SYSTEM_TABLES: Dict[str, TableSchemaSpec] = {
    "bronze_ingestion_ledger": TableSchemaSpec(
        table_name="bronze_ingestion_ledger",
        columns={
            "file_path": "STRING",
            "content_hash": "STRING",
            "hash_type": "STRING",
            "source_type": "STRING",
            "target_table": "STRING",
            "file_size_bytes": "INT64",
            "row_count": "INT64",
            "status": "STRING",
            "error_message": "STRING",
            "last_run_id": "STRING",
            "ingested_at": "TIMESTAMP",
        },
        primary_keys=("file_path",),
        order_by_column="ingested_at",
        partition_field="ingested_at",
        clustering_fields=("source_type", "status"),
        allow_schema_evolution=False,
        description="Audit ledger tracking every processed GCS file by path and content hash.",
    ),
    "bronze_etl_runs": TableSchemaSpec(
        table_name="bronze_etl_runs",
        columns={
            "run_id": "STRING",
            "trigger_mode": "STRING",
            "status": "STRING",
            "current_stage": "STRING",
            "source_prefixes_json": "STRING",
            "files_total": "INT64",
            "files_scanned": "INT64",
            "files_loaded": "INT64",
            "files_skipped": "INT64",
            "files_failed": "INT64",
            "rows_inserted": "INT64",
            "rows_updated": "INT64",
            "table_stats_json": "STRING",
            "dataform_compilation_id": "STRING",
            "dataform_invocation_id": "STRING",
            "dataform_status": "STRING",
            "error_message": "STRING",
            "started_at": "TIMESTAMP",
            "updated_at": "TIMESTAMP",
            "completed_at": "TIMESTAMP",
        },
        primary_keys=("run_id",),
        order_by_column="updated_at",
        partition_field="started_at",
        allow_schema_evolution=False,
        description="Execution log for Cloud Run ETL runs and downstream Dataform invocations.",
    ),
    "bronze_app_settings": TableSchemaSpec(
        table_name="bronze_app_settings",
        columns={
            "setting_key": "STRING",
            "setting_value": "STRING",
            "auto_detected_value": "STRING",
            "is_manual_override": "BOOL",
            "updated_at": "TIMESTAMP",
            "updated_by": "STRING",
        },
        primary_keys=("setting_key",),
        order_by_column="updated_at",
        allow_schema_evolution=False,
        description="Runtime platform settings including auto-detected/overridden cpap_start_date.",
    ),
    "bronze_schema_docs": TableSchemaSpec(
        table_name="bronze_schema_docs",
        columns={
            "doc_path": "STRING",
            "content_hash": "STRING",
            "doc_text": "STRING",
            "ingested_at": "TIMESTAMP",
        },
        primary_keys=("doc_path",),
        order_by_column="ingested_at",
        allow_schema_evolution=False,
        description="Optional catalog of README.txt documentation files from Google Takeout.",
    ),
}


CORE_HEALTH_TABLES: Dict[str, TableSchemaSpec] = {
    "bronze_reacthealth_reports": TableSchemaSpec(
        table_name="bronze_reacthealth_reports",
        columns={
            "report_id": "STRING",
            "device_sn": "STRING",
            "report_generated_date": "DATE",
            "report_date_range_start": "DATE",
            "report_date_range_end": "DATE",
            "usage_days": "INT64",
            "total_days": "INT64",
            "adherence_pct": "FLOAT64",
            "days_ge_4h": "INT64",
            "best30_start": "DATE",
            "best30_end": "DATE",
            "best30_days": "INT64",
            "best30_total_days": "INT64",
            "best30_pct": "FLOAT64",
            "avg_pressure": "FLOAT64",
            "avg_p95": "FLOAT64",
            "avg_leak": "FLOAT64",
            "avg_ahi": "FLOAT64",
            "avg_cai": "FLOAT64",
            "valid_days_count": "INT64",
            "no_data_days_count": "INT64",
            "zero_minute_days_count": "INT64",
            "patient_name": "STRING",
            **METADATA_COLUMNS,
        },
        primary_keys=("report_id",),
        order_by_column="report_generated_date",
        allow_schema_evolution=True,
        description="Page 1 summary metadata from ReactHealth Sleep Therapy PDF reports.",
    ),
    "bronze_reacthealth_daily_usage": TableSchemaSpec(
        table_name="bronze_reacthealth_daily_usage",
        columns={
            "usage_date": "DATE",
            "device_sn": "STRING",
            "usage_duration_str": "STRING",
            "usage_minutes": "INT64",
            "usage_hours": "FLOAT64",
            "pressure": "FLOAT64",
            "ahi": "FLOAT64",
            "p95": "FLOAT64",
            "cai": "FLOAT64",
            "avg_leak": "FLOAT64",
            "mode": "STRING",
            "report_generated_date": "DATE",
            **METADATA_COLUMNS,
        },
        primary_keys=("usage_date", "device_sn"),
        order_by_column="report_generated_date",
        partition_field="usage_date",
        clustering_fields=("device_sn",),
        allow_schema_evolution=True,
        description="Nightly ReactHealth CPAP therapy rows (excludes 'No data received', retains 00:00 rows).",
    ),
    "google_user_sleeps": TableSchemaSpec(
        table_name="google_user_sleeps",
        columns={
            "sleep_id": "STRING",
            "sleep_type": "STRING",
            "minutes_in_sleep_period": "INT64",
            "minutes_after_wake_up": "INT64",
            "minutes_to_fall_asleep": "INT64",
            "minutes_asleep": "INT64",
            "minutes_awake": "INT64",
            "minutes_longest_awakening": "INT64",
            "minutes_to_persistent_sleep": "INT64",
            "start_utc_offset": "STRING",
            "sleep_start": "TIMESTAMP",
            "end_utc_offset": "STRING",
            "sleep_end": "TIMESTAMP",
            "data_source": "STRING",
            "algorithm_version": "STRING",
            "sleep_created": "TIMESTAMP",
            "sleep_last_updated": "TIMESTAMP",
            **METADATA_COLUMNS,
        },
        primary_keys=("sleep_id",),
        order_by_column="sleep_last_updated",
        partition_field="sleep_end",
        clustering_fields=("sleep_type",),
        description="Google Health UserSleeps sessions.",
    ),
    "google_user_sleep_scores": TableSchemaSpec(
        table_name="google_user_sleep_scores",
        columns={
            "sleep_id": "STRING",
            "sleep_score_id": "STRING",
            "data_source": "STRING",
            "score_utc_offset": "STRING",
            "score_time": "TIMESTAMP",
            "overall_score": "FLOAT64",
            "duration_score": "FLOAT64",
            "composition_score": "FLOAT64",
            "revitalization_score": "FLOAT64",
            "sleep_time_minutes": "INT64",
            "deep_sleep_minutes": "INT64",
            "rem_sleep_percent": "FLOAT64",
            "resting_heart_rate": "FLOAT64",
            "sleep_goal_minutes": "INT64",
            "waso_count_long_wakes": "FLOAT64",
            "waso_count_all_wake_time": "FLOAT64",
            "restlessness_normalized": "FLOAT64",
            "hr_below_resting_hr": "FLOAT64",
            "sleep_score_created": "TIMESTAMP",
            "sleep_score_last_updated": "TIMESTAMP",
            **METADATA_COLUMNS,
        },
        primary_keys=("sleep_score_id",),
        order_by_column="sleep_score_last_updated",
        partition_field="score_time",
        clustering_fields=("sleep_id",),
        description="Google Health UserSleepScores (-1 sentinels preserved in Bronze).",
    ),
    "google_user_sleep_stages": TableSchemaSpec(
        table_name="google_user_sleep_stages",
        columns={
            "sleep_id": "STRING",
            "sleep_stage_id": "STRING",
            "sleep_stage_type": "STRING",
            "start_utc_offset": "STRING",
            "sleep_stage_start": "TIMESTAMP",
            "end_utc_offset": "STRING",
            "sleep_stage_end": "TIMESTAMP",
            "data_source": "STRING",
            "algorithm_version": "STRING",
            "sleep_stage_created": "TIMESTAMP",
            "sleep_stage_last_updated": "TIMESTAMP",
            **METADATA_COLUMNS,
        },
        primary_keys=("sleep_id", "sleep_stage_id"),
        order_by_column="sleep_stage_last_updated",
        partition_field="sleep_stage_end",
        clustering_fields=("sleep_id", "sleep_stage_type"),
        description="Google Health UserSleepStages intervals (DEEP, REM, LIGHT, WAKE).",
    ),
    "google_user_exercises": TableSchemaSpec(
        table_name="google_user_exercises",
        columns={
            "exercise_id": "STRING",
            "exercise_type": "STRING",
            "start_time": "TIMESTAMP",
            "end_time": "TIMESTAMP",
            "start_utc_offset": "STRING",
            "end_utc_offset": "STRING",
            "duration_milliseconds": "INT64",
            "active_duration_milliseconds": "INT64",
            "calories": "FLOAT64",
            "average_heart_rate": "FLOAT64",
            "max_heart_rate": "FLOAT64",
            "distance_meters": "FLOAT64",
            "steps": "INT64",
            "intervals": "STRING",
            "data_source": "STRING",
            "exercise_created": "TIMESTAMP",
            "exercise_last_updated": "TIMESTAMP",
            **METADATA_COLUMNS,
        },
        primary_keys=("exercise_id",),
        order_by_column="exercise_last_updated",
        partition_field="start_time",
        clustering_fields=("exercise_type",),
        description="Google Health UserExercises sessions (supports multi-line quoted intervals).",
    ),
    "google_daily_resting_heart_rate": TableSchemaSpec(
        table_name="google_daily_resting_heart_rate",
        columns={
            "timestamp": "TIMESTAMP",
            "beats_per_minute": "FLOAT64",
            "data_source": "STRING",
            **METADATA_COLUMNS,
        },
        primary_keys=("timestamp", "data_source"),
        partition_field="timestamp",
        description="Daily resting heart rate (UTC midnight encodes literal calendar date).",
    ),
    "google_daily_heart_rate_variability": TableSchemaSpec(
        table_name="google_daily_heart_rate_variability",
        columns={
            "timestamp": "TIMESTAMP",
            "average_heart_rate_variability_milliseconds": "FLOAT64",
            "non_rem_heart_rate_beats_per_minute": "FLOAT64",
            "entropy": "FLOAT64",
            "deep_sleep_root_mean_square_of_successive_differences_milliseconds": "FLOAT64",
            "data_source": "STRING",
            **METADATA_COLUMNS,
        },
        primary_keys=("timestamp", "data_source"),
        partition_field="timestamp",
        description="Daily HRV metrics (UTC midnight encodes literal calendar date).",
    ),
    "google_daily_oxygen_saturation": TableSchemaSpec(
        table_name="google_daily_oxygen_saturation",
        columns={
            "timestamp": "TIMESTAMP",
            "average_percentage": "FLOAT64",
            "lower_bound_percentage": "FLOAT64",
            "upper_bound_percentage": "FLOAT64",
            "baseline_percentage": "FLOAT64",
            "standard_deviation_percentage": "FLOAT64",
            "data_source": "STRING",
            **METADATA_COLUMNS,
        },
        primary_keys=("timestamp", "data_source"),
        partition_field="timestamp",
        description="Daily SpO2 metrics (UTC midnight encodes literal calendar date).",
    ),
    "google_daily_readiness": TableSchemaSpec(
        table_name="google_daily_readiness",
        columns={
            "timestamp": "DATE",
            "score": "FLOAT64",
            "type": "STRING",
            "readiness_level": "STRING",
            "sleep_readiness": "STRING",
            "heart_rate_variability_readiness": "STRING",
            "resting_heart_rate_readiness": "STRING",
            "data_source": "STRING",
            **METADATA_COLUMNS,
        },
        primary_keys=("timestamp", "data_source"),
        partition_field="timestamp",
        description="Daily readiness score and sub-ratings.",
    ),
    "google_daily_respiratory_rate": TableSchemaSpec(
        table_name="google_daily_respiratory_rate",
        columns={
            "timestamp": "TIMESTAMP",
            "breaths_per_minute": "FLOAT64",
            "data_source": "STRING",
            **METADATA_COLUMNS,
        },
        primary_keys=("timestamp", "data_source"),
        partition_field="timestamp",
        description="Daily respiratory rate (UTC midnight encodes literal calendar date).",
    ),
    "google_daily_sleep_breathing_quality": TableSchemaSpec(
        table_name="google_daily_sleep_breathing_quality",
        columns={
            "timestamp": "TIMESTAMP",
            "breathing_quality": "STRING",
            "optimal_breathing_intervals": "STRING",
            "strained_breathing_intervals": "STRING",
            "data_source": "STRING",
            **METADATA_COLUMNS,
        },
        primary_keys=("timestamp", "data_source"),
        partition_field="timestamp",
        description="Daily sleep breathing quality (multi-line interval strings, UTC midnight literal date).",
    ),
    "google_daily_sleep_temperature_derivations": TableSchemaSpec(
        table_name="google_daily_sleep_temperature_derivations",
        columns={
            "timestamp": "TIMESTAMP",
            "nightly_temperature_celsius": "FLOAT64",
            "baseline_temperature_celsius": "FLOAT64",
            "relative_nightly_stddev_30d_celsius": "FLOAT64",
            "data_source": "STRING",
            **METADATA_COLUMNS,
        },
        primary_keys=("timestamp", "data_source"),
        partition_field="timestamp",
        description="Daily sleep temperature derivations (NaN converted to SQL NULL).",
    ),
    "google_stress_score": TableSchemaSpec(
        table_name="google_stress_score",
        columns={
            "date": "TIMESTAMP",
            "updated_at": "TIMESTAMP",
            "stress_score": "FLOAT64",
            "sleep_points": "FLOAT64",
            "max_sleep_points": "FLOAT64",
            "responsiveness_points": "FLOAT64",
            "max_responsiveness_points": "FLOAT64",
            "exertion_points": "FLOAT64",
            "max_exertion_points": "FLOAT64",
            "status": "STRING",
            "calculation_failed": "BOOL",
            **METADATA_COLUMNS,
        },
        primary_keys=("date",),
        order_by_column="updated_at",
        partition_field="date",
        description="Stress Score daily assessments deduplicated by DATE keeping latest UPDATED_AT.",
    ),
    "google_heart_rate": TableSchemaSpec(
        table_name="google_heart_rate",
        columns={
            "timestamp": "TIMESTAMP",
            "beats_per_minute": "FLOAT64",
            "data_source": "STRING",
            **METADATA_COLUMNS,
        },
        primary_keys=("timestamp", "data_source"),
        partition_field="timestamp",
        clustering_fields=("data_source",),
        description="High-frequency intraday heart rate samples (true UTC timestamps).",
    ),
    "google_body_temperature": TableSchemaSpec(
        table_name="google_body_temperature",
        columns={
            "timestamp": "TIMESTAMP",
            "temperature_celsius": "FLOAT64",
            "data_source": "STRING",
            **METADATA_COLUMNS,
        },
        primary_keys=("timestamp", "data_source"),
        partition_field="timestamp",
        clustering_fields=("data_source",),
        description="High-frequency body/skin temperature samples.",
    ),
    "google_steps": TableSchemaSpec(
        table_name="google_steps",
        columns={
            "timestamp": "TIMESTAMP",
            "steps": "INT64",
            "data_source": "STRING",
            **METADATA_COLUMNS,
        },
        primary_keys=("timestamp", "data_source"),
        partition_field="timestamp",
        description="High-frequency step count samples.",
    ),
    "google_calories": TableSchemaSpec(
        table_name="google_calories",
        columns={
            "timestamp": "TIMESTAMP",
            "calories": "FLOAT64",
            "data_source": "STRING",
            **METADATA_COLUMNS,
        },
        primary_keys=("timestamp", "data_source"),
        partition_field="timestamp",
        description="High-frequency calories burned samples.",
    ),
    "google_active_zone_minutes": TableSchemaSpec(
        table_name="google_active_zone_minutes",
        columns={
            "timestamp": "TIMESTAMP",
            "active_zone_minutes": "INT64",
            "heart_rate_zone": "STRING",
            "data_source": "STRING",
            **METADATA_COLUMNS,
        },
        primary_keys=("timestamp", "data_source"),
        partition_field="timestamp",
        description="Active Zone Minutes intraday samples.",
    ),
    "google_distance": TableSchemaSpec(
        table_name="google_distance",
        columns={
            "timestamp": "TIMESTAMP",
            "distance_millimeters": "FLOAT64",
            "data_source": "STRING",
            **METADATA_COLUMNS,
        },
        primary_keys=("timestamp", "data_source"),
        partition_field="timestamp",
        description="Intraday distance samples.",
    ),
    "google_floors": TableSchemaSpec(
        table_name="google_floors",
        columns={
            "timestamp": "TIMESTAMP",
            "floors": "FLOAT64",
            "data_source": "STRING",
            **METADATA_COLUMNS,
        },
        primary_keys=("timestamp", "data_source"),
        partition_field="timestamp",
        description="Intraday floors climbed samples.",
    ),
    "google_oxygen_saturation": TableSchemaSpec(
        table_name="google_oxygen_saturation",
        columns={
            "timestamp": "TIMESTAMP",
            "percentage": "FLOAT64",
            "data_source": "STRING",
            **METADATA_COLUMNS,
        },
        primary_keys=("timestamp", "data_source"),
        partition_field="timestamp",
        description="Intraday nocturnal SpO2 samples.",
    ),
    "google_weight": TableSchemaSpec(
        table_name="google_weight",
        columns={
            "timestamp": "TIMESTAMP",
            "weight_grams": "FLOAT64",
            "bmi": "FLOAT64",
            "body_fat_percentage": "FLOAT64",
            "data_source": "STRING",
            **METADATA_COLUMNS,
        },
        primary_keys=("timestamp", "data_source"),
        partition_field="timestamp",
        description="Body weight measurements.",
    ),
    "google_demographic_vo2max": TableSchemaSpec(
        table_name="google_demographic_vo2max",
        columns={
            "timestamp": "TIMESTAMP",
            "demographic_vo2max": "FLOAT64",
            "demographic_vo2max_error": "FLOAT64",
            "filtered_demographic_vo2max": "FLOAT64",
            "filtered_demographic_vo2max_error": "FLOAT64",
            "data_source": "STRING",
            **METADATA_COLUMNS,
        },
        primary_keys=("timestamp", "data_source"),
        partition_field="timestamp",
        description="Daily demographic VO2max estimates.",
    ),
    "google_cardio_acute_chronic_workload_ratio": TableSchemaSpec(
        table_name="google_cardio_acute_chronic_workload_ratio",
        columns={
            "timestamp": "TIMESTAMP",
            "acute_chronic_workload_ratio": "FLOAT64",
            "acute_load": "FLOAT64",
            "chronic_load": "FLOAT64",
            "data_source": "STRING",
            **METADATA_COLUMNS,
        },
        primary_keys=("timestamp", "data_source"),
        partition_field="timestamp",
        description="Daily cardio load and ACWR metrics.",
    ),
    "transcend_cpap_daily_usage": TableSchemaSpec(
        table_name="transcend_cpap_daily_usage",
        columns={
            "usage_date": "DATE",
            "device_sn": "STRING",
            "usage_minutes": "INT64",
            "usage_hours": "FLOAT64",
            "pressure": "FLOAT64",
            "ahi": "FLOAT64",
            "avg_leak": "FLOAT64",
            "mode": "STRING",
            **METADATA_COLUMNS,
        },
        primary_keys=("usage_date", "device_sn"),
        partition_field="usage_date",
        description="Future connector target table for Transcend Micro travel CPAP exports.",
    ),
    "zenplanner_workouts": TableSchemaSpec(
        table_name="zenplanner_workouts",
        columns={
            "workout_id": "STRING",
            "workout_date": "DATE",
            "class_name": "STRING",
            "wod_name": "STRING",
            "score_text": "STRING",
            "rx_flag": "BOOL",
            "notes": "STRING",
            **METADATA_COLUMNS,
        },
        primary_keys=("workout_id",),
        partition_field="workout_date",
        description="Future connector target table for ZenPlanner CrossFit workout exports.",
    ),
    "bronze_journal_daily_observations": TableSchemaSpec(
        table_name="bronze_journal_daily_observations",
        columns={
            "observation_date": "DATE",
            "night_number": "INT64",
            "activity_notes": "STRING",
            "morning_coffee_cups": "FLOAT64",
            "wake_up_observations": "STRING",
            **METADATA_COLUMNS,
        },
        primary_keys=("observation_date",),
        order_by_column="_ingested_at",
        partition_field="observation_date",
        description="Daily activities, morning coffee intake, and wake-up subjective observations from Google Sheets.",
    ),
    "bronze_journal_baseline_notes": TableSchemaSpec(
        table_name="bronze_journal_baseline_notes",
        columns={
            "note_id": "STRING",
            "note_category": "STRING",
            "note_text": "STRING",
            **METADATA_COLUMNS,
        },
        primary_keys=("note_id",),
        order_by_column="_ingested_at",
        description="Baseline habits, routines, diet, and supplement notes from Google Sheets Notes tab.",
    ),
}


# Explicit natural keys & partition columns for known dynamic Google Health Takeout families
DYNAMIC_FAMILY_HINTS: Dict[str, Dict[str, object]] = {
    "user_activity_probabilities": {
        "primary_keys": ("timestamp", "activity_type"),
        "partition_field": "timestamp",
    },
    "user_sensor_compression_token": {
        "primary_keys": ("_row_hash",),
    },
    "app_content_history": {
        "primary_keys": ("_row_hash",),
    },
    "ecg_user_data": {
        "primary_keys": ("_row_hash",),
    },
    "takeout_irn_afib_alert_windows": {
        "primary_keys": ("_row_hash",),
    },
    "takeout_irn_user_state": {
        "primary_keys": ("_row_hash",),
    },
    "goal_settings_history": {
        "primary_keys": ("_row_hash",),
    },
    "user_profile_data": {
        "primary_keys": ("_row_hash",),
    },
    "user_demographic_data": {
        "primary_keys": ("_row_hash",),
    },
    "user_journal_entries": {
        "primary_keys": ("_row_hash",),
    },
    "paired_devices": {
        "primary_keys": ("_row_hash",),
    },
    "device_trackers": {
        "primary_keys": ("_row_hash",),
    },
    "cardio_load_preferences": {
        "primary_keys": ("_row_hash",),
    },
    "calibration_status_for_readiness_and_load": {
        "primary_keys": ("_row_hash",),
    },
    "daily_heart_rate_zones": {
        "primary_keys": ("timestamp", "data_source"),
        "partition_field": "timestamp",
    },
    "height": {
        "primary_keys": ("timestamp", "data_source"),
        "partition_field": "timestamp",
    },
    "basal_metabolic_rate": {
        "primary_keys": ("timestamp", "data_source"),
        "partition_field": "timestamp",
    },
    "moods": {
        "primary_keys": ("_row_hash",),
    },
    "symptoms": {
        "primary_keys": ("_row_hash",),
    },
    "active_minutes": {
        "primary_keys": ("timestamp", "data_source"),
        "partition_field": "timestamp",
    },
    "activity_level": {
        "primary_keys": ("timestamp", "data_source"),
        "partition_field": "timestamp",
    },
    "altitude": {
        "primary_keys": ("timestamp", "data_source"),
        "partition_field": "timestamp",
    },
    "continuous_eda": {
        "primary_keys": ("timestamp", "data_source"),
        "partition_field": "timestamp",
    },
    "gps_location": {
        "primary_keys": ("timestamp", "data_source"),
        "partition_field": "timestamp",
    },
    "heart_rate_variability": {
        "primary_keys": ("timestamp", "data_source"),
        "partition_field": "timestamp",
    },
    "live_pace": {
        "primary_keys": ("timestamp", "data_source"),
        "partition_field": "timestamp",
    },
    "micro_motion": {
        "primary_keys": ("timestamp", "data_source"),
        "partition_field": "timestamp",
    },
    "respiratory_rate_sleep_summary": {
        "primary_keys": ("timestamp", "data_source"),
        "partition_field": "timestamp",
    },
    "sedentary_period": {
        "primary_keys": ("timestamp", "data_source"),
        "partition_field": "timestamp",
    },
    "speed": {
        "primary_keys": ("timestamp", "data_source"),
        "partition_field": "timestamp",
    },
    "time_in_heart_rate_zone": {
        "primary_keys": ("timestamp", "data_source"),
        "partition_field": "timestamp",
    },
    "cardio_load": {
        "primary_keys": ("timestamp", "data_source"),
        "partition_field": "timestamp",
    },
    "body_response_algorithm_features": {
        "primary_keys": ("timestamp", "data_source"),
        "partition_field": "timestamp",
    },
    "breathing_quality": {
        "primary_keys": ("timestamp", "data_source"),
        "partition_field": "timestamp",
    },
}


def to_snake_case(raw_name: str) -> str:
    """Normalize arbitrary CSV column or filename into a valid BigQuery snake_case identifier."""
    s = raw_name.strip().lstrip("\ufeff")
    # Convert CamelCase boundaries (UserSleeps -> User_Sleeps)
    s = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", s)
    s = re.sub(r"([A-Z]+)([A-Z][a-z])", r"\1_\2", s)
    s = re.sub(r"[^a-zA-Z0-9_]+", "_", s)
    s = re.sub(r"_+", "_", s).strip("_").lower()
    if not s:
        s = "col"
    if s[0].isdigit():
        s = f"c_{s}"
    return s[:300]


def infer_google_takeout_family(blob_path: str) -> str:
    """Map a Google Takeout CSV path to a canonical schema family name."""
    filename = blob_path.rsplit("/", 1)[-1]
    stem = re.sub(r"\.csv$", "", filename, flags=re.IGNORECASE)
    # Strip trailing date/shard suffixes like _2026-01-09 or -2026-01-09 or _0001
    stem = re.sub(r"[_-]\d{4}-\d{2}-\d{2}(?:[_-]\d+)?$", "", stem)
    stem = re.sub(r"[_-]\d{6,}$", "", stem)
    family = to_snake_case(stem)
    # Preserve subfolder context for general_* folders when filename alone is generic
    parts = [p for p in blob_path.split("/") if p]
    if len(parts) >= 2:
        parent = to_snake_case(parts[-2])
        if parent.startswith("general_") and not family.startswith("general_"):
            family = f"{parent}_{family}" if family not in parent else parent
    return family


def get_spec_for_google_family(family: str) -> TableSchemaSpec:
    """Return an explicit TableSchemaSpec if known, or construct a safe dynamic spec."""
    table_name = f"google_{family}" if not family.startswith("google_") else family
    if table_name in CORE_HEALTH_TABLES:
        return CORE_HEALTH_TABLES[table_name]
    hints = DYNAMIC_FAMILY_HINTS.get(family, {})
    pks = tuple(hints.get("primary_keys", ("_row_hash",)))
    clusters = ("_row_hash",) if pks == ("_row_hash",) else ()
    return TableSchemaSpec(
        table_name=table_name,
        columns=dict(METADATA_COLUMNS),
        primary_keys=pks,
        order_by_column=hints.get("order_by_column"),  # type: ignore[arg-type]
        partition_field=hints.get("partition_field"),  # type: ignore[arg-type]
        clustering_fields=clusters,
        allow_schema_evolution=True,
        description=f"Auto-discovered Google Health Takeout table for {family}.",
    )


_UPLOAD_BATCH_PREFIX_RE = re.compile(
    r"^uploads/(?:google_takeout/(?:zips|folders|unzipped)|reacthealth_pdf|transcend_micro|zenplanner)/[^/]+/",
    re.IGNORECASE,
)


def normalize_logical_path(blob_path: str) -> str:
    """
    Strip upload batch/run prefixes and optional 'Takeout/' wrapper so identical
    historical Takeout shards uploaded in future batches match the ingestion ledger.
    """
    cleaned = blob_path.lstrip("/")
    cleaned = _UPLOAD_BATCH_PREFIX_RE.sub("", cleaned)
    if cleaned.lower().startswith("takeout/"):
        cleaned = cleaned[len("takeout/") :]
    return cleaned.strip().lower()
