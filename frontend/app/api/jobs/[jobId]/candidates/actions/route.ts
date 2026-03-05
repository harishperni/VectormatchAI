const API_BASE = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://127.0.0.1:8000";

export async function POST(
  request: Request,
  { params }: { params: Promise<{ jobId: string }> }
) {
  const { jobId } = await params;
  const payload = await request.text();

  const upstream = await fetch(`${API_BASE}/api/v1/jobs/${jobId}/candidates/actions`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: payload,
    cache: "no-store",
  });

  const contentType = upstream.headers.get("content-type") ?? "application/json";
  const bodyText = await upstream.text();

  return new Response(bodyText, {
    status: upstream.status,
    headers: { "content-type": contentType },
  });
}

