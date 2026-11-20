from __future__ import annotations

from datetime import date, timedelta
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import Response
from google.cloud import bigquery

from app.config import get_settings
from app.services.sleep_doctor_pdf import build_sleep_doctor_pdf

router = APIRouter(prefix="/api", tags=["dashboard"])

CORRELATION_WHITELIST = {
    "steps": "steps",
    "active_zone_minutes": "active_zone_minutes",
    "calories_burned": "calories_burned",
    "cardio_acwr": "cardio_acwr",
    "sleep_restoration_pct": "sleep_restoration_pct",
    "readiness_score": "readiness_score",
    "sleep_overall_score": "sleep_overall_score",
    "hrv_rmssd_ms": "hrv_rmssd_ms",
    "resting_heart_rate": "resting_heart_rate",
    "spo2_avg_pct": "spo2_avg_pct",
    "deep_sleep_pct": "deep_sleep_pct",
    "rem_sleep_pct": "rem_sleep_pct",
    "cpap_ahi": "cpap_ahi",
    "cpap_avg_leak": "cpap_avg_leak",
    "cpap_usage_hours": "cpap_usage_hours",
    "morning_coffee_cups": "morning_coffee_cups",
}


def _bq_client() -> bigquery.Client:
    s = get_settings()
    return bigquery.Client(project=s.gcp_project_id, location=s.bq_location)


def _table_exists(client: bigquery.Client, table_fqn: str) -> bool:
    try:
        client.get_table(table_fqn)
        return True
    except Exception:
        return False


@router.get("/dashboard/overview")
def get_dashboard_overview(
    start_date: Optional[str] = Query(default=None),
    end_date: Optional[str] = Query(default=None),
) -> Dict[str, Any]:
    settings = get_settings()
    client = _bq_client()
    gold_fqn = f"{settings.gcp_project_id}.{settings.bq_dataset_gold}"
    view_fqn = f"{gold_fqn}.v_daily_health_performance"

    if not _table_exists(client, view_fqn):
        return {
            "cpap_start_date": settings.default_cpap_start_date,
            "row_count": 0,
            "days": [],
        }

    where_clauses: List[str] = []
    params: List[bigquery.ScalarQueryParameter] = []
    if start_date:
        where_clauses.append("health_date >= @start_date")
        params.append(bigquery.ScalarQueryParameter("start_date", "DATE", start_date))
    if end_date:
        where_clauses.append("health_date <= @end_date")
        params.append(bigquery.ScalarQueryParameter("end_date", "DATE", end_date))

    where_sql = f"WHERE {' AND '.join(where_clauses)}" if where_clauses else ""
    sql = f"""
    SELECT *
    FROM `{gold_fqn}.v_daily_health_performance`
    {where_sql}
    ORDER BY health_date ASC
    """
    job_config = bigquery.QueryJobConfig(query_parameters=params)
    try:
        rows = [dict(r.items()) for r in client.query(sql, job_config=job_config).result()]
    except Exception:
        rows = []

    cpap_start = (
        str(rows[0]["cpap_start_date"])
        if rows and rows[0].get("cpap_start_date")
        else settings.default_cpap_start_date
    )
    return {
        "cpap_start_date": cpap_start,
        "row_count": len(rows),
        "days": rows,
    }


@router.get("/dashboard/cpap-impact")
def get_cpap_before_after() -> Dict[str, Any]:
    settings = get_settings()
    client = _bq_client()
    gold_fqn = f"{settings.gcp_project_id}.{settings.bq_dataset_gold}"
    view_fqn = f"{gold_fqn}.v_cpap_before_after_summary"
    if not _table_exists(client, view_fqn):
        return {"metrics": []}
    sql = f"""
    SELECT *
    FROM `{gold_fqn}.v_cpap_before_after_summary`
    ORDER BY metric_name
    """
    try:
        rows = [dict(r.items()) for r in client.query(sql).result()]
    except Exception:
        rows = []
    return {"metrics": rows}


