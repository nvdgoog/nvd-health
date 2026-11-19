import React, { useEffect, useState } from "react";
import { Download, Printer, Stethoscope, CheckCircle2, AlertCircle } from "lucide-react";
import { api } from "../api";

const fmtNum = (val: unknown, suffix = "", decimals = 1): string => {
  if (val == null || val === "") return "—";
  const num = Number(val);
  if (Number.isNaN(num)) return String(val);
  return `${num.toFixed(decimals)}${suffix}`;
};

export const SleepDoctorPage: React.FC = () => {
  const [data, setData] = useState<{
    window_end_date: string | null;
    cpap_start_date: string;
    device_sn: string | null;
    last_7_days_summary: Record<string, number | null>;
    last_30_days_summary: Record<string, number | null>;
    best_30_summary: Record<string, string | number | null>;
    nightly_rows: Array<Record<string, unknown>>;
  } | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    api
      .getSleepDoctorSummary()
      .then(setData)
      .finally(() => setLoading(false));
  }, []);

  if (loading) {
    return (
      <div className="py-16 text-center text-sm text-slate-500">
        Loading Sleep Doctor Clinical Summary...
      </div>
    );
  }

  const l7 = data?.last_7_days_summary || {};
  const l30 = data?.last_30_days_summary || {};
  const b30 = data?.best_30_summary || {};
  const nights = data?.nightly_rows || [];

  return (
    <div className="space-y-6">
      {/* Header + Export Actions */}
      <div className="flex flex-wrap items-center justify-between gap-4">
        <div className="flex items-center gap-3">
          <div className="p-2.5 rounded-xl bg-sky-100 dark:bg-sky-950 text-sky-700 dark:text-sky-300 no-print">
            <Stethoscope className="w-5 h-5" />
          </div>
          <div>
            <h1 className="text-2xl font-bold text-slate-900 dark:text-white">
              Sleep Doctor Clinical Summary
            </h1>
            <p className="text-sm text-slate-500 dark:text-slate-400">
              Window Ending: <b>{data?.window_end_date || "—"}</b> · CPAP Start:{" "}
              <b>{data?.cpap_start_date}</b> · Device SN:{" "}
              <b>{data?.device_sn || "—"}</b>
            </p>
          </div>
        </div>
        <div className="flex items-center gap-2.5 no-print">
          <button
            onClick={() => window.print()}
            className="inline-flex items-center gap-2 rounded-xl border border-slate-300 dark:border-slate-700 bg-white dark:bg-slate-900 hover:bg-slate-50 dark:hover:bg-slate-800 px-4 py-2 text-sm font-medium"
          >
            <Printer className="w-4 h-4" />
            Print View
          </button>
          <a
            href="/api/reports/sleep-doctor.pdf"
            className="inline-flex items-center gap-2 rounded-xl bg-sky-600 hover:bg-sky-700 text-white px-4 py-2 text-sm font-semibold shadow-sm"
          >
            <Download className="w-4 h-4" />
            Download Clinical PDF
          </a>
        </div>
      </div>

      {/* 3-Column Window Context: Past 7D | Past 30D | Best 30 */}
      <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
        <div className="rounded-2xl border border-slate-200 dark:border-slate-800 bg-white dark:bg-slate-900 p-5 print-card space-y-2.5">
          <div className="text-xs font-semibold uppercase tracking-wider text-sky-600">
            Past 7 Days
          </div>
          <div className="text-3xl font-bold">
            {fmtNum(l7.adherence_4h_pct, "%", 1)}
            <span className="text-xs font-normal text-slate-500 ml-2">
              ({l7.days_ge_4h ?? "—"}/{l7.calendar_days ?? 7} nights &ge;4h)
            </span>
          </div>
          <div className="text-xs space-y-1 text-slate-600 dark:text-slate-300">
            <div>
              Avg Usage (Used / All):{" "}
              <b>
                {fmtNum(l7.avg_hours_days_used, "h", 2)} /{" "}
                {fmtNum(l7.avg_hours_all_days, "h", 2)}
              </b>
            </div>
            <div>
              AHI / CAI: <b>{fmtNum(l7.avg_ahi, "", 2)} / {fmtNum(l7.avg_cai, "", 2)}</b>
            </div>
            <div>
              Median / P95 Pressure:{" "}
              <b>
                {fmtNum(l7.median_pressure, "", 1)} / {fmtNum(l7.avg_p95_pressure, "", 1)} cmH2O
              </b>
            </div>
            <div>
              Avg Leak: <b>{fmtNum(l7.avg_leak, " L/min", 1)}</b>
            </div>
            <div>
              SpO2 Avg / Min:{" "}
              <b>
                {fmtNum(l7.avg_spo2, "%", 1)} / {fmtNum(l7.min_spo2, "%", 1)}
              </b>
            </div>
            <div>
              RHR / HRV:{" "}
              <b>
                {fmtNum(l7.avg_rhr, " bpm", 1)} / {fmtNum(l7.avg_hrv, " ms", 1)}
              </b>
            </div>
          </div>
        </div>

        <div className="rounded-2xl border border-slate-200 dark:border-slate-800 bg-white dark:bg-slate-900 p-5 print-card space-y-2.5">
          <div className="text-xs font-semibold uppercase tracking-wider text-indigo-600">
            Past 30 Days
          </div>
          <div className="text-3xl font-bold">
            {fmtNum(l30.adherence_4h_pct, "%", 1)}
            <span className="text-xs font-normal text-slate-500 ml-2">
              ({l30.days_ge_4h ?? "—"}/{l30.calendar_days ?? 30} nights &ge;4h)
            </span>
          </div>
          <div className="text-xs space-y-1 text-slate-600 dark:text-slate-300">
            <div>
              Avg Usage (Used / All):{" "}
              <b>
                {fmtNum(l30.avg_hours_days_used, "h", 2)} /{" "}
                {fmtNum(l30.avg_hours_all_days, "h", 2)}
              </b>
            </div>
            <div>
              AHI / CAI: <b>{fmtNum(l30.avg_ahi, "", 2)} / {fmtNum(l30.avg_cai, "", 2)}</b>
            </div>
            <div>
              Median / P95 Pressure:{" "}
              <b>
                {fmtNum(l30.median_pressure, "", 1)} / {fmtNum(l30.avg_p95_pressure, "", 1)} cmH2O
              </b>
            </div>
            <div>
              Avg Leak: <b>{fmtNum(l30.avg_leak, " L/min", 1)}</b>
            </div>
            <div>
              SpO2 Avg / Min:{" "}
              <b>
                {fmtNum(l30.avg_spo2, "%", 1)} / {fmtNum(l30.min_spo2, "%", 1)}
              </b>
            </div>
            <div>
              RHR / HRV:{" "}
              <b>
                {fmtNum(l30.avg_rhr, " bpm", 1)} / {fmtNum(l30.avg_hrv, " ms", 1)}
              </b>
            </div>
          </div>
        </div>

        <div className="rounded-2xl border border-emerald-200 dark:border-emerald-900 bg-emerald-50/40 dark:bg-emerald-950/20 p-5 print-card space-y-2.5">
          <div className="text-xs font-semibold uppercase tracking-wider text-emerald-700 dark:text-emerald-400">
            Best-30 Compliance Window
          </div>
          <div className="text-3xl font-bold text-emerald-700 dark:text-emerald-300">
            {fmtNum(b30.adherence_pct, "%", 1)}
            <span className="text-xs font-normal text-slate-600 dark:text-slate-400 ml-2">
              ({b30.days_ge_4h ?? "—"}/30 days &ge;4h)
            </span>
          </div>
          <div className="text-xs space-y-1 text-slate-700 dark:text-slate-300">
            <div>
              Window: <b>{String(b30.start_date || "—")} → {String(b30.end_date || "—")}</b>
            </div>
            <div>
              Avg Usage on Days Used: <b>{fmtNum(b30.avg_hours_used, "h", 2)}</b>
            </div>
            <div>
              Window Avg AHI: <b>{fmtNum(b30.avg_ahi, " events/hr", 2)}</b>
            </div>
            <div className="pt-2 text-[11px] text-slate-500">
              CMS Medicare/Insurance compliance benchmark requires &ge;70% of nights with &ge;4.0 hours in a consecutive 30-day window.
            </div>
          </div>
        </div>
      </div>

      {/* Past 7 Days Nightly Clinical Table */}
      <div className="rounded-2xl border border-slate-200 dark:border-slate-800 bg-white dark:bg-slate-900 p-5 print-card overflow-x-auto">
        <h2 className="text-base font-semibold mb-3">
          Past 7 Nights — CPAP Therapy &amp; Google Health Nocturnal Correlation
        </h2>
        {nights.length === 0 ? (
          <p className="text-xs text-slate-500 py-6">
            No nightly summary rows loaded yet. Run ETL from the Admin Console first.
          </p>
        ) : (
          <table className="w-full text-xs text-left border-collapse">
            <thead>
              <tr className="border-b border-slate-200 dark:border-slate-800 text-slate-500">
                <th className="py-2 px-2">Wake-Up Date</th>
                <th className="py-2 px-2">CPAP Hrs</th>
                <th className="py-2 px-2">&ge;4h</th>
                <th className="py-2 px-2">Pressure / P95</th>
                <th className="py-2 px-2">AHI / CAI</th>
                <th className="py-2 px-2">Leak (L/m)</th>
                <th className="py-2 px-2">Sleep Hrs</th>
                <th className="py-2 px-2">Deep / REM %</th>
                <th className="py-2 px-2">SpO2 Avg / Min</th>
                <th className="py-2 px-2">RHR / HRV</th>
              </tr>
            </thead>
            <tbody>
              {nights.map((r) => {
                const compliant = Boolean(r.cpap_compliant_4h);
                return (
                  <tr
                    key={String(r.health_date)}
                    className="border-b border-slate-100 dark:border-slate-800/70"
                  >
                    <td className="py-2 px-2 font-mono font-semibold">
                      {String(r.health_date)}
                    </td>
                    <td className="py-2 px-2 font-medium">
                      {fmtNum(r.cpap_usage_hours, "h", 2)}
                    </td>
                    <td className="py-2 px-2">
                      {r.cpap_usage_minutes == null ? (
                        "—"
                      ) : compliant ? (
                        <CheckCircle2 className="w-4 h-4 text-emerald-600" />
                      ) : (
                        <AlertCircle className="w-4 h-4 text-amber-500" />
                      )}
                    </td>
                    <td className="py-2 px-2">
                      {fmtNum(r.cpap_pressure, "", 1)} /{" "}
                      {fmtNum(r.cpap_p95_pressure, "", 1)}
                    </td>
                    <td className="py-2 px-2">
                      {fmtNum(r.cpap_ahi, "", 1)} / {fmtNum(r.cpap_cai, "", 1)}
                    </td>
                    <td className="py-2 px-2">{fmtNum(r.cpap_avg_leak, "", 1)}</td>
                    <td className="py-2 px-2">{fmtNum(r.total_sleep_hours, "h", 2)}</td>
                    <td className="py-2 px-2">
                      {fmtNum(r.deep_sleep_pct, "%", 0)} /{" "}
                      {fmtNum(r.rem_sleep_pct, "%", 0)}
                    </td>
                    <td className="py-2 px-2">
                      {fmtNum(r.spo2_avg_pct, "%", 1)} /{" "}
                      {fmtNum(r.spo2_min_pct, "%", 1)}
                    </td>
                    <td className="py-2 px-2">
                      {fmtNum(r.resting_heart_rate, "", 0)} /{" "}
                      {fmtNum(r.hrv_rmssd_ms, "", 0)}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
};
