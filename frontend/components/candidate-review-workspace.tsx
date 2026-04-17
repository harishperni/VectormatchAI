"use client";

import { useMemo, useState } from "react";

import type { CandidateExplanation, ParsedResumeRow, RankingRow } from "@/lib/api";

type Props = {
  jobId: string;
  rows: RankingRow[];
  resumes: ParsedResumeRow[];
};

const PAGE_SIZE = 10;
const SCORE_BREAKDOWN_ORDER = [
  "semantic",
  "skill",
  "experience",
  "domain",
  "soft_skill",
  "managerial_skill",
  "distance_priority_bonus",
  "job_hopper_penalty",
  "anti_cheat_penalty",
] as const;

const SCORE_BREAKDOWN_LABELS: Record<string, string> = {
  semantic: "Semantic",
  skill: "Skill",
  experience: "Experience",
  domain: "Domain",
  soft_skill: "Soft Skill",
  managerial_skill: "Managerial Skill",
  distance_priority_bonus: "Distance Priority Bonus",
  job_hopper_penalty: "Job Hopper Penalty",
  anti_cheat_penalty: "Anti-Cheat Penalty",
};

function toBreakdownLabel(key: string): string {
  if (SCORE_BREAKDOWN_LABELS[key]) return SCORE_BREAKDOWN_LABELS[key];
  return key
    .split("_")
    .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
    .join(" ");
}

function scoreBreakdownEntries(scoreBreakdown: Record<string, number> | undefined): Array<[string, number]> {
  if (!scoreBreakdown) return [];

  const remaining = Object.keys(scoreBreakdown).filter((key) => !SCORE_BREAKDOWN_ORDER.includes(key as (typeof SCORE_BREAKDOWN_ORDER)[number]));
  const keys = [...SCORE_BREAKDOWN_ORDER, ...remaining];
  return keys
    .filter((key) => typeof scoreBreakdown[key] === "number")
    .map((key) => [key, Number(scoreBreakdown[key])]);
}

function formatApplied(value?: string | null): string {
  if (!value) return "-";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "-";
  return date.toLocaleDateString();
}

function mapActionToStage(action?: string | null): string {
  const normalized = (action || "").toLowerCase();
  if (normalized === "viewed") return "Review";
  if (normalized === "shortlisted") return "Shortlisted";
  if (normalized === "interviewed") return "Interview";
  if (normalized === "hired") return "Offer";
  if (normalized === "rejected") return "Rejected";
  return "New";
}

function stageBadgeClass(stage: string): string {
  const value = stage.toLowerCase();
  if (value === "shortlisted") return "border-emerald-200 bg-emerald-50 text-emerald-700";
  if (value === "interview") return "border-sky-200 bg-sky-50 text-sky-700";
  if (value === "offer") return "border-indigo-200 bg-indigo-50 text-indigo-700";
  if (value === "rejected") return "border-rose-200 bg-rose-50 text-rose-700";
  if (value === "review") return "border-amber-200 bg-amber-50 text-amber-700";
  return "border-slate-200 bg-slate-50 text-slate-700";
}

function scoreBadgeClass(score?: number | null): string {
  if (score === null || score === undefined) return "border-slate-200 bg-slate-50 text-slate-700";
  if (score >= 80) return "border-emerald-200 bg-emerald-50 text-emerald-700";
  if (score >= 65) return "border-amber-200 bg-amber-50 text-amber-700";
  return "border-rose-200 bg-rose-50 text-rose-700";
}

function isAntiCheatFlagged(row: RankingRow): boolean {
  const score = Number(row.anti_cheat_score ?? 0);
  return Number.isFinite(score) && score > 10;
}

