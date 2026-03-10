"use client";

import { useState } from "react";

import { type ParsedResumeRow } from "@/lib/api";

type Props = {
  jobId: string;
  rows: ParsedResumeRow[];
  onDeleted?: () => Promise<void> | void;
};

type ResumeDetail = {
  resume_id: string;
  candidate_name: string;
  parse_status: string;
  parse_error: string | null;
  source_filename: string | null;
  parsed_json: Record<string, unknown>;
  raw_text: string;
};

function statusClass(status: ParsedResumeRow["parse_status"]): string {
  if (status === "parsed") return "bg-emerald-50 text-emerald-700 border-emerald-200";
  if (status === "failed") return "bg-rose-50 text-rose-700 border-rose-200";
  return "bg-amber-50 text-amber-700 border-amber-200";
}

export default function ParsedResumesTable({ jobId, rows, onDeleted }: Props) {
  const [selected, setSelected] = useState<ResumeDetail | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [deletingResumeId, setDeletingResumeId] = useState<string | null>(null);
  const [deleteMessage, setDeleteMessage] = useState<string | null>(null);

  async function openParsedResume(resumeId: string) {
    setLoading(true);
    setError(null);
    setSelected(null);
    try {
      const response = await fetch(`/api/jobs/${jobId}/resumes/${resumeId}`, {
        cache: "no-store",
      });
      const payload = await response.json();
      if (!response.ok) {
        setError(payload?.detail ?? "Could not load parsed resume details.");
      } else {
        setSelected(payload as ResumeDetail);
      }
    } catch {
      setError("Could not load parsed resume details.");
    } finally {
      setLoading(false);
    }
  }

  async function deleteResume(resumeId: string) {
    const proceed = window.confirm("Delete this resume from the job?");
    if (!proceed) return;

    setDeletingResumeId(resumeId);
    setDeleteMessage(null);
    try {
      const response = await fetch(`/api/jobs/${jobId}/resumes/${resumeId}`, {
        method: "DELETE",
      });
      const payload = await response.json().catch(() => ({}));
      if (!response.ok) {
        setDeleteMessage(payload?.detail ?? "Could not delete resume.");
        return;
      }
      setDeleteMessage("Resume deleted.");
      if (selected?.resume_id === resumeId) {
        setSelected(null);
      }
      await onDeleted?.();
    } catch {
      setDeleteMessage("Could not delete resume.");
    } finally {
      setDeletingResumeId(null);
    }
  }

  return (
    <section className="rounded-2xl border border-slate-200 bg-white p-4 shadow-sm">
      <div className="mb-3 flex items-center justify-between">
        <h2 className="font-heading text-xl font-semibold text-ink">Parsed Resumes</h2>
        <span className="rounded-full bg-slate-100 px-3 py-1 text-xs font-semibold text-slate-700">
          {rows.length} total
        </span>
      </div>

      {rows.length === 0 ? (
        <p className="rounded-lg border border-dashed border-slate-300 bg-slate-50 p-4 text-sm text-slate-600">
          No resumes uploaded for this job yet.
        </p>
      ) : null}

      {rows.length > 0 ? (
        <div className="overflow-x-auto">
          <table className="w-full border-collapse text-left text-sm">
            <thead>
              <tr className="border-b border-slate-100 text-slate-500">
                <th className="py-2 pr-3">Candidate</th>
                <th className="py-2 pr-3">Email</th>
                <th className="py-2 pr-3">File</th>
                <th className="py-2 pr-3">Status</th>
                <th className="py-2 pr-3">Experience</th>
                <th className="py-2 pr-3">Skills</th>
                <th className="py-2 pr-3">Parse Error</th>
                <th className="py-2">Actions</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((row) => (
                <tr key={row.job_resume_id} className="border-b border-slate-50 align-top">
                  <td className="py-2 pr-3 font-medium text-slate-900">{row.candidate_name}</td>
                  <td className="py-2 pr-3 text-slate-700">{row.email ?? "-"}</td>
                  <td className="py-2 pr-3 text-slate-700">{row.source_filename ?? "-"}</td>
                  <td className="py-2 pr-3">
                    <span
                      className={`rounded-full border px-2 py-1 text-xs font-semibold ${statusClass(row.parse_status)}`}
                    >
                      {row.parse_status}
                    </span>
                  </td>
                  <td className="py-2 pr-3 text-slate-700">
                    {row.experience_years !== null ? `${row.experience_years} yrs` : "-"}
                  </td>
                  <td className="py-2 pr-3 text-slate-700">
                    {row.skills.length > 0 ? row.skills.slice(0, 6).join(", ") : "-"}
                  </td>
                  <td className="py-2 pr-3 text-rose-700">{row.parse_error ?? "-"}</td>
                  <td className="py-2">
                    <div className="flex items-center gap-2">
                      <button
                        onClick={() => openParsedResume(row.resume_id)}
                        className="rounded border border-slate-300 px-2 py-1 text-xs font-semibold text-slate-700"
                      >
                        View Parsed
                      </button>
                      <button
                        onClick={() => deleteResume(row.resume_id)}
                        disabled={deletingResumeId === row.resume_id}
                        className="rounded border border-rose-300 px-2 py-1 text-xs font-semibold text-rose-700 disabled:opacity-60"
                      >
                        {deletingResumeId === row.resume_id ? "Deleting..." : "Delete"}
                      </button>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : null}

      {deleteMessage ? (
        <p className="mt-3 rounded border border-slate-200 bg-slate-50 p-2 text-sm text-slate-700">{deleteMessage}</p>
      ) : null}
      {loading ? <p className="mt-3 text-sm text-slate-600">Loading parsed resume...</p> : null}
      {error ? (
        <p className="mt-3 rounded border border-amber-200 bg-amber-50 p-2 text-sm text-amber-900">{error}</p>
      ) : null}

      {selected ? (
        <div className="mt-4 rounded-xl border border-slate-200 bg-slate-50 p-3">
          <div className="mb-2 flex items-center justify-between">
            <p className="font-semibold text-slate-900">Parsed Resume Debug View</p>
            <button
              onClick={() => setSelected(null)}
              className="rounded border border-slate-300 px-2 py-1 text-xs"
            >
              Close
            </button>
          </div>
          <p className="text-xs text-slate-500">{selected.source_filename ?? selected.resume_id}</p>

          <div className="mt-3 grid gap-3 lg:grid-cols-2">
            <article className="rounded border border-slate-200 bg-white p-2">
              <p className="text-xs font-semibold uppercase tracking-wide text-slate-500">Extracted JSON</p>
              <pre className="mt-2 max-h-64 overflow-auto whitespace-pre-wrap break-words text-xs text-slate-800">
                {JSON.stringify(selected.parsed_json, null, 2)}
              </pre>
            </article>

            <article className="rounded border border-slate-200 bg-white p-2">
              <p className="text-xs font-semibold uppercase tracking-wide text-slate-500">Raw Resume Text</p>
              <pre className="mt-2 max-h-64 overflow-auto whitespace-pre-wrap break-words text-xs text-slate-800">
                {selected.raw_text || "No raw text extracted."}
              </pre>
            </article>
          </div>
        </div>
      ) : null}
    </section>
  );
}
