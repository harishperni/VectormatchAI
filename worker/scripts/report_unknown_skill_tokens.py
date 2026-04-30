from __future__ import annotations

import argparse
import os
from collections import Counter

import psycopg
from psycopg.rows import dict_row


def _dsn() -> str:
    value = os.getenv("DATABASE_URL", "").strip()
    if not value:
        raise RuntimeError("DATABASE_URL is not set")
    if value.startswith("postgresql+psycopg://"):
        value = value.replace("postgresql+psycopg://", "postgresql://", 1)
    return value


def _iter_unknowns(limit: int) -> list[dict]:
    sql = """
    SELECT parsed_json
    FROM resumes
    WHERE parse_status = 'parsed'
      AND parsed_json IS NOT NULL
    ORDER BY created_at DESC
    LIMIT %s
    """
    with psycopg.connect(_dsn(), row_factory=dict_row) as conn:
        with conn.cursor() as cur:
            cur.execute(sql, (limit,))
            return cur.fetchall()


def main() -> None:
    parser = argparse.ArgumentParser(description="Report most common unknown skill tokens")
    parser.add_argument("--rows", type=int, default=500, help="number of recent parsed resumes to scan")
    parser.add_argument("--top", type=int, default=100, help="max tokens to print")
    args = parser.parse_args()

    counter: Counter[str] = Counter()
    rows = _iter_unknowns(args.rows)
    for row in rows:
        parsed = row.get("parsed_json") or {}
        unknown = parsed.get("skills_unknown_tokens")
        if isinstance(unknown, list):
            for token in unknown:
                if isinstance(token, str) and token.strip():
                    counter[token.strip()] += 1

    print(f"Scanned resumes: {len(rows)}")
    print(f"Unique unknown tokens: {len(counter)}")
    print("")
    for token, count in counter.most_common(args.top):
        print(f"{count:4d}  {token}")


if __name__ == "__main__":
    main()

