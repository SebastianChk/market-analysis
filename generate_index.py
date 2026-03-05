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
from datetime import date
from pathlib import Path


DATA_DIR = Path("data")
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


def main():
    DOCS_DIR.mkdir(exist_ok=True)

    runs = collect_runs()

    manifest = {
        "generated": date.today().isoformat(),
        "runs": [
            {
                "date": run_date,
                "files": {label: f"../data/{filename}" for label, filename in files.items()},
            }
            for run_date, files in runs.items()
        ],
    }

    manifest_path = DOCS_DIR / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(f"Generated {manifest_path} ({len(runs)} run(s))")


if __name__ == "__main__":
    main()