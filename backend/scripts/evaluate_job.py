from __future__ import annotations

import argparse
import json
import urllib.request


def main() -> None:
    parser = argparse.ArgumentParser(description="Run ranking evaluation for a job.")
    parser.add_argument("--job-id", required=True, help="Job UUID")
    parser.add_argument("--top-k", type=int, default=5, help="Top-K value for precision/recall")
    parser.add_argument(
        "--base-url", default="http://127.0.0.1:8000", help="Backend API base URL"
    )
    args = parser.parse_args()

    url = f"{args.base_url.rstrip('/')}/api/v1/jobs/{args.job_id}/evaluation?top_k={args.top_k}"
    with urllib.request.urlopen(url, timeout=30) as response:
        payload = json.loads(response.read().decode("utf-8"))

    print(json.dumps(payload, indent=2))


if __name__ == "__main__":
    main()

