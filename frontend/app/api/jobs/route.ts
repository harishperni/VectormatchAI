const API_BASE = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://127.0.0.1:8000";

export async function POST(request: Request) {
  const body = await request.text();
  const upstream = await fetch(`${API_BASE}/api/v1/jobs`, {
    method: "POST",
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

