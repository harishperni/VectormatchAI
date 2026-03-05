import Link from "next/link";

const highlights = [
  {
    title: "Explainable Ranking",
    body: "Every candidate score is backed by evidence snippets, skill gaps, and confidence indicators recruiters can trust.",
  },
  {
    title: "Semantic Resume Search",
    body: "Embedding-based relevance finds strong candidates even when exact keywords are missing from the resume.",
  },
  {
    title: "Recruiter Workflow",
    body: "Shortlist, reject, interview status, and ranking filters are built into one clean operational view.",
  },
];

const workflow = [
  "Create job and define must-have skills",
  "Upload resumes in PDF/DOCX",
  "Run AI ranking with explanation",
  "Filter, shortlist, and move candidates",
];

const pricing = [
  {
    plan: "Starter",
    price: "Free",
    details: "For solo recruiters and MVP hiring",
    features: ["Up to 3 active jobs", "Manual ranking runs", "Basic explainability"],
  },
  {
    plan: "Team",
    price: "$49/mo",
    details: "For hiring teams",
    features: ["Unlimited jobs", "Action tracking + filters", "Advanced score analysis"],
  },
  {
    plan: "Enterprise",
    price: "Custom",
    details: "For high-volume recruiting",
    features: ["Custom model tuning", "Compliance tooling", "Priority support"],
  },
];

export default function HomePage() {
  return (
    <main className="min-h-screen bg-gradient-to-b from-slate-50 to-cyan-50 text-slate-900">
      <section className="mx-auto max-w-7xl px-6 pb-20 pt-10">
        <header className="mb-16 flex items-center justify-between">
          <div>
            <p className="font-heading text-xl font-bold">ATS Talent Intelligence</p>
            <p className="text-sm text-slate-600">Enterprise recruiter workspace</p>
          </div>
          <div className="flex gap-3">
            <Link
              href="/recruiter"
              className="rounded-lg border border-slate-300 px-4 py-2 text-sm font-semibold text-slate-700"
            >
              Start Screening
            </Link>
            <a
              href="#pricing"
              className="rounded-lg bg-teal px-4 py-2 text-sm font-semibold text-white"
            >
              Book Demo
            </a>
          </div>
        </header>

        <div className="grid gap-8 rounded-3xl border border-slate-200 bg-white p-8 shadow-sm lg:grid-cols-[1.2fr,0.8fr]">
          <div>
            <p className="mb-3 inline-block rounded-full bg-teal-50 px-3 py-1 text-xs font-semibold text-teal-700">
              AI-assisted Recruiting Platform
            </p>
            <h1 className="font-heading text-5xl font-bold leading-tight">
              Hire faster with transparent AI candidate intelligence.
            </h1>
            <p className="mt-4 max-w-2xl text-lg text-slate-600">
              Built for recruiters who need speed without sacrificing trust. Rank candidates by relevance,
              review evidence-backed reasoning, and move top talent through the funnel in minutes.
            </p>
            <div className="mt-8 flex flex-wrap gap-3">
              <Link
                href="/recruiter"
                className="rounded-lg bg-teal px-5 py-3 text-sm font-semibold text-white"
              >
                Start Screening
              </Link>
              <a
                href="#workflow"
                className="rounded-lg border border-slate-300 px-5 py-3 text-sm font-semibold text-slate-700"
              >
                View Workflow
              </a>
            </div>
          </div>

          <div className="rounded-2xl border border-slate-200 bg-slate-50 p-5">
            <p className="text-sm font-semibold text-slate-700">Live Recruiting Snapshot</p>
            <div className="mt-3 space-y-3 text-sm">
              <div className="rounded-lg border border-slate-200 bg-white p-3">
                <p className="font-semibold">ServiceNow Developer</p>
                <p className="text-slate-600">120 resumes • top score 92%</p>
              </div>
              <div className="rounded-lg border border-slate-200 bg-white p-3">
                <p className="font-semibold">Data Analyst</p>
                <p className="text-slate-600">87 resumes • top score 89%</p>
              </div>
              <div className="rounded-lg border border-slate-200 bg-white p-3">
                <p className="font-semibold">Product Manager</p>
                <p className="text-slate-600">63 resumes • top score 86%</p>
              </div>
            </div>
          </div>
        </div>
      </section>

      <section className="mx-auto max-w-7xl px-6 py-10">
        <h2 className="font-heading text-3xl font-bold">Product Highlights</h2>
        <div className="mt-6 grid gap-4 md:grid-cols-3">
          {highlights.map((item) => (
            <article key={item.title} className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">
              <h3 className="font-heading text-xl font-semibold">{item.title}</h3>
              <p className="mt-2 text-slate-600">{item.body}</p>
            </article>
          ))}
        </div>
      </section>

      <section id="workflow" className="mx-auto max-w-7xl px-6 py-10">
        <h2 className="font-heading text-3xl font-bold">Recruiter Workflow</h2>
        <ol className="mt-6 grid gap-4 md:grid-cols-2">
          {workflow.map((step, index) => (
            <li key={step} className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">
              <p className="text-xs font-semibold uppercase tracking-wide text-teal">Step {index + 1}</p>
              <p className="mt-2 text-lg font-medium text-slate-800">{step}</p>
            </li>
          ))}
        </ol>
      </section>

      <section id="pricing" className="mx-auto max-w-7xl px-6 py-10">
        <h2 className="font-heading text-3xl font-bold">Pricing</h2>
        <div className="mt-6 grid gap-4 md:grid-cols-3">
          {pricing.map((tier) => (
            <article key={tier.plan} className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">
              <h3 className="font-heading text-2xl font-semibold">{tier.plan}</h3>
              <p className="mt-2 text-3xl font-bold text-slate-900">{tier.price}</p>
              <p className="mt-1 text-sm text-slate-600">{tier.details}</p>
              <ul className="mt-4 space-y-2 text-sm text-slate-700">
                {tier.features.map((feature) => (
                  <li key={feature}>• {feature}</li>
                ))}
              </ul>
            </article>
          ))}
        </div>
      </section>

      <section className="mx-auto max-w-7xl px-6 py-12">
        <div className="rounded-3xl border border-teal-200 bg-teal-50 p-8 text-center">
          <h2 className="font-heading text-3xl font-bold">Ready to transform recruiter productivity?</h2>
          <p className="mx-auto mt-3 max-w-2xl text-slate-700">
            Start screening candidates with explainable AI rankings and enterprise-ready workflows.
          </p>
          <div className="mt-6 flex justify-center gap-3">
            <Link href="/recruiter" className="rounded-lg bg-teal px-5 py-3 text-sm font-semibold text-white">
              Start Screening
            </Link>
            <a href="#pricing" className="rounded-lg border border-slate-300 px-5 py-3 text-sm font-semibold text-slate-700">
              Book Demo
            </a>
          </div>
        </div>
      </section>

      <footer className="border-t border-slate-200 bg-white">
        <div className="mx-auto flex max-w-7xl flex-col gap-2 px-6 py-6 text-sm text-slate-600 md:flex-row md:items-center md:justify-between">
          <p>© 2026 ATS Talent Intelligence</p>
          <p>Built for enterprise recruiting teams</p>
        </div>
      </footer>
    </main>
  );
}
