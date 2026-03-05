# /// script
# requires-python = ">=3.13"
# dependencies = [
#     "beautifulsoup4>=4.14.3",
#     "httpx>=0.28.1",
# ]
# ///
"""
Job Market Scraper
==================
Fetches permanent job market data and saves to CSV, JSON, and HTML.

Two separate config lists let you control:
  1. URL_SKILLS       — skills passed as query parameters to the site
  2. TABLE_SKILLS     — skills used to filter rows from the returned HTML table

Each run produces files in OUTPUT_DIR named by date. Data from each configured
period (e.g. 3mo, 6mo) is combined into a single file with a `period` field:
  jobdata_YYYY-MM-DD_raw.csv   — raw table data with original column names
  jobdata_YYYY-MM-DD_raw.json  — same, as JSON
  jobdata_YYYY-MM-DD.csv       — cleaned data with renamed columns
  jobdata_YYYY-MM-DD.json      — same, as JSON
  jobdata_YYYY-MM-DD_p1.html   — full page snapshot per page scraped (per period)

Run manually:  python scraper.py
Schedule via:  cron (Linux/Mac) or GitHub Actions
"""

import argparse
import csv
import json
import logging
import os
import time
from dataclasses import dataclass, field
from datetime import date
from typing import TypedDict

import httpx
from bs4 import BeautifulSoup


logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
log = logging.getLogger(__name__)


# =============================================================================
# CONFIGURATION — edit these sections freely
# =============================================================================

class TableSkill(TypedDict):
    skill: str    # text to match against the row's description
    exact: bool   # True  = full description must match (case-insensitive)
                  # False = description just needs to contain the skill text


# Path to the shared skills config (also copied to docs/ for the frontend).
SKILLS_CONFIG_PATH = "skills.json"


def load_skills_config(path: str) -> tuple[list[str], list[TableSkill]]:
    """Load URL skills and table filter skills from the shared skills config.

    The config is the single source of truth for which skills are tracked.
    To add, remove, or recategorise a skill, edit skills.json — no other
    file needs to change.
    """
    with open(path, encoding="utf-8") as f:
        config = json.load(f)

    url_skills: list[str] = config["url_skills"]
    table_skills: list[TableSkill] = [
        {
            "skill": entry.get("match", entry["description"]),
            "exact": entry["exact"],
        }
        for entries in config["categories"].values()
        for entry in entries
    ]
    return url_skills, table_skills

# Periods to scrape. Each entry is a dict with:
#   "label" — human-readable name attached to every row as the `period` field
#   "p"     — the value of the `p` query parameter on the site
PERIODS = [
    {"label": "3mo", "p": "3"},
    {"label": "6mo", "p": "6"},
]


# =============================================================================
# URL PARAMETERS — adjust experience/employment filters here if needed
# =============================================================================

BASE_URL = "https://www.itjobswatch.co.uk/default.aspx"

# Note: `p` (period) is intentionally absent here — it is injected per-period
# by build_params() using the PERIODS config above.
FIXED_PARAMS = {
    "q":       "",
    "l":       "",
    "ll":      "",
    "id":      "0",
    "e":       "5",   # employment type
    "sortby":  "",
    "orderby": "",
}

# =============================================================================
# COLUMN RENAME MAP — the single source of truth for table structure
# =============================================================================
# Maps cleaned raw header text (as it appears in the HTML) → clean output name.
# Used for: column count validation, row parsing, and renaming.
#
# If the site adds or removes a column, the count check will raise an error.
# If a column header is renamed (e.g. the date in "Rank 6 Months to..."),
# update only the relevant key here.
#
# "Historical Absolute & Relative Jobs Vacancies" is a special case — it gets
# split into _absolute and _relative fields in both raw and clean outputs.
#
# The rank column header changes with both period and date (e.g. "Rank 6 Months
# to 5 Mar 2026", "Rank 3 Months to 5 Mar 2026"). It is matched by the pattern
# RANK_HEADER_PREFIX below rather than an exact key, so it never needs updating.

RANK_HEADER_PREFIX = "Rank"   # matches "Rank N Months to <date>"
RANK_HEADER_CLEAN  = "rank"   # clean name — period is appended at parse time (e.g. "rank_6mo")

