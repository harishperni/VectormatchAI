const API_BASE = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://127.0.0.1:8000";

export async function POST(
  _request: Request,
  { params }: { params: Promise<{ jobId: string }> }
) {
  const { jobId } = await params;
  const upstream = await fetch(`${API_BASE}/api/v1/jobs/${jobId}/rank`, {
    method: "POST",
    cache: "no-store",
  });

  const contentType = upstream.headers.get("content-type") ?? "application/json";
  const bodyText = await upstream.text();

  return new Response(bodyText, {
    status: upstream.status,
    headers: { "content-type": contentType },
  });
}
