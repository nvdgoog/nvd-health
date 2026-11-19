import React from "react";
import {
  Bar,
  BarChart,
  CartesianGrid,
  Legend,
  Line,
  LineChart,
  ResponsiveContainer,
  Scatter,
  ScatterChart,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import type { ChartSpec } from "../api";

const PALETTE = ["#0284c7", "#10b981", "#f59e0b", "#8b5cf6", "#ef4444"];

export const DynamicChart: React.FC<{ spec: ChartSpec }> = ({ spec }) => {
  const rows = spec.data || [];
  if (rows.length === 0) {
    return (
      <div className="rounded-lg border border-slate-200 dark:border-slate-700 p-4 text-xs text-slate-500">
        {spec.title}: No rows returned.
      </div>
    );
  }

  if (spec.type === "table") {
    const cols = Object.keys(rows[0]);
    return (
      <div className="rounded-xl border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-900 p-4 overflow-x-auto">
        <div className="mb-2">
          <h4 className="text-sm font-semibold text-slate-800 dark:text-slate-100">
            {spec.title}
          </h4>
          {spec.subtitle && (
            <p className="text-xs text-slate-500 dark:text-slate-400">
              {spec.subtitle}
            </p>
          )}
        </div>
        <table className="w-full text-xs text-left border-collapse">
          <thead>
            <tr className="border-b border-slate-200 dark:border-slate-700 text-slate-500">
              {cols.map((c) => (
                <th key={c} className="py-1.5 px-2 font-medium whitespace-nowrap">
                  {c}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {rows.slice(0, 30).map((r, i) => (
              <tr
                key={i}
                className="border-b border-slate-100 dark:border-slate-800"
              >
                {cols.map((c) => (
                  <td key={c} className="py-1.5 px-2 whitespace-nowrap">
                    {r[c] == null ? "—" : String(r[c])}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    );
  }

  const series = spec.series?.length
    ? spec.series
    : Object.keys(rows[0])
        .filter((k) => k !== spec.xKey)
        .slice(0, 3)
        .map((k, idx) => ({
          key: k,
          label: k,
          color: PALETTE[idx % PALETTE.length],
        }));

  return (
    <div className="rounded-xl border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-900 p-4">
      <div className="mb-3">
        <h4 className="text-sm font-semibold text-slate-800 dark:text-slate-100">
          {spec.title}
        </h4>
        {spec.subtitle && (
          <p className="text-xs text-slate-500 dark:text-slate-400">
            {spec.subtitle}
          </p>
        )}
      </div>
      <div className="h-60 w-full">
        <ResponsiveContainer width="100%" height="100%">
          {spec.type === "bar" ? (
            <BarChart data={rows}>
              <CartesianGrid strokeDasharray="3 3" strokeOpacity={0.25} />
              <XAxis dataKey={spec.xKey} tick={{ fontSize: 11 }} />
              <YAxis tick={{ fontSize: 11 }} />
              <Tooltip />
              <Legend wrapperStyle={{ fontSize: 11 }} />
              {series.map((s, idx) => (
                <Bar
                  key={s.key}
                  dataKey={s.key}
                  name={s.label}
                  fill={s.color || PALETTE[idx % PALETTE.length]}
                  radius={[4, 4, 0, 0]}
                />
              ))}
            </BarChart>
          ) : spec.type === "scatter" ? (
            <ScatterChart>
              <CartesianGrid strokeDasharray="3 3" strokeOpacity={0.25} />
              <XAxis
                type="number"
                dataKey={spec.xKey}
                name={spec.xKey}
                tick={{ fontSize: 11 }}
              />
              <YAxis
                type="number"
                dataKey={series[0]?.key}
                name={series[0]?.label}
                tick={{ fontSize: 11 }}
              />
              <Tooltip cursor={{ strokeDasharray: "3 3" }} />
              <Scatter
                name={series[0]?.label || "Samples"}
                data={rows}
                fill={series[0]?.color || PALETTE[0]}
              />
            </ScatterChart>
          ) : (
            <LineChart data={rows}>
              <CartesianGrid strokeDasharray="3 3" strokeOpacity={0.25} />
              <XAxis dataKey={spec.xKey} tick={{ fontSize: 11 }} />
              <YAxis tick={{ fontSize: 11 }} />
              <Tooltip />
              <Legend wrapperStyle={{ fontSize: 11 }} />
              {series.map((s, idx) => (
                <Line
                  key={s.key}
                  type="monotone"
                  dataKey={s.key}
                  name={s.label}
                  stroke={s.color || PALETTE[idx % PALETTE.length]}
                  strokeWidth={2}
                  dot={rows.length <= 35}
                />
              ))}
            </LineChart>
          )}
        </ResponsiveContainer>
      </div>
    </div>
  );
};