COLUMN_RENAME_MAP: dict[str, str] = {
    "Description":                                    "description",
    # Rank header is dynamic — resolved at fetch time via RANK_HEADER_PREFIX.
    # The placeholder key below is replaced in fetch_table() before validation.
    "__rank__":                                        "rank",
    "Rank YoY Change":                                "rank_yoy_change",
    "Median Salary":                                  "median_salary",
    "Median Salary YoY Change":                       "median_salary_yoy_change",
    "Historical Absolute & Relative Jobs Vacancies":  "historical_vacancies",
    "Live Jobs":                                      "live_jobs",
}

# Derived constant — do not edit directly.
HIST_VACANCIES_RAW_KEY = "Historical Absolute & Relative Jobs Vacancies"

# =============================================================================
# OUTPUT — one set of files per run, named by date
# =============================================================================

OUTPUT_DIR = "docs/data"  # relative to script location; created automatically

# If more than this many pages are detected, the script will prompt before
# continuing — to avoid hammering the site with excessive requests.
PAGINATION_SANITY_LIMIT = 2

# Delay in seconds between paginated requests — be a considerate scraper.
REQUEST_DELAY_SECONDS = 2


# =============================================================================
# SCRAPER
# =============================================================================

@dataclass
class FetchResult:
    rows: list[dict]            # rows keyed by raw header names
    resolved_url: str
    raw_html: str
    soup: BeautifulSoup         # parsed HTML, used for pagination detection
    rename_map: dict[str, str]  # resolved rename map for this page (rank key is concrete)


@dataclass
class PeriodResult:
    """All pages fetched for a single period."""
    label: str
    pages: list[FetchResult] = field(default_factory=list)
    failed_on_page: int | None = None


def build_params(skills: list[str], period_p: str, page: int = 1) -> dict:
    params = {**FIXED_PARAMS, "p": period_p, "ql": ",".join(skills)}
    if page > 1:
        params["page"] = str(page)
    return params


def detect_total_pages(soup: BeautifulSoup) -> int:
    """Detect the total number of pages from the pagination-total span.
    Returns 1 if no pagination is found (i.e. all results fit on one page)."""
    total = soup.find("span", class_="pagination-total")
    if total:
        try:
            return int(total.get_text(strip=True))
        except ValueError:
            log.warning(f"Could not parse pagination-total value: '{total.get_text(strip=True)}'")
    return 1


