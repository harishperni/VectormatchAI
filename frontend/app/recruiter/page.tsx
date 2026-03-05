import Dashboard from "@/components/dashboard";
import { fetchJobs } from "@/lib/api";

export default async function RecruiterHomePage() {
  try {
    const jobs = await fetchJobs();
    return <Dashboard jobs={jobs} />;
  } catch (error) {
    const message = error instanceof Error ? error.message : "Unknown error";
    return (
      <main className="mx-auto max-w-5xl px-6 py-10">
        <h1 className="font-heading text-4xl font-bold text-ink">Recruiter Dashboard</h1>
        <p className="mt-4 rounded-xl border border-amber-200 bg-amber-50 p-4 text-amber-900">
          Could not reach backend at `http://127.0.0.1:8000`. Error: {message}
        </p>
      </main>
    );
  }
}
