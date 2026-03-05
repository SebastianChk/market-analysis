# /// script
# requires-python = ">=3.13"
# dependencies = []
# ///
"""
generate_index.py
=================
Generates docs/manifest.json — an index of all available data files that the
web app reads at runtime to discover and load data.

Also copies docs/index.html into place if it doesn't already exist. The HTML
file itself is static and never needs to be regenerated — only the manifest
changes on each run.

Run automatically by the GitHub Actions workflow after each scrape.
Can also be run manually: uv run generate_index.py
"""

import json
import re
import shutil
from datetime import date
from pathlib import Path


DATA_DIR = Path("docs/data")
DOCS_DIR = Path("docs")


def collect_runs() -> dict[str, dict]:
    """Scan the data directory and group files by run date.
    Returns a dict of {date_str: {label: filename}}, sorted newest first."""
    runs: dict[str, dict] = {}

    if not DATA_DIR.exists():
        return runs

    for path in sorted(DATA_DIR.iterdir(), reverse=True):
        name = path.name
        if not name.startswith("jobdata_"):
            continue
        parts = name.removeprefix("jobdata_").rsplit(".", 1)
        if len(parts) != 2:
            continue
        stem, ext = parts
        run_date = stem[:10]
        label = stem[10:].lstrip("_") or "clean"
        runs.setdefault(run_date, {})[f"{label}.{ext}"] = name

    return runs


def _parse_int(s: str) -> int | None:
    """Parse strings like '1,145', '+28', '-26', '963' to int."""
    if not s or s.strip() in ("-", ""):
        return None
    cleaned = re.sub(r"[£,\s]", "", s.strip()).lstrip("+")
    try:
        return int(cleaned)
    except ValueError:
        return None


def _parse_float(s: str) -> float | None:
    """Parse strings like '7.18%', '-10.34%', '£65,000' to float."""
    if not s or s.strip() in ("-", ""):
        return None
    cleaned = re.sub(r"[£,%\s]", "", s.strip()).lstrip("+")
    try:
        return float(cleaned)
    except ValueError:
        return None


_PERIOD_CONFIGS = {
    "6mo": {
        "filename": "latest_6mo.json",
        "period_explanation": (
            "All count and rank fields use a rolling 6-month window ending on "
            "snapshot_date. This means 'total_postings' is the cumulative number "
            "of distinct job postings referencing the skill over those six months — "
            "it is NOT a monthly average or a point-in-time count."
        ),
        "postings_field": "total_postings_6mo",
        "market_share_field": "market_share_6mo_pct",
    },
    "3mo": {
        "filename": "latest_3mo.json",
        "period_explanation": (
            "All count and rank fields use a rolling 3-month window ending on "
            "snapshot_date. This means 'total_postings' is the cumulative number "
            "of distinct job postings referencing the skill over those three months — "
            "it is NOT a monthly average or a point-in-time count. "
            "The 3-month window is more reactive to recent market shifts than the 6-month file."
        ),
        "postings_field": "total_postings_3mo",
        "market_share_field": "market_share_3mo_pct",
    },
}

_SHARED_CAVEATS = [
    "demand_rank is relative to ALL IT skills tracked by IT Jobs Watch, not "
    "just the skills listed in this file. A rank of 5 means 5th most in-demand "
    "across the entire UK IT job market.",
    "live_jobs is a point-in-time count of active listings at the moment of "
    "scraping. It will typically be much lower than total_postings.",
    "market_share_pct is this skill's share of ALL permanent UK IT roles "
    "over the window, not just the skills in this file. Values will not sum to 100%.",
    "demand_rank_yoy_change is sign-flipped relative to the raw rank number: "
    "a POSITIVE value means the rank NUMBER went down (i.e. the skill became "
    "MORE in demand). A NEGATIVE value means it became less in demand.",
    "null values indicate the source site did not report a figure for that field.",
    "This file tracks a curated subset of skills. Absence from this list does "
    "not imply low demand.",
]

