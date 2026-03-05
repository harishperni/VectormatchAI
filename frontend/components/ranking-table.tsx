"use client";

import Link from "next/link";
import { useMemo, useState } from "react";

import { type RankingRow } from "@/lib/api";

type RankingTableProps = {
  jobId: string;
  initialRows: RankingRow[];
};

type RankingsResponse = {
  items: RankingRow[];
};

export default function RankingTable({ jobId, initialRows }: RankingTableProps) {
  const [rows, setRows] = useState<RankingRow[]>(initialRows);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<string>("Ready");

  const [minScore, setMinScore] = useState("");
  const [minExperience, setMinExperience] = useState("");
  const [skill, setSkill] = useState("");
  const [actionFilter, setActionFilter] = useState("");

  const anyFilters = useMemo(
    () => Boolean(minScore || minExperience || skill || actionFilter),
    [minScore, minExperience, skill, actionFilter]
  );

  async function applyFilters() {
    setBusy(true);
    setMessage("Loading filtered rankings...");
    try {
      const params = new URLSearchParams();
      if (minScore) params.set("min_score", minScore);
      if (minExperience) params.set("min_experience", minExperience);
      if (skill) params.set("skill", skill);
      if (actionFilter) params.set("action", actionFilter);

      const response = await fetch(`/api/jobs/${jobId}/rankings?${params.toString()}`, {
        cache: "no-store",
      });
      const payload = (await response.json()) as RankingsResponse;
      if (!response.ok) {
        setMessage("Failed to load rankings.");
      } else {
        setRows(payload.items ?? []);
        setMessage(`Loaded ${payload.items?.length ?? 0} ranking rows.`);
      }
    } catch {
      setMessage("Failed to load rankings.");
    } finally {
      setBusy(false);
    }
  }

  async function clearFilters() {
    setMinScore("");
    setMinExperience("");
    setSkill("");
    setActionFilter("");

    setBusy(true);
    setMessage("Resetting rankings...");
    try {
      const response = await fetch(`/api/jobs/${jobId}/rankings`, { cache: "no-store" });
      const payload = (await response.json()) as RankingsResponse;
      if (!response.ok) {
        setMessage("Failed to reset rankings.");
      } else {
        setRows(payload.items ?? []);
        setMessage("Filters cleared.");
      }
    } catch {
      setMessage("Failed to reset rankings.");
    } finally {
      setBusy(false);
    }
  }

  async function saveAction(candidateId: string, action: string) {
    setBusy(true);
    setMessage(`Saving action: ${action}...`);
    try {
      const response = await fetch(`/api/jobs/${jobId}/candidates/${candidateId}/action`, {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ action }),
      });
      if (!response.ok) {
        setMessage("Failed to save action.");
      } else {
        setRows((prev) =>
          prev.map((row) =>
            row.candidate_id === candidateId ? { ...row, action_status: action } : row
          )
        );
        setMessage(`Action saved: ${action}`);
      }
    } catch {
      setMessage("Failed to save action.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="space-y-3 rounded-2xl border border-slate-200 bg-white p-4 shadow-sm">
      <div className="rounded-xl bg-slate-50 p-3">
        <p className="mb-2 text-sm font-semibold text-slate-700">Ranking Filters</p>
        <div className="grid gap-2 md:grid-cols-4">
          <input
            value={minScore}
            onChange={(event) => setMinScore(event.target.value)}
            placeholder="Min score (0-100)"
            className="rounded-md border border-slate-300 px-2 py-1 text-sm"
          />
          <input
            value={minExperience}
            onChange={(event) => setMinExperience(event.target.value)}
            placeholder="Min experience"
            className="rounded-md border border-slate-300 px-2 py-1 text-sm"
          />
          <input
            value={skill}
            onChange={(event) => setSkill(event.target.value)}
            placeholder="Skill (e.g. python)"
            className="rounded-md border border-slate-300 px-2 py-1 text-sm"
          />
          <select
            value={actionFilter}
            onChange={(event) => setActionFilter(event.target.value)}
            className="rounded-md border border-slate-300 px-2 py-1 text-sm"
          >
            <option value="">Any action</option>
            <option value="shortlisted">Shortlisted</option>
            <option value="rejected">Rejected</option>
            <option value="interviewed">Interviewed</option>
            <option value="hired">Hired</option>
          </select>
        </div>
        <div className="mt-2 flex gap-2">
          <button
            onClick={applyFilters}
            disabled={busy}
            className="rounded-md bg-teal px-3 py-1 text-sm font-semibold text-white disabled:opacity-60"
          >
            Apply
          </button>
          <button
            onClick={clearFilters}
            disabled={busy || !anyFilters}
            className="rounded-md border border-slate-300 px-3 py-1 text-sm disabled:opacity-60"
          >
            Clear
          </button>
          <span className="self-center text-xs text-slate-600">{message}</span>
        </div>
      </div>

      {rows.length === 0 ? (
        <p className="rounded-lg border border-dashed border-slate-300 bg-slate-50 p-4 text-slate-600">
          No rankings available for current filters.
        </p>
      ) : null}

      <table className="w-full border-collapse text-left text-sm md:text-base">
        <thead>
          <tr className="border-b border-slate-100 text-slate-500">
            <th className="py-3">Rank</th>
            <th>Candidate</th>
            <th>Score</th>
            <th>Confidence</th>
            <th>Experience</th>
            <th>Action</th>
            <th>Top reasons</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row, index) => (
            <tr key={`${row.candidate_id}-${row.resume_id}`} className="border-b border-slate-50">
              <td className="py-3 font-semibold">{index + 1}</td>
              <td>
                <Link
                  href={`/jobs/${jobId}/candidates/${row.candidate_id}`}
                  className="font-medium text-teal hover:underline"
                >
                  {row.candidate_name}
                </Link>
              </td>
              <td>{row.score}%</td>
              <td>{row.confidence}%</td>
              <td>{row.experience_years} yrs</td>
              <td>
                <div className="flex flex-wrap gap-1">
                  <button
                    onClick={() => saveAction(row.candidate_id, "shortlisted")}
                    className="rounded border border-emerald-300 px-2 py-0.5 text-xs text-emerald-700"
                  >
                    Shortlist
                  </button>
                  <button
                    onClick={() => saveAction(row.candidate_id, "rejected")}
                    className="rounded border border-rose-300 px-2 py-0.5 text-xs text-rose-700"
                  >
                    Reject
                  </button>
                  <button
                    onClick={() => saveAction(row.candidate_id, "interviewed")}
                    className="rounded border border-sky-300 px-2 py-0.5 text-xs text-sky-700"
                  >
                    Interview
                  </button>
                  {row.action_status ? (
                    <span className="rounded bg-slate-100 px-2 py-0.5 text-xs text-slate-700">
                      {row.action_status}
                    </span>
                  ) : null}
                </div>
              </td>
              <td className="text-slate-600">{row.top_reasons.join(" + ")}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
