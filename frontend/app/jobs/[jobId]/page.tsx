import JobWorkspace from "@/components/job-workspace";
import JobDetailsEditor from "@/components/job-details-editor";
import JobsFilterPanel from "@/components/jobs-filter-panel";
import {
  fetchJob,
  fetchJobResumes,
  fetchRankings,
  type Job,
  type ParsedResumeRow,
  type RankingRow,
} from "@/lib/api";

export default async function JobRankingPage({
  params,
  searchParams,
}: {
  params: Promise<{ jobId: string }>;
  searchParams: Promise<Record<string, string | string[] | undefined>>;
}) {
  const { jobId } = await params;
  const resolvedSearchParams = await searchParams;
  const defaultFilters = {
    keyword: "",
    status: "",
    relevant_experience: "",
    highest_degree: "",
    distance_max: "",
    sponsorship_required: "",
    total_experience_min: "",
    knockout_status: "",
    min_score: "",
    min_experience: "",
    skill: "",
    action: "",
  };
  const minScoreValue = Array.isArray(resolvedSearchParams.min_score)
    ? resolvedSearchParams.min_score[0]
    : resolvedSearchParams.min_score;
  const minExperienceValue = Array.isArray(resolvedSearchParams.min_experience)
    ? resolvedSearchParams.min_experience[0]
    : resolvedSearchParams.min_experience;
  const skillValue = Array.isArray(resolvedSearchParams.skill)
    ? resolvedSearchParams.skill[0]
    : resolvedSearchParams.skill;
  const actionValue = Array.isArray(resolvedSearchParams.action)
    ? resolvedSearchParams.action[0]
    : resolvedSearchParams.action;
  const keywordValue = Array.isArray(resolvedSearchParams.keyword)
    ? resolvedSearchParams.keyword[0]
    : resolvedSearchParams.keyword;
  const statusValue = Array.isArray(resolvedSearchParams.status)
    ? resolvedSearchParams.status[0]
    : resolvedSearchParams.status;
  const highestDegreeValue = Array.isArray(resolvedSearchParams.highest_degree)
    ? resolvedSearchParams.highest_degree[0]
    : resolvedSearchParams.highest_degree;
  const distanceMaxValue = Array.isArray(resolvedSearchParams.distance_max)
    ? resolvedSearchParams.distance_max[0]
    : resolvedSearchParams.distance_max;
  const sponsorshipRequiredValue = Array.isArray(resolvedSearchParams.sponsorship_required)
    ? resolvedSearchParams.sponsorship_required[0]
    : resolvedSearchParams.sponsorship_required;
  const totalExperienceMinValue = Array.isArray(resolvedSearchParams.total_experience_min)
    ? resolvedSearchParams.total_experience_min[0]
    : resolvedSearchParams.total_experience_min;
  const knockoutStatusValue = Array.isArray(resolvedSearchParams.knockout_status)
    ? resolvedSearchParams.knockout_status[0]
    : resolvedSearchParams.knockout_status;

  let job: Job | null = null;
  let rankings: RankingRow[] = [];
  let resumes: ParsedResumeRow[] = [];
  let rankingsError = false;

  try {
    [job, rankings, resumes] = await Promise.all([
      fetchJob(jobId),
      fetchRankings(jobId, {
        min_score: minScoreValue ? Number(minScoreValue) : undefined,
        min_experience: minExperienceValue ? Number(minExperienceValue) : undefined,
        skill: skillValue || undefined,
        action: actionValue || undefined,
        keyword: keywordValue || undefined,
        status: statusValue || undefined,
        highest_degree: highestDegreeValue || undefined,
        distance_max: distanceMaxValue ? Number(distanceMaxValue) : undefined,
        sponsorship_required:
          sponsorshipRequiredValue === "true"
            ? true
            : sponsorshipRequiredValue === "false"
              ? false
              : undefined,
        total_experience_min: totalExperienceMinValue
          ? Number(totalExperienceMinValue)
          : undefined,
        knockout_status: knockoutStatusValue || undefined,
      }),
      fetchJobResumes(jobId),
    ]);
  } catch {
    rankingsError = true;
  }

  return (
    <main className="mx-auto w-full max-w-[1500px] overflow-x-hidden px-4 py-5 xl:px-6">
      <div>
        <h1 className="font-heading text-3xl font-bold text-ink">{job?.title ?? "Candidate Rankings"}</h1>
        <p className="mt-2 text-slate-600">Job ID: {jobId}</p>
      </div>
      {!job ? (
        <p className="mb-4 rounded-lg border border-amber-200 bg-amber-50 p-3 text-amber-900">
          Job not found in backend.
        </p>
      ) : (
        <JobDetailsEditor jobId={jobId} job={job} />
      )}
      {rankingsError ? (
        <p className="mb-4 rounded-lg border border-amber-200 bg-amber-50 p-3 text-amber-900">
          Could not load rankings from backend right now.
        </p>
      ) : null}

      <section className="grid min-w-0 gap-4 xl:grid-cols-[260px,minmax(0,1fr)]">
        <JobsFilterPanel
          initial={{
            min_score: minScoreValue ?? defaultFilters.min_score,
            min_experience: minExperienceValue ?? defaultFilters.min_experience,
            skill: skillValue ?? defaultFilters.skill,
            action: actionValue ?? defaultFilters.action,
            keyword: keywordValue ?? defaultFilters.keyword,
            status: statusValue ?? defaultFilters.status,
            highest_degree: highestDegreeValue ?? defaultFilters.highest_degree,
            distance_max: distanceMaxValue ?? defaultFilters.distance_max,
            sponsorship_required:
              sponsorshipRequiredValue ?? defaultFilters.sponsorship_required,
            total_experience_min:
              totalExperienceMinValue ?? defaultFilters.total_experience_min,
            knockout_status: knockoutStatusValue ?? defaultFilters.knockout_status,
          }}
        />

        <div className="min-w-0">
          <JobWorkspace jobId={jobId} rankings={rankings} resumes={resumes} />
        </div>
      </section>
    </main>
  );
}