@router.get("/dashboard/habits-impact")
def get_habits_impact() -> Dict[str, Any]:
    settings = get_settings()
    client = _bq_client()
    silver_fqn = f"{settings.gcp_project_id}.{settings.bq_dataset_silver}"
    bronze_fqn = f"{settings.gcp_project_id}.{settings.bq_dataset_bronze}"
    tbl_fqn = f"{silver_fqn}.daily_health_summary"
    if not _table_exists(client, tbl_fqn):
        return {"habits": [], "baseline_notes": []}

    habit_defs = [
        ("crossfit", "CrossFit WOD", "COALESCE(has_crossfit_wod, FALSE)"),
        ("cold_plunge", "Cold Plunge", "COALESCE(has_cold_plunge, FALSE)"),
        ("dry_sauna", "Dry Sauna", "COALESCE(has_dry_sauna, FALSE)"),
        ("alcohol", "Alcohol Logged", "COALESCE(has_alcohol, FALSE)"),
        ("late_dinner", "Late Dinner", "COALESCE(has_late_dinner, FALSE)"),
        ("nap", "Daytime Nap", "COALESCE(has_daytime_nap, FALSE)"),
        ("coffee_3plus", "Coffee 3+ Cups", "COALESCE(morning_coffee_cups, 0) >= 3"),
    ]

    union_queries = []
    for key, label, cond in habit_defs:
        union_queries.append(
            f"""
            SELECT
              '{key}' AS habit_key,
              '{label}' AS habit,
              COUNTIF({cond}) AS active_days,
              ROUND(AVG(IF({cond}, sleep_overall_score, NULL)), 1) AS active_sleep_score,
              ROUND(AVG(IF(NOT ({cond}), sleep_overall_score, NULL)), 1) AS other_sleep_score,
              ROUND(AVG(IF({cond}, deep_sleep_pct, NULL)), 1) AS active_deep_pct,
              ROUND(AVG(IF(NOT ({cond}), deep_sleep_pct, NULL)), 1) AS other_deep_pct,
              ROUND(AVG(IF({cond}, hrv_rmssd_ms, NULL)), 1) AS active_hrv,
              ROUND(AVG(IF(NOT ({cond}), hrv_rmssd_ms, NULL)), 1) AS other_hrv,
              ROUND(AVG(IF({cond}, resting_heart_rate, NULL)), 1) AS active_rhr,
              ROUND(AVG(IF(NOT ({cond}), resting_heart_rate, NULL)), 1) AS other_rhr,
              ROUND(AVG(IF({cond}, readiness_score, NULL)), 1) AS active_readiness,
              ROUND(AVG(IF(NOT ({cond}), readiness_score, NULL)), 1) AS other_readiness,
              ROUND(AVG(IF({cond}, cpap_ahi, NULL)), 2) AS active_ahi,
              ROUND(AVG(IF(NOT ({cond}), cpap_ahi, NULL)), 2) AS other_ahi,
              ROUND(AVG(IF({cond}, spo2_min_pct, NULL)), 1) AS active_spo2_min,
              ROUND(AVG(IF(NOT ({cond}), spo2_min_pct, NULL)), 1) AS other_spo2_min
            FROM tagged
            """.strip()
        )

    sql = f"""
    WITH tagged AS (
      SELECT
        health_date,
        sleep_overall_score,
        deep_sleep_pct,
        hrv_rmssd_ms,
        resting_heart_rate,
        readiness_score,
        cpap_ahi,
        spo2_min_pct,
        morning_coffee_cups,
        has_crossfit_wod,
        has_cold_plunge,
        has_dry_sauna,
        has_alcohol,
        has_daytime_nap,
        has_late_dinner
      FROM `{tbl_fqn}`
      WHERE activity_notes IS NOT NULL
         OR wake_up_observations IS NOT NULL
         OR morning_coffee_cups IS NOT NULL
    )
    {" UNION ALL ".join(union_queries)}
    """
    try:
        rows = [dict(r.items()) for r in client.query(sql).result()]
    except Exception:
        rows = []

    baseline_notes: List[Dict[str, Any]] = []
    notes_fqn = f"{bronze_fqn}.bronze_journal_baseline_notes"
    if _table_exists(client, notes_fqn):
        try:
            notes_sql = f"""
            SELECT note_category, note_text
            FROM `{notes_fqn}`
            ORDER BY note_category, note_id
            """
            baseline_notes = [dict(r.items()) for r in client.query(notes_sql).result()]
        except Exception:
            baseline_notes = []

    return {"habits": rows, "baseline_notes": baseline_notes}


