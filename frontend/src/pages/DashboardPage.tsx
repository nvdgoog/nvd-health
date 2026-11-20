import React, { useEffect, useMemo, useState } from "react";
import {
  Activity,
  BookOpen,
  Calendar,
  ChevronDown,
  ChevronUp,
  Coffee,
  HeartPulse,
  Moon,
  Search,
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
import {
  api,
  type BaselineNoteRow,
  type CpapImpactMetric,
  type DailyPerformanceRow,
  type HabitImpactRow,
} from "../api";
import { IntradayDrawer } from "../components/IntradayDrawer";
import { ModularExtensionWidgets } from "../components/ModularWidgets";

interface JournalTooltipProps {
  active?: boolean;
  label?: string | number;
  payload?: Array<{
    name?: string;
    value?: number | string | null;
    color?: string;
    payload?: DailyPerformanceRow;
  }>;
}

const JournalAwareTooltip: React.FC<JournalTooltipProps> = ({
  active,
  label,
  payload,
}) => {
  if (!active || !payload || payload.length === 0) return null;
  const row = payload[0]?.payload;
  return (
    <div className="max-w-xs rounded-xl border border-slate-200 dark:border-slate-700 bg-white/95 dark:bg-slate-900/95 px-3 py-2.5 shadow-lg text-[11px] space-y-1.5 backdrop-blur">
      <div className="font-mono font-semibold text-slate-900 dark:text-white border-b border-slate-100 dark:border-slate-800 pb-1">
        {String(label || row?.health_date || "")}
      </div>
      <div className="space-y-0.5">
        {payload.map((entry, idx) => (
          <div key={idx} className="flex items-center justify-between gap-3">
            <span className="flex items-center gap-1.5 text-slate-600 dark:text-slate-300">
              <span
                className="w-2 h-2 rounded-full shrink-0"
                style={{ backgroundColor: entry.color || "#0284c7" }}
              />
              {entry.name}:
            </span>
            <span className="font-semibold text-slate-900 dark:text-white">
              {entry.value != null
                ? typeof entry.value === "number"
                  ? Number.isInteger(entry.value)
                    ? String(entry.value)
                    : entry.value.toFixed(1)
                  : String(entry.value)
                : "—"}
            </span>
          </div>
        ))}
      </div>
      {row &&
        (row.activity_notes ||
          row.morning_coffee_cups != null ||
          row.wake_up_observations) && (
          <div className="border-t border-slate-100 dark:border-slate-800 pt-1.5 space-y-0.5 text-[10px]">
            {row.morning_coffee_cups != null && (
              <div className="text-amber-700 dark:text-amber-300">
                <b>Coffee:</b> {row.morning_coffee_cups} cups
              </div>
            )}
            {row.activity_notes && (
              <div className="text-sky-700 dark:text-sky-300 line-clamp-2">
                <b>Activities:</b> {row.activity_notes}
              </div>
            )}
            {row.wake_up_observations && (
              <div className="text-slate-500 dark:text-slate-400 line-clamp-2">
                <b>Wake-up:</b> {row.wake_up_observations}
              </div>
            )}
          </div>
        )}
    </div>
  );
};

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
  const [habitsImpact, setHabitsImpact] = useState<HabitImpactRow[]>([]);
  const [baselineNotes, setBaselineNotes] = useState<BaselineNoteRow[]>([]);
  const [showBaseline, setShowBaseline] = useState(false);
  const [journalQuery, setJournalQuery] = useState("");
  const [journalFilter, setJournalFilter] = useState<string>("all");
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
        setBaselineNotes(hab.baseline_notes || []);
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

  const journalRows = useMemo(() => {
    const q = journalQuery.trim().toLowerCase();
    return [...filteredDays]
      .filter(
        (d) =>
          Boolean(d.activity_notes) ||
          Boolean(d.wake_up_observations) ||
          d.morning_coffee_cups != null
      )
      .filter((d) => {
        if (journalFilter === "crossfit") return Boolean(d.has_crossfit_wod);
        if (journalFilter === "cold_plunge") return Boolean(d.has_cold_plunge);
        if (journalFilter === "dry_sauna") return Boolean(d.has_dry_sauna);
        if (journalFilter === "alcohol") return Boolean(d.has_alcohol);
        if (journalFilter === "late_dinner") return Boolean(d.has_late_dinner);
        if (journalFilter === "nap") return Boolean(d.has_daytime_nap);
        if (journalFilter === "coffee_3plus")
          return (d.morning_coffee_cups ?? 0) >= 3;
        return true;
      })
      .filter((d) => {
        if (!q) return true;
        return (
          d.health_date.toLowerCase().includes(q) ||
          (d.activity_notes || "").toLowerCase().includes(q) ||
          (d.wake_up_observations || "").toLowerCase().includes(q)
        );
      })
      .reverse();
  }, [filteredDays, journalFilter, journalQuery]);

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
                  <Tooltip content={<JournalAwareTooltip />} />
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
                  <Tooltip content={<JournalAwareTooltip />} />
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
                  <Tooltip content={<JournalAwareTooltip />} />
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
                  <Tooltip content={<JournalAwareTooltip />} />
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
                  <Tooltip content={<JournalAwareTooltip />} />
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

      {/* Section 5: Journal Habits Impact, Baseline Protocol & Searchable Activity Log */}
      {(habitsImpact.some((h) => h.active_days > 0) ||
        baselineNotes.length > 0 ||
        journalRows.length > 0 ||
        journalQuery !== "" ||
        journalFilter !== "all") && (
        <section className="space-y-5">
          {habitsImpact.some((h) => h.active_days > 0) && (
            <div className="rounded-2xl border border-slate-200 dark:border-slate-800 bg-white dark:bg-slate-900 p-5 space-y-4">
              <div className="flex flex-wrap items-center justify-between gap-2">
                <div>
                  <h3 className="text-sm font-semibold">
                    Daily Activities &amp; Habits Impact (From Google Sheet Journal)
                  </h3>
                  <p className="text-xs text-slate-500">
                    Comparing logged habit/trigger nights vs. non-habit nights across sleep, autonomic recovery, and CPAP AHI. Click any card to filter the journal table below.
                  </p>
                </div>
                {baselineNotes.length > 0 && (
                  <button
                    onClick={() => setShowBaseline((v) => !v)}
                    className="inline-flex items-center gap-1.5 text-xs px-3 py-1.5 rounded-xl border border-slate-200 dark:border-slate-700 hover:bg-slate-50 dark:hover:bg-slate-800 font-medium"
                  >
                    <BookOpen className="w-3.5 h-3.5 text-indigo-600" />
                    Baseline Routines ({baselineNotes.length})
                    {showBaseline ? (
                      <ChevronUp className="w-3.5 h-3.5" />
                    ) : (
                      <ChevronDown className="w-3.5 h-3.5" />
                    )}
                  </button>
                )}
              </div>

              {showBaseline && baselineNotes.length > 0 && (
                <div className="rounded-xl border border-indigo-200/80 dark:border-indigo-900/60 bg-indigo-50/50 dark:bg-indigo-950/20 p-3.5">
                  <div className="text-[11px] font-semibold text-indigo-900 dark:text-indigo-200 mb-2">
                    Active Baseline Protocol &amp; Regular Routines (Notes Tab)
                  </div>
                  <div className="flex flex-wrap gap-1.5">
                    {baselineNotes.map((n, idx) => (
                      <span
                        key={idx}
                        className="inline-block rounded-lg bg-white dark:bg-slate-900 border border-indigo-100 dark:border-indigo-900/60 px-2.5 py-1 text-[11px] text-slate-700 dark:text-slate-200"
                      >
                        {n.note_text}
                      </span>
                    ))}
                  </div>
                </div>
              )}

              <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-3.5">
                {habitsImpact
                  .filter((h) => h.active_days > 0)
                  .map((h) => {
                    const selected = journalFilter === h.habit_key;
                    const rows: Array<{
                      label: string;
                      a: number | null;
                      b: number | null;
                      unit: string;
                      higherBetter: boolean;
                    }> = [
                      {
                        label: "Sleep Score",
                        a: h.active_sleep_score,
                        b: h.other_sleep_score,
                        unit: " pts",
                        higherBetter: true,
                      },
                      {
                        label: "Deep Sleep %",
                        a: h.active_deep_pct,
                        b: h.other_deep_pct,
                        unit: "%",
                        higherBetter: true,
                      },
                      {
                        label: "HRV (RMSSD)",
                        a: h.active_hrv,
                        b: h.other_hrv,
                        unit: " ms",
                        higherBetter: true,
                      },
                      {
                        label: "Resting HR",
                        a: h.active_rhr,
                        b: h.other_rhr,
                        unit: " bpm",
                        higherBetter: false,
                      },
                      {
                        label: "Readiness",
                        a: h.active_readiness,
                        b: h.other_readiness,
                        unit: " pts",
                        higherBetter: true,
                      },
                      {
                        label: "CPAP AHI",
                        a: h.active_ahi,
                        b: h.other_ahi,
                        unit: " ev/hr",
                        higherBetter: false,
                      },
                    ];
                    return (
                      <button
                        key={h.habit_key}
                        type="button"
                        onClick={() =>
                          setJournalFilter((prev) =>
                            prev === h.habit_key ? "all" : h.habit_key
                          )
                        }
                        className={`text-left rounded-xl border p-3.5 text-xs space-y-1.5 transition ${
                          selected
                            ? "border-sky-500 bg-sky-50/70 dark:bg-sky-950/30 ring-1 ring-sky-500"
                            : "border-slate-200 dark:border-slate-800 bg-slate-50/70 dark:bg-slate-800/50 hover:border-slate-300 dark:hover:border-slate-700"
                        }`}
                      >
                        <div className="flex items-center justify-between gap-2 pb-0.5">
                          <span className="font-semibold text-sm text-slate-900 dark:text-white">
                            {h.habit}
                          </span>
                          <span className="px-2 py-0.5 rounded-full bg-sky-100 text-sky-800 dark:bg-sky-950 dark:text-sky-300 font-medium">
                            {h.active_days} nights
                          </span>
                        </div>
                        {rows.map((r) => {
                          const hasBoth = r.a != null && r.b != null;
                          const better = hasBoth
                            ? r.higherBetter
                              ? (r.a as number) >= (r.b as number)
                              : (r.a as number) <= (r.b as number)
                            : null;
                          return (
                            <div
                              key={r.label}
                              className="flex items-center justify-between gap-2"
                            >
                              <span className="text-slate-500">{r.label}:</span>
                              <span className="tabular-nums">
                                <b
                                  className={
                                    better === true
                                      ? "text-emerald-600 dark:text-emerald-400"
                                      : better === false
                                      ? "text-amber-600 dark:text-amber-400"
                                      : ""
                                  }
                                >
                                  {r.a != null ? `${r.a}${r.unit}` : "—"}
                                </b>{" "}
                                <span className="text-slate-400">
                                  vs. {r.b != null ? `${r.b}${r.unit}` : "—"}
                                </span>
                              </span>
                            </div>
                          );
                        })}
                      </button>
                    );
                  })}
              </div>
            </div>
          )}

          {/* Filterable Nightly Activity & Wake-Up Journal Table */}
          <div className="rounded-2xl border border-slate-200 dark:border-slate-800 bg-white dark:bg-slate-900 p-5 space-y-3">
            <div className="flex flex-wrap items-center justify-between gap-3">
              <div>
                <h3 className="text-sm font-semibold">
                  Nightly Activity &amp; Wake-Up Journal ({journalRows.length} nights)
                </h3>
                <p className="text-xs text-slate-500">
                  Filter by keyword (e.g. &quot;groggy&quot;, &quot;stuffy&quot;, &quot;late dinner&quot;) or click any night to open intraday sleep &amp; SpO2
                </p>
              </div>
              <div className="flex flex-wrap items-center gap-2">
                <div className="relative">
                  <Search className="w-3.5 h-3.5 text-slate-400 absolute left-2.5 top-1/2 -translate-y-1/2" />
                  <input
                    type="text"
                    value={journalQuery}
                    onChange={(e) => setJournalQuery(e.target.value)}
                    placeholder="Search notes or date..."
                    className="pl-8 pr-3 py-1.5 text-xs rounded-xl border border-slate-200 dark:border-slate-700 bg-slate-50 dark:bg-slate-950 focus:outline-none focus:ring-1 focus:ring-sky-500"
                  />
                </div>
                {journalFilter !== "all" && (
                  <button
                    onClick={() => setJournalFilter("all")}
                    className="text-xs px-2.5 py-1.5 rounded-xl bg-sky-100 text-sky-800 dark:bg-sky-950 dark:text-sky-300 font-medium"
                  >
                    Clear filter
                  </button>
                )}
              </div>
            </div>

            {journalRows.length === 0 ? (
              <div className="py-6 text-center text-xs text-slate-500">
                No journal entries match your current date range or filter.
              </div>
            ) : (
              <div className="overflow-x-auto max-h-96 overflow-y-auto">
                <table className="w-full text-xs text-left border-collapse">
                  <thead className="sticky top-0 bg-white dark:bg-slate-900 z-10">
                    <tr className="border-b border-slate-200 dark:border-slate-800 text-slate-500">
                      <th className="py-2 pr-3">Date</th>
                      <th className="py-2 pr-3 whitespace-nowrap">Coffee (cups)</th>
                      <th className="py-2 pr-3 min-w-[210px]">Prior-Day Activities</th>
                      <th className="py-2 pr-3 min-w-[240px]">Wake-Up Observations</th>
                      <th className="py-2 pr-3 text-right whitespace-nowrap">Sleep Score (pts)</th>
                      <th className="py-2 pr-3 text-right whitespace-nowrap">HRV (ms)</th>
                      <th className="py-2 pr-3 text-right whitespace-nowrap">RHR (bpm)</th>
                      <th className="py-2 text-right whitespace-nowrap">CPAP AHI (ev/hr)</th>
                    </tr>
                  </thead>
                  <tbody>
                    {journalRows.map((d) => (
                      <tr
                        key={d.health_date}
                        onClick={() => setSelectedDate(d.health_date)}
                        className="border-b border-slate-100 dark:border-slate-800/60 hover:bg-sky-50/60 dark:hover:bg-slate-800/60 cursor-pointer transition align-top"
                      >
                        <td className="py-2 pr-3 font-mono font-medium whitespace-nowrap">
                          {d.health_date}
                        </td>
                        <td className="py-2 pr-3 whitespace-nowrap">
                          {d.morning_coffee_cups != null ? (
                            <span className="inline-flex items-center gap-1 px-1.5 py-0.5 rounded bg-amber-50 dark:bg-amber-950/40 text-amber-800 dark:text-amber-300">
                              <Coffee className="w-3 h-3" />
                              {d.morning_coffee_cups}
                            </span>
                          ) : (
                            "—"
                          )}
                        </td>
                        <td className="py-2 pr-3 text-slate-700 dark:text-slate-200">
                          {d.activity_notes || "—"}
                        </td>
                        <td className="py-2 pr-3 text-slate-600 dark:text-slate-300">
                          {d.wake_up_observations || "—"}
                        </td>
                        <td className="py-2 pr-3 text-right font-semibold tabular-nums">
                          {d.sleep_overall_score != null
                            ? d.sleep_overall_score.toFixed(1)
                            : "—"}
                        </td>
                        <td className="py-2 pr-3 text-right tabular-nums">
                          {d.hrv_rmssd_ms != null
                            ? `${Math.round(d.hrv_rmssd_ms)}`
                            : "—"}
                        </td>
                        <td className="py-2 pr-3 text-right tabular-nums">
                          {d.resting_heart_rate != null
                            ? `${Math.round(d.resting_heart_rate)}`
                            : "—"}
                        </td>
                        <td className="py-2 text-right tabular-nums">
                          {d.cpap_ahi != null ? d.cpap_ahi.toFixed(1) : "—"}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
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