def fetch_table(params: dict) -> FetchResult:
    """Fetch the page and return parsed rows (raw column names), resolved URL, and raw HTML."""
    headers = {"User-Agent": "Mozilla/5.0 (compatible; JobMarketScraper/1.0)"}
    response = httpx.get(BASE_URL, params=params, headers=headers, timeout=15)
    response.raise_for_status()
    resolved_url = str(response.url)
    raw_html = response.text

    soup = BeautifulSoup(raw_html, "html.parser")
    table = soup.find("table")
    if not table:
        raise ValueError("No table found on page — the site structure may have changed.")

    # Read and clean actual header text from the page.
    header_row = table.find("tr")
    actual_headers = [" ".join(th.get_text(separator=" ").split()) for th in header_row.find_all(["th", "td"])]

    # Resolve the dynamic rank header (e.g. "Rank 6 Months to 5 Mar 2026") by
    # finding whichever actual header starts with RANK_HEADER_PREFIX but is not
    # "Rank YoY Change". Replace the __rank__ placeholder in the map with it.
    rank_header = next(
        (h for h in actual_headers
         if h.startswith(RANK_HEADER_PREFIX) and h != "Rank YoY Change"),
        None,
    )
    if rank_header is None:
        raise ValueError(
            f"Could not find a rank header starting with '{RANK_HEADER_PREFIX}' "
            f"in actual headers: {actual_headers}"
        )

    # Build a resolved copy of the rename map with the real rank header substituted in.
    resolved_rename_map = {
        (rank_header if k == "__rank__" else k): v
        for k, v in COLUMN_RENAME_MAP.items()
    }
    resolved_raw_columns = list(resolved_rename_map.keys())
    hist_idx = resolved_raw_columns.index(HIST_VACANCIES_RAW_KEY)

    # Validate resolved headers against actual page headers.
    if actual_headers != resolved_raw_columns:
        added   = [h for h in actual_headers       if h not in resolved_raw_columns]
        removed = [h for h in resolved_raw_columns if h not in actual_headers]
        raise ValueError(
            f"Table structure has changed.\n"
            f"  Added   (in page, not in map) : {added   or 'none'}\n"
            f"  Removed (in map, not in page) : {removed or 'none'}\n"
            f"  Full actual headers           : {actual_headers}"
        )

    rows = []
    for tr in table.find_all("tr")[1:]:  # skip header row
        cells = tr.find_all(["td", "th"])
        if not cells:
            continue

        # Build row using resolved raw header names.
        row = {
            resolved_raw_columns[i]: cells[i].get_text(strip=True)
            for i in range(min(len(resolved_raw_columns), len(cells)))
        }

        # Split the historical vacancies cell into two fields using text nodes.
        # The visual pipe separator naturally divides them into distinct nodes.
        row.pop(HIST_VACANCIES_RAW_KEY, None)
        hist_cell = cells[hist_idx]
        text_nodes = [s.strip() for s in hist_cell.strings if s.strip()]
        if len(text_nodes) >= 2:
            row[f"{HIST_VACANCIES_RAW_KEY}_absolute"] = text_nodes[0]
            row[f"{HIST_VACANCIES_RAW_KEY}_relative"] = text_nodes[1]
        else:
            row[f"{HIST_VACANCIES_RAW_KEY}_absolute"] = text_nodes[0] if text_nodes else ""
            row[f"{HIST_VACANCIES_RAW_KEY}_relative"] = None

        rows.append(row)

    return FetchResult(
        rows=rows,
        resolved_url=resolved_url,
        raw_html=raw_html,
        soup=soup,
        rename_map=resolved_rename_map,
    )


def scrape_period(
    period: dict,
    url_skills: list[str],
    pages_to_scrape: int | None,
    prompt_fn,
) -> PeriodResult:
    """Fetch all pages for a single period. Returns a PeriodResult."""
    label   = period["label"]
    period_p = period["p"]
    result  = PeriodResult(label=label)

    log.info(f"[{label}] Fetching page 1")
    params       = build_params(url_skills, period_p, page=1)
    first_result = fetch_table(params)
    result.pages.append(first_result)

    total_pages = detect_total_pages(first_result.soup)
    log.info(f"[{label}] Total pages detected: {total_pages}")

    if pages_to_scrape is not None:
        n = min(pages_to_scrape, total_pages)
    elif total_pages > PAGINATION_SANITY_LIMIT:
        n = prompt_fn(total_pages, label)
        if n == 0:
            log.info(f"[{label}] Scrape cancelled.")
            return result
    else:
        n = total_pages

    for page in range(2, n + 1):
        time.sleep(REQUEST_DELAY_SECONDS)
        params = build_params(url_skills, period_p, page=page)
        log.info(f"[{label}] Fetching page {page} of {n}…")
        try:
            result.pages.append(fetch_table(params))
        except Exception as e:
            result.failed_on_page = page
            log.error(f"[{label}] Failed on page {page}: {e}")
            log.warning(f"[{label}] Saving partial data from {len(result.pages)} page(s).")
            break

    return result


def rename_row(row: dict, rename_map: dict[str, str]) -> dict:
    """Return a copy of a row with raw header names replaced by clean names.

    For split columns (e.g. "Historical..._absolute"), the base key is looked
    up in rename_map and the suffix (_absolute, _relative) is preserved.
    Metadata keys (date_scraped, source_url, period, page) pass through unchanged.
    """
    renamed = {}
    for key, value in row.items():
        if key in rename_map:
            renamed[rename_map[key]] = value
            continue
        matched = False
        for raw_key, clean_key in rename_map.items():
            if key.startswith(raw_key + "_"):
                suffix = key[len(raw_key):]
                renamed[clean_key + suffix] = value
                matched = True
                break
        if not matched:
            renamed[key] = value  # metadata keys pass through as-is
    return renamed