@router.get("/dashboard/correlations")
def get_correlations(
    x: str = Query(default="active_zone_minutes"),
    y: str = Query(default="hrv_rmssd_ms"),
    lag_next_night: bool = Query(default=False),
    start_date: Optional[str] = Query(default=None),
    end_date: Optional[str] = Query(default=None),
) -> Dict[str, Any]:
    if x not in CORRELATION_WHITELIST or y not in CORRELATION_WHITELIST:
        raise HTTPException(status_code=400, detail="Unsupported correlation metric.")
    x_col = CORRELATION_WHITELIST[x]
    y_col = CORRELATION_WHITELIST[y]

    settings = get_settings()
    client = _bq_client()
    silver_fqn = f"{settings.gcp_project_id}.{settings.bq_dataset_silver}"
    if not _table_exists(client, f"{silver_fqn}.daily_health_summary"):
        return {
            "x": x,
            "y": y,
            "lag_next_night": lag_next_night,
            "pearson_r": None,
            "sample_size": 0,
            "points": [],
        }

    y_expr = f"LEAD({y_col}, 1) OVER (ORDER BY health_date)" if lag_next_night else y_col
    filters: List[str] = []
    params: List[bigquery.ScalarQueryParameter] = []
    if start_date:
        filters.append("health_date >= @start_date")
        params.append(bigquery.ScalarQueryParameter("start_date", "DATE", start_date))
    if end_date:
        filters.append("health_date <= @end_date")
        params.append(bigquery.ScalarQueryParameter("end_date", "DATE", end_date))
    where_sql = f"WHERE {' AND '.join(filters)}" if filters else ""

    sql = f"""
    WITH paired AS (
      SELECT
        health_date,
        is_cpap_era,
        CAST({x_col} AS FLOAT64) AS x_val,
        CAST({y_expr} AS FLOAT64) AS y_val
      FROM `{silver_fqn}.daily_health_summary`
      {where_sql}
    )
    SELECT *
    FROM paired
    WHERE x_val IS NOT NULL AND y_val IS NOT NULL
    ORDER BY health_date ASC
    """
    job_config = bigquery.QueryJobConfig(query_parameters=params)
    try:
        points = [dict(r.items()) for r in client.query(sql, job_config=job_config).result()]
    except Exception:
        points = []

    pearson_r = _compute_pearson(
        [float(p["x_val"]) for p in points],
        [float(p["y_val"]) for p in points],
    )
    return {
        "x": x,
        "y": y,
        "lag_next_night": lag_next_night,
        "pearson_r": pearson_r,
        "sample_size": len(points),
        "points": points,
    }


