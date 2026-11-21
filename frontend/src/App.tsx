import React, { useEffect, useState } from "react";
import {
  Activity,
  Bot,
  Database,
  Moon,
  Stethoscope,
  Sun,
  X,
} from "lucide-react";
import { api, type HealthInfo } from "./api";
import { AnalystPanel } from "./components/AnalystPanel";
import { AdminPage } from "./pages/AdminPage";
import { DashboardPage } from "./pages/DashboardPage";
import { SleepDoctorPage } from "./pages/SleepDoctorPage";

type TabId = "dashboard" | "sleep-doctor" | "analyst" | "admin";

export const App: React.FC = () => {
  const [tab, setTab] = useState<TabId>("dashboard");
  const [dark, setDark] = useState<boolean>(() => {
    return localStorage.getItem("nvd-theme") === "dark";
  });
  const [drawerOpen, setDrawerOpen] = useState(false);
  const [healthInfo, setHealthInfo] = useState<HealthInfo | null>(null);

  useEffect(() => {
    api
      .getHealth()
      .then(setHealthInfo)
      .catch(() => null);
  }, []);

  useEffect(() => {
    const root = document.documentElement;
    if (dark) {
      root.classList.add("dark");
      localStorage.setItem("nvd-theme", "dark");
    } else {
      root.classList.remove("dark");
      localStorage.setItem("nvd-theme", "light");
    }
  }, [dark]);

  const navItems: Array<{ id: TabId; label: string; icon: React.ReactNode }> = [
    {
      id: "dashboard",
      label: "Performance Dashboard",
      icon: <Activity className="w-4 h-4" />,
    },
    {
      id: "sleep-doctor",
      label: "Sleep Doctor Summary",
      icon: <Stethoscope className="w-4 h-4" />,
    },
    {
      id: "analyst",
      label: "AI Health Analyst",
      icon: <Bot className="w-4 h-4" />,
    },
    {
      id: "admin",
      label: "Data Engineering & Admin",
      icon: <Database className="w-4 h-4" />,
    },
  ];

  return (
    <div className="min-h-screen flex flex-col bg-slate-50 dark:bg-slate-950 text-slate-900 dark:text-slate-100">
      {/* Top Bar */}
      <header className="sticky top-0 z-30 border-b border-slate-200 dark:border-slate-800 bg-white/90 dark:bg-slate-900/90 backdrop-blur no-print">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 h-16 flex items-center justify-between gap-4">
          <div className="flex items-center gap-3">
            <div className="w-9 h-9 rounded-xl bg-gradient-to-br from-sky-600 to-indigo-600 text-white flex items-center justify-center font-bold text-sm shadow-sm">
              NH
            </div>
            <div>
              <div className="font-bold text-sm leading-tight">
                NVD Health Platform
              </div>
              <div className="text-[11px] text-slate-500">
                {healthInfo?.project_id ? `${healthInfo.project_id} · ` : ""}America/Los_Angeles
              </div>
            </div>
          </div>

          <nav className="flex items-center gap-1 overflow-x-auto">
            {navItems.map((item) => (
              <button
                key={item.id}
                onClick={() => setTab(item.id)}
                className={`inline-flex items-center gap-2 px-3 py-2 rounded-xl text-xs sm:text-sm font-medium whitespace-nowrap transition ${
                  tab === item.id
                    ? "bg-sky-50 dark:bg-sky-950 text-sky-700 dark:text-sky-300"
                    : "text-slate-600 dark:text-slate-300 hover:bg-slate-100 dark:hover:bg-slate-800"
                }`}
              >
                {item.icon}
                {item.label}
              </button>
            ))}
          </nav>

          <div className="flex items-center gap-2">
            {tab !== "analyst" && (
              <button
                onClick={() => setDrawerOpen(true)}
                className="inline-flex items-center gap-1.5 rounded-xl bg-sky-600 hover:bg-sky-700 text-white px-3 py-1.5 text-xs font-semibold shadow-sm"
              >
                <Bot className="w-3.5 h-3.5" />
                Ask AI
              </button>
            )}
            <button
              onClick={() => setDark((d) => !d)}
              className="p-2 rounded-xl border border-slate-200 dark:border-slate-700 hover:bg-slate-100 dark:hover:bg-slate-800"
              aria-label="Toggle theme"
            >
              {dark ? <Sun className="w-4 h-4" /> : <Moon className="w-4 h-4" />}
            </button>
          </div>
        </div>
      </header>

      {/* Main Content */}
      <main className="flex-1 max-w-7xl w-full mx-auto px-4 sm:px-6 py-6">
        {tab === "dashboard" && <DashboardPage />}
        {tab === "sleep-doctor" && <SleepDoctorPage />}
        {tab === "analyst" && <AnalystPanel />}
        {tab === "admin" && <AdminPage />}
      </main>

      {/* Slide-over Embedded AI Health Analyst Drawer */}
      {drawerOpen && tab !== "analyst" && (
        <div className="fixed inset-0 z-40 flex justify-end bg-slate-900/30 backdrop-blur-sm no-print">
          <div className="w-full max-w-2xl bg-white dark:bg-slate-900 h-full p-4 shadow-2xl border-l border-slate-200 dark:border-slate-800 flex flex-col">
            <div className="flex justify-end mb-2">
              <button
                onClick={() => setDrawerOpen(false)}
                className="p-1.5 rounded-lg hover:bg-slate-100 dark:hover:bg-slate-800"
              >
                <X className="w-4 h-4" />
              </button>
            </div>
            <div className="flex-1 overflow-hidden">
              <AnalystPanel />
            </div>
          </div>
        </div>
      )}
    </div>
  );
};

export default App;
