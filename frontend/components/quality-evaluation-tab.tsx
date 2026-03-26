"use client";

import Link from "next/link";
import { useEffect, useState } from "react";

import type { JobEvaluation } from "@/lib/api";

export default function QualityEvaluationTab({ jobId }: { jobId: string }) {
  const [topK, setTopK] = useState("5");
  const [evaluation, setEvaluation] = useState<JobEvaluation | null>(null);
  const [status, setStatus] = useState("Loading quality metrics...");
  const [loading, setLoading] = useState(false);

  function normalizeTopK(raw: string): number {
    const parsed = Number.parseInt((raw || "").trim(), 10);
    if (!Number.isFinite(parsed)) {
      return 5;
    }
    return Math.max(1, Math.min(50, parsed));
  }

  async function loadEvaluation(currentTopK: string) {
    const kValue = normalizeTopK(currentTopK);
    setTopK(String(kValue));
    setLoading(true);
    setStatus("Loading quality metrics...");
    try {
      const response = await fetch(`/api/jobs/${jobId}/evaluation?top_k=${kValue}`, {
        cache: "no-store",
      });
      if (!response.ok) {
        setEvaluation(null);
        setStatus("Evaluation is unavailable. Run ranking for this job first.");
        return;
      }
      const payload = (await response.json()) as JobEvaluation;
      setEvaluation(payload);
      setStatus("Loaded.");
    } catch {
      setEvaluation(null);
      setStatus("Could not load quality metrics.");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    void loadEvaluation(topK);
  }, [jobId]);

  return (
    <section className="space-y-4 rounded-2xl border border-slate-200 bg-white p-4 shadow-sm">
      <header className="flex flex-wrap items-center justify-between gap-2">
        <div>
          <h2 className="font-heading text-xl font-semibold text-slate-900">Quality & Evaluation</h2>
          <p className="text-xs text-slate-500">
            Ranking quality metrics and parsing benchmark quick-run panel.
          </p>
        </div>
        <div className="flex items-center gap-2">
          <input
            value={topK}
            onChange={(event) => setTopK(event.target.value)}
            placeholder="Top-K"
            className="w-20 rounded-md border border-slate-300 px-2 py-1.5 text-sm"
          />
          <button
            onClick={() => loadEvaluation(topK)}
            disabled={loading}
            className="rounded-md border border-slate-300 px-3 py-1.5 text-sm font-semibold text-slate-700 disabled:opacity-60"
          >
            {loading ? "Refreshing..." : "Refresh"}
          </button>
          <Link
            href={`/jobs/${jobId}/evaluation`}
            className="rounded-md border border-slate-300 px-3 py-1.5 text-sm font-semibold text-slate-700"
          >
            Full Evaluation
          </Link>
        </div>
      </header>

      <p className="text-xs text-slate-500">{status}</p>

      {!evaluation ? (
        <p className="rounded-lg border border-dashed border-slate-300 bg-slate-50 p-4 text-sm text-slate-600">
          No evaluation data yet.
        </p>
      ) : (
        <div className="grid gap-3 md:grid-cols-4">
          <article className="rounded-xl border border-slate-200 bg-slate-50 p-3">
            <p className="text-[11px] uppercase tracking-wide text-slate-500">Precision@{evaluation.top_k}</p>
            <p className="mt-1 text-xl font-semibold text-slate-900">{evaluation.precision_at_k ?? "-"}%</p>
          </article>
          <article className="rounded-xl border border-slate-200 bg-slate-50 p-3">
            <p className="text-[11px] uppercase tracking-wide text-slate-500">Recall@{evaluation.top_k}</p>
            <p className="mt-1 text-xl font-semibold text-slate-900">{evaluation.recall_at_k ?? "-"}%</p>
          </article>
          <article className="rounded-xl border border-slate-200 bg-slate-50 p-3">
            <p className="text-[11px] uppercase tracking-wide text-slate-500">Avg Score</p>
            <p className="mt-1 text-xl font-semibold text-slate-900">
              {evaluation.score_summary.average_score}%
            </p>
          </article>
          <article className="rounded-xl border border-slate-200 bg-slate-50 p-3">
            <p className="text-[11px] uppercase tracking-wide text-slate-500">Expected Match</p>
            <p className="mt-1 text-xl font-semibold text-slate-900">
              {evaluation.matched_expected}/{evaluation.expected_total}
            </p>
          </article>
        </div>
      )}

      <section className="rounded-xl border border-slate-200 bg-slate-50 p-3">
        <h3 className="text-sm font-semibold text-slate-900">Parsing Benchmark (CLI Quick Run)</h3>
        <p className="mt-1 text-xs text-slate-600">
          Run these in a worker terminal to benchmark parsing accuracy on the golden sample.
        </p>
        <pre className="mt-2 overflow-x-auto rounded-md border border-slate-200 bg-white p-3 text-xs text-slate-700">{`cd /Users/yeswanthperni/VectorMatchAI/worker
source .venv/bin/activate
python scripts/evaluate_parsing.py --dataset data/parsing/parsing_golden_sample.json
python scripts/evaluate_parsing.py --dataset data/parsing/parsing_golden_sample.json --enable-llm`}</pre>
      </section>

      <section className="rounded-xl border border-slate-200 bg-slate-50 p-3">
        <h3 className="text-sm font-semibold text-slate-900">Ranking Regression (CLI Quick Run)</h3>
        <p className="mt-1 text-xs text-slate-600">
          Run this in backend terminal to validate ranking metrics against golden candidates.
        </p>
        <pre className="mt-2 overflow-x-auto rounded-md border border-slate-200 bg-white p-3 text-xs text-slate-700">{`cd /Users/yeswanthperni/VectorMatchAI/backend
source .venv/bin/activate
python scripts/evaluate_ranking_regression.py --job-id ${jobId} --top-k 5`}</pre>
      </section>
    </section>
  );
}
