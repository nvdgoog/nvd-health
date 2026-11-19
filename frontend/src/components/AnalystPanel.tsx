import React, { useState } from "react";
import { Bot, Send, Code2, Sparkles, Loader2 } from "lucide-react";
import { api, type ChartSpec } from "../api";
import { DynamicChart } from "./DynamicChart";

interface MessageItem {
  id: string;
  role: "user" | "assistant";
  text: string;
  charts?: ChartSpec[];
  sqlQueries?: string[];
  meta?: string;
}

const STARTER_PROMPTS = [
  "How has my SpO2 and HRV changed since starting CPAP?",
  "On nights where my leak was above 8 L/min, what happened to my AHI and deep sleep?",
  "Summarize my past week for my sleep doctor.",
  "Which days had the biggest gap between total sleep and CPAP usage?",
];

export const AnalystPanel: React.FC<{ compact?: boolean }> = ({
  compact = false,
}) => {
  const [messages, setMessages] = useState<MessageItem[]>([
    {
      id: "welcome",
      role: "assistant",
      text: "Ask me anything about your CPAP therapy, sleep stages, SpO2, HRV, readiness, or intraday vitals. Every metric is verified via read-only BigQuery SQL across Gold, Silver, and Bronze.",
    },
  ]);
  const [input, setInput] = useState("");
  const [sessionId, setSessionId] = useState<string | undefined>(undefined);
  const [loading, setLoading] = useState(false);
  const [openSqlMap, setOpenSqlMap] = useState<Record<string, boolean>>({});

  const sendPrompt = async (promptText: string) => {
    const trimmed = promptText.trim();
    if (!trimmed || loading) return;

    const userMsg: MessageItem = {
      id: `u-${Date.now()}`,
      role: "user",
      text: trimmed,
    };
    setMessages((prev) => [...prev, userMsg]);
    setInput("");
    setLoading(true);

    try {
      const res = await api.chatAnalyst(trimmed, sessionId);
      setSessionId(res.session_id);
      setMessages((prev) => [
        ...prev,
        {
          id: `a-${Date.now()}`,
          role: "assistant",
          text: res.reply,
          charts: res.charts,
          sqlQueries: res.sql_queries,
          meta: `${res.model} · ${res.mode}`,
        },
      ]);
    } catch (err) {
      setMessages((prev) => [
        ...prev,
        {
          id: `e-${Date.now()}`,
          role: "assistant",
          text: `Error querying Vertex AI Agent: ${(err as Error).message}`,
        },
      ]);
    } finally {
      setLoading(false);
    }
  };

  return (
    <div
      className={`flex flex-col rounded-2xl border border-slate-200 dark:border-slate-800 bg-white dark:bg-slate-900 shadow-sm ${
        compact ? "h-[600px]" : "h-[calc(100vh-11rem)]"
      }`}
    >
      <div className="flex items-center justify-between px-5 py-3.5 border-b border-slate-200 dark:border-slate-800">
        <div className="flex items-center gap-2.5">
          <div className="p-2 rounded-lg bg-sky-50 dark:bg-sky-950 text-sky-600 dark:text-sky-400">
            <Bot className="w-4 h-4" />
          </div>
          <div>
            <h3 className="text-sm font-semibold text-slate-900 dark:text-white">
              AI Health Analyst (Vertex AI Agent Engine · ADK)
            </h3>
            <p className="text-xs text-slate-500">
              Read-only SQL grounded in Gold, Silver &amp; Bronze (America/Los_Angeles)
            </p>
          </div>
        </div>
      </div>

      {/* Starter Chips */}
      <div className="px-4 py-2.5 border-b border-slate-100 dark:border-slate-800 flex flex-wrap gap-2 bg-slate-50/70 dark:bg-slate-950/40">
        {STARTER_PROMPTS.map((q) => (
          <button
            key={q}
            onClick={() => sendPrompt(q)}
            disabled={loading}
            className="text-xs px-2.5 py-1 rounded-full bg-white dark:bg-slate-800 border border-slate-200 dark:border-slate-700 hover:border-sky-500 text-slate-700 dark:text-slate-200 transition flex items-center gap-1"
          >
            <Sparkles className="w-3 h-3 text-sky-500" />
            {q}
          </button>
        ))}
      </div>

      {/* Messages */}
      <div className="flex-1 overflow-y-auto p-4 space-y-4">
        {messages.map((m) => (
          <div
            key={m.id}
            className={`flex ${m.role === "user" ? "justify-end" : "justify-start"}`}
          >
            <div
              className={`max-w-[90%] rounded-2xl px-4 py-3 text-sm space-y-3 ${
                m.role === "user"
                  ? "bg-sky-600 text-white"
                  : "bg-slate-100 dark:bg-slate-800 text-slate-900 dark:text-slate-100"
              }`}
            >
              <div className="whitespace-pre-wrap leading-relaxed">{m.text}</div>

              {m.charts && m.charts.length > 0 && (
                <div className="space-y-3 pt-1">
                  {m.charts.map((c, idx) => (
                    <DynamicChart key={idx} spec={c} />
                  ))}
                </div>
              )}

              {m.sqlQueries && m.sqlQueries.length > 0 && (
                <div>
                  <button
                    onClick={() =>
                      setOpenSqlMap((prev) => ({
                        ...prev,
                        [m.id]: !prev[m.id],
                      }))
                    }
                    className="inline-flex items-center gap-1.5 text-xs font-medium text-sky-700 dark:text-sky-300 hover:underline"
                  >
                    <Code2 className="w-3.5 h-3.5" />
                    {openSqlMap[m.id] ? "Hide Verified SQL" : `Show Verified SQL (${m.sqlQueries.length})`}
                  </button>
                  {openSqlMap[m.id] && (
                    <div className="mt-2 space-y-2">
                      {m.sqlQueries.map((sql, idx) => (
                        <pre
                          key={idx}
                          className="text-[11px] bg-slate-950 text-emerald-300 p-3 rounded-lg overflow-x-auto"
                        >
                          {sql}
                        </pre>
                      ))}
                    </div>
                  )}
                </div>
              )}

              {m.meta && (
                <div className="text-[10px] opacity-60">{m.meta}</div>
              )}
            </div>
          </div>
        ))}
        {loading && (
          <div className="flex items-center gap-2 text-xs text-slate-500 px-2">
            <Loader2 className="w-4 h-4 animate-spin text-sky-600" />
            Querying BigQuery &amp; synthesizing clinical response...
          </div>
        )}
      </div>

      {/* Input */}
      <form
        onSubmit={(e) => {
          e.preventDefault();
          sendPrompt(input);
        }}
        className="p-3 border-t border-slate-200 dark:border-slate-800 flex gap-2"
      >
        <input
          value={input}
          onChange={(e) => setInput(e.target.value)}
          placeholder="Ask about SpO2, HRV, AHI, mask leak, or a specific night..."
          className="flex-1 rounded-xl border border-slate-300 dark:border-slate-700 bg-white dark:bg-slate-950 px-3.5 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-sky-500"
        />
        <button
          type="submit"
          disabled={loading || !input.trim()}
          className="inline-flex items-center gap-1.5 rounded-xl bg-sky-600 hover:bg-sky-700 disabled:opacity-50 text-white px-4 py-2 text-sm font-medium transition"
        >
          <Send className="w-4 h-4" />
          Ask
        </button>
      </form>
    </div>
  );
};
