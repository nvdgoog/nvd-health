export interface DailyPerformanceRow {
  health_date: string;
  cpap_start_date?: string;
  is_cpap_era?: boolean;
  era?: "Pre-CPAP" | "Post-CPAP";
  days_since_cpap_start?: number;
  cpap_device_sn?: string;
  cpap_mode?: string;
  cpap_usage_duration_str?: string;
  cpap_usage_minutes?: number | null;
  cpap_usage_hours?: number | null;
  cpap_compliant_4h?: boolean | null;
  cpap_pressure?: number | null;
  cpap_p95_pressure?: number | null;
  cpap_ahi?: number | null;
  cpap_cai?: number | null;
  cpap_avg_leak?: number | null;
  cpap_adherence_streak_days?: number;
  mask_off_sleep_gap_minutes?: number | null;
  primary_sleep_id?: string;
  total_sleep_minutes?: number | null;
  nap_minutes?: number | null;
  deep_sleep_minutes?: number | null;
  rem_sleep_minutes?: number | null;
  light_sleep_minutes?: number | null;
  sleep_stage_awake_minutes?: number | null;
  deep_sleep_pct?: number | null;
  rem_sleep_pct?: number | null;
  light_sleep_pct?: number | null;
  sleep_overall_score?: number | null;
  sleep_efficiency_pct?: number | null;
  resting_heart_rate?: number | null;
  hrv_rmssd_ms?: number | null;
  non_rem_hr_bpm?: number | null;
  spo2_avg_pct?: number | null;
  spo2_min_pct?: number | null;
  nocturnal_hr_avg?: number | null;
  nocturnal_spo2_avg?: number | null;
  nocturnal_spo2_min?: number | null;
  respiratory_rate_bpm?: number | null;
  breathing_quality?: string | null;
  skin_temp_deviation_celsius?: number | null;
  readiness_score?: number | null;
  sleep_restoration_pct?: number | null;
  stress_score?: number | null;
  steps?: number | null;
  active_zone_minutes?: number | null;
  calories_burned?: number | null;
  vo2max?: number | null;
  cardio_acwr?: number | null;
  weight_lbs?: number | null;
  exercise_count?: number | null;
  exercise_types?: string | null;
  spo2_avg_7d?: number | null;
  rhr_avg_7d?: number | null;
  hrv_avg_7d?: number | null;
  sleep_hours_avg_7d?: number | null;
  cpap_hours_avg_7d?: number | null;
  transcend_usage_minutes?: number | null;
  zenplanner_workout_count?: number | null;
  zenplanner_wod_name?: string | null;
  activity_notes?: string | null;
  morning_coffee_cups?: number | null;
  wake_up_observations?: string | null;
  has_crossfit_wod?: boolean | null;
  has_cold_plunge?: boolean | null;
  has_dry_sauna?: boolean | null;
  has_alcohol?: boolean | null;
  has_daytime_nap?: boolean | null;
  has_late_dinner?: boolean | null;
  has_travel_day?: boolean | null;
}

export interface HabitImpactRow {
  habit_key: string;
  habit: string;
  active_days: number;
  active_sleep_score: number | null;
  other_sleep_score: number | null;
  active_deep_pct: number | null;
  other_deep_pct: number | null;
  active_hrv: number | null;
  other_hrv: number | null;
  active_rhr: number | null;
  other_rhr: number | null;
  active_readiness: number | null;
  other_readiness: number | null;
  active_ahi: number | null;
  other_ahi: number | null;
  active_spo2_min: number | null;
  other_spo2_min: number | null;
}

export interface BaselineNoteRow {
  note_category: string;
  note_text: string;
}

export interface CpapImpactMetric {
  metric_name: string;
  pre_days: number | null;
  pre_mean: number | null;
  pre_stddev: number | null;
  pre_median: number | null;
  pre_p10: number | null;
  pre_p90: number | null;
  post_days: number | null;
  post_mean: number | null;
  post_stddev: number | null;
  post_median: number | null;
  post_p10: number | null;
  post_p90: number | null;
  mean_delta: number | null;
  pct_change: number | null;
  pre_optimal_breathing_days?: number;
  pre_breathing_days?: number;
  post_optimal_breathing_days?: number;
  post_breathing_days?: number;
}

