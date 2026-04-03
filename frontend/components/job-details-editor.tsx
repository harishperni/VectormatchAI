"use client";

import { FormEvent, useMemo, useState } from "react";
import { useRouter } from "next/navigation";

import type { Job } from "@/lib/api";

function toList(value: string): string[] {
  return value
    .split(",")
    .map((item) => item.trim())
    .filter(Boolean);
}

type Props = {
  jobId: string;
  job: Job;
};

export default function JobDetailsEditor({ jobId, job }: Props) {
  const router = useRouter();
  const [editing, setEditing] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const [title, setTitle] = useState(job.title);
  const [description, setDescription] = useState(job.description);
  const [location, setLocation] = useState(job.location ?? "");
  const [workMode, setWorkMode] = useState<"remote" | "hybrid" | "inperson">(job.work_mode ?? "remote");
  const [minExperience, setMinExperience] = useState(
    job.min_experience_years == null ? "" : String(job.min_experience_years)
  );
  const [requiredSkills, setRequiredSkills] = useState(job.required_skills.join(", "));
  const [niceToHaveSkills, setNiceToHaveSkills] = useState(job.nice_to_have_skills.join(", "));
  const [domainTags, setDomainTags] = useState(job.domain_tags.join(", "));

  const hasData = useMemo(() => {
    return Boolean(
      job.location ||
        job.min_experience_years != null ||
        job.required_skills.length ||
        job.nice_to_have_skills.length ||
        job.domain_tags.length
    );
  }, [job]);

  async function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setSubmitting(true);
    setError(null);

    try {
      const payload = {
        title: title.trim(),
        description: description.trim(),
        location: location.trim() || null,
        work_mode: workMode,
        min_experience_years: minExperience.trim() ? Number(minExperience) : null,
        required_skills: toList(requiredSkills),
        nice_to_have_skills: toList(niceToHaveSkills),
        domain_tags: toList(domainTags),
      };

      const response = await fetch(`/api/jobs/${jobId}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      if (!response.ok) {
        const text = await response.text();
        throw new Error(text || `Update failed (${response.status})`);
      }
      setEditing(false);
      router.refresh();
    } catch (submitError) {
      const message = submitError instanceof Error ? submitError.message : "Could not update job";
      setError(message);
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <section className="mt-4 rounded-2xl border border-slate-200 bg-white p-4 shadow-sm">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div>
          <p className="text-xs uppercase tracking-wide text-slate-500">Saved Job</p>
          <h2 className="text-lg font-semibold text-slate-900">{job.title}</h2>
        </div>
        <button
          type="button"
          onClick={() => {
            setEditing((prev) => !prev);
            setError(null);
          }}
          className="rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm font-semibold text-slate-700"
        >
          {editing ? "Close" : "Edit Job"}
        </button>
      </div>

      {!editing ? (
        <div className="mt-3 grid gap-2 text-sm text-slate-700 md:grid-cols-2">
          <p className="md:col-span-2 text-slate-600">{job.description}</p>
          <p>
            <span className="font-semibold text-slate-900">Location:</span> {job.location || "Not set"}
          </p>
          <p>
            <span className="font-semibold text-slate-900">Work Mode:</span> {job.work_mode}
          </p>
          <p>
            <span className="font-semibold text-slate-900">Min Experience:</span>{" "}
            {job.min_experience_years == null ? "Not set" : `${job.min_experience_years} years`}
          </p>
          <p>
            <span className="font-semibold text-slate-900">Required Skills:</span>{" "}
            {job.required_skills.length ? job.required_skills.join(", ") : "Not set"}
          </p>
          <p>
            <span className="font-semibold text-slate-900">Nice to Have:</span>{" "}
            {job.nice_to_have_skills.length ? job.nice_to_have_skills.join(", ") : "Not set"}
          </p>
          <p className="md:col-span-2">
            <span className="font-semibold text-slate-900">Domain Tags:</span>{" "}
            {job.domain_tags.length ? job.domain_tags.join(", ") : "Not set"}
          </p>
          {!hasData ? <p className="md:col-span-2 text-slate-500">No additional job details yet.</p> : null}
        </div>
      ) : (
        <form className="mt-4 grid gap-3 md:grid-cols-2" onSubmit={onSubmit}>
          <label className="flex flex-col gap-1 text-sm font-medium text-slate-700">
            Title
            <input
              required
              minLength={2}
              value={title}
              onChange={(event) => setTitle(event.target.value)}
              className="rounded-lg border border-slate-300 px-3 py-2 text-sm"
            />
          </label>

          <label className="flex flex-col gap-1 text-sm font-medium text-slate-700">
            Location
            <input
              value={location}
              onChange={(event) => setLocation(event.target.value)}
              className="rounded-lg border border-slate-300 px-3 py-2 text-sm"
              placeholder="Chicago, IL"
            />
          </label>

          <label className="flex flex-col gap-1 text-sm font-medium text-slate-700">
            Work Mode
            <select
              value={workMode}
              onChange={(event) => setWorkMode(event.target.value as "remote" | "hybrid" | "inperson")}
              className="rounded-lg border border-slate-300 px-3 py-2 text-sm"
            >
              <option value="remote">Remote</option>
              <option value="hybrid">Hybrid</option>
              <option value="inperson">In-person</option>
            </select>
          </label>

          <label className="flex flex-col gap-1 text-sm font-medium text-slate-700 md:col-span-2">
            Job Duties / Description
            <textarea
              required
              minLength={20}
              value={description}
              onChange={(event) => setDescription(event.target.value)}
              className="min-h-28 rounded-lg border border-slate-300 px-3 py-2 text-sm"
            />
          </label>

          <label className="flex flex-col gap-1 text-sm font-medium text-slate-700">
            Min Experience (years)
            <input
              type="number"
              min={0}
              step="0.5"
              value={minExperience}
              onChange={(event) => setMinExperience(event.target.value)}
              className="rounded-lg border border-slate-300 px-3 py-2 text-sm"
            />
          </label>

          <label className="flex flex-col gap-1 text-sm font-medium text-slate-700">
            Domain Tags
            <input
              value={domainTags}
              onChange={(event) => setDomainTags(event.target.value)}
              className="rounded-lg border border-slate-300 px-3 py-2 text-sm"
              placeholder="frontend, sharepoint, enterprise"
            />
          </label>

          <label className="flex flex-col gap-1 text-sm font-medium text-slate-700">
            Required Skills
            <input
              value={requiredSkills}
              onChange={(event) => setRequiredSkills(event.target.value)}
              className="rounded-lg border border-slate-300 px-3 py-2 text-sm"
              placeholder="SharePoint, Power Automate, JavaScript"
            />
          </label>

          <label className="flex flex-col gap-1 text-sm font-medium text-slate-700">
            Nice to Have Skills
            <input
              value={niceToHaveSkills}
              onChange={(event) => setNiceToHaveSkills(event.target.value)}
              className="rounded-lg border border-slate-300 px-3 py-2 text-sm"
            />
          </label>

          <div className="md:col-span-2">
            <button
              type="submit"
              disabled={submitting}
              className="rounded-lg bg-teal px-5 py-2 text-sm font-semibold text-white disabled:cursor-not-allowed disabled:opacity-60"
            >
              {submitting ? "Saving..." : "Save Job"}
            </button>
          </div>

          {error ? (
            <p className="md:col-span-2 rounded-lg border border-rose-200 bg-rose-50 px-3 py-2 text-sm text-rose-800">
              {error}
            </p>
          ) : null}
        </form>
      )}
    </section>
  );
}
