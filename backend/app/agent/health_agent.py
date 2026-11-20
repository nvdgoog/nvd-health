from __future__ import annotations

import json
import os
import re
from typing import Any, Dict, List, Optional

from app.agent.sql_tools import (
    describe_table_schema,
    list_health_tables,
    run_readonly_sql,
    start_sql_audit_log,
)
from app.config import Settings, get_settings


def build_system_instruction(settings: Settings) -> str:
    return f"""You are the Personal Health Data Analyst for GCP project `{settings.gcp_project_id}`.

You have read-only BigQuery SQL tools spanning three Medallion datasets:
1. `{settings.gcp_project_id}.{settings.bq_dataset_gold}`:
   - `v_daily_health_performance`: Daily conformed dashboard view with 7d/30d rolling averages, sleep_efficiency_pct, mask_off_sleep_gap_minutes, cpap_adherence_streak_days, and `era` ('Pre-CPAP' vs 'Post-CPAP').
   - `v_cpap_before_after_summary`: Pre-CPAP vs. Post-CPAP mean, stddev, median, p10, p90, mean_delta, pct_change across spo2_avg_pct, spo2_min_pct, resting_heart_rate, hrv_rmssd_ms, non_rem_hr_bpm, sleep_overall_score, deep_sleep_pct, rem_sleep_pct, total_sleep_hours, respiratory_rate_bpm, readiness_score, stress_score.
   - `v_sleep_doctor_weekly_summary`: Past 7 days nightly detail + l7_*, l30_*, and best30_* clinical CPAP & Google Health metrics.
2. `{settings.gcp_project_id}.{settings.bq_dataset_silver}`:
   - `daily_health_summary`: 1 row per `health_date` (DATE in `America/Los_Angeles`). Combines ReactHealth CPAP (`cpap_usage_minutes`, `cpap_usage_hours`, `cpap_compliant_4h`, `cpap_pressure`, `cpap_p95_pressure`, `cpap_ahi`, `cpap_cai`, `cpap_avg_leak`), sleep architecture (`primary_sleep_start`, `primary_sleep_end`, `total_sleep_minutes`, `deep_sleep_pct`, `rem_sleep_pct`, `sleep_overall_score`), vitals (`resting_heart_rate`, `hrv_rmssd_ms`, `spo2_avg_pct`, `spo2_min_pct`, `respiratory_rate_bpm`, `breathing_quality`, `readiness_score`, `stress_score`), nocturnal rollups (`nocturnal_hr_avg`, `nocturnal_spo2_avg`, `nocturnal_body_temp_avg`), activity (`steps`, `active_zone_minutes`, `calories_burned`, `vo2max`, `cardio_acwr`, `weight_lbs`, `exercise_count`), and subjective journal context from Google Sheets (`activity_notes`, `morning_coffee_cups`, `wake_up_observations`, `has_crossfit_wod`, `has_cold_plunge`, `has_dry_sauna`, `has_alcohol`, `has_daytime_nap`, `has_late_dinner`, `has_travel_day`).
3. `{settings.gcp_project_id}.{settings.bq_dataset_bronze}` (use for intraday drill-downs or raw audit):
   - `google_user_sleeps`, `google_user_sleep_stages` (`sleep_stage_type`, `sleep_stage_start`, `sleep_stage_end`), `google_heart_rate` (`timestamp`, `beats_per_minute`), `google_oxygen_saturation` (`timestamp`, `percentage`), `bronze_reacthealth_daily_usage`, `bronze_app_settings`, `bronze_journal_daily_observations`, `bronze_journal_baseline_notes` (regular habits, Chilipad 55F, intermittent fasting, supplements).

CRITICAL DOMAIN & TIMEZONE RULES:
- `health_date` is always in `America/Los_Angeles` (San Diego).
- Sleep & CPAP align on the wake-up date in `America/Los_Angeles`.
- When querying intraday Bronze tables (`google_heart_rate`, `google_user_sleep_stages`, `google_oxygen_saturation`), filter using `TIMESTAMP` bounds converted with `'America/Los_Angeles'` or join to `daily_health_summary.primary_sleep_start` / `primary_sleep_end`.
- Default CPAP start date is `{settings.default_cpap_start_date}` (verify dynamically via `cpap_start_date` in Silver or `bronze_app_settings`).
- NEVER hallucinate or estimate numbers. ALWAYS call `run_readonly_sql` to verify every metric before responding.

OUTPUT FORMATTING (FOR NON-TECHNICAL BUSINESS & CLINICAL USERS):
- Write in clear, warm, easy-to-read plain English suited for a non-technical reader (no database table names, no snake_case column names like `hrv_rmssd_ms` or `v_cpap_before_after_summary`, and NO SQL code or `<details>` HTML tags in your response unless the user explicitly asks to see the SQL).
- Translate metrics into human terms (e.g. "Average Blood Oxygen (SpO2)", "Heart Rate Variability (HRV)", "Resting Heart Rate", "Deep Sleep %", "CPAP AHI").
- Lead with a concise 1–2 sentence takeaway, followed by scannable bullet points or a clean summary table, citing exact dates and verified numbers.
- Whenever answering trend, comparison, or tabular breakdown questions, emit a structured ```chart-json fenced block matching this schema so the UI renders an interactive chart/table inline:
```chart-json
{{
  "type": "line" | "bar" | "scatter" | "table",
  "title": "Chart Title",
  "subtitle": "Optional subtitle",
  "xKey": "health_date",
  "series": [{{"key": "spo2_avg_pct", "label": "SpO2 Avg (%)", "color": "#0ea5e9"}}],
  "data": [ ...rows from SQL... ]
}}
```
"""


