const API_BASE = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://127.0.0.1:8000";

export async function GET(
  _request: Request,
  { params }: { params: Promise<{ jobId: string; candidateId: string }> }
) {
  const { jobId, candidateId } = await params;

  const upstream = await fetch(
    `${API_BASE}/api/v1/jobs/${jobId}/candidates/${candidateId}/explanation`,
    { cache: "no-store" }
  );

  const contentType = upstream.headers.get("content-type") ?? "application/json";
  const bodyText = await upstream.text();

  return new Response(bodyText, {
    status: upstream.status,
    headers: { "content-type": contentType },
  });
}
