import { type ParsedResumeRow } from "@/lib/api";

function statusClass(status: ParsedResumeRow["parse_status"]): string {
  if (status === "parsed") return "bg-emerald-50 text-emerald-700 border-emerald-200";
  if (status === "failed") return "bg-rose-50 text-rose-700 border-rose-200";
  return "bg-amber-50 text-amber-700 border-amber-200";
}

export default function ParsedResumesTable({ rows }: { rows: ParsedResumeRow[] }) {
  return (
    <section className="rounded-2xl border border-slate-200 bg-white p-4 shadow-sm">
      <div className="mb-3 flex items-center justify-between">
        <h2 className="font-heading text-xl font-semibold text-ink">Parsed Resumes</h2>
        <span className="rounded-full bg-slate-100 px-3 py-1 text-xs font-semibold text-slate-700">
          {rows.length} total
        </span>
      </div>

      {rows.length === 0 ? (
        <p className="rounded-lg border border-dashed border-slate-300 bg-slate-50 p-4 text-sm text-slate-600">
          No resumes uploaded for this job yet.
        </p>
      ) : null}

      {rows.length > 0 ? (
        <div className="overflow-x-auto">
          <table className="w-full border-collapse text-left text-sm">
            <thead>
              <tr className="border-b border-slate-100 text-slate-500">
                <th className="py-2 pr-3">Candidate</th>
                <th className="py-2 pr-3">Email</th>
                <th className="py-2 pr-3">File</th>
                <th className="py-2 pr-3">Status</th>
                <th className="py-2 pr-3">Experience</th>
                <th className="py-2 pr-3">Skills</th>
                <th className="py-2">Parse Error</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((row) => (
                <tr key={row.job_resume_id} className="border-b border-slate-50 align-top">
                  <td className="py-2 pr-3 font-medium text-slate-900">{row.candidate_name}</td>
                  <td className="py-2 pr-3 text-slate-700">{row.email ?? "-"}</td>
                  <td className="py-2 pr-3 text-slate-700">{row.source_filename ?? "-"}</td>
                  <td className="py-2 pr-3">
                    <span className={`rounded-full border px-2 py-1 text-xs font-semibold ${statusClass(row.parse_status)}`}>
                      {row.parse_status}
                    </span>
                  </td>
                  <td className="py-2 pr-3 text-slate-700">
                    {row.experience_years !== null ? `${row.experience_years} yrs` : "-"}
                  </td>
                  <td className="py-2 pr-3 text-slate-700">
                    {row.skills.length > 0 ? row.skills.slice(0, 6).join(", ") : "-"}
                  </td>
                  <td className="py-2 text-rose-700">{row.parse_error ?? "-"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : null}
    </section>
  );
}