def configure_vertex_genai_env(settings: Settings) -> None:
    """Ensure google-genai / google-adk routes through Vertex AI global/regional ADC."""
    os.environ["GOOGLE_GENAI_USE_VERTEXAI"] = "TRUE"
    os.environ["GOOGLE_CLOUD_PROJECT"] = settings.gcp_project_id
    os.environ["GOOGLE_CLOUD_LOCATION"] = settings.vertex_genai_location


def build_adk_agent(
    settings: Optional[Settings] = None,
    model_override: Optional[str] = None,
) -> Any:
    """Construct the Google ADK Agent configured for Vertex AI / Gemini + BigQuery tools."""
    cfg = settings or get_settings()
    configure_vertex_genai_env(cfg)
    try:
        from google.adk.agents import Agent  # type: ignore
    except ImportError as exc:
        raise RuntimeError(
            "google-adk is required to instantiate the AI Health Analyst agent."
        ) from exc

    return Agent(
        name="nvd_health_analyst",
        model=model_override or cfg.gemini_model,
        description=(
            "Personal Health Data Analyst querying Medallion BigQuery datasets "
            "(Gold, Silver, Bronze) for CPAP, sleep architecture, vitals, and intraday trends."
        ),
        instruction=build_system_instruction(cfg),
        tools=[list_health_tables, describe_table_schema, run_readonly_sql],
    )


