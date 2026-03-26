from __future__ import annotations

import argparse
import json
import random
import re
from pathlib import Path
from typing import Any

import fitz


def _normalize_phone(value: Any) -> str | None:
    if value is None:
        return None
    digits = re.sub(r"\D+", "", str(value))
    return digits or None


def _normalize_degree(value: str) -> str | None:
    text = value.strip().lower()
    if not text:
        return None
    if "phd" in text or "doctor" in text:
        return "PhD"
    if "master" in text or "m.sc" in text or "m.e" in text or "m.b.a" in text or text.startswith("m."):
        return "Master's"
    if "bachelor" in text or "b.sc" in text or "b.e" in text or text.startswith("b."):
        return "Bachelor's"
    if "associate" in text:
        return "Associate's"
    return value.strip()


def _extract_text_from_pdf(path: Path) -> str:
    with fitz.open(path) as doc:
        chunks: list[str] = []
        for page in doc:
            chunks.append(page.get_text("text"))
    return "\n".join(chunks).strip()


def _expected_from_kaggle(payload: dict[str, Any]) -> dict[str, Any]:
    contact = payload.get("contact_info")
    if not isinstance(contact, dict):
        contact = {}

    skills_flat = payload.get("skills_flat")
    if isinstance(skills_flat, list):
        skills = [str(item).strip().lower() for item in skills_flat if str(item).strip()]
    else:
        skills = []

    degrees = payload.get("degrees")
    degree_values = [str(item) for item in degrees] if isinstance(degrees, list) else []
    normalized_degree = None
    for degree in degree_values:
        normalized = _normalize_degree(degree)
        if normalized:
            normalized_degree = normalized
            if normalized in {"PhD", "Master's", "Bachelor's", "Associate's"}:
                break

    job_titles = payload.get("job_titles")
    current_last_job = str(job_titles[0]).strip() if isinstance(job_titles, list) and job_titles else None

    years = payload.get("years_of_experience")
    try:
        years_value = float(years) if years is not None else None
    except (TypeError, ValueError):
        years_value = None

    return {
        "full_name": contact.get("full_name") or payload.get("full_name"),
        "email": contact.get("email") or payload.get("email"),
        "phone": _normalize_phone(contact.get("phone") or payload.get("phone")),
        "candidate_location": contact.get("location") or payload.get("location"),
        "current_last_job": current_last_job,
        "highest_degree": normalized_degree,
        "experience_years_final": years_value,
        "skills": skills,
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Build parsing-eval dataset from Kaggle resume PDFs + JSON labels."
    )
    parser.add_argument("--resumes-dir", required=True, help="Directory containing resume PDFs")
    parser.add_argument("--json-dir", required=True, help="Directory containing Kaggle JSON files")
    parser.add_argument(
        "--output",
        default="data/parsing/kaggle_parsing_eval.json",
        help="Output dataset JSON path",
    )
    parser.add_argument("--limit", type=int, default=0, help="Optional max number of cases (0 = all)")
    parser.add_argument(
        "--sample-size",
        type=int,
        default=0,
        help="Random sample size from matched files (0 = no random sampling)",
    )
    parser.add_argument("--seed", type=int, default=42, help="Random seed for sampling")
    args = parser.parse_args()

    resumes_dir = Path(args.resumes_dir)
    json_dir = Path(args.json_dir)
    output_path = Path(args.output)

    if not resumes_dir.exists():
        raise SystemExit(f"Resumes directory not found: {resumes_dir}")
    if not json_dir.exists():
        raise SystemExit(f"JSON directory not found: {json_dir}")

    json_files = sorted(json_dir.glob("*.json"))
    if not json_files:
        raise SystemExit("No JSON files found.")

    matched: list[tuple[Path, Path]] = []
    for json_file in json_files:
        pdf_path = resumes_dir / f"{json_file.stem}.pdf"
        if pdf_path.exists():
            matched.append((pdf_path, json_file))

    if not matched:
        raise SystemExit("No matching PDF+JSON pairs found.")

    if args.sample_size and args.sample_size > 0:
        random.seed(args.seed)
        matched = random.sample(matched, min(args.sample_size, len(matched)))
    if args.limit and args.limit > 0:
        matched = matched[: args.limit]

    cases: list[dict[str, Any]] = []
    skipped = 0
    for idx, (pdf_path, json_path) in enumerate(matched, start=1):
        try:
            json_payload = json.loads(json_path.read_text(encoding="utf-8", errors="ignore"))
            if not isinstance(json_payload, dict):
                skipped += 1
                continue
            text = _extract_text_from_pdf(pdf_path)
            if not text:
                skipped += 1
                continue

            parsing_meta = json_payload.get("parsing_metadata")
            tags: list[str] = []
            if isinstance(parsing_meta, dict):
                domain = parsing_meta.get("domain")
                tier = parsing_meta.get("tier")
                if isinstance(domain, str) and domain.strip():
                    tags.append(domain.strip().lower())
                if isinstance(tier, str) and tier.strip():
                    tags.append(tier.strip().lower())

            cases.append(
                {
                    "id": pdf_path.stem,
                    "tags": tags,
                    "text": text,
                    "expected": _expected_from_kaggle(json_payload),
                }
            )
        except Exception:
            skipped += 1
            continue

        if idx % 200 == 0:
            print(f"[build_kaggle_parsing_dataset] processed {idx}/{len(matched)}")

    output_payload = {
        "version": "1.0",
        "source": {
            "resumes_dir": str(resumes_dir),
            "json_dir": str(json_dir),
            "matched_pairs": len(matched),
            "skipped": skipped,
        },
        "cases": cases,
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(output_payload, indent=2), encoding="utf-8")

    print(
        json.dumps(
            {
                "output": str(output_path),
                "matched_pairs": len(matched),
                "written_cases": len(cases),
                "skipped": skipped,
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
