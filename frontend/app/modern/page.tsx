import Link from "next/link";

const features = [
  {
    title: "Neural Match Engine",
    body: "Semantic retrieval + LLM reasoning ranks candidates with context-aware fit signals instead of brittle keyword filters.",
  },
  {
    title: "Evidence-First Decisions",
    body: "Each score is traceable to resume evidence, missing skills, and confidence rationale for transparent recruiter decisions.",
  },
  {
    title: "Workflow in One Surface",
    body: "Upload, parse, shortlist, and move candidates through actions without leaving a single recruiter workspace.",
  },
];

const stats = [
  { label: "Avg. Screen Time Saved", value: "58%" },
  { label: "Top-10 Relevance", value: "+34%" },
  { label: "Resume Throughput", value: "10k/mo" },
];

const plans = [
  {
    name: "Launch",
    price: "Free",
    tagline: "Best for early hiring teams",
    perks: ["3 active jobs", "Manual rank runs", "Core explanations"],
  },
  {
    name: "Growth",
    price: "$79/mo",
    tagline: "Best for scaling recruiters",
    perks: ["Unlimited jobs", "Action analytics", "LLM-assisted scoring"],
    featured: true,
  },
  {
    name: "Scale",
    price: "Custom",
    tagline: "Best for enterprise orgs",
    perks: ["Compliance controls", "Custom weighting", "Priority model tuning"],
  },
];

