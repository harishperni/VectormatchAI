"use client";

import { useMemo, useState } from "react";

import type { CandidateExplanation, ParsedResumeRow, RankingRow } from "@/lib/api";

type Props = {
  jobId: string;
  rows: RankingRow[];
  resumes: ParsedResumeRow[];
};

const PAGE_SIZE = 10;

function formatApplied(value?: string | null): string {
  if (!value) return "-";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "-";
  return date.toLocaleDateString();
}

export default function CandidateReviewWorkspace({ jobId, rows, resumes }: Props) {
  const [actionMessage, setActionMessage] = useState("Ready");
  const [page, setPage] = useState(1);
  const [selectedCandidateId, setSelectedCandidateId] = useState<string | null>(null);
  const [selectedResumeId, setSelectedResumeId] = useState<string | null>(null);
  const [selectedIds, setSelectedIds] = useState<string[]>([]);
  const [drawerLoading, setDrawerLoading] = useState(false);
  const [drawerError, setDrawerError] = useState<string | null>(null);
  const [explanation, setExplanation] = useState<CandidateExplanation | null>(null);

  const totalPages = Math.max(1, Math.ceil(rows.length / PAGE_SIZE));
  const currentPage = Math.min(page, totalPages);

  const pagedRows = useMemo(() => {
    const start = (currentPage - 1) * PAGE_SIZE;
    return rows.slice(start, start + PAGE_SIZE);
  }, [rows, currentPage]);

  const selectedRow = useMemo(
    () => rows.find((row) => row.candidate_id === selectedCandidateId && row.resume_id === selectedResumeId) ??
      rows.find((row) => row.candidate_id === selectedCandidateId) ??
      null,
    [rows, selectedCandidateId, selectedResumeId]
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
      const response = await fetch(`/api/jobs/${jobId}/candidates/actions`, {
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

  if (rows.length === 0) {
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
        <div className="flex items-center justify-between border-b border-slate-200 px-4 py-3">
          <div>
            <h2 className="font-heading text-xl font-semibold text-slate-900">Applicants</h2>
            <p className="text-xs text-slate-500">
              Showing {(currentPage - 1) * PAGE_SIZE + 1}-{Math.min(currentPage * PAGE_SIZE, rows.length)} of {rows.length}
            </p>
          </div>
          <div className="flex items-center gap-2">
            <button
              onClick={() => saveBulkAction("shortlisted")}
              className="rounded border border-emerald-300 px-2 py-1 text-xs font-semibold text-emerald-700"
            >
              Bulk Recommend
            </button>
            <button
              onClick={() => saveBulkAction("rejected")}
              className="rounded border border-rose-300 px-2 py-1 text-xs font-semibold text-rose-700"
            >
              Bulk Reject
            </button>
            <button
              onClick={() => saveBulkAction("shortlisted", "recommended_for_other_jobs")}
              className="rounded border border-violet-300 px-2 py-1 text-xs font-semibold text-violet-700"
            >
              Recommend Other Jobs
            </button>
            <p className="text-xs text-slate-500">{actionMessage}</p>
          </div>
        </div>

        <div className="max-h-[68vh] overflow-auto">
          <table className="w-full min-w-[1600px] border-collapse text-left text-sm">
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
                <th className="sticky left-0 z-30 border-b border-slate-200 bg-slate-50 px-3 py-2">Name</th>
                <th className="border-b border-slate-200 px-3 py-2">Type</th>
                <th className="border-b border-slate-200 px-3 py-2">Applied</th>
                <th className="border-b border-slate-200 px-3 py-2">Stage</th>
                <th className="border-b border-slate-200 px-3 py-2">Step</th>
                <th className="border-b border-slate-200 px-3 py-2">Current/Last Job</th>
                <th className="border-b border-slate-200 px-3 py-2">Relevant Experience</th>
                <th className="border-b border-slate-200 px-3 py-2">Highest Degree</th>
                <th className="border-b border-slate-200 px-3 py-2">Distance</th>
                <th className="border-b border-slate-200 px-3 py-2">Score</th>
                <th className="border-b border-slate-200 px-3 py-2">Audit</th>
                <th className="border-b border-slate-200 px-3 py-2">Actions</th>
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
                  <td className="sticky left-0 z-10 bg-white px-3 py-2 font-semibold text-slate-900 group-hover:bg-slate-50">
                    {row.candidate_name}
                  </td>
                  <td className="px-3 py-2 text-slate-700">{row.candidate_type ?? "External"}</td>
                  <td className="px-3 py-2 text-slate-700">{formatApplied(row.applied_at)}</td>
                  <td className="px-3 py-2 text-slate-700">{row.stage ?? row.action_status ?? "Review"}</td>
                  <td className="px-3 py-2 text-slate-700">{row.step ?? "Review"}</td>
                  <td className="px-3 py-2 text-slate-700">{row.current_last_job ?? "-"}</td>
                  <td className="px-3 py-2 text-slate-700">
                    {row.experience_years !== null && row.experience_years !== undefined
                      ? `${row.experience_years} years`
                      : "-"}
                  </td>
                  <td className="px-3 py-2 text-slate-700">{row.highest_degree ?? "-"}</td>
                  <td className="px-3 py-2 text-slate-700">
                    {row.distance_miles !== null && row.distance_miles !== undefined
                      ? `Under ${row.distance_miles} miles`
                      : "-"}
                  </td>
                  <td className="px-3 py-2 font-semibold text-slate-900">{row.score}%</td>
                  <td className="px-3 py-2 text-xs text-slate-700">
                    {row.audit_flags?.length ? row.audit_flags.join(" | ") : "OK"}
                  </td>
                  <td className="px-3 py-2" onClick={(e) => e.stopPropagation()}>
                    <div className="flex flex-wrap gap-1">
                      <button
                        onClick={() => saveAction(row.candidate_id, "shortlisted")}
                        className="rounded border border-emerald-300 px-2 py-0.5 text-xs font-semibold text-emerald-700"
                      >
                        Recommend
                      </button>
                      <button
                        onClick={() => saveAction(row.candidate_id, "interviewed")}
                        className="rounded border border-sky-300 px-2 py-0.5 text-xs font-semibold text-sky-700"
                      >
                        Contact
                      </button>
                      <button
                        onClick={() =>
                          saveAction(row.candidate_id, "shortlisted", "recommended_for_other_jobs")
                        }
                        className="rounded border border-violet-300 px-2 py-0.5 text-xs font-semibold text-violet-700"
                      >
                        Recommend Other Jobs
                      </button>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
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
                  <p className="text-sm text-slate-600">
                    Match {selectedRow?.score ?? "N/A"}% • Confidence {selectedRow?.confidence ?? "N/A"}%
                  </p>
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
                <p className="mt-2 text-sm text-slate-700">Candidate: {selectedRow?.candidate_name ?? "N/A"}</p>
                <p className="text-sm text-slate-700">Email: {selectedResume?.email ?? "N/A"}</p>
                <p className="text-sm text-slate-700">Resume File: {selectedResume?.source_filename ?? "N/A"}</p>
              </article>

              <article className="rounded-lg border border-slate-200 p-3">
                <p className="text-xs font-semibold uppercase tracking-wide text-slate-500">Summary</p>
                <p className="mt-2 text-sm text-slate-700">{explanation?.summary ?? "No summary available yet."}</p>
              </article>

              <article className="rounded-lg border border-slate-200 p-3">
                <p className="text-xs font-semibold uppercase tracking-wide text-slate-500">Score Breakdown</p>
                <div className="mt-2 grid gap-2 text-sm text-slate-700 sm:grid-cols-2">
                  <p>Semantic: {explanation?.score_breakdown?.semantic ?? "N/A"}</p>
                  <p>Skill: {explanation?.score_breakdown?.skill ?? "N/A"}</p>
                  <p>Experience: {explanation?.score_breakdown?.experience ?? "N/A"}</p>
                  <p>Domain: {explanation?.score_breakdown?.domain ?? "N/A"}</p>
                </div>
              </article>

              <article className="rounded-lg border border-slate-200 p-3">
                <p className="text-xs font-semibold uppercase tracking-wide text-slate-500">Matched Skills</p>
                <p className="mt-2 text-sm text-slate-700">
                  {explanation?.matched_skills?.length ? explanation.matched_skills.join(", ") : "None detected"}
                </p>
              </article>

              <article className="rounded-lg border border-slate-200 p-3">
                <p className="text-xs font-semibold uppercase tracking-wide text-slate-500">Missing Skills</p>
                <p className="mt-2 text-sm text-slate-700">
                  {explanation?.missing_skills?.length ? explanation.missing_skills.join(", ") : "None"}
                </p>
              </article>

              <article className="rounded-lg border border-slate-200 p-3">
                <p className="text-xs font-semibold uppercase tracking-wide text-slate-500">Explainability Audit</p>
                <p className="mt-2 text-sm text-slate-700">
                  {selectedRow?.audit_flags?.length ? selectedRow.audit_flags.join(" | ") : "No risk flags"}
                </p>
              </article>
            </div>
          </aside>
        </div>
      ) : null}
    </>
  );
}
