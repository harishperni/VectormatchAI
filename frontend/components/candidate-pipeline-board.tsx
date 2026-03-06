"use client";

import Link from "next/link";
import { useMemo, useState } from "react";

import type { RankingRow } from "@/lib/api";

type StageKey = "new" | "review" | "shortlisted" | "interviewed" | "offer" | "rejected";

const STAGES: { key: StageKey; label: string; action?: string }[] = [
  { key: "new", label: "New", action: "reset" },
  { key: "review", label: "Review", action: "viewed" },
  { key: "shortlisted", label: "Shortlisted", action: "shortlisted" },
  { key: "interviewed", label: "Interview", action: "interviewed" },
  { key: "offer", label: "Offer", action: "hired" },
  { key: "rejected", label: "Rejected", action: "rejected" },
];

function mapActionToStage(action?: string | null): StageKey {
  const normalized = (action || "").toLowerCase();
  if (normalized === "viewed") return "review";
  if (normalized === "shortlisted") return "shortlisted";
  if (normalized === "interviewed") return "interviewed";
  if (normalized === "hired") return "offer";
  if (normalized === "rejected") return "rejected";
  return "new";
}

export default function CandidatePipelineBoard({
  jobId,
  rows,
  onActionUpdated,
}: {
  jobId: string;
  rows: RankingRow[];
  onActionUpdated?: (candidateId: string, action: string) => void;
}) {
  const [status, setStatus] = useState("Ready");
  const [draggingId, setDraggingId] = useState<string | null>(null);
  const [draggingStage, setDraggingStage] = useState<StageKey | null>(null);

  const grouped = useMemo(() => {
    const bucket: Record<StageKey, RankingRow[]> = {
      new: [],
      review: [],
      shortlisted: [],
      interviewed: [],
      offer: [],
      rejected: [],
    };
    for (const row of rows) {
      bucket[mapActionToStage(row.action_status)].push(row);
    }
    return bucket;
  }, [rows]);

  async function setStage(candidateId: string, action: string) {
    setStatus(`Updating ${action}...`);
    if (onActionUpdated) {
      onActionUpdated(candidateId, action);
    }
    try {
      const response = await fetch(`/api/jobs/${jobId}/candidates/${candidateId}/action`, {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ action }),
      });
      if (!response.ok) {
        setStatus("Update failed.");
        return;
      }
      setStatus("Updated.");
    } catch {
      setStatus("Update failed.");
    }
  }

  function onDragStart(candidateId: string, stage: StageKey) {
    setDraggingId(candidateId);
    setDraggingStage(stage);
  }

  async function onDrop(stage: StageKey) {
    if (!draggingId || !stage) return;
    const target = STAGES.find((item) => item.key === stage);
    if (!target?.action) {
      setStatus("Target stage does not map to an action.");
      setDraggingId(null);
      setDraggingStage(null);
      return;
    }
    await setStage(draggingId, target.action);
    setDraggingId(null);
    setDraggingStage(null);
  }

  return (
    <section className="rounded-2xl border border-slate-200 bg-white p-4 shadow-sm">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h2 className="font-heading text-xl font-semibold text-slate-900">Candidate Pipeline</h2>
          <p className="text-xs text-slate-500">Drag-and-drop coming later. Use quick actions for now.</p>
        </div>
        <p className="text-xs text-slate-500">{status}</p>
      </div>

      <div className="mt-4 overflow-x-auto">
        <div className="grid min-w-[1200px] grid-cols-6 gap-3">
          {STAGES.map((stage) => (
            <div
              key={stage.key}
              onDragOver={(event) => event.preventDefault()}
              onDrop={() => onDrop(stage.key)}
              className="rounded-xl border border-slate-200 bg-slate-50 p-3"
            >
              <div className="flex items-center justify-between">
                <p className="text-sm font-semibold text-slate-700">{stage.label}</p>
                <span className="rounded-full bg-white px-2 py-0.5 text-xs text-slate-600">
                  {grouped[stage.key].length}
                </span>
              </div>
              <div className="mt-3 space-y-2">
                {grouped[stage.key].length === 0 ? (
                  <p className="rounded border border-dashed border-slate-200 bg-white p-2 text-xs text-slate-500">
                    No candidates
                  </p>
                ) : null}
                {grouped[stage.key].map((row) => (
                  <div
                    key={row.candidate_id}
                    draggable
                    onDragStart={() => onDragStart(row.candidate_id, stage.key)}
                    className={`rounded-lg border border-slate-200 bg-white p-3 ${
                      draggingId === row.candidate_id && draggingStage === stage.key ? "opacity-60" : ""
                    }`}
                  >
                    <div className="flex items-start justify-between gap-2">
                      <div>
                        <p className="text-sm font-semibold text-slate-900">{row.candidate_name}</p>
                        <p className="text-xs text-slate-500">Score {row.score}%</p>
                      </div>
                      <Link
                        href={`/jobs/${jobId}/candidates/${row.candidate_id}`}
                        className="text-xs font-semibold text-teal-700"
                      >
                        Open
                      </Link>
                    </div>
                    <div className="mt-2 flex flex-wrap gap-1">
                      {STAGES.filter((item) => item.action).map((item) => (
                        <button
                          key={item.key}
                          onClick={() => setStage(row.candidate_id, item.action!)}
                          className="rounded border border-slate-200 px-2 py-0.5 text-[11px] text-slate-600 hover:border-slate-300"
                        >
                          {item.label}
                        </button>
                      ))}
                    </div>
                  </div>
                ))}
              </div>
            </div>
          ))}
        </div>
      </div>
    </section>
  );
}
