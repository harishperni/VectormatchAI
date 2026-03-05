"use client";

import { useRouter } from "next/navigation";
import { type FormEvent, useState } from "react";

type IngestionStatus = {
  job_id: string;
  queued: number;
  queue_failed: number;
  total_uploaded: number;
};

export default function ResumeUploadPanel({ jobId }: { jobId: string }) {
  const router = useRouter();
  const [files, setFiles] = useState<FileList | null>(null);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<string>("Idle");
  const [status, setStatus] = useState<IngestionStatus | null>(null);

  async function onUpload(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    if (!files || files.length === 0) {
      setMessage("Please choose at least one resume.");
      return;
    }

    const formData = new FormData();
    for (const file of Array.from(files)) {
      formData.append("files", file);
    }

    setBusy(true);
    setMessage("Uploading resumes...");

    try {
      const response = await fetch(`/api/jobs/${jobId}/resumes/upload`, {
        method: "POST",
        body: formData,
      });

      const payload = await response.json();
      if (!response.ok) {
        setMessage(payload?.detail ?? "Upload failed.");
      } else {
        setMessage(`Uploaded ${payload.uploaded_count} file(s), queued ${payload.queued_count}.`);
        setFiles(null);
      }
    } catch {
      setMessage("Upload request failed.");
    } finally {
      setBusy(false);
      router.refresh();
    }
  }

  async function refreshStatus() {
    setBusy(true);
    setMessage("Checking ingestion status...");

    try {
      const response = await fetch(`/api/jobs/${jobId}/ingestion-status`, { cache: "no-store" });
      const payload = await response.json();
      if (!response.ok) {
        setMessage(payload?.detail ?? "Status check failed.");
      } else {
        setStatus(payload);
        setMessage("Ingestion status updated.");
      }
    } catch {
      setMessage("Status request failed.");
    } finally {
      setBusy(false);
    }
  }

  async function runRanking() {
    setBusy(true);
    setMessage("Running ranking...");

    try {
      const response = await fetch(`/api/jobs/${jobId}/rank`, {
        method: "POST",
      });
      const payload = await response.json();
      if (!response.ok) {
        setMessage(payload?.detail ?? "Ranking failed.");
      } else {
        setMessage(`Ranking completed. Processed resumes: ${payload.processed_resumes}`);
        router.refresh();
      }
    } catch {
      setMessage("Ranking request failed.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="rounded-2xl border border-slate-200 bg-white p-4 shadow-sm">
      <h2 className="font-heading text-xl font-semibold text-ink">Resume Upload & Ingestion</h2>
      <p className="mt-1 text-sm text-slate-600">Upload PDF/DOCX resumes and trigger ranking directly from UI.</p>

      <form onSubmit={onUpload} className="mt-4 space-y-3">
        <input
          type="file"
          multiple
          accept=".pdf,.doc,.docx"
          onChange={(event) => setFiles(event.target.files)}
          className="block w-full rounded-lg border border-slate-300 bg-slate-50 p-2 text-sm"
        />
        <div className="flex flex-wrap gap-2">
          <button
            type="submit"
            disabled={busy}
            className="rounded-lg bg-teal px-4 py-2 text-sm font-semibold text-white disabled:opacity-60"
          >
            Upload
          </button>
          <button
            type="button"
            disabled={busy}
            onClick={refreshStatus}
            className="rounded-lg border border-slate-300 px-4 py-2 text-sm font-semibold text-slate-700 disabled:opacity-60"
          >
            Refresh Status
          </button>
          <button
            type="button"
            disabled={busy}
            onClick={runRanking}
            className="rounded-lg border border-teal px-4 py-2 text-sm font-semibold text-teal disabled:opacity-60"
          >
            Run Ranking
          </button>
        </div>
      </form>

      <p className="mt-3 text-sm text-slate-700">{message}</p>

      {status ? (
        <div className="mt-3 rounded-lg bg-slate-50 p-3 text-sm text-slate-700">
          <p>Total Uploaded: {status.total_uploaded}</p>
          <p>Queued: {status.queued}</p>
          <p>Queue Failed: {status.queue_failed}</p>
        </div>
      ) : null}
    </section>
  );
}
