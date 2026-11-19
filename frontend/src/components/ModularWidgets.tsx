import React from "react";
import { Dumbbell, Plane } from "lucide-react";
import type { DailyPerformanceRow } from "../api";

export interface DashboardWidgetConfig {
  id: string;
  title: string;
  sourceName: string;
  isActive: (days: DailyPerformanceRow[]) => boolean;
}

export const EXTENSION_WIDGET_REGISTRY: DashboardWidgetConfig[] = [
  {
    id: "transcend_micro",
    title: "Transcend Micro Travel CPAP Comparison",
    sourceName: "uploads/transcend_micro/",
    isActive: (days) => days.some((d) => d.transcend_usage_minutes != null),
  },
  {
    id: "zenplanner",
    title: "ZenPlanner CrossFit WOD & Strength Correlation",
    sourceName: "uploads/zenplanner/",
    isActive: (days) => days.some((d) => (d.zenplanner_workout_count ?? 0) > 0),
  },
];

export const ModularExtensionWidgets: React.FC<{
  days: DailyPerformanceRow[];
}> = ({ days }) => {
  const transcendDays = days.filter((d) => d.transcend_usage_minutes != null);
  const zenDays = days.filter((d) => (d.zenplanner_workout_count ?? 0) > 0);

  return (
    <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
      {/* Transcend Micro Widget */}
      <div className="rounded-2xl border border-dashed border-slate-300 dark:border-slate-700 bg-white/70 dark:bg-slate-900/60 p-5">
        <div className="flex items-center justify-between mb-2">
          <div className="flex items-center gap-2 font-semibold text-sm text-slate-800 dark:text-slate-100">
            <Plane className="w-4 h-4 text-sky-600" />
            Transcend Micro Travel CPAP Module
          </div>
          <span className="text-[11px] px-2 py-0.5 rounded-full bg-slate-100 dark:bg-slate-800 text-slate-600 dark:text-slate-300">
            {transcendDays.length > 0 ? "Active" : "Connector Ready"}
          </span>
        </div>
        {transcendDays.length > 0 ? (
          <p className="text-xs text-slate-600 dark:text-slate-300">
            {transcendDays.length} travel CPAP nights loaded. Avg usage:{" "}
            {(
              transcendDays.reduce(
                (s, d) => s + (d.transcend_usage_minutes || 0),
                0
              ) /
              transcendDays.length /
              60
            ).toFixed(2)}
            h.
          </p>
        ) : (
          <p className="text-xs text-slate-500">
            Drop Transcend Micro exports under{" "}
            <code className="text-[11px]">uploads/transcend_micro/</code> to
            automatically populate travel vs. home ReactHealth CPAP comparisons.
          </p>
        )}
      </div>

      {/* ZenPlanner CrossFit Widget */}
      <div className="rounded-2xl border border-dashed border-slate-300 dark:border-slate-700 bg-white/70 dark:bg-slate-900/60 p-5">
        <div className="flex items-center justify-between mb-2">
          <div className="flex items-center gap-2 font-semibold text-sm text-slate-800 dark:text-slate-100">
            <Dumbbell className="w-4 h-4 text-emerald-600" />
            ZenPlanner CrossFit WOD &amp; Strength Module
          </div>
          <span className="text-[11px] px-2 py-0.5 rounded-full bg-slate-100 dark:bg-slate-800 text-slate-600 dark:text-slate-300">
            {zenDays.length > 0 ? "Active" : "Connector Ready"}
          </span>
        </div>
        {zenDays.length > 0 ? (
          <p className="text-xs text-slate-600 dark:text-slate-300">
            {zenDays.length} CrossFit WOD days synced. Latest:{" "}
            {zenDays[zenDays.length - 1]?.zenplanner_wod_name || "WOD logged"}.
          </p>
        ) : (
          <p className="text-xs text-slate-500">
            Drop ZenPlanner workout exports under{" "}
            <code className="text-[11px]">uploads/zenplanner/</code> to analyze
            WOD intensity &amp; RX performance against next-night HRV and AHI.
          </p>
        )}
      </div>
    </div>
  );
};