def row_matches(row: dict, filters: list[TableSkill]) -> bool:
    """Return True if the row's description matches any entry in TABLE_SKILLS.
    An empty TABLE_SKILLS list matches all rows.
    Works with both raw and renamed rows."""
    if not filters:
        return True

    description = (row.get("description") or row.get("Description") or "").strip().lower()

    for f in filters:
        skill = f["skill"].strip().lower()
        if f["exact"]:
            if description == skill:
                return True
        else:
            if skill in description:
                return True
    return False


# =============================================================================
# OUTPUT HELPERS
# =============================================================================

def _make_filepath(output_dir: str, today: str, extension: str, suffix: str = "") -> str:
    """Create the output directory if needed and return the dated file path."""
    os.makedirs(output_dir, exist_ok=True)
    return os.path.join(output_dir, f"jobdata_{today}{suffix}.{extension}")


def _row_key(row: dict) -> tuple:
    """Return a (description, period) tuple that uniquely identifies a row.
    Works for both raw rows (capital-D Description) and clean rows."""
    description = row.get("description") or row.get("Description") or ""
    return (description, row.get("period", ""))


def save_to_csv(rows: list[dict], output_dir: str, today: str, suffix: str = "") -> str:
    """Merge rows into a dated CSV file (upsert by description+period).
    Existing rows are preserved; only genuinely new keys are appended."""
    if not rows:
        log.warning("No matching rows found — CSV not written.")
        return ""

    filepath = _make_filepath(output_dir, today, "csv", suffix)

    existing: list[dict] = []
    if os.path.exists(filepath):
        with open(filepath, newline="", encoding="utf-8") as f:
            existing = list(csv.DictReader(f))

    existing_keys = {_row_key(r) for r in existing}
    new_rows = [r for r in rows if _row_key(r) not in existing_keys]
    if not new_rows:
        log.info(f"CSV up to date (no new rows): {filepath}")
        return filepath

    merged = existing + new_rows
    fieldnames = list(dict.fromkeys(key for row in merged for key in row))
    with open(filepath, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(merged)

    log.info(f"CSV: added {len(new_rows)} new row(s), kept {len(existing)} existing.")
    return filepath


def save_to_json(rows: list[dict], output_dir: str, today: str, suffix: str = "") -> str:
    """Merge rows into a dated JSON file (upsert by description+period).
    Existing rows are preserved; only genuinely new keys are appended."""
    if not rows:
        log.warning("No matching rows found — JSON not written.")
        return ""

    filepath = _make_filepath(output_dir, today, "json", suffix)

    existing: list[dict] = []
    if os.path.exists(filepath):
        with open(filepath, encoding="utf-8") as f:
            existing = json.load(f)

    existing_keys = {_row_key(r) for r in existing}
    new_rows = [r for r in rows if _row_key(r) not in existing_keys]
    if not new_rows:
        log.info(f"JSON up to date (no new rows): {filepath}")
        return filepath

    merged = existing + new_rows
    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(merged, f, indent=2, ensure_ascii=False)

    log.info(f"JSON: added {len(new_rows)} new row(s), kept {len(existing)} existing.")
    return filepath


def save_to_html(raw_html: str, resolved_url: str, output_dir: str, today: str,
                 period_label: str, page: int = 1) -> str:
    """Save the raw page HTML to a dated file, with a <base> tag injected so
    relative URLs (CSS, images) resolve correctly when opened locally.
    Skips writing if the file already exists."""
    suffix = f"_{period_label}_p{page}"
    filepath = _make_filepath(output_dir, today, "html", suffix)

    if os.path.exists(filepath):
        log.info(f"HTML snapshot already exists, skipping: {filepath}")
        return filepath

    soup = BeautifulSoup(raw_html, "html.parser")
    head = soup.find("head")
    if head:
        base_tag = soup.new_tag("base", href=resolved_url)
        head.insert(0, base_tag)
        html = str(soup)
    else:
        log.warning("No <head> tag found — HTML saved without <base> injection.")
        html = raw_html

    with open(filepath, "w", encoding="utf-8") as f:
        f.write(html)

    return filepath


# =============================================================================
# ENTRY POINT
# =============================================================================

def prompt_page_limit(total_pages: int, label: str = "") -> int:
    """Ask the user how many pages to scrape. Returns 0 to cancel."""
    prefix = f"[{label}] " if label else ""
    print(
        f"\n  {prefix}{total_pages} pages of results detected, which exceeds the "
        f"sanity limit of {PAGINATION_SANITY_LIMIT}.\n"
        f"  Scraping too many pages in one run may put excessive load on the site.\n"
    )
    while True:
        response = input(
            f"  {prefix}How many pages would you like to scrape? "
            f"(0 to cancel, 1–{total_pages}, or press Enter to scrape all {total_pages}): "
        ).strip()
        if response == "":
            return total_pages
        try:
            n = int(response)
            if 0 <= n <= total_pages:
                return n
            print(f"  Please enter a number between 0 and {total_pages}.")
        except ValueError:
            print("  Please enter a valid number.")


def main():
    parser = argparse.ArgumentParser(description="Scrape job market data")
    page_group = parser.add_mutually_exclusive_group()
    page_group.add_argument(
        "--page-limit",
        type=int,
        metavar="N",
        help="Maximum number of pages to scrape per period. Skips the interactive prompt.",
    )
    page_group.add_argument(
        "--all-pages",
        action="store_true",
        help="Scrape all available pages without prompting, regardless of page count.",
    )
    parser.add_argument(
        "--no-filter",
        action="store_true",
        help="Disable all skill filters — fetch all URL results and keep every row.",
    )
    args = parser.parse_args()

    try:
        url_skills_cfg, table_skills_cfg = load_skills_config(SKILLS_CONFIG_PATH)
    except FileNotFoundError:
        log.error(f"Skills config not found: {SKILLS_CONFIG_PATH}. Create it before running.")
        raise SystemExit(1)

    url_skills   = [] if args.no_filter else url_skills_cfg
    table_skills = [] if args.no_filter else table_skills_cfg
    pages_to_scrape = (
        None          if args.all_pages else
        args.page_limit               # may be None if neither flag set
    )

    if args.no_filter:
        log.info("--no-filter flag set: all skill filters disabled.")

    today = date.today().isoformat()

    # Scrape each period in turn.
    all_raw_rows: list[dict] = []
    all_rename_maps: list[dict] = []  # parallel to all_raw_rows
    all_html_pages: list[tuple[FetchResult, str, int]] = []

    for period in PERIODS:
        log.info(f"── Period: {period['label']} ──────────────────────────")
        period_result = scrape_period(period, url_skills, pages_to_scrape, prompt_page_limit)

        if period_result.failed_on_page:
            log.warning(
                f"[{period['label']}] Run incomplete — failed on page "
                f"{period_result.failed_on_page}. "
                f"Output contains data from page(s) 1–{len(period_result.pages)} only."
            )

        for page_num, fetch_result in enumerate(period_result.pages, start=1):
            log.info(f"[{period['label']}] Page {page_num}: {len(fetch_result.rows)} rows")
            for row in fetch_result.rows:
                if row_matches(row, table_skills):
                    row["period"]       = period["label"]
                    row["date_scraped"] = today
                    row["source_url"]   = fetch_result.resolved_url
                    row["page"]         = page_num
                    all_raw_rows.append(row)
                    all_rename_maps.append(fetch_result.rename_map)
            all_html_pages.append((fetch_result, period["label"], page_num))

    log.info(f"Total rows after filtering across all periods: {len(all_raw_rows)}")

    clean_rows = [rename_row(row, rmap) for row, rmap in zip(all_raw_rows, all_rename_maps)]

    for save_fn in (save_to_csv, save_to_json):
        filepath = save_fn(all_raw_rows, OUTPUT_DIR, today, suffix="_raw")
        if filepath:
            log.info(f"Saved to: {filepath}")

    for save_fn in (save_to_csv, save_to_json):
        filepath = save_fn(clean_rows, OUTPUT_DIR, today)
        if filepath:
            log.info(f"Saved to: {filepath}")

    for fetch_result, period_label, page_num in all_html_pages:
        filepath = save_to_html(
            fetch_result.raw_html, fetch_result.resolved_url,
            OUTPUT_DIR, today, period_label, page_num,
        )
        log.info(f"Saved to: {filepath}")


if __name__ == "__main__":
    main()
