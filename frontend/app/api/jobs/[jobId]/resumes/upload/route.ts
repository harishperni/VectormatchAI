const API_BASE = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://127.0.0.1:8000";

export async function POST(
  request: Request,
  { params }: { params: Promise<{ jobId: string }> }
) {
  const { jobId } = await params;
  const incoming = await request.formData();
  const files = incoming.getAll("files");

  if (files.length === 0) {
    return Response.json({ detail: "No files provided" }, { status: 400 });
  }

  const outbound = new FormData();
  for (const file of files) {
    if (typeof file === "string") {
      continue;
    }
    const name =
      typeof (file as { name?: unknown }).name === "string"
        ? ((file as { name: string }).name ?? "resume.bin")
        : "resume.bin";
    outbound.append("files", file, name);
  }

  const upstream = await fetch(`${API_BASE}/api/v1/jobs/${jobId}/resumes/upload`, {
    method: "POST",
    body: outbound,
    cache: "no-store",
  });

  const contentType = upstream.headers.get("content-type") ?? "application/json";
  const bodyText = await upstream.text();

  return new Response(bodyText, {
    status: upstream.status,
    headers: { "content-type": contentType },
  });
}