_SHARED_FIELD_DEFINITIONS = {
    "skill": "Technology or domain name.",
    "demand_rank": (
        "Demand rank among all IT skills on IT Jobs Watch. "
        "Lower number = higher demand. Rank 1 = most in-demand skill in the UK IT market."
    ),
    "demand_rank_yoy_change": (
        "Change in demand rank versus the same window one year ago. "
        "Positive = skill became more in demand (rank number fell). "
        "Negative = skill became less in demand (rank number rose)."
    ),
    "live_jobs": "Active job listings at the moment of scraping (point-in-time).",
    "total_postings": (
        "Cumulative count of job postings referencing this skill over the rolling window. "
        "Not an average — this is the total."
    ),
    "market_share_pct": (
        "Percentage of all permanent UK IT job postings (not just tracked skills) "
        "that reference this skill, over the rolling window."
    ),
    "median_salary_gbp": "Median advertised annual salary in GBP for roles requiring this skill.",
    "median_salary_yoy_change_pct": (
        "Year-over-year percentage change in median salary. "
        "Positive = salaries rose. Negative = salaries fell."
    ),
}


def generate_latest_json(runs: dict[str, dict]) -> None:
    """Write docs/latest_6mo.json and docs/latest_3mo.json — LLM-readable snapshots."""
    if not runs:
        return

    latest_date = next(iter(runs))  # runs is sorted newest-first
    clean_file = runs[latest_date].get("clean.json")
    if not clean_file:
        return

    clean_path = DATA_DIR / clean_file
    if not clean_path.exists():
        return

    raw_rows: list[dict] = json.loads(clean_path.read_text(encoding="utf-8"))

    for period, cfg in _PERIOD_CONFIGS.items():
        skills = []
        for row in raw_rows:
            if row.get("period") != period:
                continue
            skills.append({
                "skill":                        row.get("description", ""),
                "demand_rank":                  _parse_int(row.get("rank") or row.get("rank_6mo")),
                "demand_rank_yoy_change":       _parse_int(row.get("rank_yoy_change")),
                "live_jobs":                    _parse_int(row.get("live_jobs")),
                "total_postings":               _parse_int(row.get("historical_vacancies_absolute")),
                "market_share_pct":             _parse_float(row.get("historical_vacancies_relative")),
                "median_salary_gbp":            _parse_int(row.get("median_salary")),
                "median_salary_yoy_change_pct": _parse_float(row.get("median_salary_yoy_change")),
            })

        skills.sort(key=lambda r: r["demand_rank"] if r["demand_rank"] is not None else 9999)

        output = {
            "_meta": {
                "description": (
                    "Latest UK IT job market snapshot for a curated set of technology skills. "
                    "Data sourced from IT Jobs Watch (itjobswatch.co.uk), which aggregates "
                    "permanent job listings across the UK. Scraped weekly via GitHub Actions."
                ),
                "snapshot_date": latest_date,
                "data_source": "IT Jobs Watch (itjobswatch.co.uk)",
                "market": "United Kingdom — permanent roles only",
                "period": period,
                "period_explanation": cfg["period_explanation"],
                "companion_file": (
                    "latest_3mo.json" if period == "6mo" else "latest_6mo.json"
                ),
                "caveats": _SHARED_CAVEATS,
                "field_definitions": _SHARED_FIELD_DEFINITIONS,
            },
            "skills": skills,
        }

        out_path = DOCS_DIR / cfg["filename"]
        out_path.write_text(json.dumps(output, indent=2, ensure_ascii=False), encoding="utf-8")
        print(f"Generated {out_path} ({len(skills)} skill(s) for {latest_date})")


def main():
    DOCS_DIR.mkdir(exist_ok=True)

    runs = collect_runs()

    manifest = {
        "generated": date.today().isoformat(),
        "runs": [
            {
                "date": run_date,
                "files": {label: f"data/{filename}" for label, filename in files.items()},
            }
            for run_date, files in runs.items()
        ],
    }

    manifest_path = DOCS_DIR / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(f"Generated {manifest_path} ({len(runs)} run(s))")

    generate_latest_json(runs)

    skills_src = Path("skills.json")
    if skills_src.exists():
        shutil.copy(skills_src, DOCS_DIR / "skills.json")
        print(f"Copied {skills_src} → {DOCS_DIR / 'skills.json'}")


if __name__ == "__main__":
    main()
