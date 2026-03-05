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

Each run produces five files in OUTPUT_DIR:
  jobdata_YYYY-MM-DD_raw.csv   — raw table data with original column names
  jobdata_YYYY-MM-DD_raw.json  — same, as JSON
  jobdata_YYYY-MM-DD.csv       — cleaned data with renamed columns
  jobdata_YYYY-MM-DD.json      — same, as JSON
  jobdata_YYYY-MM-DD.html      — full page snapshot

Run manually:  python scraper.py
Schedule via:  cron (Linux/Mac) or GitHub Actions
"""

import argparse
import csv
import json
import logging
import os
import time
from dataclasses import dataclass
from datetime import date
from typing import TypedDict

import httpx
from bs4 import BeautifulSoup


logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
log = logging.getLogger(__name__)


# =============================================================================
# CONFIGURATION — edit these two sections freely
# =============================================================================

# Skills sent as URL query parameters (comma-joined into the `ql` param).
# These tell the website which skills to search across.
URL_SKILLS = [
    "Alteryx",
    "Python",
    "AI",
]


class TableSkill(TypedDict):
    skill: str    # text to match against the row's description
    exact: bool   # True  = full description must match (case-insensitive)
                  # False = description just needs to contain the skill text


# Skills used to filter rows from the HTML table.
TABLE_SKILLS: list[TableSkill] = [
    {"skill": "AI",                      "exact": True},
    {"skill": "Python",                  "exact": True},
    {"skill": "Alteryx",                 "exact": True},
    {"skill": "Python Developer",        "exact": True},
    {"skill": "Python Engineer",         "exact": True},
    {"skill": "Senior Python Developer", "exact": True},
    {"skill": "PySpark",                 "exact": False},  # catches "PySpark - Spark Python API"
]


# =============================================================================
# URL PARAMETERS — adjust pagination/experience filters here if needed
# =============================================================================

BASE_URL = "https://www.itjobswatch.co.uk/default.aspx"

FIXED_PARAMS = {
    "q":       "",
    "l":       "",
    "ll":      "",
    "id":      "0",
    "p":       "6",   # experience level filter
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

COLUMN_RENAME_MAP: dict[str, str] = {
    "Description":                                    "description",
    "Rank 6 Months to 5 Mar 2026":                   "rank_6mo",
    "Rank YoY Change":                                "rank_yoy_change",
    "Median Salary":                                  "median_salary",
    "Median Salary YoY Change":                       "median_salary_yoy_change",
    "Historical Absolute & Relative Jobs Vacancies":  "historical_vacancies",
    "Live Jobs":                                      "live_jobs",
}

# Derived constants — do not edit these directly.
_RAW_COLUMNS = list(COLUMN_RENAME_MAP.keys())
HIST_VACANCIES_RAW_KEY = "Historical Absolute & Relative Jobs Vacancies"
HIST_VACANCIES_IDX = _RAW_COLUMNS.index(HIST_VACANCIES_RAW_KEY)

# =============================================================================
# OUTPUT — one file per format per run, named by date
# =============================================================================

OUTPUT_DIR = "data"  # relative to script location; created automatically

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
    rows: list[dict]       # rows keyed by raw header names
    resolved_url: str
    raw_html: str
    soup: BeautifulSoup    # parsed HTML, used for pagination detection


def build_params(skills: list[str], page: int = 1) -> dict:
    params = {**FIXED_PARAMS, "ql": ",".join(skills)}
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

    # Validate against COLUMN_RENAME_MAP keys — both count and exact names.
    expected_headers = _RAW_COLUMNS
    if actual_headers != expected_headers:
        added   = [h for h in actual_headers  if h not in expected_headers]
        removed = [h for h in expected_headers if h not in actual_headers]
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

        # Build row using raw header names.
        row = {
            _RAW_COLUMNS[i]: cells[i].get_text(strip=True)
            for i in range(min(len(_RAW_COLUMNS), len(cells)))
        }

        # Split the historical vacancies cell into two fields using text nodes.
        # The visual pipe separator naturally divides them into distinct nodes.
        row.pop(HIST_VACANCIES_RAW_KEY, None)
        hist_cell = cells[HIST_VACANCIES_IDX]
        text_nodes = [s.strip() for s in hist_cell.strings if s.strip()]
        if len(text_nodes) >= 2:
            row[f"{HIST_VACANCIES_RAW_KEY}_absolute"] = text_nodes[0]
            row[f"{HIST_VACANCIES_RAW_KEY}_relative"] = text_nodes[1]
        else:
            row[f"{HIST_VACANCIES_RAW_KEY}_absolute"] = text_nodes[0] if text_nodes else ""
            row[f"{HIST_VACANCIES_RAW_KEY}_relative"] = None

        rows.append(row)

    return FetchResult(rows=rows, resolved_url=resolved_url, raw_html=raw_html, soup=soup)


def rename_row(row: dict) -> dict:
    """Return a copy of a row with raw header names replaced by clean names.

    For split columns (e.g. "Historical..._absolute"), the base key is looked
    up in COLUMN_RENAME_MAP and the suffix (_absolute, _relative) is preserved.
    Metadata keys (date_scraped, source_url) pass through unchanged.
    """
    renamed = {}
    for key, value in row.items():
        # Direct match
        if key in COLUMN_RENAME_MAP:
            renamed[COLUMN_RENAME_MAP[key]] = value
            continue
        # Suffix match for split columns (e.g. "Historical..._absolute")
        matched = False
        for raw_key, clean_key in COLUMN_RENAME_MAP.items():
            if key.startswith(raw_key + "_"):
                suffix = key[len(raw_key):]   # e.g. "_absolute"
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


def save_to_csv(rows: list[dict], output_dir: str, today: str, suffix: str = "") -> str:
    """Save rows to a dated CSV file. Returns the output path."""
    if not rows:
        log.warning("No matching rows found — CSV not written.")
        return ""

    filepath = _make_filepath(output_dir, today, "csv", suffix)
    fieldnames = list(rows[0].keys())
    with open(filepath, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

    return filepath


def save_to_json(rows: list[dict], output_dir: str, today: str, suffix: str = "") -> str:
    """Save rows to a dated JSON file. Returns the output path."""
    if not rows:
        log.warning("No matching rows found — JSON not written.")
        return ""

    filepath = _make_filepath(output_dir, today, "json", suffix)
    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(rows, f, indent=2, ensure_ascii=False)

    return filepath


def save_to_html(raw_html: str, resolved_url: str, output_dir: str, today: str, page: int = 1) -> str:
    """Save the raw page HTML to a dated file, with a <base> tag injected so
    relative URLs (CSS, images) resolve correctly when opened locally."""
    page_suffix = f"_p{page}"
    filepath = _make_filepath(output_dir, today, "html", page_suffix)

    # Use BeautifulSoup to inject <base href="..."> so it works regardless of
    # whether the original <head> tag has attributes or unusual casing.
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

def prompt_page_limit(total_pages: int) -> int:
    """If total pages exceeds PAGINATION_SANITY_LIMIT, ask the user how many
    pages to scrape. Returns the number of pages to scrape, or 0 to cancel."""
    print(
        f"\n  {total_pages} pages of results detected, which exceeds the "
        f"sanity limit of {PAGINATION_SANITY_LIMIT}.\n"
        f"  Scraping too many pages in one run may put excessive load on the site.\n"
    )
    while True:
        response = input(
            f"  How many pages would you like to scrape? "
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
    parser = argparse.ArgumentParser(description="Scrape IT job market data")
    page_group = parser.add_mutually_exclusive_group()
    page_group.add_argument(
        "--page-limit",
        type=int,
        metavar="N",
        help="Maximum number of pages to scrape. Skips the interactive prompt if page count exceeds the sanity limit.",
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

    url_skills = [] if args.no_filter else URL_SKILLS
    table_skills = [] if args.no_filter else TABLE_SKILLS

    if args.no_filter:
        log.info("--no-filter flag set: all skill filters disabled.")

    today = date.today().isoformat()

    # Fetch page 1.
    params = build_params(url_skills, page=1)
    log.info(f"Fetching page 1: {BASE_URL} with params {params}")
    first_result = fetch_table(params)
    log.info(f"Resolved URL: {first_result.resolved_url}")

    # Detect total pages from the first page's HTML.
    total_pages = detect_total_pages(first_result.soup)
    log.info(f"Total pages detected: {total_pages}")

    # Determine how many pages to scrape.
    if args.all_pages:
        pages_to_scrape = total_pages
        log.info(f"--all-pages flag set: scraping all {total_pages} page(s).")
    elif args.page_limit is not None:
        pages_to_scrape = min(args.page_limit, total_pages)
        log.info(f"--page-limit flag set: scraping {pages_to_scrape} of {total_pages} page(s).")
    elif total_pages > PAGINATION_SANITY_LIMIT:
        pages_to_scrape = prompt_page_limit(total_pages)
    else:
        pages_to_scrape = total_pages

    if pages_to_scrape == 0:
        log.info("Scrape cancelled.")
        return

    # Collect results across all pages, starting with what we already fetched.
    # On error, break out of the loop and save whatever was collected so far.
    results = [first_result]
    failed_on_page = None

    for page in range(2, pages_to_scrape + 1):
        time.sleep(REQUEST_DELAY_SECONDS)
        params = build_params(url_skills, page=page)
        log.info(f"Fetching page {page} of {pages_to_scrape}…")
        try:
            result = fetch_table(params)
            results.append(result)
        except Exception as e:
            failed_on_page = page
            log.error(f"Failed on page {page}: {e}")
            log.warning(f"Saving partial data from {len(results)} successfully fetched page(s).")
            break

    # Filter and attach metadata across all collected pages.
    all_raw_rows: list[dict] = []
    for page_num, result in enumerate(results, start=1):
        log.info(f"Page {page_num}: {len(result.rows)} rows in table")
        for row in result.rows:
            if row_matches(row, table_skills):
                row["date_scraped"] = today
                row["source_url"] = result.resolved_url
                row["page"] = page_num
                all_raw_rows.append(row)

    if failed_on_page:
        log.warning(
            f"Run incomplete — failed on page {failed_on_page} of {pages_to_scrape}. "
            f"Output files contain data from page(s) 1–{len(results)} only."
        )

    log.info(f"Total rows after filtering across {len(results)} page(s): {len(all_raw_rows)}")

    # Produce clean-named rows.
    clean_rows = [rename_row(row) for row in all_raw_rows]

    # Save raw and clean data files.
    for save_fn in (save_to_csv, save_to_json):
        filepath = save_fn(all_raw_rows, OUTPUT_DIR, today, suffix="_raw")
        if filepath:
            log.info(f"Saved to: {filepath}")

    for save_fn in (save_to_csv, save_to_json):
        filepath = save_fn(clean_rows, OUTPUT_DIR, today)
        if filepath:
            log.info(f"Saved to: {filepath}")

    # Save one HTML snapshot per page.
    for page_num, result in enumerate(results, start=1):
        filepath = save_to_html(result.raw_html, result.resolved_url, OUTPUT_DIR, today, page=page_num)
        log.info(f"Saved to: {filepath}")


if __name__ == "__main__":
    main()