def extract_structured_blocks(
    markdown_text: str,
    executed_sql: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """Extract ```chart-json and ```sql blocks and strip raw SQL/HTML details from user-facing prose."""
    charts: List[Dict[str, Any]] = []
    sql_queries: List[str] = list(executed_sql or [])

    for match in re.finditer(r"```chart-json\s*\n(.*?)```", markdown_text, re.DOTALL):
        raw_json = match.group(1).strip()
        try:
            parsed = json.loads(raw_json)
            if isinstance(parsed, dict):
                charts.append(parsed)
        except json.JSONDecodeError:
            continue

    for match in re.finditer(r"```sql\s*\n(.*?)```", markdown_text, re.DOTALL):
        q = match.group(1).strip()
        if q and q not in sql_queries:
            sql_queries.append(q)

    cleaned_text = re.sub(
        r"```chart-json\s*\n.*?```", "", markdown_text, flags=re.DOTALL
    )
    cleaned_text = re.sub(
        r"<details>.*?</details>", "", cleaned_text, flags=re.DOTALL | re.IGNORECASE
    )
    cleaned_text = re.sub(
        r"```sql\s*\n.*?```", "", cleaned_text, flags=re.DOTALL | re.IGNORECASE
    )
    cleaned_text = re.sub(r"\n{3,}", "\n\n", cleaned_text).strip()

    return {
        "reply": cleaned_text,
        "charts": charts,
        "sql_queries": sql_queries,
    }


class HealthAnalystService:
    """
    Dual-mode AI Health Analyst client:
    - Production: invokes deployed Vertex AI Agent Engine (`agent_engine_resource_name`)
    - Local/Fallback: runs the exact same ADK Agent via in-process ADK Runner
    """

    def __init__(self, settings: Optional[Settings] = None) -> None:
        self.settings = settings or get_settings()
        self._local_sessions: Dict[str, Any] = {}

    async def ask(
        self,
        message: str,
        session_id: Optional[str] = None,
        user_id: str = "default-user",
    ) -> Dict[str, Any]:
        if self.settings.agent_engine_resource_name:
            return await self._ask_agent_engine(message, session_id, user_id)
        return await self._ask_local_adk(message, session_id, user_id)

    async def _ask_agent_engine(
        self,
        message: str,
        session_id: Optional[str],
        user_id: str,
    ) -> Dict[str, Any]:
        import vertexai  # type: ignore
        from vertexai import agent_engines  # type: ignore

        vertexai.init(
            project=self.settings.gcp_project_id,
            location=self.settings.gcp_region,
        )
        remote_app = agent_engines.get(self.settings.agent_engine_resource_name)

        active_session_id = session_id
        if not active_session_id:
            session = remote_app.create_session(user_id=user_id)
            active_session_id = (
                session.get("id") if isinstance(session, dict) else getattr(session, "id", "default")
            )

        chunks: List[str] = []
        for event in remote_app.stream_query(
            user_id=user_id,
            session_id=active_session_id,
            message=message,
        ):
            text = _extract_text_from_event(event)
            if text:
                chunks.append(text)

        full_text = "\n".join(chunks).strip()
        structured = extract_structured_blocks(full_text)
        return {
            "session_id": active_session_id,
            "mode": "vertex_agent_engine",
            "model": self.settings.gemini_model,
            **structured,
        }

    async def _ask_local_adk(
        self,
        message: str,
        session_id: Optional[str],
        user_id: str,
    ) -> Dict[str, Any]:
        import uuid
        from google.adk.runners import Runner  # type: ignore
        from google.adk.sessions import InMemorySessionService  # type: ignore
        from google.genai import types  # type: ignore

        configure_vertex_genai_env(self.settings)
        session_service = self._local_sessions.setdefault(
            "service", InMemorySessionService()
        )

        active_session_id = session_id or f"local-{uuid.uuid4().hex[:10]}"
        existing = await session_service.get_session(
            app_name="nvd_health_analyst",
            user_id=user_id,
            session_id=active_session_id,
        )
        if existing is None:
            await session_service.create_session(
                app_name="nvd_health_analyst",
                user_id=user_id,
                session_id=active_session_id,
            )

        content = types.Content(
            role="user",
            parts=[types.Part.from_text(text=message)],
        )

        models_to_try = [self.settings.gemini_model]
        for fallback in ("gemini-4-hydrogen", "gemini-4-argon", "gemini-3.5-flash-lite"):
            if fallback not in models_to_try:
                models_to_try.append(fallback)

        last_exc: Optional[Exception] = None
        for model_name in models_to_try:
            cache_key = f"runner:{model_name}"
            runner = self._local_sessions.get(cache_key)
            if runner is None:
                agent = build_adk_agent(self.settings, model_override=model_name)
                runner = Runner(
                    agent=agent,
                    app_name="nvd_health_analyst",
                    session_service=session_service,
                )
                self._local_sessions[cache_key] = runner

            try:
                sql_audit_log = start_sql_audit_log()
                chunks: List[str] = []
                async for event in runner.run_async(
                    user_id=user_id,
                    session_id=active_session_id,
                    new_message=content,
                ):
                    if event.content and getattr(event.content, "parts", None):
                        for part in event.content.parts:
                            if getattr(part, "text", None):
                                chunks.append(part.text)

                full_text = "\n".join(chunks).strip()
                structured = extract_structured_blocks(
                    full_text, executed_sql=sql_audit_log
                )
                return {
                    "session_id": active_session_id,
                    "mode": "local_adk_runner",
                    "model": model_name,
                    **structured,
                }
            except Exception as exc:
                last_exc = exc
                msg = str(exc)
                if ("404" in msg or "NOT_FOUND" in msg) and model_name != models_to_try[-1]:
                    continue
                raise

        raise last_exc or RuntimeError("ADK runner failed without output.")


def _extract_text_from_event(event: Any) -> str:
    if isinstance(event, dict):
        content = event.get("content") or {}
        parts = content.get("parts") or []
        texts = [p.get("text", "") for p in parts if isinstance(p, dict) and p.get("text")]
        if texts:
            return "".join(texts)
        if isinstance(event.get("text"), str):
            return event["text"]
    return ""
