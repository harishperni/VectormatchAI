"use client";

export default function GlobalError({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  return (
    <html>
      <body>
        <main className="mx-auto max-w-3xl px-6 py-12">
          <h2 className="text-2xl font-semibold text-slate-900">Application error</h2>
          <p className="mt-3 text-sm text-slate-600">{error.message || "Unexpected global error."}</p>
          <button
            onClick={() => reset()}
            className="mt-5 rounded-md bg-slate-900 px-4 py-2 text-sm font-semibold text-white"
          >
            Try again
          </button>
        </main>
      </body>
    </html>
  );
}
