const API_BASE = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://127.0.0.1:8000";

export async function GET(
  _request: Request,
  { params }: { params: Promise<{ jobId: string; resumeId: string }> }
) {
  const { jobId, resumeId } = await params;
  const upstream = await fetch(`${API_BASE}/api/v1/jobs/${jobId}/resumes/${resumeId}`, {
    cache: "no-store",
  });

  const contentType = upstream.headers.get("content-type") ?? "application/json";
  const bodyText = await upstream.text();

  return new Response(bodyText, {
    status: upstream.status,
    headers: { "content-type": contentType },
  });
}

export async function DELETE(
  _request: Request,
  { params }: { params: Promise<{ jobId: string; resumeId: string }> }
) {
  const { jobId, resumeId } = await params;
  const upstream = await fetch(`${API_BASE}/api/v1/jobs/${jobId}/resumes/${resumeId}`, {
    method: "DELETE",
    cache: "no-store",
  });

  const contentType = upstream.headers.get("content-type") ?? "application/json";
  const bodyText = await upstream.text();

  return new Response(bodyText, {
    status: upstream.status,
    headers: { "content-type": contentType },
  });
}
