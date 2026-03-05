import Link from "next/link";

import { Job } from "@/lib/api";

export default function Dashboard({ jobs }: { jobs: Job[] }) {
  return (
    <main className="mx-auto max-w-6xl px-6 py-10">
      <header className="mb-8">
        <h1 className="font-heading text-4xl font-bold text-ink">Active Jobs</h1>
        <p className="text-lg text-slate-600">AI-ranked candidate pipelines with explainable scoring</p>
      </header>

      {jobs.length === 0 ? (
        <section className="rounded-2xl border border-dashed border-slate-300 bg-white p-8 text-center text-slate-600">
          No jobs found yet. Create one via API (`POST /api/v1/jobs`) and refresh.
        </section>
      ) : null}

      <section className="grid gap-4 md:grid-cols-3">
        {jobs.map((job) => (
          <Link key={job.id} href={`/jobs/${job.id}`} className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm transition hover:-translate-y-1 hover:shadow-md">
            <h2 className="font-heading text-xl font-semibold text-ink">{job.title}</h2>
            <p className="mt-2 line-clamp-3 text-slate-600">{job.description}</p>
            <p className="mt-2 text-sm text-slate-500">
              Min experience: {job.min_experience_years ?? "Not specified"} years
            </p>
          </Link>
        ))}
      </section>
    </main>
  );
}