export default function CandidateReviewWorkspace({ jobId, rows, resumes }: Props) {
  const [actionMessage, setActionMessage] = useState("Ready");
  const [page, setPage] = useState(1);
  const [showUnflaggedOnly, setShowUnflaggedOnly] = useState(true);
  const [selectedCandidateId, setSelectedCandidateId] = useState<string | null>(null);
  const [selectedResumeId, setSelectedResumeId] = useState<string | null>(null);
  const [selectedIds, setSelectedIds] = useState<string[]>([]);
  const [drawerLoading, setDrawerLoading] = useState(false);
  const [drawerError, setDrawerError] = useState<string | null>(null);
  const [explanation, setExplanation] = useState<CandidateExplanation | null>(null);

  const visibleRows = useMemo(
    () => (showUnflaggedOnly ? rows.filter((row) => !isAntiCheatFlagged(row)) : rows),
    [rows, showUnflaggedOnly]
  );

  const totalPages = Math.max(1, Math.ceil(visibleRows.length / PAGE_SIZE));
  const currentPage = Math.min(page, totalPages);

  const pagedRows = useMemo(() => {
    const start = (currentPage - 1) * PAGE_SIZE;
    return visibleRows.slice(start, start + PAGE_SIZE);
  }, [visibleRows, currentPage]);

  const selectedRow = useMemo(
    () => visibleRows.find((row) => row.candidate_id === selectedCandidateId && row.resume_id === selectedResumeId) ??
      visibleRows.find((row) => row.candidate_id === selectedCandidateId) ??
      null,
    [visibleRows, selectedCandidateId, selectedResumeId]
  );

  const selectedResume = useMemo(
    () => resumes.find((item) => item.resume_id === selectedRow?.resume_id) ?? null,
    [resumes, selectedRow?.resume_id]
  );

  async function saveAction(candidateId: string, action: string, notes?: string) {
    setActionMessage(`Saving ${action}...`);
    try {
      const response = await fetch(`/api/jobs/${jobId}/candidates/${candidateId}/action`, {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ action, notes }),
      });
      if (!response.ok) {
        setActionMessage(`Failed to save ${action}.`);
        return;
      }
      setActionMessage(`Saved action: ${action}`);
    } catch {
      setActionMessage(`Failed to save ${action}.`);
    }
  }

  async function saveBulkAction(action: string, notes?: string) {
    if (!selectedIds.length) {
      setActionMessage("Select at least one candidate first.");
      return;
    }
    setActionMessage(`Saving ${action} for ${selectedIds.length} candidates...`);
    try {
      const response = await fetch(`/api/jobs/${jobId}/candidates/bulk-actions`, {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ candidate_ids: selectedIds, action, notes }),
      });
      if (!response.ok) {
        setActionMessage(`Failed to save bulk ${action}.`);
        return;
      }
      setActionMessage(`Saved ${action} for ${selectedIds.length} candidates.`);
    } catch {
      setActionMessage(`Failed to save bulk ${action}.`);
    }
  }

  function toggleSelected(candidateId: string) {
    setSelectedIds((prev) =>
      prev.includes(candidateId) ? prev.filter((id) => id !== candidateId) : [...prev, candidateId]
    );
  }

  function togglePageSelected() {
    const pageIds = pagedRows.map((row) => row.candidate_id);
    const allSelected = pageIds.every((id) => selectedIds.includes(id));
    if (allSelected) {
      setSelectedIds((prev) => prev.filter((id) => !pageIds.includes(id)));
      return;
    }
    setSelectedIds((prev) => Array.from(new Set([...prev, ...pageIds])));
  }

  async function openCandidateDrawer(candidateId: string, resumeId: string) {
    setSelectedCandidateId(candidateId);
    setSelectedResumeId(resumeId);
    setDrawerLoading(true);
    setDrawerError(null);
    setExplanation(null);

    try {
      const response = await fetch(`/api/jobs/${jobId}/candidates/${candidateId}/explanation`, {
        cache: "no-store",
      });
      const payload = await response.json();
      if (!response.ok) {
        setDrawerError(payload?.detail ?? "Could not load candidate details.");
      } else {
        setExplanation(payload as CandidateExplanation);
      }
    } catch {
      setDrawerError("Could not load candidate details.");
    } finally {
      setDrawerLoading(false);
    }
  }

  function closeDrawer() {
    setSelectedCandidateId(null);
    setSelectedResumeId(null);
    setExplanation(null);
    setDrawerError(null);
  }

  if (visibleRows.length === 0) {
    return (
      <section className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">
        <h2 className="font-heading text-xl font-semibold">Applicants</h2>
        <p className="mt-3 rounded-lg border border-dashed border-slate-300 bg-slate-50 p-4 text-slate-600">
          No candidates found for current filters.
        </p>
      </section>
    );
  }

  return (
    <>
      <section className="rounded-2xl border border-slate-200 bg-white shadow-sm">
        <div className="space-y-3 border-b border-slate-200 px-4 py-3">
          <div className="flex flex-wrap items-center justify-between gap-2">
          <div>
            <h2 className="font-heading text-xl font-semibold text-slate-900">Applicants</h2>
            <p className="text-xs text-slate-500">
              Showing {(currentPage - 1) * PAGE_SIZE + 1}-{Math.min(currentPage * PAGE_SIZE, visibleRows.length)} of {visibleRows.length}
            </p>
          </div>
          <p className="text-xs text-slate-500">{selectedIds.length} selected</p>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <button
              onClick={() => saveBulkAction("shortlisted")}
              className="rounded-lg border border-emerald-300 px-2.5 py-1 text-xs font-semibold text-emerald-700"
            >
              Bulk Recommend
            </button>
            <button
              onClick={() => saveBulkAction("rejected")}
              className="rounded-lg border border-rose-300 px-2.5 py-1 text-xs font-semibold text-rose-700"
            >
              Bulk Reject
            </button>
            <button
              onClick={() => saveBulkAction("shortlisted", "recommended_for_other_jobs")}
              className="rounded-lg border border-violet-300 px-2.5 py-1 text-xs font-semibold text-violet-700"
            >
              Bulk Recommend Other Jobs
            </button>
            <label className="ml-2 inline-flex items-center gap-2 rounded-lg border border-slate-300 bg-slate-50 px-2.5 py-1 text-xs font-semibold text-slate-700">
              <input
                type="checkbox"
                checked={showUnflaggedOnly}
                onChange={(event) => {
                  setPage(1);
                  setShowUnflaggedOnly(event.target.checked);
                }}
                aria-label="Show unflagged only"
              />
              Unflagged only (anti-fraud ≤ 10)
            </label>
          </div>
          <p className="text-xs text-slate-500">{actionMessage}</p>
        </div>

        <div className="max-h-[68vh] overflow-y-auto">
          <div className="w-full overflow-x-auto overscroll-x-contain">
            <table className="w-full min-w-[1120px] border-collapse text-left text-sm xl:min-w-[1200px]">
              <thead className="sticky top-0 z-20 bg-slate-50 text-[11px] uppercase tracking-wide text-slate-500">
                <tr>
                  <th className="border-b border-slate-200 px-3 py-2">
                    <input
                      type="checkbox"
                      checked={pagedRows.length > 0 && pagedRows.every((row) => selectedIds.includes(row.candidate_id))}
                      onChange={togglePageSelected}
                      aria-label="Select page candidates"
                    />
                  </th>
                  <th className="sticky left-0 z-30 w-[180px] border-b border-slate-200 bg-slate-50 px-3 py-2">Name</th>
                  <th className="hidden border-b border-slate-200 px-3 py-2 2xl:table-cell">Type</th>
                  <th className="border-b border-slate-200 px-3 py-2">Applied</th>
                  <th className="border-b border-slate-200 px-3 py-2">Stage</th>
                  <th className="border-b border-slate-200 px-3 py-2">Current/Last Job</th>
                  <th className="border-b border-slate-200 px-3 py-2">Relevant Experience</th>
                  <th className="border-b border-slate-200 px-3 py-2">Highest Degree</th>
                  <th className="border-b border-slate-200 px-3 py-2">Distance</th>
                  <th className="border-b border-slate-200 px-3 py-2">Score</th>
                  <th className="hidden w-[360px] border-b border-slate-200 px-3 py-2 lg:table-cell">Audit</th>
                  <th className="sticky right-0 z-30 border-b border-slate-200 bg-slate-50 px-3 py-2">Actions</th>
                </tr>
              </thead>
              <tbody>
                {pagedRows.map((row) => (
                  <tr
                    key={`${row.candidate_id}-${row.resume_id}`}
                    className="group cursor-pointer border-b border-slate-100 hover:bg-slate-50"
                    onClick={() => openCandidateDrawer(row.candidate_id, row.resume_id)}
                  >
                    <td className="px-3 py-2" onClick={(e) => e.stopPropagation()}>
                      <input
                        type="checkbox"
                        checked={selectedIds.includes(row.candidate_id)}
                        onChange={() => toggleSelected(row.candidate_id)}
                        aria-label={`Select ${row.candidate_name}`}
                      />
                    </td>
                    <td className="sticky left-0 z-10 w-[180px] bg-white px-3 py-2 font-semibold text-slate-900 group-hover:bg-slate-50">
                      <p className="line-clamp-2 break-words">{row.candidate_name}</p>
                    </td>
                    <td className="hidden px-3 py-2 text-slate-700 2xl:table-cell">{row.candidate_type ?? "External"}</td>
                    <td className="px-3 py-2 text-slate-700">{formatApplied(row.applied_at)}</td>
                    <td className="px-3 py-2 text-slate-700">
                      <span className={`inline-flex rounded-full border px-2 py-0.5 text-[11px] font-semibold ${stageBadgeClass(mapActionToStage(row.action_status))}`}>
                        {mapActionToStage(row.action_status)}
                      </span>
                    </td>
                    <td className="px-3 py-2 text-slate-700">{row.current_last_job ?? "-"}</td>
                    <td className="px-3 py-2 text-slate-700">
                      {row.experience_years !== null && row.experience_years !== undefined
                        ? `${row.experience_years} years`
                        : "-"}
                    </td>
                    <td className="px-3 py-2 text-slate-700">{row.highest_degree ?? "-"}</td>
                    <td className="px-3 py-2 text-slate-700">
                      {row.distance_miles !== null && row.distance_miles !== undefined
                        ? `${Math.trunc(row.distance_miles)} miles`
                        : "-"}
                    </td>
                    <td className="px-3 py-2 font-semibold text-slate-900">
                      <span className={`inline-flex rounded-full border px-2 py-0.5 text-[11px] font-semibold ${scoreBadgeClass(row.score)}`}>
                        {row.score}%
                      </span>
                    </td>
                    <td className="hidden w-[360px] px-3 py-2 text-xs text-slate-700 lg:table-cell">
                      <div className="max-w-[340px] space-y-1">
                        <p className="font-medium text-slate-800">
                          {row.audit_summary ?? (row.audit_flags?.length ? row.audit_flags[0] : "OK")}
                        </p>
                        <p className="text-[11px] text-slate-500">
                          Anti-fraud score: {Number(row.anti_cheat_score ?? 0).toFixed(1)}
                        </p>
                        {row.audit_detail?.length ? (
                          <p className="line-clamp-3 text-[11px] leading-4 text-slate-500">
                            {row.audit_detail.join(" | ")}
                          </p>
                        ) : row.audit_flags?.length ? (
                          <p className="line-clamp-3 text-[11px] leading-4 text-slate-500">
                            {row.audit_flags.join(" | ")}
                          </p>
                        ) : null}
                      </div>
                    </td>
                    <td className="sticky right-0 z-10 bg-white px-3 py-2 group-hover:bg-slate-50" onClick={(e) => e.stopPropagation()}>
                      <div className="flex flex-wrap gap-1">
                        <button
                          onClick={() => saveAction(row.candidate_id, "shortlisted")}
                          className="rounded border border-emerald-300 px-2 py-0.5 text-[11px] font-semibold text-emerald-700"
                        >
                          Recommend
                        </button>
                        <button
                          onClick={() => saveAction(row.candidate_id, "interviewed")}
                          className="rounded border border-sky-300 px-2 py-0.5 text-[11px] font-semibold text-sky-700"
                        >
                          Contact
                        </button>
                        <button
                          onClick={() =>
                            saveAction(row.candidate_id, "shortlisted", "recommended_for_other_jobs")
                          }
                          className="rounded border border-violet-300 px-2 py-0.5 text-[11px] font-semibold text-violet-700"
                        >
                          Other Jobs
                        </button>
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>

        <div className="flex items-center justify-between border-t border-slate-200 px-4 py-3 text-sm">
          <p className="text-slate-600">
            Page {currentPage} of {totalPages}
          </p>
          <div className="flex gap-2">
            <button
              onClick={() => setPage((prev) => Math.max(1, prev - 1))}
              disabled={currentPage === 1}
              className="rounded border border-slate-300 px-3 py-1 disabled:opacity-40"
            >
              Previous
            </button>
            <button
              onClick={() => setPage((prev) => Math.min(totalPages, prev + 1))}
              disabled={currentPage === totalPages}
              className="rounded border border-slate-300 px-3 py-1 disabled:opacity-40"
            >
              Next
            </button>
          </div>
        </div>
      </section>

      {selectedCandidateId ? (
        <div className="fixed inset-0 z-50 flex justify-end bg-slate-900/35">
          <button className="h-full flex-1 cursor-default" onClick={closeDrawer} aria-label="Close overlay" />
          <aside className="h-full w-full max-w-2xl overflow-y-auto bg-white shadow-2xl">
            <div className="sticky top-0 z-10 border-b border-slate-200 bg-white px-5 py-4">
              <div className="flex items-start justify-between gap-3">
                <div>
                  <h3 className="font-heading text-2xl font-semibold text-slate-900">
                    {selectedRow?.candidate_name ?? "Candidate Profile"}
                  </h3>
                  <div className="mt-1 flex flex-wrap items-center gap-2">
                    <span className={`inline-flex rounded-full border px-2 py-0.5 text-xs font-semibold ${scoreBadgeClass(selectedRow?.score)}`}>
                      Match {selectedRow?.score ?? "N/A"}%
                    </span>
                    <span className="inline-flex rounded-full border border-slate-200 bg-slate-50 px-2 py-0.5 text-xs font-semibold text-slate-700">
                      Confidence {selectedRow?.confidence ?? "N/A"}%
                    </span>
                  </div>
                </div>
                <button onClick={closeDrawer} className="rounded border border-slate-300 px-3 py-1 text-sm">
                  Close
                </button>
              </div>
            </div>

            <div className="space-y-4 px-5 py-4">
              {drawerLoading ? <p className="text-sm text-slate-600">Loading profile...</p> : null}
              {drawerError ? (
                <p className="rounded border border-amber-200 bg-amber-50 p-3 text-sm text-amber-900">
                  {drawerError}
                </p>
              ) : null}

              <article className="rounded-lg border border-slate-200 p-3">
                <p className="text-xs font-semibold uppercase tracking-wide text-slate-500">Personal Details</p>
                <div className="mt-2 grid gap-2 text-sm text-slate-700 sm:grid-cols-2">
                  <p>Candidate: {selectedRow?.candidate_name ?? "N/A"}</p>
                  <p>Email: {selectedResume?.email ?? "N/A"}</p>
                  <p className="sm:col-span-2">Resume File: {selectedResume?.source_filename ?? "N/A"}</p>
                </div>
              </article>

              <article className="rounded-lg border border-slate-200 p-3">
                <p className="text-xs font-semibold uppercase tracking-wide text-slate-500">Summary</p>
                <p className="mt-2 text-sm text-slate-700">{explanation?.summary ?? "No summary available yet."}</p>
              </article>

              <article className="rounded-lg border border-slate-200 p-3">
                <p className="text-xs font-semibold uppercase tracking-wide text-slate-500">Why Ranked</p>
                <ul className="mt-2 list-disc space-y-1 pl-5 text-sm text-slate-700">
                  {(explanation?.top_reasons?.length ? explanation.top_reasons : selectedRow?.top_reasons || []).map(
                    (reason, idx) => (
                      <li key={`reason-${idx}`}>{reason}</li>
                    )
                  )}
                  {!(explanation?.top_reasons?.length || selectedRow?.top_reasons?.length) ? (
                    <li>No explicit ranking reasons available yet.</li>
                  ) : null}
                </ul>
              </article>

              <article className="rounded-lg border border-slate-200 p-3">
                <p className="text-xs font-semibold uppercase tracking-wide text-slate-500">Score Breakdown</p>
                <div className="mt-2 grid gap-2 text-sm text-slate-700 sm:grid-cols-2">
                  {scoreBreakdownEntries(explanation?.score_breakdown).map(([key, value]) => (
                    <p key={`score-breakdown-${key}`}>
                      {toBreakdownLabel(key)}: {value}
                    </p>
                  ))}
                  {!scoreBreakdownEntries(explanation?.score_breakdown).length ? <p>N/A</p> : null}
                </div>
              </article>

              <article className="rounded-lg border border-slate-200 p-3">
                <p className="text-xs font-semibold uppercase tracking-wide text-slate-500">Score Comparison</p>
                <div className="mt-2 grid gap-2 text-sm text-slate-700 sm:grid-cols-3">
                  <p>Ranking Score: {selectedRow?.score ?? "N/A"}</p>
                  <p>LLM Score: {explanation?.llm_score ?? "N/A"}</p>
                  <p>
                    Delta:{" "}
                    {selectedRow?.score !== undefined &&
                    explanation?.llm_score !== undefined &&
                    explanation?.llm_score !== null
                      ? (explanation.llm_score - selectedRow.score).toFixed(2)
                      : "N/A"}
                  </p>
                </div>
              </article>

              <article className="rounded-lg border border-slate-200 p-3">
                <p className="text-xs font-semibold uppercase tracking-wide text-slate-500">Skills Fit</p>
                <div className="mt-2 grid gap-3 sm:grid-cols-2">
                  <div>
                    <p className="text-xs font-semibold text-slate-600">Matched</p>
                    <p className="mt-1 text-sm text-slate-700">
                      {explanation?.matched_skills?.length ? explanation.matched_skills.join(", ") : "None detected"}
                    </p>
                  </div>
                  <div>
                    <p className="text-xs font-semibold text-slate-600">Missing</p>
                    <p className="mt-1 text-sm text-slate-700">
                      {explanation?.missing_skills?.length ? explanation.missing_skills.join(", ") : "None"}
                    </p>
                  </div>
                </div>
              </article>

              <article className="rounded-lg border border-slate-200 p-3">
                <p className="text-xs font-semibold uppercase tracking-wide text-slate-500">Evidence Snippets</p>
                <div className="mt-2 space-y-2">
                  {explanation?.evidence_snippets?.length ? (
                    explanation.evidence_snippets.map((snippet, idx) => (
                      <div key={`evidence-${idx}`} className="rounded border border-slate-200 bg-slate-50 p-2 text-sm">
                        <p className="font-semibold text-slate-800">{snippet.label}</p>
                        <p className="mt-1 text-slate-700">{snippet.text}</p>
                      </div>
                    ))
                  ) : (
                    <p className="text-sm text-slate-700">No evidence snippets available yet.</p>
                  )}
                </div>
              </article>

              <article className="rounded-lg border border-slate-200 p-3">
                <p className="text-xs font-semibold uppercase tracking-wide text-slate-500">Confidence Reasoning</p>
                <p className="mt-2 text-sm text-slate-700">
                  {explanation?.confidence_reasoning ?? "No confidence narrative available yet."}
                </p>
              </article>

              <article className="rounded-lg border border-slate-200 p-3">
                <p className="text-xs font-semibold uppercase tracking-wide text-slate-500">Explainability Audit</p>
                <p className="mt-2 text-sm text-slate-700">
                  {selectedRow?.audit_flags?.length ? selectedRow.audit_flags.join(" | ") : "No risk flags"}
                </p>
                <p className="mt-2 text-sm text-slate-700">
                  Anti-fraud score: {Number(explanation?.anti_cheat_score ?? selectedRow?.anti_cheat_score ?? 0).toFixed(1)}
                </p>
                {explanation?.anti_cheat_breakdown?.length ? (
                  <div className="mt-3 space-y-2">
                    <p className="text-xs font-semibold uppercase tracking-wide text-slate-500">
                      Anti-Fraud Score Breakdown
                    </p>
                    {explanation.anti_cheat_breakdown.map((item, idx) => (
                      <div key={`anti-cheat-breakdown-${idx}`} className="rounded border border-slate-200 bg-slate-50 p-2">
                        <p className="text-sm font-semibold text-slate-800">
                          +{Number(item.points ?? 0).toFixed(1)} {item.rule ?? "rule"}
                        </p>
                        <p className="mt-1 text-xs text-slate-600">{item.evidence ?? "No evidence text"}</p>
                      </div>
                    ))}
                  </div>
                ) : null}
              </article>
            </div>
          </aside>
        </div>
      ) : null}
    </>
  );
}
