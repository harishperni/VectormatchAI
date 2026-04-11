"use client";

import { useEffect, useRef, useState } from "react";

import CandidatePipelineBoard from "@/components/candidate-pipeline-board";
import Link from "next/link";

import CandidateDashboardTab from "@/components/candidate-dashboard-tab";
import CandidateReviewWorkspace from "@/components/candidate-review-workspace";
import InterviewTasksTab from "@/components/interview-tasks-tab";
import ParsedResumesTable from "@/components/parsed-resumes-table";
import QualityEvaluationTab from "@/components/quality-evaluation-tab";
import ResumeUploadPanel from "@/components/resume-upload-panel";
import type { ParsedResumeRow, RankingRow } from "@/lib/api";

export default function JobWorkspace({
  jobId,
  rankings,
  resumes,
}: {
  jobId: string;
  rankings: RankingRow[];
  resumes: ParsedResumeRow[];
}) {
  const [localRankings, setLocalRankings] = useState<RankingRow[]>(rankings);
  const [localResumes, setLocalResumes] = useState<ParsedResumeRow[]>(resumes);
  const [showPipeline, setShowPipeline] = useState(false);
  const [activeTab, setActiveTab] = useState<"workspace" | "dashboard" | "tasks" | "quality">("workspace");
  const storageKey = `ats:job:${jobId}:showKanban`;
  const tabStorageKey = `ats:job:${jobId}:activeTab`;
  const [refreshing, setRefreshing] = useState(false);
  const refreshTimer = useRef<number | null>(null);

  useEffect(() => {
    try {
      const saved = window.localStorage.getItem(storageKey);
      if (saved === "true") {
        setShowPipeline(true);
      }
      const savedTab = window.localStorage.getItem(tabStorageKey);
      if (savedTab === "dashboard" || savedTab === "tasks" || savedTab === "quality") {
        setActiveTab(savedTab);
      }
    } catch {
      // ignore storage errors
    }
  }, [storageKey, tabStorageKey]);

  useEffect(() => {
    setLocalRankings(rankings);
  }, [rankings]);

  useEffect(() => {
    setLocalResumes(resumes);
  }, [resumes]);

  async function refreshRankings() {
    setRefreshing(true);
    try {
      const response = await fetch(`/api/jobs/${jobId}/rankings`, { cache: "no-store" });
      if (!response.ok) {
        return;
      }
      const payload = await response.json();
      if (payload?.items) {
        setLocalRankings(payload.items);
      }
    } finally {
      setRefreshing(false);
    }
  }

  async function refreshResumes() {
    try {
      const response = await fetch(`/api/jobs/${jobId}/resumes`, { cache: "no-store" });
      if (!response.ok) {
        return;
      }
      const payload = await response.json();
      if (payload?.items) {
        setLocalResumes(payload.items);
      }
    } catch {
      // ignore refresh failures
    }
  }

  async function refreshWorkspace() {
    await Promise.all([refreshRankings(), refreshResumes()]);
  }

  useEffect(() => {
    if (!showPipeline) {
      return;
    }
    if (refreshTimer.current) {
      window.clearInterval(refreshTimer.current);
    }
    refreshTimer.current = window.setInterval(() => {
      void refreshRankings();
    }, 2000);
    return () => {
      if (refreshTimer.current) {
        window.clearInterval(refreshTimer.current);
        refreshTimer.current = null;
      }
    };
  }, [showPipeline]);

  useEffect(() => {
    const hasPending = localResumes.some((row) => (row.parse_status || "").toLowerCase() === "pending");
    if (!hasPending) {
      return;
    }

    const timer = window.setInterval(() => {
      void refreshResumes();
    }, 2000);

    return () => window.clearInterval(timer);
  }, [localResumes, jobId]);

  return (
    <div className="min-w-0 space-y-4 overflow-x-hidden">
      <header className="flex flex-wrap items-center justify-between gap-3 rounded-2xl border border-slate-200 bg-white px-4 py-3 shadow-sm">
        <div>
          <p className="text-xs uppercase tracking-wide text-slate-500">Workspace</p>
          <p className="text-sm text-slate-600">
            View: {activeTab === "tasks" ? "Interview Tasks" : activeTab === "quality" ? "Quality Metrics" : showPipeline ? "Kanban + Table" : "Table only"}
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <div className="inline-flex rounded-lg border border-slate-200 bg-slate-50 p-1">
            <button
              onClick={() => {
                setActiveTab("workspace");
                try {
                  window.localStorage.setItem(tabStorageKey, "workspace");
                } catch {
                  // ignore storage errors
                }
              }}
              className={`rounded-md px-3 py-1.5 text-sm font-semibold ${
                activeTab === "workspace" ? "bg-white text-slate-900 shadow-sm" : "text-slate-600"
              }`}
            >
              Workspace
            </button>
            <button
              onClick={() => {
                setActiveTab("dashboard");
                try {
                  window.localStorage.setItem(tabStorageKey, "dashboard");
                } catch {
                  // ignore storage errors
                }
              }}
              className={`rounded-md px-3 py-1.5 text-sm font-semibold ${
                activeTab === "dashboard" ? "bg-white text-slate-900 shadow-sm" : "text-slate-600"
              }`}
            >
              Dashboard
            </button>
            <button
              onClick={() => {
                setActiveTab("tasks");
                try {
                  window.localStorage.setItem(tabStorageKey, "tasks");
                } catch {
                  // ignore storage errors
                }
              }}
              className={`rounded-md px-3 py-1.5 text-sm font-semibold ${
                activeTab === "tasks" ? "bg-white text-slate-900 shadow-sm" : "text-slate-600"
              }`}
            >
              Tasks
            </button>
            <button
              onClick={() => {
                setActiveTab("quality");
                try {
                  window.localStorage.setItem(tabStorageKey, "quality");
                } catch {
                  // ignore storage errors
                }
              }}
              className={`rounded-md px-3 py-1.5 text-sm font-semibold ${
                activeTab === "quality" ? "bg-white text-slate-900 shadow-sm" : "text-slate-600"
              }`}
            >
              Quality
            </button>
          </div>
          <button
            onClick={() =>
              setShowPipeline((prev) => {
                const next = !prev;
                try {
                  window.localStorage.setItem(storageKey, String(next));
                } catch {
                  // ignore storage errors
                }
                return next;
              })
            }
            className="rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm font-semibold text-slate-700"
          >
            {showPipeline ? "Hide Kanban" : "Show Kanban"}
          </button>
          <button
            onClick={refreshWorkspace}
            disabled={refreshing}
            className="rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm font-semibold text-slate-700 disabled:opacity-60"
          >
            {refreshing ? "Refreshing..." : "Refresh"}
          </button>
          <Link
            href={`/jobs/${jobId}/evaluation`}
            className="rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm font-semibold text-slate-700"
          >
            Evaluation
          </Link>
        </div>
      </header>

      {activeTab === "tasks" ? (
        <InterviewTasksTab jobId={jobId} />
      ) : activeTab === "dashboard" ? (
        <CandidateDashboardTab rows={localRankings} />
      ) : activeTab === "quality" ? (
        <QualityEvaluationTab jobId={jobId} />
      ) : (
        <>
          {!showPipeline ? <ResumeUploadPanel jobId={jobId} /> : null}
          {showPipeline ? (
            <CandidatePipelineBoard
              jobId={jobId}
              rows={localRankings}
              onActionUpdated={(candidateId, action) => {
                setLocalRankings((prev) =>
                  prev.map((row) =>
                    row.candidate_id === candidateId
                      ? { ...row, action_status: action === "reset" ? null : action }
                      : row
                  )
                );
              }}
            />
          ) : (
            <>
              <CandidateReviewWorkspace jobId={jobId} rows={localRankings} resumes={localResumes} />
              <ParsedResumesTable jobId={jobId} rows={localResumes} onDeleted={refreshWorkspace} />
            </>
          )}
        </>
      )}
    </div>
  );
}
