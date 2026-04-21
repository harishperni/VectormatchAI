"use client";

import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { useState } from "react";

type Props = {
  initial: {
    keyword?: string;
    status?: string;
    relevant_experience?: string;
    highest_degree?: string;
    distance_max?: string;
    sponsorship_required?: string;
    total_experience_min?: string;
    knockout_status?: string;
    min_score?: string;
    min_experience?: string;
    skill?: string;
    action?: string;
  };
};

export default function JobsFilterPanel({ initial }: Props) {
  const router = useRouter();
  const pathname = usePathname();
  const current = useSearchParams();

  const [minScore, setMinScore] = useState(initial.min_score ?? "");
  const [minExperience, setMinExperience] = useState(initial.min_experience ?? "");
  const [skill, setSkill] = useState(initial.skill ?? "");
  const [action, setAction] = useState(initial.action ?? "");
  const [keyword, setKeyword] = useState(initial.keyword ?? "");
  const [status, setStatus] = useState(initial.status ?? "");
  const [highestDegree, setHighestDegree] = useState(initial.highest_degree ?? "");
  const [distanceMax, setDistanceMax] = useState(initial.distance_max ?? "");
  const [sponsorshipRequired, setSponsorshipRequired] = useState(initial.sponsorship_required ?? "");
  const [totalExperienceMin, setTotalExperienceMin] = useState(initial.total_experience_min ?? "");
  const [knockoutStatus, setKnockoutStatus] = useState(initial.knockout_status ?? "");

  function applyFilters() {
    const params = new URLSearchParams(current.toString());

    if (minScore) params.set("min_score", minScore);
    else params.delete("min_score");

    if (minExperience) params.set("min_experience", minExperience);
    else params.delete("min_experience");

    if (skill) params.set("skill", skill);
    else params.delete("skill");

    if (action) params.set("action", action);
    else params.delete("action");

    if (keyword) params.set("keyword", keyword);
    else params.delete("keyword");

    if (status) params.set("status", status);
    else params.delete("status");

    if (highestDegree) params.set("highest_degree", highestDegree);
    else params.delete("highest_degree");

    if (distanceMax) params.set("distance_max", distanceMax);
    else params.delete("distance_max");

    if (sponsorshipRequired) params.set("sponsorship_required", sponsorshipRequired);
    else params.delete("sponsorship_required");

    if (totalExperienceMin) params.set("total_experience_min", totalExperienceMin);
    else params.delete("total_experience_min");

    if (knockoutStatus) params.set("knockout_status", knockoutStatus);
    else params.delete("knockout_status");

    router.push(`${pathname}?${params.toString()}`);
  }

  function clearFilters() {
    setMinScore("");
    setMinExperience("");
    setSkill("");
    setAction("");
    setKeyword("");
    setStatus("");
    setHighestDegree("");
    setDistanceMax("");
    setSponsorshipRequired("");
    setTotalExperienceMin("");
    setKnockoutStatus("");
    router.push(pathname);
  }

  return (
    <aside className="rounded-xl border border-slate-200 bg-white p-4 shadow-sm">
      <h2 className="font-heading text-lg font-semibold text-slate-900">Filters</h2>
      <p className="mt-1 text-xs text-slate-500">Refine applicants for this job</p>

      <div className="mt-4 space-y-3">
        <div>
          <label className="mb-1 block text-xs font-semibold uppercase tracking-wide text-slate-500">
            Keywords
          </label>
          <input
            value={keyword}
            onChange={(event) => setKeyword(event.target.value)}
            placeholder="marketing, sql, servicenow..."
            className="w-full rounded-md border border-slate-300 px-2 py-1.5 text-sm"
          />
        </div>

        <div>
          <label className="mb-1 block text-xs font-semibold uppercase tracking-wide text-slate-500">
            Status
          </label>
          <select
            value={status}
            onChange={(event) => setStatus(event.target.value)}
            className="w-full rounded-md border border-slate-300 px-2 py-1.5 text-sm"
          >
            <option value="">Any</option>
            <option value="review">Review</option>
            <option value="shortlisted">Shortlisted</option>
            <option value="rejected">Rejected</option>
            <option value="interviewed">Interviewed</option>
            <option value="hired">Hired</option>
            <option value="parsed">Parsed</option>
            <option value="pending">Pending</option>
          </select>
        </div>

        <div>
          <label className="mb-1 block text-xs font-semibold uppercase tracking-wide text-slate-500">
            Minimum Score
          </label>
          <input
            value={minScore}
            onChange={(event) => setMinScore(event.target.value)}
            placeholder="0 - 100"
            className="w-full rounded-md border border-slate-300 px-2 py-1.5 text-sm"
          />
        </div>

        <div>
          <label className="mb-1 block text-xs font-semibold uppercase tracking-wide text-slate-500">
            Relevant Experience
          </label>
          <input
            value={minExperience}
            onChange={(event) => setMinExperience(event.target.value)}
            placeholder="years"
            className="w-full rounded-md border border-slate-300 px-2 py-1.5 text-sm"
          />
        </div>

        <div>
          <label className="mb-1 block text-xs font-semibold uppercase tracking-wide text-slate-500">
            Skill
          </label>
          <input
            value={skill}
            onChange={(event) => setSkill(event.target.value)}
            placeholder="python / servicenow / sql"
            className="w-full rounded-md border border-slate-300 px-2 py-1.5 text-sm"
          />
        </div>

        <div>
          <label className="mb-1 block text-xs font-semibold uppercase tracking-wide text-slate-500">
            Action Status
          </label>
          <select
            value={action}
            onChange={(event) => setAction(event.target.value)}
            className="w-full rounded-md border border-slate-300 px-2 py-1.5 text-sm"
          >
            <option value="">Any</option>
            <option value="shortlisted">Shortlisted</option>
            <option value="rejected">Rejected</option>
            <option value="interviewed">Interviewed</option>
            <option value="hired">Hired</option>
            <option value="viewed">Viewed</option>
          </select>
        </div>

        <div>
          <label className="mb-1 block text-xs font-semibold uppercase tracking-wide text-slate-500">
            Highest Degree
          </label>
          <select
            value={highestDegree}
            onChange={(event) => setHighestDegree(event.target.value)}
            className="w-full rounded-md border border-slate-300 px-2 py-1.5 text-sm"
          >
            <option value="">Any</option>
            <option value="Master">Master's</option>
            <option value="Bachelor">Bachelor's</option>
            <option value="Associate">Associate's</option>
            <option value="PhD">PhD</option>
          </select>
        </div>

        <div>
          <label className="mb-1 block text-xs font-semibold uppercase tracking-wide text-slate-500">
            Distance (max miles)
          </label>
          <input
            value={distanceMax}
            onChange={(event) => setDistanceMax(event.target.value)}
            placeholder="25"
            className="w-full rounded-md border border-slate-300 px-2 py-1.5 text-sm"
          />
        </div>

        <div>
          <label className="mb-1 block text-xs font-semibold uppercase tracking-wide text-slate-500">
            Total Years Experience
          </label>
          <input
            value={totalExperienceMin}
            onChange={(event) => setTotalExperienceMin(event.target.value)}
            placeholder="3"
            className="w-full rounded-md border border-slate-300 px-2 py-1.5 text-sm"
          />
        </div>

        <div>
          <label className="mb-1 block text-xs font-semibold uppercase tracking-wide text-slate-500">
            Knockout Status
          </label>
          <select
            value={knockoutStatus}
            onChange={(event) => setKnockoutStatus(event.target.value)}
            className="w-full rounded-md border border-slate-300 px-2 py-1.5 text-sm"
          >
            <option value="">All</option>
            <option value="qualified">Qualified</option>
            <option value="disqualified">Disqualified</option>
          </select>
        </div>

        <div>
          <label className="mb-1 block text-xs font-semibold uppercase tracking-wide text-slate-500">
            Sponsorship Required?
          </label>
          <select
            value={sponsorshipRequired}
            onChange={(event) => setSponsorshipRequired(event.target.value)}
            className="w-full rounded-md border border-slate-300 px-2 py-1.5 text-sm"
          >
            <option value="">Any</option>
            <option value="true">Yes</option>
            <option value="false">No</option>
          </select>
        </div>
      </div>

      <div className="mt-4 flex gap-2">
        <button
          onClick={applyFilters}
          className="rounded-md bg-teal px-3 py-1.5 text-sm font-semibold text-white"
        >
          Apply
        </button>
        <button
          onClick={clearFilters}
          className="rounded-md border border-slate-300 px-3 py-1.5 text-sm font-semibold text-slate-700"
        >
          Clear
        </button>
      </div>
    </aside>
  );
}
