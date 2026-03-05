"use client";

import { FormEvent, useState } from "react";
import { useRouter } from "next/navigation";

type CreateJobResponse = {
  id: string;
  title: string;
};

function toList(value: string): string[] {
  return value
    .split(",")
    .map((item) => item.trim())
    .filter(Boolean);
}

export default function CreateJobForm() {
  const router = useRouter();
  const [title, setTitle] = useState("");
  const [description, setDescription] = useState("");
  const [location, setLocation] = useState("");
  const [minExperience, setMinExperience] = useState("");
  const [requiredSkills, setRequiredSkills] = useState("");
  const [niceToHaveSkills, setNiceToHaveSkills] = useState("");
  const [domainTags, setDomainTags] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setSubmitting(true);
    setError(null);

    try {
      const payload = {
        title: title.trim(),
        description: description.trim(),
        location: location.trim() || null,
        min_experience_years: minExperience.trim() ? Number(minExperience) : null,
        required_skills: toList(requiredSkills),
        nice_to_have_skills: toList(niceToHaveSkills),
        domain_tags: toList(domainTags),
      };

      const response = await fetch("/api/jobs", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      if (!response.ok) {
        const text = await response.text();
        throw new Error(text || `Create job failed (${response.status})`);
      }
      const created = (await response.json()) as CreateJobResponse;
      setTitle("");
      setDescription("");
      setLocation("");
      setMinExperience("");
      setRequiredSkills("");
      setNiceToHaveSkills("");
      setDomainTags("");
      router.push(`/jobs/${created.id}`);
      router.refresh();
    } catch (submitError) {
      const message = submitError instanceof Error ? submitError.message : "Could not create job";
      setError(message);
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <section className="mb-8 rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">
      <h2 className="font-heading text-2xl font-semibold text-ink">Create New Job</h2>
      <p className="mt-1 text-sm text-slate-600">Use UI instead of curl. Skills and tags are comma-separated.</p>

      <form className="mt-4 grid gap-3 md:grid-cols-2" onSubmit={onSubmit}>
        <label className="flex flex-col gap-1 text-sm font-medium text-slate-700">
          Title
          <input
            required
            minLength={2}
            value={title}
            onChange={(event) => setTitle(event.target.value)}
            className="rounded-lg border border-slate-300 px-3 py-2 text-sm"
            placeholder="Data Analyst - Manufacturing Analytics"
          />
        </label>

        <label className="flex flex-col gap-1 text-sm font-medium text-slate-700">
          Location
          <input
            value={location}
            onChange={(event) => setLocation(event.target.value)}
            className="rounded-lg border border-slate-300 px-3 py-2 text-sm"
            placeholder="Fort Worth, TX"
          />
        </label>

        <label className="flex flex-col gap-1 text-sm font-medium text-slate-700 md:col-span-2">
          Description
          <textarea
            required
            minLength={20}
            value={description}
            onChange={(event) => setDescription(event.target.value)}
            className="min-h-32 rounded-lg border border-slate-300 px-3 py-2 text-sm"
            placeholder="Paste full JD here..."
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
            placeholder="3"
          />
        </label>

        <label className="flex flex-col gap-1 text-sm font-medium text-slate-700">
          Domain Tags
          <input
            value={domainTags}
            onChange={(event) => setDomainTags(event.target.value)}
            className="rounded-lg border border-slate-300 px-3 py-2 text-sm"
            placeholder="manufacturing, analytics, finance"
          />
        </label>

        <label className="flex flex-col gap-1 text-sm font-medium text-slate-700">
          Required Skills
          <input
            value={requiredSkills}
            onChange={(event) => setRequiredSkills(event.target.value)}
            className="rounded-lg border border-slate-300 px-3 py-2 text-sm"
            placeholder="SQL, Python, Power BI"
          />
        </label>

        <label className="flex flex-col gap-1 text-sm font-medium text-slate-700">
          Nice to Have Skills
          <input
            value={niceToHaveSkills}
            onChange={(event) => setNiceToHaveSkills(event.target.value)}
            className="rounded-lg border border-slate-300 px-3 py-2 text-sm"
            placeholder="KNIME, Tableau"
          />
        </label>

        <div className="md:col-span-2">
          <button
            type="submit"
            disabled={submitting}
            className="rounded-lg bg-teal px-5 py-2 text-sm font-semibold text-white disabled:cursor-not-allowed disabled:opacity-60"
          >
            {submitting ? "Creating..." : "Create Job"}
          </button>
        </div>

        {error ? (
          <p className="md:col-span-2 rounded-lg border border-rose-200 bg-rose-50 px-3 py-2 text-sm text-rose-800">
            {error}
          </p>
        ) : null}
      </form>
    </section>
  );
}