@router.get("/dashboard/intraday/{health_date}")
def get_intraday_drilldown(health_date: str) -> Dict[str, Any]:
    try:
        target_date = date.fromisoformat(health_date)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="health_date must be YYYY-MM-DD.") from exc

    settings = get_settings()
    client = _bq_client()
    silver_fqn = f"{settings.gcp_project_id}.{settings.bq_dataset_silver}"
    bronze_fqn = f"{settings.gcp_project_id}.{settings.bq_dataset_bronze}"

    day_rows: List[Dict[str, Any]] = []
    if _table_exists(client, f"{silver_fqn}.daily_health_summary"):
        day_sql = f"""
        SELECT *
        FROM `{silver_fqn}.daily_health_summary`
        WHERE health_date = @hdate
        LIMIT 1
        """
        day_cfg = bigquery.QueryJobConfig(
            query_parameters=[bigquery.ScalarQueryParameter("hdate", "DATE", target_date.isoformat())]
        )
        try:
            day_rows = [dict(r.items()) for r in client.query(day_sql, job_config=day_cfg).result()]
        except Exception:
            day_rows = []

    day_summary = day_rows[0] if day_rows else {}
    sleep_id = day_summary.get("primary_sleep_id")
    sleep_start = day_summary.get("primary_sleep_start")
    sleep_end = day_summary.get("primary_sleep_end")

    # Fetch sleep stage hypnogram from Bronze
    stages: List[Dict[str, Any]] = []
    if sleep_id:
        stages_sql = f"""
        SELECT
          sleep_stage_id,
          sleep_stage_type,
          sleep_stage_start,
          sleep_stage_end,
          DATETIME(sleep_stage_start, 'America/Los_Angeles') AS local_start,
          DATETIME(sleep_stage_end, 'America/Los_Angeles') AS local_end
        FROM `{bronze_fqn}.google_user_sleep_stages`
        WHERE sleep_id = @sleep_id
        ORDER BY sleep_stage_start ASC
        """
        st_cfg = bigquery.QueryJobConfig(
            query_parameters=[bigquery.ScalarQueryParameter("sleep_id", "STRING", str(sleep_id))]
        )
        try:
            stages = [dict(r.items()) for r in client.query(stages_sql, job_config=st_cfg).result()]
        except Exception:
            stages = []

    # Determine intraday time window: primary sleep window if present, else overnight window ending on health_date
    if sleep_start and sleep_end:
        win_start = sleep_start
        win_end = sleep_end
        hr_filter = "timestamp BETWEEN @win_start AND @win_end"
        hr_params = [
            bigquery.ScalarQueryParameter("win_start", "TIMESTAMP", win_start),
            bigquery.ScalarQueryParameter("win_end", "TIMESTAMP", win_end),
        ]
    else:
        prev_day = (target_date - timedelta(days=1)).isoformat()
        hr_filter = (
            "DATETIME(timestamp, 'America/Los_Angeles') BETWEEN "
            "DATETIME(@prev_day || ' 20:00:00') AND DATETIME(@hdate || ' 12:00:00')"
        )
        hr_params = [
            bigquery.ScalarQueryParameter("prev_day", "STRING", prev_day),
            bigquery.ScalarQueryParameter("hdate", "STRING", target_date.isoformat()),
        ]

    # Minute-level binned HR curve (handles per-second Pixel Watch data cleanly in browser)
    hr_sql = f"""
    SELECT
      TIMESTAMP_TRUNC(timestamp, MINUTE) AS ts_utc,
      FORMAT_TIMESTAMP('%Y-%m-%d %H:%M', TIMESTAMP_TRUNC(timestamp, MINUTE), 'America/Los_Angeles') AS local_time,
      ROUND(AVG(beats_per_minute), 1) AS avg_bpm,
      MIN(beats_per_minute) AS min_bpm,
      MAX(beats_per_minute) AS max_bpm
    FROM `{bronze_fqn}.google_heart_rate`
    WHERE {hr_filter}
    GROUP BY 1, 2
    ORDER BY 1 ASC
    LIMIT 1500
    """
    spo2_sql = f"""
    SELECT
      timestamp AS ts_utc,
      FORMAT_TIMESTAMP('%Y-%m-%d %H:%M', timestamp, 'America/Los_Angeles') AS local_time,
      percentage AS spo2_pct
    FROM `{bronze_fqn}.google_oxygen_saturation`
    WHERE {hr_filter}
    ORDER BY 1 ASC
    LIMIT 1500
    """
    hr_cfg = bigquery.QueryJobConfig(query_parameters=hr_params)
    try:
        hr_series = [dict(r.items()) for r in client.query(hr_sql, job_config=hr_cfg).result()]
    except Exception:
        hr_series = []
    try:
        spo2_series = [dict(r.items()) for r in client.query(spo2_sql, job_config=hr_cfg).result()]
    except Exception:
        spo2_series = []

    return {
        "health_date": target_date.isoformat(),
        "summary": day_summary,
        "sleep_stages": stages,
        "heart_rate_series": hr_series,
        "spo2_series": spo2_series,
    }


@router.get("/reports/sleep-doctor")
def get_sleep_doctor_summary() -> Dict[str, Any]:
    return _fetch_sleep_doctor_payload()


@router.get("/reports/sleep-doctor.pdf")
def download_sleep_doctor_pdf() -> Response:
    payload = _fetch_sleep_doctor_payload()
    pdf_bytes = build_sleep_doctor_pdf(payload)
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={
            "Content-Disposition": 'attachment; filename="sleep-doctor-clinical-summary.pdf"'
        },
    )


