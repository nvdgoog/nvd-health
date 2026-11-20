import React, { useEffect, useMemo, useState } from "react";
import {
  Activity,
  Calendar,
  HeartPulse,
  Moon,
  SlidersHorizontal,
  TrendingDown,
  TrendingUp,
} from "lucide-react";
import {
  Bar,
  BarChart,
  CartesianGrid,
  ComposedChart,
  Legend,
  Line,
  LineChart,
  ReferenceLine,
  ResponsiveContainer,
  Scatter,
  ScatterChart,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { api, type CpapImpactMetric, type DailyPerformanceRow } from "../api";
import { IntradayDrawer } from "../components/IntradayDrawer";
import { ModularExtensionWidgets } from "../components/ModularWidgets";

type RangePreset = "7D" | "30D" | "90D" | "YTD" | "ALL" | "CUSTOM";

const IMPACT_LABELS: Record<
  string,
  { label: string; unit: string; higherIsBetter: boolean }
> = {
  spo2_avg_pct: { label: "SpO2 Average", unit: "%", higherIsBetter: true },
  spo2_min_pct: { label: "SpO2 Minimum", unit: "%", higherIsBetter: true },
  resting_heart_rate: { label: "Resting HR", unit: " bpm", higherIsBetter: false },
  hrv_rmssd_ms: { label: "HRV (RMSSD)", unit: " ms", higherIsBetter: true },
  non_rem_hr_bpm: { label: "Non-REM HR", unit: " bpm", higherIsBetter: false },
  sleep_overall_score: { label: "Sleep Score", unit: "", higherIsBetter: true },
  deep_sleep_pct: { label: "Deep Sleep %", unit: "%", higherIsBetter: true },
  rem_sleep_pct: { label: "REM Sleep %", unit: "%", higherIsBetter: true },
  total_sleep_hours: { label: "Total Sleep", unit: "h", higherIsBetter: true },
  respiratory_rate_bpm: { label: "Resp Rate", unit: " br/m", higherIsBetter: false },
  readiness_score: { label: "Readiness", unit: "", higherIsBetter: true },
  stress_score: { label: "Stress Score", unit: "", higherIsBetter: true },
};

const CORR_OPTIONS = [
  { key: "active_zone_minutes", label: "Active Zone Minutes" },
  { key: "steps", label: "Daily Steps" },
  { key: "calories_burned", label: "Calories Burned" },
  { key: "cardio_acwr", label: "Cardio ACWR" },
  { key: "stress_score", label: "Stress Score" },
  { key: "readiness_score", label: "Readiness Score" },
  { key: "sleep_overall_score", label: "Sleep Score" },
  { key: "hrv_rmssd_ms", label: "HRV (RMSSD ms)" },
  { key: "resting_heart_rate", label: "Resting HR (bpm)" },
  { key: "spo2_avg_pct", label: "SpO2 Avg (%)" },
  { key: "deep_sleep_pct", label: "Deep Sleep (%)" },
  { key: "cpap_ahi", label: "CPAP AHI" },
  { key: "cpap_avg_leak", label: "CPAP Leak (L/min)" },
  { key: "cpap_usage_hours", label: "CPAP Hours" },
  { key: "morning_coffee_cups", label: "Morning Coffee (cups)" },
];

export const DashboardPage: React.FC = () => {
  const [preset, setPreset] = useState<RangePreset>("90D");
  const [customStart, setCustomStart] = useState("");
  const [customEnd, setCustomEnd] = useState("");
  const [showCpapMarker, setShowCpapMarker] = useState(true);

  const [allDays, setAllDays] = useState<DailyPerformanceRow[]>([]);
  const [cpapStartDate, setCpapStartDate] = useState("2026-10-13");
  const [impactMetrics, setImpactMetrics] = useState<CpapImpactMetric[]>([]);
  const [habitsImpact, setHabitsImpact] = useState<
    Array<{
      habit: string;
      active_days: number;
      active_sleep_score: number | null;
      other_sleep_score: number | null;
      active_deep_pct: number | null;
      other_deep_pct: number | null;
      active_hrv: number | null;
      other_hrv: number | null;
    }>
  >([]);
  const [loading, setLoading] = useState(true);
  const [selectedDate, setSelectedDate] = useState<string | null>(null);

  // Correlation Explorer
  const [corrX, setCorrX] = useState("active_zone_minutes");
  const [corrY, setCorrY] = useState("hrv_rmssd_ms");
  const [lagNextNight, setLagNextNight] = useState(true);
  const [corrResult, setCorrResult] = useState<{
    pearson_r: number | null;
    sample_size: number;
    points: Array<{
      health_date: string;
      is_cpap_era: boolean;
      x_val: number;
      y_val: number;
    }>;
  } | null>(null);

  useEffect(() => {
    setLoading(true);
    Promise.all([api.getOverview(), api.getCpapImpact(), api.getHabitsImpact()])
      .then(([ov, imp, hab]) => {
        setAllDays(ov.days);
        setCpapStartDate(ov.cpap_start_date);
        setImpactMetrics(imp.metrics);
        setHabitsImpact(hab.habits);
      })
      .finally(() => setLoading(false));
  }, []);

  const filteredDays = useMemo(() => {
    if (allDays.length === 0) return [];
    const latest = allDays[allDays.length - 1].health_date;
    const latestDt = new Date(`${latest}T00:00:00Z`);

    const cutoff = (daysBack: number) => {
      const d = new Date(latestDt);
      d.setUTCDate(d.getUTCDate() - (daysBack - 1));
      return d.toISOString().slice(0, 10);
    };

    let start = allDays[0].health_date;
    let end = latest;
    if (preset === "7D") start = cutoff(7);
    else if (preset === "30D") start = cutoff(30);
    else if (preset === "90D") start = cutoff(90);
    else if (preset === "YTD") start = `${latest.slice(0, 4)}-01-01`;
    else if (preset === "CUSTOM") {
      if (customStart) start = customStart;
      if (customEnd) end = customEnd;
    }

    return allDays
      .filter((d) => d.health_date >= start && d.health_date <= end)
      .map((d) => ({
        ...d,
        total_sleep_hours:
          d.total_sleep_minutes != null
            ? Number((d.total_sleep_minutes / 60).toFixed(2))
            : null,
      }));
  }, [allDays, preset, customStart, customEnd]);

  useEffect(() => {
    const start = filteredDays[0]?.health_date;
    const end = filteredDays[filteredDays.length - 1]?.health_date;
    api
      .getCorrelations(corrX, corrY, lagNextNight, start, end)
      .then(setCorrResult)
      .catch(() => setCorrResult(null));
  }, [corrX, corrY, lagNextNight, filteredDays]);

  const cpapDaysOnly = useMemo(
    () =>
      filteredDays.filter(
        (d) =>
          d.cpap_usage_hours != null ||
          d.cpap_ahi != null ||
          d.health_date >= cpapStartDate
      ),
    [filteredDays, cpapStartDate]
  );

  const breathingContext = impactMetrics[0];

  return (
    <div className="space-y-6">
      {/* Global Controls Header */}
      <div className="flex flex-wrap items-center justify-between gap-4 rounded-2xl border border-slate-200 dark:border-slate-800 bg-white dark:bg-slate-900 p-4">
        <div>
          <h1 className="text-xl font-bold text-slate-900 dark:text-white">
            Health Performance &amp; CPAP Therapy Analytics
          </h1>
          <p className="text-xs text-slate-500">
            Click any night on the sleep or CPAP charts to inspect intraday Bronze sleep stages, HR &amp; SpO2
          </p>
        </div>

        <div className="flex flex-wrap items-center gap-2">
          <div className="inline-flex rounded-xl border border-slate-200 dark:border-slate-700 p-0.5 bg-slate-50 dark:bg-slate-950">
            {(["7D", "30D", "90D", "YTD", "ALL", "CUSTOM"] as RangePreset[]).map(
              (p) => (
                <button
                  key={p}
                  onClick={() => setPreset(p)}
                  className={`px-2.5 py-1 text-xs font-medium rounded-lg transition ${
                    preset === p
                      ? "bg-sky-600 text-white"
                      : "text-slate-600 dark:text-slate-300 hover:bg-slate-200/60 dark:hover:bg-slate-800"
                  }`}
                >
                  {p}
                </button>
              )
            )}
          </div>

          {preset === "CUSTOM" && (
            <div className="flex items-center gap-1.5 text-xs">
              <Calendar className="w-3.5 h-3.5 text-slate-400" />
              <input
                type="date"
                value={customStart}
                onChange={(e) => setCustomStart(e.target.value)}
                className="rounded-lg border border-slate-300 dark:border-slate-700 bg-white dark:bg-slate-950 px-2 py-1"
              />
              <span>→</span>
              <input
                type="date"
                value={customEnd}
                onChange={(e) => setCustomEnd(e.target.value)}
                className="rounded-lg border border-slate-300 dark:border-slate-700 bg-white dark:bg-slate-950 px-2 py-1"
              />
            </div>
          )}

          <label className="inline-flex items-center gap-1.5 text-xs px-3 py-1.5 rounded-xl border border-slate-200 dark:border-slate-700 cursor-pointer">
            <input
              type="checkbox"
              checked={showCpapMarker}
              onChange={(e) => setShowCpapMarker(e.target.checked)}
              className="rounded border-slate-300"
            />
            CPAP Marker ({cpapStartDate})
          </label>
        </div>
      </div>

      {loading && (
        <div className="py-12 text-center text-sm text-slate-500">
          Loading Gold &amp; Silver health metrics...
        </div>
      )}

      {!loading && allDays.length === 0 && (
        <div className="rounded-2xl border border-amber-200 dark:border-amber-900 bg-amber-50/70 dark:bg-amber-950/30 p-6 text-sm text-amber-800 dark:text-amber-200">
          No conformed health data found in <code>nvd_health_gold</code> yet. Open the{" "}
          <b>Data Engineering &amp; Admin</b> tab and click{" "}
          <b>Run ETL on Existing GCS Prefix</b> to ingest{" "}
          <code>gs://nvd-health-raw-data</code>.
        </div>
      )}

      {/* Section 1: CPAP Impact ("Before vs. After") Panel */}
      {impactMetrics.length > 0 && (
        <section className="space-y-3">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <h2 className="text-base font-semibold flex items-center gap-2">
              <Activity className="w-4 h-4 text-sky-600" />
              CPAP Impact — Pre-CPAP Baseline vs. Post-CPAP Era ({cpapStartDate}+)
            </h2>
            {breathingContext && (
              <div className="text-xs text-slate-500">
                Optimal Breathing Nights: Pre{" "}
                <b>
                  {breathingContext.pre_optimal_breathing_days ?? 0}/
                  {breathingContext.pre_breathing_days ?? 0}
                </b>{" "}
                vs. Post{" "}
                <b>
                  {breathingContext.post_optimal_breathing_days ?? 0}/
                  {breathingContext.post_breathing_days ?? 0}
                </b>
              </div>
            )}
          </div>

          <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-6 gap-3">
            {impactMetrics.map((m) => {
              const meta = IMPACT_LABELS[m.metric_name] || {
                label: m.metric_name,
                unit: "",
                higherIsBetter: true,
              };
              const delta = m.mean_delta ?? 0;
              const improved = meta.higherIsBetter ? delta > 0 : delta < 0;
              return (
                <div
                  key={m.metric_name}
                  className="rounded-2xl border border-slate-200 dark:border-slate-800 bg-white dark:bg-slate-900 p-3.5 space-y-1.5"
                >
                  <div className="text-xs font-medium text-slate-500 truncate">
                    {meta.label}
                  </div>
                  <div className="flex items-baseline justify-between gap-1">
                    <span className="text-lg font-bold">
                      {m.post_mean != null
                        ? `${m.post_mean.toFixed(1)}${meta.unit}`
                        : "—"}
                    </span>
                    {m.mean_delta != null && (
                      <span
                        className={`inline-flex items-center gap-0.5 text-[11px] font-semibold px-1.5 py-0.5 rounded ${
                          improved
                            ? "bg-emerald-100 text-emerald-800 dark:bg-emerald-950 dark:text-emerald-300"
                            : "bg-amber-100 text-amber-800 dark:bg-amber-950 dark:text-amber-300"
                        }`}
                      >
                        {delta >= 0 ? (
                          <TrendingUp className="w-3 h-3" />
                        ) : (
                          <TrendingDown className="w-3 h-3" />
                        )}
                        {delta >= 0 ? `+${delta.toFixed(1)}` : delta.toFixed(1)}
                      </span>
                    )}
                  </div>
                  <div className="text-[11px] text-slate-400">
                    Pre: {m.pre_mean != null ? `${m.pre_mean.toFixed(1)}${meta.unit}` : "—"} (
                    {m.pre_days ?? 0}d) · Post ({m.post_days ?? 0}d)
                  </div>
                </div>
              );
            })}
          </div>
        </section>
      )}

      {/* Section 2: Intervention Trend + Sleep & CPAP Adherence */}
      {filteredDays.length > 0 && (
        <section className="grid grid-cols-1 lg:grid-cols-2 gap-5">
          {/* SpO2, HRV & RHR Trend with Intervention Line */}
          <div className="rounded-2xl border border-slate-200 dark:border-slate-800 bg-white dark:bg-slate-900 p-5">
            <h3 className="text-sm font-semibold mb-1">
              Cardiopulmonary Trend (SpO2, HRV &amp; Resting HR)
            </h3>
            <p className="text-xs text-slate-500 mb-3">
              Vertical marker indicates CPAP initiation ({cpapStartDate})
            </p>
            <div className="h-72 w-full">
              <ResponsiveContainer width="100%" height="100%">
                <LineChart
                  data={filteredDays}
                  onClick={(state) => {
                    if (state?.activeLabel) {
                      setSelectedDate(String(state.activeLabel));
                    }
                  }}
                >
                  <CartesianGrid strokeDasharray="3 3" strokeOpacity={0.2} />
                  <XAxis dataKey="health_date" tick={{ fontSize: 10 }} />
                  <YAxis yAxisId="left" domain={["auto", "auto"]} tick={{ fontSize: 11 }} />
                  <YAxis
                    yAxisId="right"
                    orientation="right"
                    domain={[85, 100]}
                    tick={{ fontSize: 11 }}
                  />
                  <Tooltip />
                  <Legend wrapperStyle={{ fontSize: 11 }} />
                  {showCpapMarker && (
                    <ReferenceLine
                      x={cpapStartDate}
                      yAxisId="left"
                      stroke="#dc2626"
                      strokeDasharray="4 4"
                      label={{ value: "CPAP Start", fontSize: 10, fill: "#dc2626" }}
                    />
                  )}
                  <Line
                    yAxisId="right"
                    type="monotone"
                    dataKey="spo2_avg_pct"
                    name="SpO2 Avg (%)"
                    stroke="#0284c7"
                    dot={false}
                    strokeWidth={2}
                  />
                  <Line
                    yAxisId="left"
                    type="monotone"
                    dataKey="hrv_rmssd_ms"
                    name="HRV RMSSD (ms)"
                    stroke="#10b981"
                    dot={false}
                    strokeWidth={2}
                  />
                  <Line
                    yAxisId="left"
                    type="monotone"
                    dataKey="resting_heart_rate"
                    name="Resting HR (bpm)"
                    stroke="#f43f5e"
                    dot={false}
                    strokeWidth={1.75}
                  />
                </LineChart>
              </ResponsiveContainer>
            </div>
          </div>

          {/* CPAP Hours vs Total Sleep Hours */}
          <div className="rounded-2xl border border-slate-200 dark:border-slate-800 bg-white dark:bg-slate-900 p-5">
            <h3 className="text-sm font-semibold mb-1">
              CPAP Usage vs. Total Sleep Duration (Mask-Off Gap Detector)
            </h3>
            <p className="text-xs text-slate-500 mb-3">
              4.0h compliance threshold dashed · Click any date to drill into intraday stages
            </p>
            <div className="h-72 w-full">
              <ResponsiveContainer width="100%" height="100%">
                <ComposedChart
                  data={cpapDaysOnly}
                  onClick={(state) => {
                    if (state?.activeLabel) {
                      setSelectedDate(String(state.activeLabel));
                    }
                  }}
                >
                  <CartesianGrid strokeDasharray="3 3" strokeOpacity={0.2} />
                  <XAxis dataKey="health_date" tick={{ fontSize: 10 }} />
                  <YAxis tick={{ fontSize: 11 }} unit="h" />
                  <Tooltip />
                  <Legend wrapperStyle={{ fontSize: 11 }} />
                  <ReferenceLine
                    y={4}
                    stroke="#059669"
                    strokeDasharray="4 4"
                    label={{ value: "4h Goal", fontSize: 10, fill: "#059669" }}
                  />
                  <Bar
                    dataKey="cpap_usage_hours"
                    name="CPAP Usage (hrs)"
                    fill="#0284c7"
                    radius={[4, 4, 0, 0]}
                  />
                  <Line
                    type="monotone"
                    dataKey="total_sleep_hours"
                    name="Google Total Sleep (hrs)"
                    stroke="#8b5cf6"
                    strokeWidth={2}
                    dot={false}
                  />
                </ComposedChart>
              </ResponsiveContainer>
            </div>
          </div>
        </section>
      )}

      {/* Section 3: Sleep Architecture + AHI vs Mask Leak */}
      {filteredDays.length > 0 && (
        <section className="grid grid-cols-1 lg:grid-cols-2 gap-5">
          {/* Sleep Architecture Stacked Bars */}
          <div className="rounded-2xl border border-slate-200 dark:border-slate-800 bg-white dark:bg-slate-900 p-5">
            <div className="flex items-center gap-2 mb-1">
              <Moon className="w-4 h-4 text-indigo-600" />
              <h3 className="text-sm font-semibold">
                Sleep Architecture (Deep / REM / Light / Awake Minutes)
              </h3>
            </div>
            <p className="text-xs text-slate-500 mb-3">
              Click any bar to inspect that night&apos;s UserSleepStages hypnogram
            </p>
            <div className="h-72 w-full">
              <ResponsiveContainer width="100%" height="100%">
                <BarChart
                  data={filteredDays}
                  onClick={(state) => {
                    if (state?.activeLabel) {
                      setSelectedDate(String(state.activeLabel));
                    }
                  }}
                >
                  <CartesianGrid strokeDasharray="3 3" strokeOpacity={0.2} />
                  <XAxis dataKey="health_date" tick={{ fontSize: 10 }} />
                  <YAxis tick={{ fontSize: 11 }} unit="m" />
                  <Tooltip />
                  <Legend wrapperStyle={{ fontSize: 11 }} />
                  <Bar dataKey="deep_sleep_minutes" stackId="a" name="Deep" fill="#1d4ed8" />
                  <Bar dataKey="rem_sleep_minutes" stackId="a" name="REM" fill="#7c3aed" />
                  <Bar dataKey="light_sleep_minutes" stackId="a" name="Light" fill="#38bdf8" />
                  <Bar
                    dataKey="sleep_stage_awake_minutes"
                    stackId="a"
                    name="Awake"
                    fill="#fb923c"
                  />
                </BarChart>
              </ResponsiveContainer>
            </div>
          </div>

          {/* AHI & CAI vs Pressure P95 & Mask Leak */}
          <div className="rounded-2xl border border-slate-200 dark:border-slate-800 bg-white dark:bg-slate-900 p-5">
            <div className="flex items-center gap-2 mb-1">
              <HeartPulse className="w-4 h-4 text-rose-500" />
              <h3 className="text-sm font-semibold">
                AHI &amp; CAI vs. Pressure P95 &amp; Mask Leak
              </h3>
            </div>
            <p className="text-xs text-slate-500 mb-3">
              Spot whether high mask leak nights correlate with elevated AHI
            </p>
            <div className="h-72 w-full">
              <ResponsiveContainer width="100%" height="100%">
                <ComposedChart data={cpapDaysOnly}>
                  <CartesianGrid strokeDasharray="3 3" strokeOpacity={0.2} />
                  <XAxis dataKey="health_date" tick={{ fontSize: 10 }} />
                  <YAxis yAxisId="left" tick={{ fontSize: 11 }} />
                  <YAxis yAxisId="right" orientation="right" tick={{ fontSize: 11 }} />
                  <Tooltip />
                  <Legend wrapperStyle={{ fontSize: 11 }} />
                  <Bar yAxisId="left" dataKey="cpap_ahi" name="AHI" fill="#ef4444" />
                  <Bar yAxisId="left" dataKey="cpap_cai" name="CAI" fill="#f97316" />
                  <Line
                    yAxisId="right"
                    type="monotone"
                    dataKey="cpap_avg_leak"
                    name="Avg Leak (L/min)"
                    stroke="#0284c7"
                    strokeWidth={2}
                  />
                  <Line
                    yAxisId="right"
                    type="monotone"
                    dataKey="cpap_p95_pressure"
                    name="P95 Pressure"
                    stroke="#10b981"
                    strokeWidth={1.75}
                  />
                </ComposedChart>
              </ResponsiveContainer>
            </div>
          </div>
        </section>
      )}

      {/* Section 4: Holistic Correlation Explorer & Recovery Trend */}
      {filteredDays.length > 0 && (
        <section className="grid grid-cols-1 lg:grid-cols-2 gap-5">
          {/* Interactive Correlation Explorer */}
          <div className="rounded-2xl border border-slate-200 dark:border-slate-800 bg-white dark:bg-slate-900 p-5 space-y-3">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <div className="flex items-center gap-2 font-semibold text-sm">
                <SlidersHorizontal className="w-4 h-4 text-sky-600" />
                Holistic Correlation Explorer
              </div>
              {corrResult && (
                <span className="text-xs px-2.5 py-1 rounded-full bg-slate-100 dark:bg-slate-800 font-mono">
                  r = {corrResult.pearson_r ?? "—"} (n={corrResult.sample_size})
                </span>
              )}
            </div>
            <div className="flex flex-wrap items-center gap-2 text-xs">
              <select
                value={corrX}
                onChange={(e) => setCorrX(e.target.value)}
                className="rounded-lg border border-slate-300 dark:border-slate-700 bg-white dark:bg-slate-950 px-2.5 py-1.5"
              >
                {CORR_OPTIONS.map((o) => (
                  <option key={o.key} value={o.key}>
                    X: {o.label}
                  </option>
                ))}
              </select>
              <select
                value={corrY}
                onChange={(e) => setCorrY(e.target.value)}
                className="rounded-lg border border-slate-300 dark:border-slate-700 bg-white dark:bg-slate-950 px-2.5 py-1.5"
              >
                {CORR_OPTIONS.map((o) => (
                  <option key={o.key} value={o.key}>
                    Y: {o.label}
                  </option>
                ))}
              </select>
              <label className="inline-flex items-center gap-1.5">
                <input
                  type="checkbox"
                  checked={lagNextNight}
                  onChange={(e) => setLagNextNight(e.target.checked)}
                />
                Next-Night Lag
              </label>
            </div>
            <div className="h-64 w-full">
              <ResponsiveContainer width="100%" height="100%">
                <ScatterChart>
                  <CartesianGrid strokeDasharray="3 3" strokeOpacity={0.2} />
                  <XAxis type="number" dataKey="x_val" name={corrX} tick={{ fontSize: 11 }} />
                  <YAxis type="number" dataKey="y_val" name={corrY} tick={{ fontSize: 11 }} />
                  <Tooltip cursor={{ strokeDasharray: "3 3" }} />
                  <Legend wrapperStyle={{ fontSize: 11 }} />
                  <Scatter
                    name="Pre-CPAP"
                    data={(corrResult?.points || []).filter((p) => !p.is_cpap_era)}
                    fill="#94a3b8"
                  />
                  <Scatter
                    name="Post-CPAP"
                    data={(corrResult?.points || []).filter((p) => p.is_cpap_era)}
                    fill="#0284c7"
                  />
                </ScatterChart>
              </ResponsiveContainer>
            </div>
          </div>

          {/* Recovery & Readiness Trends */}
          <div className="rounded-2xl border border-slate-200 dark:border-slate-800 bg-white dark:bg-slate-900 p-5 space-y-3">
            <h3 className="text-sm font-semibold">
              Readiness, Stress Score &amp; Respiratory Rate Trend
            </h3>
            <div className="h-72 w-full">
              <ResponsiveContainer width="100%" height="100%">
                <LineChart data={filteredDays}>
                  <CartesianGrid strokeDasharray="3 3" strokeOpacity={0.2} />
                  <XAxis dataKey="health_date" tick={{ fontSize: 10 }} />
                  <YAxis yAxisId="left" tick={{ fontSize: 11 }} />
                  <YAxis yAxisId="right" orientation="right" tick={{ fontSize: 11 }} />
                  <Tooltip />
                  <Legend wrapperStyle={{ fontSize: 11 }} />
                  {showCpapMarker && (
                    <ReferenceLine
                      x={cpapStartDate}
                      yAxisId="left"
                      stroke="#dc2626"
                      strokeDasharray="4 4"
                    />
                  )}
                  <Line
                    yAxisId="left"
                    type="monotone"
                    dataKey="readiness_score"
                    name="Readiness"
                    stroke="#10b981"
                    dot={false}
                    strokeWidth={2}
                  />
                  <Line
                    yAxisId="left"
                    type="monotone"
                    dataKey="stress_score"
                    name="Stress Score"
                    stroke="#f59e0b"
                    dot={false}
                    strokeWidth={2}
                  />
                  <Line
                    yAxisId="right"
                    type="monotone"
                    dataKey="respiratory_rate_bpm"
                    name="Resp Rate (br/m)"
                    stroke="#6366f1"
                    dot={false}
                    strokeWidth={1.75}
                  />
                </LineChart>
              </ResponsiveContainer>
            </div>
          </div>
        </section>
      )}

      {/* Section 5: Journal Habits Impact + Extensible Modular Widgets */}
      {habitsImpact.some((h) => h.active_days > 0) && (
        <section className="rounded-2xl border border-slate-200 dark:border-slate-800 bg-white dark:bg-slate-900 p-5 space-y-3">
          <div>
            <h3 className="text-sm font-semibold">
              Daily Activities &amp; Habits Impact (From Google Sheet Journal)
            </h3>
            <p className="text-xs text-slate-500">
              Comparing nights following each logged activity against non-activity nights (click any chart date to read your wake-up notes)
            </p>
          </div>
          <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
            {habitsImpact.map((h) => (
              <div
                key={h.habit}
                className="rounded-xl border border-slate-200 dark:border-slate-800 bg-slate-50/70 dark:bg-slate-800/50 p-4 text-xs space-y-1.5"
              >
                <div className="flex items-center justify-between">
                  <span className="font-semibold text-sm">{h.habit}</span>
                  <span className="px-2 py-0.5 rounded-full bg-sky-100 text-sky-800 dark:bg-sky-950 dark:text-sky-300 font-medium">
                    {h.active_days} nights
                  </span>
                </div>
                <div className="flex justify-between">
                  <span className="text-slate-500">Sleep Score:</span>
                  <span>
                    <b>{h.active_sleep_score ?? "—"}</b> vs. {h.other_sleep_score ?? "—"}
                  </span>
                </div>
                <div className="flex justify-between">
                  <span className="text-slate-500">Deep Sleep %:</span>
                  <span>
                    <b>{h.active_deep_pct ?? "—"}%</b> vs. {h.other_deep_pct ?? "—"}%
                  </span>
                </div>
                <div className="flex justify-between">
                  <span className="text-slate-500">HRV (RMSSD):</span>
                  <span>
                    <b>{h.active_hrv ?? "—"} ms</b> vs. {h.other_hrv ?? "—"} ms
                  </span>
                </div>
              </div>
            ))}
          </div>
        </section>
      )}

      <ModularExtensionWidgets days={filteredDays} />

      {/* Bronze Intraday Drill-Down Drawer */}
      <IntradayDrawer
        healthDate={selectedDate}
        onClose={() => setSelectedDate(null)}
      />
    </div>
  );
};