export interface EtlRunRecord {
  run_id: string;
  trigger_mode: string;
  status: string;
  current_stage: string;
  source_prefixes?: string[];
  files_total: number;
  files_scanned: number;
  files_loaded: number;
  files_skipped: number;
  files_failed: number;
  rows_inserted: number;
  rows_updated: number;
  table_stats?: Record<
    string,
    { staged: number; inserted: number; updated: number; files: number }
  >;
  dataform_compilation_id?: string | null;
  dataform_invocation_id?: string | null;
  dataform_status?: string | null;
  dataform_actions?: Array<{
    target: string;
    state: string;
    failure_reason: string;
  }>;
  error_message?: string | null;
  started_at?: string;
  updated_at?: string;
  completed_at?: string | null;
}

export interface ChartSpec {
  type: "line" | "bar" | "scatter" | "table";
  title: string;
  subtitle?: string;
  xKey: string;
  series: Array<{ key: string; label: string; color?: string }>;
  data: Array<Record<string, unknown>>;
}

export interface AnalystChatResponse {
  session_id: string;
  mode: string;
  model: string;
  reply: string;
  charts: ChartSpec[];
  sql_queries: string[];
}

async function fetchJson<T>(url: string, init?: RequestInit): Promise<T> {
  const res = await fetch(url, init);
  if (!res.ok) {
    const body = await res.text();
    throw new Error(body || `HTTP ${res.status}`);
  }
  return (await res.json()) as T;
}

