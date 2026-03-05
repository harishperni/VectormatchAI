const API_BASE = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://127.0.0.1:8000";

export async function GET(
  request: Request,
  { params }: { params: Promise<{ jobId: string }> }
) {
  const { jobId } = await params;
  const incomingUrl = new URL(request.url);
  const query = incomingUrl.searchParams.toString();
  const upstreamUrl = `${API_BASE}/api/v1/jobs/${jobId}/rankings${query ? `?${query}` : ""}`;

  const upstream = await fetch(upstreamUrl, { cache: "no-store" });
  const contentType = upstream.headers.get("content-type") ?? "application/json";
  const bodyText = await upstream.text();

  return new Response(bodyText, {
    status: upstream.status,
    headers: { "content-type": contentType },
  });
}
