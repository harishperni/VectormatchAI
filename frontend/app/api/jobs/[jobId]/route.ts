const API_BASE = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://127.0.0.1:8000";

type Params = {
  params: Promise<{ jobId: string }>;
};

export async function GET(_: Request, context: Params) {
  const { jobId } = await context.params;
  const upstream = await fetch(`${API_BASE}/api/v1/jobs/${jobId}`, {
    cache: "no-store",
  });
  const contentType = upstream.headers.get("content-type") ?? "application/json";
  const responseText = await upstream.text();
  return new Response(responseText, {
    status: upstream.status,
    headers: { "content-type": contentType },
  });
}

export async function PATCH(request: Request, context: Params) {
  const { jobId } = await context.params;
  const body = await request.text();
  const upstream = await fetch(`${API_BASE}/api/v1/jobs/${jobId}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body,
    cache: "no-store",
  });
  const contentType = upstream.headers.get("content-type") ?? "application/json";
  const responseText = await upstream.text();
  return new Response(responseText, {
    status: upstream.status,
    headers: { "content-type": contentType },
  });
}