export const api = {
  getOverview: (startDate?: string, endDate?: string) => {
    const qs = new URLSearchParams();
    if (startDate) qs.set("start_date", startDate);
    if (endDate) qs.set("end_date", endDate);
    const suffix = qs.toString() ? `?${qs.toString()}` : "";
    return fetchJson<{
      cpap_start_date: string;
      row_count: number;
      days: DailyPerformanceRow[];
    }>(`/api/dashboard/overview${suffix}`);
  },
  getCpapImpact: () =>
    fetchJson<{ metrics: CpapImpactMetric[] }>("/api/dashboard/cpap-impact"),
  getCorrelations: (
    x: string,
    y: string,
    lagNextNight: boolean,
    startDate?: string,
    endDate?: string
  ) => {
    const qs = new URLSearchParams({
      x,
      y,
      lag_next_night: String(lagNextNight),
    });
    if (startDate) qs.set("start_date", startDate);
    if (endDate) qs.set("end_date", endDate);
    return fetchJson<{
      x: string;
      y: string;
      lag_next_night: boolean;
      pearson_r: number | null;
      sample_size: number;
      points: Array<{
        health_date: string;
        is_cpap_era: boolean;
        x_val: number;
        y_val: number;
      }>;
    }>(`/api/dashboard/correlations?${qs.toString()}`);
  },
  getIntraday: (healthDate: string) =>
    fetchJson<{
      health_date: string;
      summary: DailyPerformanceRow;
      sleep_stages: Array<{
        sleep_stage_id: string;
        sleep_stage_type: string;
        sleep_stage_start: string;
        sleep_stage_end: string;
        local_start: string;
        local_end: string;
      }>;
      heart_rate_series: Array<{
        ts_utc: string;
        local_time: string;
        avg_bpm: number;
        min_bpm: number;
        max_bpm: number;
      }>;
      spo2_series: Array<{
        ts_utc: string;
        local_time: string;
        spo2_pct: number;
      }>;
    }>(`/api/dashboard/intraday/${encodeURIComponent(healthDate)}`),
  getSleepDoctorSummary: () =>
    fetchJson<{
      window_end_date: string | null;
      cpap_start_date: string;
      device_sn: string | null;
      last_7_days_summary: Record<string, number | null>;
      last_30_days_summary: Record<string, number | null>;
      best_30_summary: Record<string, string | number | null>;
      nightly_rows: Array<Record<string, unknown>>;
    }>("/api/reports/sleep-doctor"),
  chatAnalyst: (message: string, sessionId?: string) =>
    fetchJson<AnalystChatResponse>("/api/analyst/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ message, session_id: sessionId }),
    }),
  getSignedUrl: (payload: {
    source_type: string;
    relative_path: string;
    content_type: string;
    resumable: boolean;
    upload_batch_id?: string;
  }) =>
    fetchJson<{
      upload_url: string;
      method: string;
      mode: string;
      required_headers: Record<string, string>;
      gcs_path: string;
      gcs_uri: string;
      upload_batch_id: string;
    }>("/api/admin/uploads/signed-url", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    }),
  getBatchSignedUrls: (payload: {
    source_type: string;
    files: Array<{
      relative_path: string;
      content_type: string;
      resumable: boolean;
    }>;
    upload_batch_id?: string;
  }) =>
    fetchJson<{
      upload_batch_id: string;
      prefix: string;
      items: Array<{
        relative_path: string;
        upload_url: string;
        method: string;
        mode: string;
        required_headers: Record<string, string>;
        gcs_path: string;
      }>;
    }>("/api/admin/uploads/signed-urls-batch", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    }),
  previewReactHealthLocal: (file: File) => {
    const fd = new FormData();
    fd.append("file", file);
    return fetchJson<{
      metadata: Record<string, unknown>;
      valid_days_count: number;
      no_data_days_count: number;
      no_data_dates_sample: string[];
      daily_rows_preview: Array<Record<string, unknown>>;
      warnings: string[];
    }>("/api/admin/reacthealth/preview-local", {
      method: "POST",
      body: fd,
    });
  },
  triggerEtl: (payload: {
    mode: "existing_gcs" | "zip" | "prefix" | "reacthealth_pdf";
    prefixes?: string[];
    zip_gcs_path?: string;
    force_reload?: boolean;
  }) =>
    fetchJson<{ run_id: string; status: string; execution_target: string }>(
      "/api/admin/etl/trigger",
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      }
    ),
  listEtlRuns: () => fetchJson<{ runs: EtlRunRecord[] }>("/api/admin/etl/runs"),
  getEtlRun: (runId: string) =>
    fetchJson<EtlRunRecord>(`/api/admin/etl/runs/${encodeURIComponent(runId)}`),
  getLedger: () =>
    fetchJson<{
      sources: Array<Record<string, unknown>>;
      bronze_tables: Array<Record<string, unknown>>;
      coverage: Record<string, unknown>;
      recent_files: Array<Record<string, unknown>>;
    }>("/api/admin/ledger"),
  getSettings: () =>
    fetchJson<{
      setting_key: string;
      setting_value: string;
      auto_detected_value: string;
      is_manual_override: boolean;
      updated_at: string | null;
      updated_by: string;
    }>("/api/admin/settings"),
  updateCpapStartDate: (payload: {
    cpap_start_date?: string;
    use_auto_detected?: boolean;
  }) =>
    fetchJson<{
      setting_key: string;
      setting_value: string;
      auto_detected_value: string;
      is_manual_override: boolean;
      updated_at: string | null;
      updated_by: string;
    }>("/api/admin/settings/cpap-start-date", {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    }),
  getConnectors: () =>
    fetchJson<{
      connectors: Array<{
        name: string;
        display_name: string;
        supported_extensions: string[];
        expected_prefixes: string[];
        status: string;
        description: string;
      }>;
    }>("/api/admin/connectors"),
  getHabitsImpact: () =>
    fetchJson<{
      habits: HabitImpactRow[];
      baseline_notes: BaselineNoteRow[];
    }>("/api/dashboard/habits-impact"),
  getGSheetsStatus: () =>
    fetchJson<{
      spreadsheet_id: string;
      web_service_account: string;
      etl_service_account: string;
      observation_rows: number;
      baseline_note_rows: number;
      min_date: string | null;
      max_date: string | null;
    }>("/api/admin/gsheets/status"),
  syncGSheets: () =>
    fetchJson<{
      spreadsheet_id: string;
      run_id: string;
      observations: { staged: number; inserted: number; updated: number };
      baseline_notes: { staged: number; inserted: number; updated: number };
      dataform_status: string;
    }>("/api/admin/gsheets/sync", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ trigger_dataform: true }),
    }),
};
