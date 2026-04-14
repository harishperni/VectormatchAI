"use client";

import { useMemo } from "react";

import type { RankingRow } from "@/lib/api";

type Props = {
  rows: RankingRow[];
};

function pct(value: number, total: number): string {
  if (total <= 0) return "0%";
  return `${Math.round((value / total) * 100)}%`;
}

function stageLabel(action?: string | null): string {
  const normalized = (action || "").toLowerCase();
  if (normalized === "shortlisted") return "Shortlisted";
  if (normalized === "interviewed") return "Interview";
  if (normalized === "hired") return "Hired";
  if (normalized === "rejected") return "Rejected";
  return "New/Review";
}

function isAntiCheatFlagged(row: RankingRow): boolean {
  const score = Number(row.anti_cheat_score ?? 0);
  return Number.isFinite(score) && score > 10;
}

export default function CandidateDashboardTab({ rows }: Props) {
  const summary = useMemo(() => {
    const total = rows.length;
    const stageCounts: Record<string, number> = {
      "New/Review": 0,
      Shortlisted: 0,
      Interview: 0,
      Hired: 0,
      Rejected: 0,
    };
    const scoreBands: Record<string, number> = {
      "85-100": 0,
      "70-84": 0,
      "50-69": 0,
      "0-49": 0,
    };
    const experienceBands: Record<string, number> = {
      "0-2 yrs": 0,
      "2-5 yrs": 0,
      "5+ yrs": 0,
      Unknown: 0,
    };
    const degreeCounts: Record<string, number> = {};

    let scoreSum = 0;
    let confidenceSum = 0;
    let antiCheatFlags = 0;

    for (const row of rows) {
      const stage = stageLabel(row.action_status);
      stageCounts[stage] = (stageCounts[stage] || 0) + 1;

      const score = Number(row.score || 0);
      scoreSum += score;
      if (score >= 85) scoreBands["85-100"] += 1;
      else if (score >= 70) scoreBands["70-84"] += 1;
      else if (score >= 50) scoreBands["50-69"] += 1;
      else scoreBands["0-49"] += 1;

      const confidence = Number(row.confidence || 0);
      confidenceSum += confidence;

      const years = row.experience_years;
      if (years === null || years === undefined) experienceBands.Unknown += 1;
      else if (years < 2) experienceBands["0-2 yrs"] += 1;
      else if (years < 5) experienceBands["2-5 yrs"] += 1;
      else experienceBands["5+ yrs"] += 1;

      const degree = (row.highest_degree || "Unknown").trim() || "Unknown";
      degreeCounts[degree] = (degreeCounts[degree] || 0) + 1;

      if (isAntiCheatFlagged(row)) {
        antiCheatFlags += 1;
      }
    }

    const avgScore = total ? Number((scoreSum / total).toFixed(2)) : 0;
    const avgConfidence = total ? Number((confidenceSum / total).toFixed(2)) : 0;

    const topDegrees = Object.entries(degreeCounts)
      .sort((a, b) => b[1] - a[1])
      .slice(0, 5);

    return {
      total,
      avgScore,
      avgConfidence,
      antiCheatFlags,
      stageCounts,
      scoreBands,
      experienceBands,
      topDegrees,
    };
  }, [rows]);

  const total = summary.total;

  return (
    <section className="space-y-4 rounded-2xl border border-slate-200 bg-white p-4 shadow-sm">
      <div>
        <h2 className="font-heading text-xl font-semibold text-slate-900">Candidate Dashboard</h2>
        <p className="text-sm text-slate-600">Live insights from current filtered candidates.</p>
      </div>

      <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
        <article className="rounded-xl border border-slate-200 bg-slate-50 p-3">
          <p className="text-xs uppercase tracking-wide text-slate-500">Total Candidates</p>
          <p className="mt-1 text-2xl font-semibold text-slate-900">{summary.total}</p>
        </article>
        <article className="rounded-xl border border-slate-200 bg-slate-50 p-3">
          <p className="text-xs uppercase tracking-wide text-slate-500">Average Score</p>
          <p className="mt-1 text-2xl font-semibold text-slate-900">{summary.avgScore}</p>
        </article>
        <article className="rounded-xl border border-slate-200 bg-slate-50 p-3">
          <p className="text-xs uppercase tracking-wide text-slate-500">Average Confidence</p>
          <p className="mt-1 text-2xl font-semibold text-slate-900">{summary.avgConfidence}</p>
        </article>
        <article className="rounded-xl border border-slate-200 bg-slate-50 p-3">
          <p className="text-xs uppercase tracking-wide text-slate-500">Anti-Cheat Flagged</p>
          <p className="mt-1 text-2xl font-semibold text-slate-900">{summary.antiCheatFlags}</p>
          <p className="text-xs text-slate-600">{pct(summary.antiCheatFlags, total)} of current pool</p>
        </article>
      </div>

      <div className="grid gap-4 xl:grid-cols-2">
        <article className="rounded-xl border border-slate-200 p-3">
          <p className="text-xs font-semibold uppercase tracking-wide text-slate-500">Stage Distribution</p>
          <div className="mt-3 space-y-2">
            {Object.entries(summary.stageCounts).map(([label, count]) => (
              <div key={label}>
                <div className="mb-1 flex items-center justify-between text-sm text-slate-700">
                  <span>{label}</span>
                  <span>{count}</span>
                </div>
                <div className="h-2 rounded-full bg-slate-100">
                  <div
                    className="h-2 rounded-full bg-slate-700"
                    style={{ width: pct(count, total) }}
                  />
                </div>
              </div>
            ))}
          </div>
        </article>

        <article className="rounded-xl border border-slate-200 p-3">
          <p className="text-xs font-semibold uppercase tracking-wide text-slate-500">Score Bands</p>
          <div className="mt-3 space-y-2">
            {Object.entries(summary.scoreBands).map(([label, count]) => (
              <div key={label}>
                <div className="mb-1 flex items-center justify-between text-sm text-slate-700">
                  <span>{label}</span>
                  <span>{count}</span>
                </div>
                <div className="h-2 rounded-full bg-slate-100">
                  <div
                    className="h-2 rounded-full bg-emerald-600"
                    style={{ width: pct(count, total) }}
                  />
                </div>
              </div>
            ))}
          </div>
        </article>

        <article className="rounded-xl border border-slate-200 p-3">
          <p className="text-xs font-semibold uppercase tracking-wide text-slate-500">Experience Mix</p>
          <div className="mt-3 space-y-2">
            {Object.entries(summary.experienceBands).map(([label, count]) => (
              <div key={label}>
                <div className="mb-1 flex items-center justify-between text-sm text-slate-700">
                  <span>{label}</span>
                  <span>{count}</span>
                </div>
                <div className="h-2 rounded-full bg-slate-100">
                  <div
                    className="h-2 rounded-full bg-sky-600"
                    style={{ width: pct(count, total) }}
                  />
                </div>
              </div>
            ))}
          </div>
        </article>

        <article className="rounded-xl border border-slate-200 p-3">
          <p className="text-xs font-semibold uppercase tracking-wide text-slate-500">Top Degrees</p>
          <div className="mt-3 space-y-2">
            {summary.topDegrees.length ? (
              summary.topDegrees.map(([degree, count]) => (
                <div key={degree}>
                  <div className="mb-1 flex items-center justify-between text-sm text-slate-700">
                    <span className="line-clamp-1">{degree}</span>
                    <span>{count}</span>
                  </div>
                  <div className="h-2 rounded-full bg-slate-100">
                    <div
                      className="h-2 rounded-full bg-violet-600"
                      style={{ width: pct(count, total) }}
                    />
                  </div>
                </div>
              ))
            ) : (
              <p className="text-sm text-slate-600">No degree data available.</p>
            )}
          </div>
        </article>
      </div>
    </section>
  );
}
