"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";

type GoldenPayload = {
  expected_top_candidate_ids: string[];
  expected_top_candidate_names: string[];
};

const DEFAULT_TEMPLATE = {
  expected_top_candidate_ids: [],
  expected_top_candidate_names: [],
};

export default function GoldenDatasetEditor({ jobId }: { jobId: string }) {
  const router = useRouter();
  const [text, setText] = useState(JSON.stringify(DEFAULT_TEMPLATE, null, 2));
  const [status, setStatus] = useState("Idle");
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    let mounted = true;
    async function load() {
      setStatus("Loading current golden dataset...");
      try {
        const response = await fetch(`/api/jobs/${jobId}/golden-dataset`, { cache: "no-store" });
        if (!response.ok) {
          setStatus("No golden dataset found yet.");
          return;
        }
        const payload = (await response.json()) as GoldenPayload;
        if (!mounted) return;
        setText(
          JSON.stringify(
            {
              expected_top_candidate_ids: payload.expected_top_candidate_ids ?? [],
              expected_top_candidate_names: payload.expected_top_candidate_names ?? [],
            },
            null,
            2
          )
        );
        setStatus("Loaded.");
      } catch {
        setStatus("Could not load golden dataset.");
      }
    }
    void load();
    return () => {
      mounted = false;
    };
  }, [jobId]);

  async function save() {
    setLoading(true);
    setStatus("Saving...");
    try {
      const parsed = JSON.parse(text) as GoldenPayload;
      const response = await fetch(`/api/jobs/${jobId}/golden-dataset`, {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify(parsed),
      });
      if (!response.ok) {
        const body = await response.text();
        setStatus(`Save failed: ${body}`);
        return;
      }
      setStatus("Saved. Refreshing evaluation...");
      router.refresh();
    } catch {
      setStatus("Save failed: invalid JSON.");
    } finally {
      setLoading(false);
    }
  }

  return (
    <section className="rounded-xl border border-slate-200 bg-white p-4 shadow-sm">
      <h2 className="font-heading text-xl font-semibold text-slate-900">Golden Dataset Manager</h2>
      <p className="mt-1 text-sm text-slate-600">
        Paste JSON with `expected_top_candidate_ids` or `expected_top_candidate_names`.
      </p>
      <textarea
        value={text}
        onChange={(event) => setText(event.target.value)}
        className="mt-3 min-h-48 w-full rounded-lg border border-slate-300 p-3 font-mono text-xs"
      />
      <div className="mt-3 flex items-center gap-3">
        <button
          onClick={save}
          disabled={loading}
          className="rounded-lg bg-teal px-4 py-2 text-sm font-semibold text-white disabled:opacity-60"
        >
          {loading ? "Saving..." : "Save Golden Dataset"}
        </button>
        <p className="text-sm text-slate-600">{status}</p>
      </div>
    </section>
  );
}

