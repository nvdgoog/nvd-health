import React, { useEffect, useRef, useState } from "react";
import {
  CheckCircle2,
  CloudUpload,
  Database,
  FileText,
  FolderUp,
  Loader2,
  Play,
  RefreshCw,
  Settings2,
  AlertTriangle,
  PlugZap,
} from "lucide-react";
import { api, type EtlRunRecord } from "../api";
import { uploadFileDirectToGcs } from "../gcsUpload";

const PIPELINE_STAGES = [
  { key: "QUEUED", label: "Queued / Upload Ready" },
  { key: "UNZIPPING", label: "Unzipping Archive" },
  { key: "SCANNING", label: "Scanning GCS & Ledger" },
  { key: "LOADING_BRONZE", label: "Loading & Merging Bronze" },
  { key: "RUNNING_DATAFORM", label: "Dataform Silver & Gold" },
  { key: "COMPLETED", label: "Completed" },
];

export const AdminPage: React.FC = () => {
  // Upload states
  const [zipFile, setZipFile] = useState<File | null>(null);
  const [zipProgress, setZipProgress] = useState<number>(0);
  const [folderFiles, setFolderFiles] = useState<File[]>([]);
  const [folderProgress, setFolderProgress] = useState<{
    done: number;
    total: number;
  }>({ done: 0, total: 0 });
  const [pdfFile, setPdfFile] = useState<File | null>(null);
  const [pdfPreview, setPdfPreview] = useState<{
    metadata: Record<string, unknown>;
    valid_days_count: number;
    no_data_days_count: number;
    warnings: string[];
  } | null>(null);
  const [uploadingKind, setUploadingKind] = useState<string | null>(null);
  const [uploadStatusMsg, setUploadStatusMsg] = useState<string | null>(null);
  const [errorMsg, setErrorMsg] = useState<string | null>(null);
  const [forceReload, setForceReload] = useState(false);

  // ETL & Ledger states
  const [activeRun, setActiveRun] = useState<EtlRunRecord | null>(null);
  const [runs, setRuns] = useState<EtlRunRecord[]>([]);
  const [ledger, setLedger] = useState<{
    sources: Array<Record<string, unknown>>;
    bronze_tables: Array<Record<string, unknown>>;
    coverage: Record<string, unknown>;
    recent_files: Array<Record<string, unknown>>;
  } | null>(null);
  const [connectors, setConnectors] = useState<
    Array<{
      name: string;
      display_name: string;
      supported_extensions: string[];
      expected_prefixes: string[];
      status: string;
      description: string;
    }>
  >([]);

  // Settings
  const [cpapStartDate, setCpapStartDate] = useState("2026-10-13");
  const [autoDetectedDate, setAutoDetectedDate] = useState("2026-10-13");
  const [isManualOverride, setIsManualOverride] = useState(false);
  const [savingSetting, setSavingSetting] = useState(false);

  // Google Sheets Journal Sync
  const [gsStatus, setGsStatus] = useState<{
    spreadsheet_id: string;
    web_service_account: string;
    etl_service_account: string;
    observation_rows: number;
    baseline_note_rows: number;
    min_date: string | null;
    max_date: string | null;
  } | null>(null);
  const [syncingSheet, setSyncingSheet] = useState(false);

  const sseRef = useRef<EventSource | null>(null);

  const refreshAll = async () => {
    try {
      const [runsRes, ledgerRes, settingsRes, connRes, gsRes] = await Promise.all([
        api.listEtlRuns(),
        api.getLedger(),
        api.getSettings(),
        api.getConnectors(),
        api.getGSheetsStatus().catch(() => null),
      ]);
      setRuns(runsRes.runs);
      if (activeRun) {
        const updated = runsRes.runs.find((r) => r.run_id === activeRun.run_id);
        if (updated) setActiveRun(updated);
      } else if (runsRes.runs.length > 0) {
        setActiveRun(runsRes.runs[0]);
      }
      setLedger(ledgerRes);
      setCpapStartDate(settingsRes.setting_value || "2026-10-13");
      setAutoDetectedDate(settingsRes.auto_detected_value || "2026-10-13");
      setIsManualOverride(Boolean(settingsRes.is_manual_override));
      setConnectors(connRes.connectors);
      if (gsRes) setGsStatus(gsRes);
    } catch (err) {
      setErrorMsg((err as Error).message);
    }
  };

  useEffect(() => {
    refreshAll();
    return () => {
      sseRef.current?.close();
    };
  }, []);

  const watchRunStream = (runId: string) => {
    sseRef.current?.close();
    const es = new EventSource(
      `/api/admin/etl/runs/${encodeURIComponent(runId)}/stream`
    );
    sseRef.current = es;
    es.onmessage = (evt) => {
      try {
        const parsed = JSON.parse(evt.data) as EtlRunRecord;
        setActiveRun(parsed);
        if (parsed.status === "COMPLETED" || parsed.status === "FAILED") {
          es.close();
          refreshAll();
        }
      } catch {
        // ignore parse errors
      }
    };
    es.onerror = () => {
      es.close();
    };
  };

  const handleZipUploadAndRun = async () => {
    if (!zipFile) return;
    setErrorMsg(null);
    setUploadingKind("zip");
    setZipProgress(0);
    setUploadStatusMsg(`Requesting resumable GCS signed URL for ${zipFile.name}...`);
    try {
      const signed = await api.getSignedUrl({
        source_type: "google_takeout_zip",
        relative_path: zipFile.name,
        content_type: zipFile.type || "application/zip",
        resumable: true,
      });
      setUploadStatusMsg("Uploading directly to gs://nvd-health-raw-data...");
      await uploadFileDirectToGcs(zipFile, signed, (done, total) => {
        setZipProgress(total > 0 ? Math.round((done / total) * 100) : 100);
      });
      setUploadStatusMsg("Upload complete. Triggering Cloud Run Job ETL...");
      const triggered = await api.triggerEtl({
        mode: "zip",
        zip_gcs_path: signed.gcs_path,
        force_reload: forceReload,
      });
      watchRunStream(triggered.run_id);
      setUploadStatusMsg(`Triggered ETL run ${triggered.run_id}`);
    } catch (err) {
      setErrorMsg((err as Error).message);
    } finally {
      setUploadingKind(null);
    }
  };

  const handleFolderUploadAndRun = async () => {
    if (folderFiles.length === 0) return;
    setErrorMsg(null);
    setUploadingKind("folder");
    const relevant = folderFiles.filter((f) => {
      const p = (
        (f as unknown as { webkitRelativePath?: string }).webkitRelativePath ||
        f.name
      ).toLowerCase();
      return p.endsWith(".csv") || p.endsWith("readme.txt");
    });
    const batchId = new Date().toISOString().replace(/[:.]/g, "-");
    setFolderProgress({ done: 0, total: relevant.length });

    try {
      let targetPrefix = "";
      // Sign in batches of 200 files
      const allSigned: Array<{
        file: File;
        signed: {
          upload_url: string;
          method: string;
          mode: string;
          required_headers: Record<string, string>;
          gcs_path: string;
        };
      }> = [];

      for (let i = 0; i < relevant.length; i += 200) {
        const slice = relevant.slice(i, i + 200);
        const batchRes = await api.getBatchSignedUrls({
          source_type: "google_takeout_folder",
          upload_batch_id: batchId,
          files: slice.map((f) => ({
            relative_path:
              (f as unknown as { webkitRelativePath?: string })
                .webkitRelativePath || f.name,
            content_type: f.type || "text/csv",
            resumable: f.size > 15 * 1024 * 1024,
          })),
        });
        targetPrefix = batchRes.prefix;
        batchRes.items.forEach((item, idx) => {
          allSigned.push({ file: slice[idx], signed: item });
        });
      }

      // Concurrent worker pool of 6 uploads
      let completed = 0;
      let cursor = 0;
      const worker = async () => {
        while (cursor < allSigned.length) {
          const idx = cursor++;
          const { file, signed } = allSigned[idx];
          await uploadFileDirectToGcs(file, signed);
          completed += 1;
          setFolderProgress({ done: completed, total: allSigned.length });
        }
      };
      await Promise.all(Array.from({ length: 6 }, () => worker()));

      setUploadStatusMsg(
        `Uploaded ${allSigned.length} files to GCS. Triggering ETL...`
      );
      const triggered = await api.triggerEtl({
        mode: "prefix",
        prefixes: [targetPrefix],
        force_reload: forceReload,
      });
      watchRunStream(triggered.run_id);
    } catch (err) {
      setErrorMsg((err as Error).message);
    } finally {
      setUploadingKind(null);
    }
  };

  const handleSelectPdf = async (file: File | null) => {
    setPdfFile(file);
    setPdfPreview(null);
    if (!file) return;
    try {
      const preview = await api.previewReactHealthLocal(file);
      setPdfPreview(preview);
    } catch (err) {
      setErrorMsg(`PDF preview failed: ${(err as Error).message}`);
    }
  };

  const handlePdfUploadAndRun = async () => {
    if (!pdfFile) return;
    setErrorMsg(null);
    setUploadingKind("pdf");
    try {
      const signed = await api.getSignedUrl({
        source_type: "reacthealth_pdf",
        relative_path: pdfFile.name,
        content_type: "application/pdf",
        resumable: false,
      });
      await uploadFileDirectToGcs(pdfFile, signed);
      const triggered = await api.triggerEtl({
        mode: "reacthealth_pdf",
        prefixes: [signed.gcs_path],
        force_reload: forceReload,
      });
      watchRunStream(triggered.run_id);
      setUploadStatusMsg(`Uploaded ReactHealth PDF & started ${triggered.run_id}`);
    } catch (err) {
      setErrorMsg((err as Error).message);
    } finally {
      setUploadingKind(null);
    }
  };

  const handleRunExistingGcs = async () => {
    setErrorMsg(null);
    try {
      const triggered = await api.triggerEtl({
        mode: "existing_gcs",
        force_reload: forceReload,
      });
      watchRunStream(triggered.run_id);
      setUploadStatusMsg(
        `Triggered ETL run ${triggered.run_id} against gs://nvd-health-raw-data/`
      );
    } catch (err) {
      setErrorMsg((err as Error).message);
    }
  };

  const handleSaveCpapDate = async (useAuto: boolean) => {
    setSavingSetting(true);
    try {
      const res = await api.updateCpapStartDate(
        useAuto
          ? { use_auto_detected: true }
          : { cpap_start_date: cpapStartDate, use_auto_detected: false }
      );
      setCpapStartDate(res.setting_value);
      setAutoDetectedDate(res.auto_detected_value);
      setIsManualOverride(res.is_manual_override);
    } catch (err) {
      setErrorMsg((err as Error).message);
    } finally {
      setSavingSetting(false);
    }
  };

  const stageIndex = activeRun
    ? PIPELINE_STAGES.findIndex((s) => s.key === activeRun.status)
    : -1;

  return (
    <div className="space-y-6">
      {/* Header Banner */}
      <div className="flex flex-wrap items-center justify-between gap-4">
        <div>
          <h1 className="text-2xl font-bold text-slate-900 dark:text-white">
            Data Engineering &amp; Ingestion Console
          </h1>
          <p className="text-sm text-slate-500 dark:text-slate-400">
            Direct-to-GCS Signed Uploads · Cloud Run Job Bronze ETL · Dataform Silver/Gold ELT
          </p>
        </div>
        <div className="flex items-center gap-3">
          <label className="inline-flex items-center gap-2 text-xs text-slate-600 dark:text-slate-300">
            <input
              type="checkbox"
              checked={forceReload}
              onChange={(e) => setForceReload(e.target.checked)}
              className="rounded border-slate-300"
            />
            Force Reload (ignore ledger hashes)
          </label>
          <button
            onClick={handleRunExistingGcs}
            className="inline-flex items-center gap-2 rounded-xl bg-emerald-600 hover:bg-emerald-700 text-white px-4 py-2.5 text-sm font-semibold shadow-sm transition"
          >
            <Play className="w-4 h-4" />
            Run ETL on Existing GCS Prefix
          </button>
          <button
            onClick={refreshAll}
            className="p-2.5 rounded-xl border border-slate-200 dark:border-slate-700 hover:bg-slate-100 dark:hover:bg-slate-800"
            title="Refresh ledger & runs"
          >
            <RefreshCw className="w-4 h-4" />
          </button>
        </div>
      </div>

      {errorMsg && (
        <div className="rounded-xl border border-rose-300 dark:border-rose-800 bg-rose-50 dark:bg-rose-950/40 px-4 py-3 text-sm text-rose-700 dark:text-rose-300 flex items-center gap-2">
          <AlertTriangle className="w-4 h-4 shrink-0" />
          <span>{errorMsg}</span>
        </div>
      )}
      {uploadStatusMsg && (
        <div className="rounded-xl border border-sky-200 dark:border-sky-800 bg-sky-50 dark:bg-sky-950/40 px-4 py-2.5 text-xs text-sky-800 dark:text-sky-200">
          {uploadStatusMsg}
        </div>
      )}

      {/* Uploaders Grid */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-5">
        {/* Option A: Takeout .zip */}
        <div className="rounded-2xl border border-slate-200 dark:border-slate-800 bg-white dark:bg-slate-900 p-5 space-y-4">
          <div className="flex items-center gap-2 font-semibold text-sm">
            <CloudUpload className="w-4 h-4 text-sky-600" />
            Option A — Google Takeout .zip
          </div>
          <p className="text-xs text-slate-500">
            Resumable Direct-to-GCS Signed URL upload (&gt;400 MB files bypass Cloud Run&apos;s 32 MiB limit) + automatic Cloud Run Job unzip &amp; Bronze load.
          </p>
          <input
            type="file"
            accept=".zip,application/zip"
            onChange={(e) => setZipFile(e.target.files?.[0] || null)}
            className="block w-full text-xs text-slate-500 file:mr-3 file:py-2 file:px-3 file:rounded-lg file:border-0 file:bg-sky-50 file:text-sky-700 dark:file:bg-sky-950 dark:file:text-sky-300"
          />
          {uploadingKind === "zip" && (
            <div className="space-y-1">
              <div className="h-2 rounded-full bg-slate-100 dark:bg-slate-800 overflow-hidden">
                <div
                  className="h-full bg-sky-600 transition-all"
                  style={{ width: `${zipProgress}%` }}
                />
              </div>
              <div className="text-[11px] text-slate-500">{zipProgress}% uploaded to GCS</div>
            </div>
          )}
          <button
            onClick={handleZipUploadAndRun}
            disabled={!zipFile || uploadingKind !== null}
            className="w-full rounded-xl bg-sky-600 hover:bg-sky-700 disabled:opacity-40 text-white py-2 text-sm font-medium transition"
          >
            Upload .zip &amp; Run ETL
          </button>
        </div>

        {/* Option B: Unzipped Folder */}
        <div className="rounded-2xl border border-slate-200 dark:border-slate-800 bg-white dark:bg-slate-900 p-5 space-y-4">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-2 font-semibold text-sm">
              <FolderUp className="w-4 h-4 text-emerald-600" />
              Option B — Unzipped Takeout Folder
            </div>
            <span className="text-[10px] font-semibold uppercase px-2 py-0.5 rounded-full bg-emerald-100 text-emerald-800 dark:bg-emerald-950 dark:text-emerald-300">
              Recommended
            </span>
          </div>
          <p className="text-xs text-slate-500">
            Select <code className="text-[11px]">Health Fitness Data_GoogleData/</code>,{" "}
            <code className="text-[11px]">Physical Activity_GoogleData/</code>, or{" "}
            <code className="text-[11px]">Stress Score/</code> for fast incremental GCS sync.
          </p>
          <input
            type="file"
            multiple
            // @ts-expect-error webkitdirectory is supported by Chromium/Safari/Firefox
            webkitdirectory=""
            onChange={(e) => setFolderFiles(Array.from(e.target.files || []))}
            className="block w-full text-xs text-slate-500 file:mr-3 file:py-2 file:px-3 file:rounded-lg file:border-0 file:bg-emerald-50 file:text-emerald-700 dark:file:bg-emerald-950 dark:file:text-emerald-300"
          />
          {folderFiles.length > 0 && (
            <div className="text-xs text-slate-600 dark:text-slate-300">
              Selected {folderFiles.length} files
              {uploadingKind === "folder" &&
                ` (${folderProgress.done}/${folderProgress.total} uploaded)`}
            </div>
          )}
          <button
            onClick={handleFolderUploadAndRun}
            disabled={folderFiles.length === 0 || uploadingKind !== null}
            className="w-full rounded-xl bg-emerald-600 hover:bg-emerald-700 disabled:opacity-40 text-white py-2 text-sm font-medium transition"
          >
            Upload Folder &amp; Run Incremental ETL
          </button>
        </div>

        {/* ReactHealth PDF Uploader */}
        <div className="rounded-2xl border border-slate-200 dark:border-slate-800 bg-white dark:bg-slate-900 p-5 space-y-4">
          <div className="flex items-center gap-2 font-semibold text-sm">
            <FileText className="w-4 h-4 text-indigo-600" />
            ReactHealth CPAP PDF Uploader
          </div>
          <p className="text-xs text-slate-500">
            Extracts Page 1 summary + nightly therapy rows. Skips &quot;No data received&quot; and preserves 00:00 sessions.
          </p>
          <input
            type="file"
            accept=".pdf,application/pdf"
            onChange={(e) => handleSelectPdf(e.target.files?.[0] || null)}
            className="block w-full text-xs text-slate-500 file:mr-3 file:py-2 file:px-3 file:rounded-lg file:border-0 file:bg-indigo-50 file:text-indigo-700 dark:file:bg-indigo-950 dark:file:text-indigo-300"
          />
          {pdfPreview && (
            <div className="rounded-lg bg-slate-50 dark:bg-slate-800/70 p-3 text-xs space-y-1">
              <div className="font-semibold text-slate-800 dark:text-slate-100">
                Preview: SN {String(pdfPreview.metadata.device_sn || "—")}
              </div>
              <div>
                Range: {String(pdfPreview.metadata.report_date_range_start || "—")} →{" "}
                {String(pdfPreview.metadata.report_date_range_end || "—")} (Gen:{" "}
                {String(pdfPreview.metadata.report_generated_date || "—")})
              </div>
              <div>
                Valid nights: <b>{pdfPreview.valid_days_count}</b> · No data days:{" "}
                <b>{pdfPreview.no_data_days_count}</b> · Adherence:{" "}
                <b>{String(pdfPreview.metadata.adherence_pct ?? "—")}%</b>
              </div>
            </div>
          )}
          <button
            onClick={handlePdfUploadAndRun}
            disabled={!pdfFile || uploadingKind !== null}
            className="w-full rounded-xl bg-indigo-600 hover:bg-indigo-700 disabled:opacity-40 text-white py-2 text-sm font-medium transition"
          >
            Upload PDF &amp; Run Incremental Load
          </button>
        </div>
      </div>

      {/* Live Pipeline Execution & Status Tracker */}
      <div className="rounded-2xl border border-slate-200 dark:border-slate-800 bg-white dark:bg-slate-900 p-5 space-y-4">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <div>
            <h2 className="text-base font-semibold">
              Live Pipeline Status (Upload → Bronze ETL → Dataform Silver/Gold)
            </h2>
            <p className="text-xs text-slate-500">
              {activeRun
                ? `Run ${activeRun.run_id} · Mode: ${activeRun.trigger_mode} · ${activeRun.current_stage}`
                : "No runs executed yet. Click 'Run ETL on Existing GCS Prefix' to perform initial historical load."}
            </p>
          </div>
          {activeRun && (
            <span
              className={`text-xs font-semibold px-3 py-1 rounded-full ${
                activeRun.status === "COMPLETED"
                  ? "bg-emerald-100 text-emerald-800 dark:bg-emerald-950 dark:text-emerald-300"
                  : activeRun.status === "FAILED"
                  ? "bg-rose-100 text-rose-800 dark:bg-rose-950 dark:text-rose-300"
                  : "bg-sky-100 text-sky-800 dark:bg-sky-950 dark:text-sky-300"
              }`}
            >
              {activeRun.status}
            </span>
          )}
        </div>

        {/* Stepper */}
        <div className="grid grid-cols-2 sm:grid-cols-6 gap-2">
          {PIPELINE_STAGES.map((st, idx) => {
            const done =
              activeRun?.status === "COMPLETED" ||
              (stageIndex >= 0 && idx < stageIndex);
            const active = activeRun?.status === st.key && st.key !== "COMPLETED";
            return (
              <div
                key={st.key}
                className={`rounded-xl border p-2.5 text-xs flex items-center gap-2 ${
                  done
                    ? "border-emerald-300 bg-emerald-50/70 dark:border-emerald-800 dark:bg-emerald-950/30"
                    : active
                    ? "border-sky-400 bg-sky-50/80 dark:border-sky-700 dark:bg-sky-950/40"
                    : "border-slate-200 dark:border-slate-800 opacity-60"
                }`}
              >
                {done ? (
                  <CheckCircle2 className="w-4 h-4 text-emerald-600 shrink-0" />
                ) : active ? (
                  <Loader2 className="w-4 h-4 text-sky-600 animate-spin shrink-0" />
                ) : (
                  <span className="w-4 h-4 rounded-full border border-slate-300 shrink-0" />
                )}
                <span className="font-medium leading-tight">{st.label}</span>
              </div>
            );
          })}
        </div>

        {activeRun && (
          <div className="space-y-3">
            <div className="grid grid-cols-2 sm:grid-cols-6 gap-3 text-xs">
              <div className="rounded-lg bg-slate-50 dark:bg-slate-800/60 p-2.5">
                <div className="text-slate-500">Scanned</div>
                <div className="text-base font-semibold">
                  {activeRun.files_scanned}/{activeRun.files_total}
                </div>
              </div>
              <div className="rounded-lg bg-slate-50 dark:bg-slate-800/60 p-2.5">
                <div className="text-slate-500">Loaded</div>
                <div className="text-base font-semibold text-emerald-600">
                  {activeRun.files_loaded}
                </div>
              </div>
              <div className="rounded-lg bg-slate-50 dark:bg-slate-800/60 p-2.5">
                <div className="text-slate-500">Skipped (Ledger)</div>
                <div className="text-base font-semibold">{activeRun.files_skipped}</div>
              </div>
              <div className="rounded-lg bg-slate-50 dark:bg-slate-800/60 p-2.5">
                <div className="text-slate-500">Failed</div>
                <div className="text-base font-semibold text-rose-600">
                  {activeRun.files_failed}
                </div>
              </div>
              <div className="rounded-lg bg-slate-50 dark:bg-slate-800/60 p-2.5">
                <div className="text-slate-500">Rows Inserted</div>
                <div className="text-base font-semibold">
                  {activeRun.rows_inserted.toLocaleString()}
                </div>
              </div>
              <div className="rounded-lg bg-slate-50 dark:bg-slate-800/60 p-2.5">
                <div className="text-slate-500">Dataform</div>
                <div className="text-sm font-semibold">
                  {activeRun.dataform_status || "PENDING"}
                </div>
              </div>
            </div>

            {activeRun.error_message && (
              <div className="rounded-lg bg-rose-50 dark:bg-rose-950/50 p-3 text-xs text-rose-700 dark:text-rose-300 font-mono">
                {activeRun.error_message}
              </div>
            )}

            {activeRun.table_stats &&
              Object.keys(activeRun.table_stats).length > 0 && (
                <div className="overflow-x-auto">
                  <table className="w-full text-xs text-left">
                    <thead>
                      <tr className="border-b border-slate-200 dark:border-slate-800 text-slate-500">
                        <th className="py-1.5 px-2">Bronze Table</th>
                        <th className="py-1.5 px-2">Files</th>
                        <th className="py-1.5 px-2">Staged</th>
                        <th className="py-1.5 px-2">Inserted</th>
                        <th className="py-1.5 px-2">Updated</th>
                      </tr>
                    </thead>
                    <tbody>
                      {Object.entries(activeRun.table_stats).map(([tbl, st]) => (
                        <tr
                          key={tbl}
                          className="border-b border-slate-100 dark:border-slate-800/60"
                        >
                          <td className="py-1.5 px-2 font-mono">{tbl}</td>
                          <td className="py-1.5 px-2">{st.files}</td>
                          <td className="py-1.5 px-2">{st.staged.toLocaleString()}</td>
                          <td className="py-1.5 px-2 text-emerald-600">
                            {st.inserted.toLocaleString()}
                          </td>
                          <td className="py-1.5 px-2">{st.updated.toLocaleString()}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}

            {activeRun.dataform_actions && activeRun.dataform_actions.length > 0 && (
              <div className="rounded-lg border border-slate-200 dark:border-slate-800 p-3">
                <div className="text-xs font-semibold mb-2">
                  Dataform Invocation Actions ({activeRun.dataform_invocation_id})
                </div>
                <div className="grid grid-cols-1 sm:grid-cols-2 gap-1.5 text-xs">
                  {activeRun.dataform_actions.map((act, idx) => (
                    <div
                      key={idx}
                      className="flex items-center justify-between bg-slate-50 dark:bg-slate-800/60 px-2.5 py-1.5 rounded"
                    >
                      <span className="font-mono truncate">{act.target}</span>
                      <span
                        className={
                          act.state === "SUCCEEDED"
                            ? "text-emerald-600 font-semibold"
                            : "text-amber-600 font-semibold"
                        }
                      >
                        {act.state}
                      </span>
                    </div>
                  ))}
                </div>
              </div>
            )}
          </div>
        )}
      </div>

      {/* Settings + Ledger + Connector Registry */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-5">
        {/* CPAP Start Date Config & Coverage */}
        <div className="rounded-2xl border border-slate-200 dark:border-slate-800 bg-white dark:bg-slate-900 p-5 space-y-4">
          <div className="flex items-center gap-2 font-semibold text-sm">
            <Settings2 className="w-4 h-4 text-sky-600" />
            CPAP Intervention Date &amp; Data Coverage
          </div>
          <div className="rounded-xl bg-slate-50 dark:bg-slate-800/60 p-3.5 text-xs space-y-2">
            <div className="flex justify-between">
              <span className="text-slate-500">Auto-detected first CPAP night:</span>
              <span className="font-mono font-semibold">{autoDetectedDate}</span>
            </div>
            <div className="flex justify-between">
              <span className="text-slate-500">Mode:</span>
              <span>{isManualOverride ? "Manual Override" : "Auto-detected"}</span>
            </div>
            <div className="flex flex-wrap items-center gap-2 pt-1">
              <input
                type="date"
                value={cpapStartDate}
                onChange={(e) => setCpapStartDate(e.target.value)}
                className="rounded-lg border border-slate-300 dark:border-slate-700 bg-white dark:bg-slate-950 px-2.5 py-1.5 text-xs"
              />
              <button
                onClick={() => handleSaveCpapDate(false)}
                disabled={savingSetting}
                className="rounded-lg bg-sky-600 hover:bg-sky-700 text-white px-3 py-1.5 text-xs font-medium"
              >
                Save Override
              </button>
              <button
                onClick={() => handleSaveCpapDate(true)}
                disabled={savingSetting}
                className="rounded-lg border border-slate-300 dark:border-slate-700 px-3 py-1.5 text-xs"
              >
                Reset to Auto
              </button>
            </div>
          </div>

          {ledger && (
            <div className="space-y-2 text-xs">
              <div className="font-semibold text-slate-700 dark:text-slate-200">
                Silver Date Coverage
              </div>
              <div className="grid grid-cols-2 gap-2">
                <div className="rounded-lg bg-slate-50 dark:bg-slate-800/50 p-2.5">
                  <div className="text-slate-500">Google Health Range</div>
                  <div className="font-mono">
                    {String(ledger.coverage.min_health_date || "—")} →{" "}
                    {String(ledger.coverage.max_health_date || "—")}
                  </div>
                </div>
                <div className="rounded-lg bg-slate-50 dark:bg-slate-800/50 p-2.5">
                  <div className="text-slate-500">CPAP Therapy Range</div>
                  <div className="font-mono">
                    {String(ledger.coverage.cpap_min_date || "—")} →{" "}
                    {String(ledger.coverage.cpap_max_date || "—")}
                  </div>
                </div>
              </div>
            </div>
          )}

          {/* Google Sheet Activities & Wake-Up Observations Sync */}
          <div className="rounded-xl border border-slate-200 dark:border-slate-800 bg-slate-50/70 dark:bg-slate-800/40 p-3.5 text-xs space-y-2">
            <div className="flex items-center justify-between gap-2">
              <span className="font-semibold text-slate-800 dark:text-slate-100">
                Google Sheet Journal &amp; Activities Sync
              </span>
              <button
                onClick={async () => {
                  setSyncingSheet(true);
                  setErrorMsg(null);
                  try {
                    const res = await api.syncGSheets();
                    setUploadStatusMsg(
                      `Synced ${res.observations.staged} daily journal rows & ${res.baseline_notes.staged} routine notes (Dataform: ${res.dataform_status}).`
                    );
                    await refreshAll();
                  } catch (err) {
                    setErrorMsg((err as Error).message);
                  } finally {
                    setSyncingSheet(false);
                  }
                }}
                disabled={syncingSheet}
                className="rounded-lg bg-indigo-600 hover:bg-indigo-700 disabled:opacity-50 text-white px-3 py-1.5 font-medium"
              >
                {syncingSheet ? "Syncing..." : "Sync Sheet & Rebuild Silver/Gold"}
              </button>
            </div>
            <div className="text-slate-500">
              Imports only <b>Activity Notes</b>, <b>Morning Coffee</b>, <b>Wake-Up Observations</b>, and <b>Notes</b> routines (official exports remain source of truth for health/CPAP numbers).
            </div>
            {gsStatus && (
              <div className="space-y-1 text-[11px] text-slate-500">
                <div>
                  Loaded: <b>{gsStatus.observation_rows}</b> nights ({gsStatus.min_date || "—"} → {gsStatus.max_date || "—"}) · <b>{gsStatus.baseline_note_rows}</b> baseline notes
                </div>
                <div className="font-mono break-all">
                  Share Sheet (Viewer) with: {gsStatus.web_service_account} &amp; {gsStatus.etl_service_account}
                </div>
              </div>
            )}
          </div>
        </div>

        {/* Pluggable Connector Registry */}
        <div className="rounded-2xl border border-slate-200 dark:border-slate-800 bg-white dark:bg-slate-900 p-5 space-y-3">
          <div className="flex items-center gap-2 font-semibold text-sm">
            <PlugZap className="w-4 h-4 text-emerald-600" />
            Pluggable Connector Registry
          </div>
          <div className="space-y-2.5">
            {connectors.map((c) => (
              <div
                key={c.name}
                className="rounded-xl border border-slate-200 dark:border-slate-800 p-3 text-xs space-y-1"
              >
                <div className="flex items-center justify-between">
                  <span className="font-semibold">{c.display_name}</span>
                  <span
                    className={`px-2 py-0.5 rounded-full text-[10px] font-semibold ${
                      c.status === "active"
                        ? "bg-emerald-100 text-emerald-800 dark:bg-emerald-950 dark:text-emerald-300"
                        : "bg-amber-100 text-amber-800 dark:bg-amber-950 dark:text-amber-300"
                    }`}
                  >
                    {c.status}
                  </span>
                </div>
                <p className="text-slate-500">{c.description}</p>
                <div className="text-[11px] font-mono text-slate-400">
                  Prefixes: {c.expected_prefixes.filter(Boolean).join(", ") || "root/*.pdf"}
                </div>
              </div>
            ))}
          </div>
        </div>
      </div>

      {/* Bronze Tables & Recent Runs */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-5">
        <div className="rounded-2xl border border-slate-200 dark:border-slate-800 bg-white dark:bg-slate-900 p-5 space-y-3">
          <div className="flex items-center gap-2 font-semibold text-sm">
            <Database className="w-4 h-4 text-sky-600" />
            Bronze Tables Inventory ({ledger?.bronze_tables.length || 0})
          </div>
          <div className="max-h-72 overflow-y-auto">
            <table className="w-full text-xs text-left">
              <thead>
                <tr className="border-b border-slate-200 dark:border-slate-800 text-slate-500">
                  <th className="py-1.5">Table</th>
                  <th className="py-1.5">Rows</th>
                  <th className="py-1.5">Size (MB)</th>
                </tr>
              </thead>
              <tbody>
                {(ledger?.bronze_tables || []).map((t) => (
                  <tr
                    key={String(t.table_id)}
                    className="border-b border-slate-100 dark:border-slate-800/60"
                  >
                    <td className="py-1.5 font-mono">{String(t.table_id)}</td>
                    <td className="py-1.5">{Number(t.row_count || 0).toLocaleString()}</td>
                    <td className="py-1.5">{String(t.size_mb ?? "0")}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>

        <div className="rounded-2xl border border-slate-200 dark:border-slate-800 bg-white dark:bg-slate-900 p-5 space-y-3">
          <h3 className="font-semibold text-sm">Recent ETL Runs</h3>
          <div className="max-h-72 overflow-y-auto space-y-2">
            {runs.map((r) => (
              <button
                key={r.run_id}
                onClick={() => setActiveRun(r)}
                className="w-full text-left rounded-xl border border-slate-200 dark:border-slate-800 hover:border-sky-500 p-3 text-xs flex items-center justify-between transition"
              >
                <div>
                  <div className="font-mono font-semibold">{r.run_id}</div>
                  <div className="text-slate-500">
                    {r.trigger_mode} · loaded {r.files_loaded} · skipped {r.files_skipped}
                  </div>
                </div>
                <span className="font-semibold">{r.status}</span>
              </button>
            ))}
          </div>
        </div>
      </div>
    </div>
  );
};
