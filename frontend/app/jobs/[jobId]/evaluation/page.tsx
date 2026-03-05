import Link from "next/link";

import GoldenDatasetEditor from "@/components/golden-dataset-editor";
import { fetchJob, fetchJobEvaluation } from "@/lib/api";

export default async function JobEvaluationPage({
  params,
}: {
  params: Promise<{ jobId: string }>;
}) {
  const { jobId } = await params;
  const [job, evaluation] = await Promise.all([fetchJob(jobId), fetchJobEvaluation(jobId, 5)]);

  return (
    <main className="mx-auto w-[98%] max-w-none px-3 py-5">
      <div className="mb-5 flex items-center justify-between">
        <div>
          <h1 className="font-heading text-3xl font-bold text-ink">
            Evaluation - {job?.title ?? "Unknown Job"}
          </h1>
          <p className="mt-1 text-slate-600">Job ID: {jobId}</p>
        </div>
        <Link
          href={`/jobs/${jobId}`}
          className="rounded-lg border border-slate-300 bg-white px-4 py-2 text-sm font-semibold text-slate-700"
        >
          Back to Job
        </Link>
      </div>

      {!evaluation ? (
        <p className="rounded-lg border border-amber-200 bg-amber-50 p-3 text-amber-900">
          Evaluation data unavailable. Run ranking first.
        </p>
      ) : (
        <div className="space-y-4">
          <GoldenDatasetEditor jobId={jobId} />

          <section className="grid gap-3 md:grid-cols-3">
            <article className="rounded-xl border border-slate-200 bg-white p-4 shadow-sm">
              <p className="text-xs font-semibold uppercase tracking-wide text-slate-500">Precision@{evaluation.top_k}</p>
              <p className="mt-2 text-2xl font-bold text-slate-900">
                {evaluation.precision_at_k ?? "-"}%
              </p>
            </article>
            <article className="rounded-xl border border-slate-200 bg-white p-4 shadow-sm">
              <p className="text-xs font-semibold uppercase tracking-wide text-slate-500">Recall@{evaluation.top_k}</p>
              <p className="mt-2 text-2xl font-bold text-slate-900">{evaluation.recall_at_k ?? "-"}%</p>
            </article>
            <article className="rounded-xl border border-slate-200 bg-white p-4 shadow-sm">
              <p className="text-xs font-semibold uppercase tracking-wide text-slate-500">Averages</p>
              <p className="mt-2 text-sm text-slate-700">
                Score {evaluation.score_summary.average_score}% • Confidence{" "}
                {evaluation.score_summary.average_confidence}%
              </p>
            </article>
          </section>

          <section className="rounded-xl border border-slate-200 bg-white p-4 shadow-sm">
            <h2 className="font-heading text-xl font-semibold text-slate-900">Golden Dataset Match</h2>
            <p className="mt-2 text-sm text-slate-700">
              Expected: {evaluation.expected_total} • Matched in top {evaluation.top_k}: {evaluation.matched_expected}
            </p>
            <p className="text-xs text-slate-500">
              Source: {evaluation.expected_reference ?? "Not configured"}
            </p>
          </section>

          <section className="rounded-xl border border-slate-200 bg-white p-4 shadow-sm">
            <h2 className="font-heading text-xl font-semibold text-slate-900">Run-to-Run Diff</h2>
            <div className="mt-3 overflow-auto">
              <table className="w-full min-w-[800px] text-left text-sm">
                <thead className="text-xs uppercase tracking-wide text-slate-500">
                  <tr>
                    <th className="border-b border-slate-200 px-2 py-2">Candidate</th>
                    <th className="border-b border-slate-200 px-2 py-2">Current Rank</th>
                    <th className="border-b border-slate-200 px-2 py-2">Previous Rank</th>
                    <th className="border-b border-slate-200 px-2 py-2">Score Delta</th>
                    <th className="border-b border-slate-200 px-2 py-2">Top Reasons</th>
                  </tr>
                </thead>
                <tbody>
                  {evaluation.run_diff.map((row) => (
                    <tr key={row.candidate_id} className="border-b border-slate-100">
                      <td className="px-2 py-2">{row.candidate_name}</td>
                      <td className="px-2 py-2">#{row.current_rank}</td>
                      <td className="px-2 py-2">{row.previous_rank ? `#${row.previous_rank}` : "-"}</td>
                      <td className="px-2 py-2">
                        {row.score_delta !== null ? `${row.score_delta > 0 ? "+" : ""}${row.score_delta}` : "-"}
                      </td>
                      <td className="px-2 py-2">{row.top_reasons.join(" | ")}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </section>
        </div>
      )}
    </main>
  );
}
