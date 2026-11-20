import React, { useEffect, useState } from "react";
import { X, Moon, HeartPulse, Activity } from "lucide-react";
import {
  Area,
  AreaChart,
  CartesianGrid,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { api, type DailyPerformanceRow } from "../api";

interface IntradayDrawerProps {
  healthDate: string | null;
  onClose: () => void;
}

const STAGE_COLOR: Record<string, string> = {
  DEEP: "#1d4ed8",
  REM: "#7c3aed",
  LIGHT: "#38bdf8",
  WAKE: "#f97316",
  AWAKE: "#f97316",
};

export const IntradayDrawer: React.FC<IntradayDrawerProps> = ({
  healthDate,
  onClose,
}) => {
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [data, setData] = useState<{
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
      local_time: string;
      avg_bpm: number;
      min_bpm: number;
      max_bpm: number;
    }>;
    spo2_series: Array<{
      local_time: string;
      spo2_pct: number;
    }>;
  } | null>(null);

  useEffect(() => {
    if (!healthDate) return;
    let active = true;
    setLoading(true);
    setError(null);
    api
      .getIntraday(healthDate)
      .then((res) => {
        if (active) setData(res);
      })
      .catch((err: Error) => {
        if (active) setError(err.message);
      })
      .finally(() => {
        if (active) setLoading(false);
      });
    return () => {
      active = false;
    };
  }, [healthDate]);

  if (!healthDate) return null;

  const stages = data?.sleep_stages || [];
  const totalStageDurationMs = stages.reduce((acc, s) => {
    const dt =
      new Date(s.sleep_stage_end).getTime() -
      new Date(s.sleep_stage_start).getTime();
    return acc + Math.max(0, dt);
  }, 0);

  return (
    <div className="fixed inset-0 z-50 flex justify-end bg-slate-900/40 backdrop-blur-sm no-print">
      <div className="w-full max-w-3xl bg-white dark:bg-slate-900 h-full shadow-2xl overflow-y-auto p-6 border-l border-slate-200 dark:border-slate-800">
        <div className="flex items-center justify-between pb-4 border-b border-slate-200 dark:border-slate-800">
          <div>
            <p className="text-xs font-medium uppercase tracking-wider text-sky-600 dark:text-sky-400">
              Bronze Intraday Drill-Down (America/Los_Angeles)
            </p>
            <h2 className="text-xl font-bold text-slate-900 dark:text-white">
              Night of {healthDate}
            </h2>
          </div>
          <button
            onClick={onClose}
            className="p-2 rounded-lg hover:bg-slate-100 dark:hover:bg-slate-800 text-slate-500"
            aria-label="Close drilldown"
          >
            <X className="w-5 h-5" />
          </button>
        </div>

        {loading && (
          <div className="py-12 text-center text-sm text-slate-500">
            Querying Bronze sleep stages, heart rate &amp; SpO2 curves...
          </div>
        )}
        {error && (
          <div className="mt-4 rounded-lg bg-rose-50 dark:bg-rose-950/40 border border-rose-200 dark:border-rose-800 p-4 text-sm text-rose-700 dark:text-rose-300">
            {error}
          </div>
        )}

        {!loading && data && (
          <div className="mt-5 space-y-6">
            {/* Nightly Summary Strip */}
            <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
              <div className="rounded-lg bg-slate-50 dark:bg-slate-800/60 p-3">
                <div className="text-xs text-slate-500">CPAP Usage / AHI</div>
                <div className="text-base font-semibold">
                  {data.summary.cpap_usage_hours != null
                    ? `${data.summary.cpap_usage_hours.toFixed(2)}h`
                    : "—"}{" "}
                  /{" "}
                  {data.summary.cpap_ahi != null
                    ? data.summary.cpap_ahi.toFixed(1)
                    : "—"}
                </div>
              </div>
              <div className="rounded-lg bg-slate-50 dark:bg-slate-800/60 p-3">
                <div className="text-xs text-slate-500">Total Sleep / Score</div>
                <div className="text-base font-semibold">
                  {data.summary.total_sleep_minutes != null
                    ? `${(data.summary.total_sleep_minutes / 60).toFixed(2)}h`
                    : "—"}{" "}
                  /{" "}
                  {data.summary.sleep_overall_score != null
                    ? Math.round(data.summary.sleep_overall_score)
                    : "—"}
                </div>
              </div>
              <div className="rounded-lg bg-slate-50 dark:bg-slate-800/60 p-3">
                <div className="text-xs text-slate-500">Nocturnal HR Avg</div>
                <div className="text-base font-semibold">
                  {data.summary.nocturnal_hr_avg != null
                    ? `${data.summary.nocturnal_hr_avg.toFixed(1)} bpm`
                    : "—"}
                </div>
              </div>
              <div className="rounded-lg bg-slate-50 dark:bg-slate-800/60 p-3">
                <div className="text-xs text-slate-500">SpO2 Avg / Min</div>
                <div className="text-base font-semibold">
                  {data.summary.spo2_avg_pct != null
                    ? `${data.summary.spo2_avg_pct.toFixed(1)}%`
                    : "—"}{" "}
                  /{" "}
                  {data.summary.spo2_min_pct != null
                    ? `${data.summary.spo2_min_pct.toFixed(1)}%`
                    : "—"}
                </div>
              </div>
            </div>

            {(data.summary.activity_notes ||
              data.summary.wake_up_observations ||
              data.summary.morning_coffee_cups != null) && (
              <div className="rounded-xl border border-amber-200 dark:border-amber-900/60 bg-amber-50/50 dark:bg-amber-950/20 p-4 space-y-2 text-xs">
                <div className="font-semibold text-amber-900 dark:text-amber-300">
                  Journal &amp; Wake-Up Observations
                </div>
                {data.summary.activity_notes && (
                  <div>
                    <span className="text-slate-500">Day-Before Activities:</span>{" "}
                    <span className="font-medium text-slate-800 dark:text-slate-100">
                      {data.summary.activity_notes}
                    </span>
                  </div>
                )}
                {data.summary.morning_coffee_cups != null && (
                  <div>
                    <span className="text-slate-500">Morning Coffee:</span>{" "}
                    <span className="font-medium text-slate-800 dark:text-slate-100">
                      {data.summary.morning_coffee_cups} cups
                    </span>
                  </div>
                )}
                {data.summary.wake_up_observations && (
                  <div>
                    <span className="text-slate-500">Wake-Up Notes:</span>{" "}
                    <span className="text-slate-800 dark:text-slate-100">
                      {data.summary.wake_up_observations}
                    </span>
                  </div>
                )}
              </div>
            )}

            {/* Hypnogram Timeline */}
            <div className="rounded-xl border border-slate-200 dark:border-slate-800 p-4">
              <div className="flex items-center justify-between mb-3">
                <div className="flex items-center gap-2 font-semibold text-sm">
                  <Moon className="w-4 h-4 text-indigo-600" />
                  Sleep Architecture Hypnogram (UserSleepStages)
                </div>
                <div className="flex gap-3 text-xs">
                  {["DEEP", "REM", "LIGHT", "WAKE"].map((st) => (
                    <span key={st} className="flex items-center gap-1">
                      <span
                        className="w-2.5 h-2.5 rounded-sm inline-block"
                        style={{ backgroundColor: STAGE_COLOR[st] }}
                      />
                      {st}
                    </span>
                  ))}
                </div>
              </div>
              {stages.length === 0 ? (
                <p className="text-xs text-slate-500 py-4">
                  No stage-level intervals recorded for this date.
                </p>
              ) : (
                <div className="space-y-2">
                  <div className="flex w-full h-10 rounded-md overflow-hidden bg-slate-100 dark:bg-slate-800">
                    {stages.map((s) => {
                      const ms = Math.max(
                        0,
                        new Date(s.sleep_stage_end).getTime() -
                          new Date(s.sleep_stage_start).getTime()
                      );
                      const pct =
                        totalStageDurationMs > 0
                          ? (ms / totalStageDurationMs) * 100
                          : 0;
                      const stKey = s.sleep_stage_type.toUpperCase();
                      return (
                        <div
                          key={s.sleep_stage_id}
                          style={{
                            width: `${pct}%`,
                            backgroundColor: STAGE_COLOR[stKey] || "#94a3b8",
                          }}
                          title={`${stKey}: ${s.local_start} → ${s.local_end}`}
                          className="h-full transition-opacity hover:opacity-80"
                        />
                      );
                    })}
                  </div>
                  <div className="flex justify-between text-[11px] text-slate-500">
                    <span>{stages[0]?.local_start}</span>
                    <span>{stages[stages.length - 1]?.local_end}</span>
                  </div>
                </div>
              )}
            </div>

            {/* Nocturnal Heart Rate Curve */}
            <div className="rounded-xl border border-slate-200 dark:border-slate-800 p-4">
              <div className="flex items-center gap-2 font-semibold text-sm mb-3">
                <HeartPulse className="w-4 h-4 text-rose-500" />
                Nocturnal Heart Rate Curve (1-min binned from Bronze)
              </div>
              {data.heart_rate_series.length === 0 ? (
                <p className="text-xs text-slate-500 py-4">
                  No intraday heart rate samples in this sleep window.
                </p>
              ) : (
                <div className="h-56 w-full">
                  <ResponsiveContainer width="100%" height="100%">
                    <AreaChart data={data.heart_rate_series}>
                      <CartesianGrid strokeDasharray="3 3" strokeOpacity={0.2} />
                      <XAxis
                        dataKey="local_time"
                        tick={{ fontSize: 10 }}
                        tickFormatter={(v) => String(v).slice(11, 16)}
                      />
                      <YAxis domain={["auto", "auto"]} tick={{ fontSize: 11 }} />
                      <Tooltip />
                      <Area
                        type="monotone"
                        dataKey="avg_bpm"
                        name="Avg BPM"
                        stroke="#e11d48"
                        fill="#fecdd3"
                        fillOpacity={0.35}
                      />
                    </AreaChart>
                  </ResponsiveContainer>
                </div>
              )}
            </div>

            {/* Nocturnal SpO2 Curve */}
            <div className="rounded-xl border border-slate-200 dark:border-slate-800 p-4">
              <div className="flex items-center gap-2 font-semibold text-sm mb-3">
                <Activity className="w-4 h-4 text-sky-600" />
                Nocturnal Oxygen Saturation (SpO2 %)
              </div>
              {data.spo2_series.length === 0 ? (
                <p className="text-xs text-slate-500 py-4">
                  No intraday SpO2 curve samples for this night (daily SpO2 summary still available above).
                </p>
              ) : (
                <div className="h-48 w-full">
                  <ResponsiveContainer width="100%" height="100%">
                    <LineChart data={data.spo2_series}>
                      <CartesianGrid strokeDasharray="3 3" strokeOpacity={0.2} />
                      <XAxis
                        dataKey="local_time"
                        tick={{ fontSize: 10 }}
                        tickFormatter={(v) => String(v).slice(11, 16)}
                      />
                      <YAxis domain={[85, 100]} tick={{ fontSize: 11 }} />
                      <Tooltip />
                      <Line
                        type="monotone"
                        dataKey="spo2_pct"
                        name="SpO2 %"
                        stroke="#0284c7"
                        strokeWidth={2}
                        dot={false}
                      />
                    </LineChart>
                  </ResponsiveContainer>
                </div>
              )}
            </div>
          </div>
        )}
      </div>
    </div>
  );
};
