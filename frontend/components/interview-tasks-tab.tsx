"use client";

import { useEffect, useMemo, useState } from "react";

import type { InterviewTask } from "@/lib/api";

type TasksResponse = {
  items?: InterviewTask[];
};

function formatDateTime(value?: string | null): string {
  if (!value) return "-";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "-";
  return date.toLocaleString();
}

function defaultStartLocal(): string {
  const now = new Date();
  now.setMinutes(now.getMinutes() + (30 - (now.getMinutes() % 30 || 30)));
  return now.toISOString().slice(0, 16);
}

export default function InterviewTasksTab({ jobId }: { jobId: string }) {
  const [tasks, setTasks] = useState<InterviewTask[]>([]);
  const [loading, setLoading] = useState(true);
  const [message, setMessage] = useState("Ready");
  const [draftByCandidate, setDraftByCandidate] = useState<
    Record<string, { startsAt: string; durationMin: string; interviewer: string; notes: string; meetingLink: string }>
  >({});

  const pendingCount = useMemo(
    () => tasks.filter((task) => (task.status || "").toLowerCase() === "pending").length,
    [tasks]
  );

  async function loadTasks() {
    setLoading(true);
    try {
      const response = await fetch(`/api/jobs/${jobId}/tasks`, { cache: "no-store" });
      const payload = (await response.json()) as TasksResponse;
      if (!response.ok) {
        setMessage("Failed to load interview tasks.");
        setTasks([]);
        return;
      }
      setTasks(Array.isArray(payload.items) ? payload.items : []);
      setMessage("Tasks loaded.");
    } catch {
      setMessage("Failed to load interview tasks.");
      setTasks([]);
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    void loadTasks();
  }, [jobId]);

  function updateDraft(
    candidateId: string,
    patch: Partial<{ startsAt: string; durationMin: string; interviewer: string; notes: string; meetingLink: string }>
  ) {
    setDraftByCandidate((prev) => ({
      ...prev,
      [candidateId]: {
        startsAt: prev[candidateId]?.startsAt ?? defaultStartLocal(),
        durationMin: prev[candidateId]?.durationMin ?? "45",
        interviewer: prev[candidateId]?.interviewer ?? "",
        notes: prev[candidateId]?.notes ?? "",
        meetingLink: prev[candidateId]?.meetingLink ?? "",
        ...patch,
      },
    }));
  }

  async function schedule(task: InterviewTask) {
    const draft = draftByCandidate[task.candidate_id] ?? {
      startsAt: defaultStartLocal(),
      durationMin: "45",
      interviewer: "",
      notes: "",
      meetingLink: "",
    };
    const startDate = new Date(draft.startsAt);
    if (Number.isNaN(startDate.getTime())) {
      setMessage("Invalid interview start time.");
      return;
    }
    const duration = Math.max(15, Number(draft.durationMin || 45));
    const endDate = new Date(startDate.getTime() + duration * 60 * 1000);

    setMessage(`Scheduling interview for ${task.candidate_name}...`);
    try {
      const response = await fetch(
        `/api/jobs/${jobId}/tasks/interviews/${task.candidate_id}/schedule`,
        {
          method: "POST",
          headers: { "content-type": "application/json" },
          body: JSON.stringify({
            starts_at: startDate.toISOString(),
            ends_at: endDate.toISOString(),
            interviewer: draft.interviewer || null,
            notes: draft.notes || null,
            timezone: Intl.DateTimeFormat().resolvedOptions().timeZone,
            meeting_link: draft.meetingLink || null,
          }),
        }
      );

      const payload = await response.json();
      if (!response.ok) {
        setMessage(payload?.detail ?? "Could not schedule interview.");
        return;
      }

      setMessage(`Interview scheduled for ${task.candidate_name}.`);
      if (payload?.google_calendar_url) {
        window.open(payload.google_calendar_url as string, "_blank", "noopener,noreferrer");
      }
      await loadTasks();
    } catch {
      setMessage("Could not schedule interview.");
    }
  }

  return (
    <section className="space-y-3 rounded-2xl border border-slate-200 bg-white p-4 shadow-sm">
      <header className="flex flex-wrap items-center justify-between gap-2">
        <div>
          <h2 className="font-heading text-xl font-semibold text-slate-900">Interview Tasks</h2>
          <p className="text-xs text-slate-500">
            Auto-created when a candidate is moved to Interview.
          </p>
        </div>
        <div className="flex items-center gap-2">
          <span className="rounded-full bg-amber-100 px-2 py-0.5 text-xs font-semibold text-amber-800">
            Pending: {pendingCount}
          </span>
          <button
            onClick={loadTasks}
            disabled={loading}
            className="rounded-md border border-slate-300 px-3 py-1.5 text-sm font-semibold text-slate-700 disabled:opacity-60"
          >
            {loading ? "Loading..." : "Refresh"}
          </button>
        </div>
      </header>

      <p className="text-xs text-slate-500">{message}</p>

      {tasks.length === 0 ? (
        <p className="rounded-lg border border-dashed border-slate-300 bg-slate-50 p-4 text-sm text-slate-600">
          No interview tasks yet. Move a candidate to Interview to auto-create a task.
        </p>
      ) : null}

      <div className="space-y-3">
        {tasks.map((task) => {
          const draft = draftByCandidate[task.candidate_id] ?? {
            startsAt: defaultStartLocal(),
            durationMin: "45",
            interviewer: task.interviewer ?? "",
            notes: task.notes ?? "",
            meetingLink: task.meeting_link ?? "",
          };
          const isScheduled = (task.status || "").toLowerCase() === "scheduled";
          return (
            <article key={task.task_id} className="rounded-xl border border-slate-200 p-3">
              <div className="flex flex-wrap items-center justify-between gap-2">
                <div>
                  <p className="text-base font-semibold text-slate-900">{task.candidate_name}</p>
                  <p className="text-xs text-slate-500">
                    {task.candidate_email || "No email on profile"} • Status: {task.status}
                  </p>
                </div>
                {task.google_calendar_url ? (
                  <a
                    href={task.google_calendar_url}
                    target="_blank"
                    rel="noreferrer"
                    className="rounded-md border border-sky-300 px-2 py-1 text-xs font-semibold text-sky-700"
                  >
                    Open Calendar Draft
                  </a>
                ) : null}
              </div>

              <p className="mt-2 text-xs text-slate-600">
                Scheduled: {formatDateTime(task.scheduled_start_at)} to {formatDateTime(task.scheduled_end_at)}
              </p>

              <div className="mt-3 grid gap-2 md:grid-cols-5">
                <input
                  type="datetime-local"
                  value={draft.startsAt}
                  onChange={(event) => updateDraft(task.candidate_id, { startsAt: event.target.value })}
                  className="rounded-md border border-slate-300 px-2 py-1.5 text-sm"
                />
                <input
                  value={draft.durationMin}
                  onChange={(event) => updateDraft(task.candidate_id, { durationMin: event.target.value })}
                  placeholder="Duration (min)"
                  className="rounded-md border border-slate-300 px-2 py-1.5 text-sm"
                />
                <input
                  value={draft.interviewer}
                  onChange={(event) => updateDraft(task.candidate_id, { interviewer: event.target.value })}
                  placeholder="Interviewer"
                  className="rounded-md border border-slate-300 px-2 py-1.5 text-sm"
                />
                <input
                  value={draft.meetingLink}
                  onChange={(event) => updateDraft(task.candidate_id, { meetingLink: event.target.value })}
                  placeholder="Google Meet URL (optional)"
                  className="rounded-md border border-slate-300 px-2 py-1.5 text-sm"
                />
                <button
                  onClick={() => schedule(task)}
                  className="rounded-md bg-slate-900 px-3 py-1.5 text-sm font-semibold text-white"
                >
                  {isScheduled ? "Reschedule" : "Schedule"}
                </button>
              </div>
              <textarea
                value={draft.notes}
                onChange={(event) => updateDraft(task.candidate_id, { notes: event.target.value })}
                placeholder="Interview notes"
                className="mt-2 min-h-16 w-full rounded-md border border-slate-300 px-2 py-1.5 text-sm"
              />
              <p className="mt-2 text-[11px] text-slate-500">
                Tip: after scheduling, a Google Calendar draft opens where HR can add Google Meet in one click.
              </p>
            </article>
          );
        })}
      </div>
    </section>
  );
}