def _fetch_sleep_doctor_payload() -> Dict[str, Any]:
    settings = get_settings()
    client = _bq_client()
    gold_fqn = f"{settings.gcp_project_id}.{settings.bq_dataset_gold}"
    view_fqn = f"{gold_fqn}.v_sleep_doctor_weekly_summary"
    if not _table_exists(client, view_fqn):
        rows = []
    else:
        sql = f"""
        SELECT *
        FROM `{view_fqn}`
        ORDER BY health_date DESC
        """
        try:
            rows = [dict(r.items()) for r in client.query(sql).result()]
        except Exception:
            rows = []

    if not rows:
        return {
            "window_end_date": None,
            "cpap_start_date": settings.default_cpap_start_date,
            "device_sn": None,
            "last_7_days_summary": {},
            "last_30_days_summary": {},
            "best_30_summary": {},
            "nightly_rows": [],
        }

    head = rows[0]
    return {
        "window_end_date": str(head.get("window_end_date") or ""),
        "cpap_start_date": str(head.get("cpap_start_date") or settings.default_cpap_start_date),
        "device_sn": next((r.get("cpap_device_sn") for r in rows if r.get("cpap_device_sn")), None),
        "last_7_days_summary": {
            "calendar_days": head.get("l7_calendar_days"),
            "days_used": head.get("l7_days_used"),
            "days_ge_4h": head.get("l7_days_ge_4h"),
            "adherence_4h_pct": head.get("l7_adherence_4h_pct"),
            "avg_hours_days_used": head.get("l7_avg_hours_days_used"),
            "avg_hours_all_days": head.get("l7_avg_hours_all_days"),
            "avg_ahi": head.get("l7_avg_ahi"),
            "avg_cai": head.get("l7_avg_cai"),
            "median_pressure": head.get("l7_median_pressure"),
            "avg_p95_pressure": head.get("l7_avg_p95_pressure"),
            "avg_leak": head.get("l7_avg_leak"),
            "avg_spo2": head.get("l7_avg_spo2"),
            "min_spo2": head.get("l7_min_spo2"),
            "avg_rhr": head.get("l7_avg_rhr"),
            "avg_hrv": head.get("l7_avg_hrv"),
            "avg_sleep_hours": head.get("l7_avg_sleep_hours"),
            "avg_deep_pct": head.get("l7_avg_deep_pct"),
            "avg_rem_pct": head.get("l7_avg_rem_pct"),
        },
        "last_30_days_summary": {
            "calendar_days": head.get("l30_calendar_days"),
            "days_used": head.get("l30_days_used"),
            "days_ge_4h": head.get("l30_days_ge_4h"),
            "adherence_4h_pct": head.get("l30_adherence_4h_pct"),
            "avg_hours_days_used": head.get("l30_avg_hours_days_used"),
            "avg_hours_all_days": head.get("l30_avg_hours_all_days"),
            "avg_ahi": head.get("l30_avg_ahi"),
            "avg_cai": head.get("l30_avg_cai"),
            "median_pressure": head.get("l30_median_pressure"),
            "avg_p95_pressure": head.get("l30_avg_p95_pressure"),
            "avg_leak": head.get("l30_avg_leak"),
            "avg_spo2": head.get("l30_avg_spo2"),
            "min_spo2": head.get("l30_min_spo2"),
            "avg_rhr": head.get("l30_avg_rhr"),
            "avg_hrv": head.get("l30_avg_hrv"),
        },
        "best_30_summary": {
            "start_date": str(head.get("best30_start_date") or ""),
            "end_date": str(head.get("best30_end_date") or ""),
            "days_ge_4h": head.get("best30_days_ge_4h"),
            "days_used": head.get("best30_days_used"),
            "adherence_pct": head.get("best30_adherence_pct"),
            "avg_hours_used": head.get("best30_avg_hours_used"),
            "avg_ahi": head.get("best30_avg_ahi"),
        },
        "nightly_rows": rows,
    }


def _compute_pearson(xs: List[float], ys: List[float]) -> Optional[float]:
    n = len(xs)
    if n < 3:
        return None
    mx = sum(xs) / n
    my = sum(ys) / n
    num = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    den_x = sum((x - mx) ** 2 for x in xs) ** 0.5
    den_y = sum((y - my) ** 2 for y in ys) ** 0.5
    if den_x == 0 or den_y == 0:
        return None
    return round(num / (den_x * den_y), 4)