export default function ModernHomePage() {
  return (
    <main className="min-h-screen bg-[#060B16] text-white">
      <div className="absolute inset-0 -z-10 bg-[radial-gradient(circle_at_20%_20%,rgba(0,211,255,0.18),transparent_30%),radial-gradient(circle_at_80%_30%,rgba(42,255,157,0.16),transparent_28%),radial-gradient(circle_at_50%_80%,rgba(255,115,0,0.14),transparent_35%)]" />

      <section className="mx-auto max-w-7xl px-6 pb-20 pt-10">
        <header className="mb-14 flex items-center justify-between">
          <div>
            <p className="font-heading text-xl font-bold tracking-tight">ATS Talent Intelligence</p>
            <p className="text-xs uppercase tracking-[0.2em] text-cyan-200/80">Modern Startup Variant</p>
          </div>
          <div className="flex gap-3">
            <Link href="/" className="rounded-full border border-white/25 px-4 py-2 text-sm font-semibold text-white/90">
              Enterprise Style
            </Link>
            <Link href="/recruiter" className="rounded-full bg-cyan-400 px-4 py-2 text-sm font-semibold text-slate-900">
              Start Screening
            </Link>
          </div>
        </header>

        <div className="grid gap-8 lg:grid-cols-[1.1fr,0.9fr]">
          <div>
            <p className="inline-block rounded-full border border-cyan-300/40 bg-cyan-300/10 px-3 py-1 text-xs font-semibold text-cyan-100">
              AI Recruiter Operating System
            </p>
            <h1 className="mt-5 font-heading text-5xl font-bold leading-tight md:text-6xl">
              Build your shortlist before your coffee gets cold.
            </h1>
            <p className="mt-5 max-w-2xl text-lg text-slate-200/85">
              A recruiter-first intelligence layer that turns raw resumes into ranked talent pipelines with
              explainable scoring, confidence signals, and action-ready insights.
            </p>
            <div className="mt-8 flex flex-wrap gap-3">
              <Link href="/recruiter" className="rounded-full bg-cyan-400 px-6 py-3 text-sm font-bold text-slate-900">
                Start Screening
              </Link>
              <a href="#pricing" className="rounded-full border border-white/30 px-6 py-3 text-sm font-semibold text-white/90">
                Book Demo
              </a>
            </div>

            <div className="mt-10 grid gap-3 sm:grid-cols-3">
              {stats.map((stat) => (
                <div key={stat.label} className="rounded-2xl border border-white/15 bg-white/5 p-4 backdrop-blur">
                  <p className="text-2xl font-bold text-cyan-200">{stat.value}</p>
                  <p className="mt-1 text-xs text-slate-300">{stat.label}</p>
                </div>
              ))}
            </div>
          </div>

          <div className="rounded-3xl border border-white/15 bg-white/5 p-5 backdrop-blur">
            <p className="text-sm font-semibold text-cyan-100">Live Hiring Feed</p>
            <div className="mt-4 space-y-3">
              <div className="rounded-2xl border border-white/10 bg-slate-900/60 p-4">
                <p className="font-semibold">Data Analyst - Manufacturing</p>
                <p className="text-sm text-slate-300">2 resumes parsed • top confidence 93%</p>
              </div>
              <div className="rounded-2xl border border-white/10 bg-slate-900/60 p-4">
                <p className="font-semibold">ServiceNow Developer</p>
                <p className="text-sm text-slate-300">120 resumes • 38 shortlisted</p>
              </div>
              <div className="rounded-2xl border border-white/10 bg-slate-900/60 p-4">
                <p className="font-semibold">Product Manager</p>
                <p className="text-sm text-slate-300">63 resumes • rank rerun 5 mins ago</p>
              </div>
            </div>
          </div>
        </div>
      </section>

      <section className="mx-auto max-w-7xl px-6 py-8">
        <h2 className="font-heading text-3xl font-bold">Product Highlights</h2>
        <div className="mt-5 grid gap-4 md:grid-cols-3">
          {features.map((feature) => (
            <article key={feature.title} className="rounded-2xl border border-white/15 bg-white/5 p-5 backdrop-blur">
              <h3 className="font-heading text-xl font-semibold text-cyan-100">{feature.title}</h3>
              <p className="mt-2 text-slate-200/85">{feature.body}</p>
            </article>
          ))}
        </div>
      </section>

      <section className="mx-auto max-w-7xl px-6 py-8">
        <h2 className="font-heading text-3xl font-bold">Workflow</h2>
        <div className="mt-5 grid gap-4 md:grid-cols-4">
          {[
            "Create job profile",
            "Upload and parse resumes",
            "Run ranking + reasoning",
            "Take recruiter actions",
          ].map((step, index) => (
            <div key={step} className="rounded-2xl border border-white/15 bg-white/5 p-4 backdrop-blur">
              <p className="text-xs font-semibold uppercase tracking-[0.18em] text-cyan-200">Step {index + 1}</p>
              <p className="mt-2 font-medium text-white">{step}</p>
            </div>
          ))}
        </div>
      </section>

      <section id="pricing" className="mx-auto max-w-7xl px-6 py-10">
        <h2 className="font-heading text-3xl font-bold">Pricing</h2>
        <div className="mt-6 grid gap-4 md:grid-cols-3">
          {plans.map((plan) => (
            <article
              key={plan.name}
              className={`rounded-2xl border p-5 backdrop-blur ${
                plan.featured
                  ? "border-cyan-300 bg-cyan-400/10 shadow-[0_0_0_1px_rgba(34,211,238,0.35)]"
                  : "border-white/15 bg-white/5"
              }`}
            >
              <h3 className="font-heading text-2xl font-semibold">{plan.name}</h3>
              <p className="mt-2 text-3xl font-bold text-cyan-100">{plan.price}</p>
              <p className="mt-1 text-sm text-slate-300">{plan.tagline}</p>
              <ul className="mt-4 space-y-2 text-sm text-slate-200">
                {plan.perks.map((perk) => (
                  <li key={perk}>• {perk}</li>
                ))}
              </ul>
            </article>
          ))}
        </div>
      </section>

      <section className="mx-auto max-w-7xl px-6 pb-16 pt-4">
        <div className="rounded-3xl border border-cyan-300/35 bg-cyan-400/10 p-8 text-center backdrop-blur">
          <h2 className="font-heading text-3xl font-bold">Move from resume chaos to hiring clarity.</h2>
          <p className="mx-auto mt-3 max-w-2xl text-slate-200/90">
            Rank smarter, explain decisions, and operate a faster recruiting funnel with one connected platform.
          </p>
          <div className="mt-6 flex justify-center gap-3">
            <Link href="/recruiter" className="rounded-full bg-cyan-300 px-6 py-3 text-sm font-bold text-slate-900">
              Start Screening
            </Link>
            <a href="#pricing" className="rounded-full border border-white/30 px-6 py-3 text-sm font-semibold text-white">
              Book Demo
            </a>
          </div>
        </div>
      </section>

      <footer className="border-t border-white/10 py-6">
        <div className="mx-auto flex max-w-7xl flex-col gap-2 px-6 text-sm text-slate-300 md:flex-row md:items-center md:justify-between">
          <p>© 2026 ATS Talent Intelligence</p>
          <p>Modern startup style preview</p>
        </div>
      </footer>
    </main>
  );
}
