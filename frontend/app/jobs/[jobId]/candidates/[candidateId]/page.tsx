import {
  fetchCandidateExplanation,
  fetchJob,
  fetchRankings,
  type CandidateExplanation,
  type Job,
  type RankingRow,
} from "@/lib/api";

export default async function CandidatePage({
  params,
}: {
  params: Promise<{ jobId: string; candidateId: string }>;
}) {
  const { jobId, candidateId } = await params;
  let job: Job | null = null;
  let rankings: RankingRow[] = [];
  let explanation: CandidateExplanation | null = null;
  let loadError = false;

  try {
    [job, rankings, explanation] = await Promise.all([
      fetchJob(jobId),
      fetchRankings(jobId),
      fetchCandidateExplanation(jobId, candidateId),
    ]);
  } catch {
    loadError = true;
  }

  const current = rankings.find((item) => item.candidate_id === candidateId);

  return (
    <main className="mx-auto max-w-4xl px-6 py-8">
      <h1 className="font-heading text-3xl font-bold text-ink">Candidate Profile</h1>
      <p className="mt-1 text-slate-600">Job: {job?.title ?? jobId}</p>
      <p className="mb-6 text-slate-600">Candidate: {candidateId}</p>
      {loadError ? (
        <p className="mb-4 rounded-lg border border-amber-200 bg-amber-50 p-3 text-amber-900">
          Could not load candidate data from backend right now.
        </p>
      ) : null}

      <section className="rounded-2xl border border-slate-200 bg-white p-6 shadow-sm">
        <h2 className="font-heading text-2xl font-semibold">
          {current?.candidate_name ?? "Candidate"}
        </h2>
        <p className="mt-2 text-lg text-slate-700">
          Match Score: <strong>{current?.score ?? "N/A"}%</strong> | Confidence:{" "}
          <strong>{current?.confidence ?? "N/A"}%</strong>
        </p>
        {explanation ? (
          <div className="mt-3 rounded-lg bg-slate-50 p-3 text-sm text-slate-700">
            <p>
              Base Score: <strong>{explanation.base_score ?? "N/A"}</strong> | LLM Score:{" "}
              <strong>{explanation.llm_score ?? "N/A"}</strong> | Final Score:{" "}
              <strong>{explanation.final_score ?? "N/A"}</strong>
            </p>
            <p className="mt-1">
              Base Confidence: <strong>{explanation.base_confidence ?? "N/A"}</strong> | LLM
              Confidence: <strong>{explanation.llm_confidence ?? "N/A"}</strong> | Final
              Confidence: <strong>{explanation.final_confidence ?? "N/A"}</strong>
            </p>
            <p className="mt-1 text-xs text-slate-500">
              LLM Scoring Used: {explanation.llm_used ? "Yes" : "No"}
            </p>
          </div>
        ) : null}

        <div className="mt-6 grid gap-6 md:grid-cols-2">
          <div>
            <h3 className="font-semibold text-teal">Matched Skills</h3>
            <ul className="mt-2 space-y-1 text-slate-700">
              {(explanation?.matched_skills ?? []).map((skill) => (
                <li key={skill}>{skill}</li>
              ))}
              {explanation?.matched_skills.length === 0 ? <li>None detected</li> : null}
            </ul>
          </div>

          <div>
            <h3 className="font-semibold text-amber-700">Missing Skills</h3>
            <ul className="mt-2 space-y-1 text-slate-700">
              {(explanation?.missing_skills ?? []).map((skill) => (
                <li key={skill}>{skill}</li>
              ))}
              {explanation?.missing_skills.length === 0 ? <li>None</li> : null}
            </ul>
          </div>
        </div>

        <div className="mt-6">
          <h3 className="font-semibold text-ink">Summary</h3>
          <p className="mt-2 rounded-lg bg-slate-50 p-3 text-slate-700">
            {explanation?.summary ?? "No explanation available yet."}
          </p>
          {explanation?.confidence_reasoning ? (
            <p className="mt-2 rounded-lg bg-slate-50 p-3 text-slate-700">
              <span className="font-semibold">Confidence Reasoning: </span>
              {explanation.confidence_reasoning}
            </p>
          ) : null}
          {explanation?.strengths && explanation.strengths.length > 0 ? (
            <div className="mt-2 rounded-lg bg-slate-50 p-3 text-slate-700">
              <p className="font-semibold text-slate-800">LLM Strengths</p>
              <ul className="mt-1 list-disc pl-5">
                {explanation.strengths.map((item) => (
                  <li key={item}>{item}</li>
                ))}
              </ul>
            </div>
          ) : null}
          {explanation ? (
            <p className="mt-2 text-xs text-slate-500">
              Model: {explanation.model_version} | Scoring: {explanation.scoring_version}
            </p>
          ) : null}
        </div>

        <div className="mt-6">
          <h3 className="font-semibold text-ink">Score Breakdown</h3>
          <ul className="mt-2 grid gap-2 text-slate-700 md:grid-cols-2">
            <li>Semantic: {explanation?.score_breakdown.semantic ?? "N/A"}</li>
            <li>Skill: {explanation?.score_breakdown.skill ?? "N/A"}</li>
            <li>Experience: {explanation?.score_breakdown.experience ?? "N/A"}</li>
            <li>Domain: {explanation?.score_breakdown.domain ?? "N/A"}</li>
          </ul>
        </div>

        <div className="mt-6">
          <h3 className="font-semibold text-ink">Evidence</h3>
          {(explanation?.evidence_snippets ?? []).map((snippet) => (
            <div key={`${snippet.label}-${snippet.text}`} className="mt-2 rounded-lg bg-slate-50 p-3 text-slate-700">
              <p className="font-semibold text-slate-800">{snippet.label}</p>
              <p>{snippet.text}</p>
            </div>
          ))}
          {explanation?.evidence_snippets.length === 0 ? (
            <p className="mt-2 rounded-lg bg-slate-50 p-3 text-slate-700">No evidence snippets yet.</p>
          ) : null}
        </div>
      </section>
    </main>
  );
}
