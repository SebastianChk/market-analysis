# ***[Vibe Coded]*** Job Market Scraper

Automated daily scraper for UK IT job market data, storing results as CSV, JSON,
and HTML snapshots. Data is committed directly to this repository on each run and
served via GitHub Pages as an interactive dashboard.

## Files

```
skills.json              # Single source of truth for tracked skills and categories
scraper.py               # Fetches data from IT Jobs Watch and writes dated output files
generate_index.py        # Generates the manifest and LLM-readable snapshot files
docs/
  index.html             # Dashboard (static — served via GitHub Pages)
  manifest.json          # Index of all available data runs (read by the dashboard at runtime)
  skills.json            # Copy of skills.json (read by the dashboard at runtime)
  latest_6mo.json        # Latest snapshot, 6-month window, grouped by category (LLM-readable)
  latest_3mo.json        # Latest snapshot, 3-month window, grouped by category (LLM-readable)
  data/
    jobdata_YYYY-MM-DD.csv            # Clean data, both periods
    jobdata_YYYY-MM-DD.json           # Same, as JSON
    jobdata_YYYY-MM-DD_raw.csv        # Raw column names from source site
    jobdata_YYYY-MM-DD_raw.json       # Same, as JSON
    jobdata_YYYY-MM-DD_3mo_p1.html    # Full page HTML snapshot (3-month period, page 1)
    jobdata_YYYY-MM-DD_6mo_p1.html    # Full page HTML snapshot (6-month period, page 1)
```

Each dated data file contains rows for both the 3-month and 6-month rolling windows,
distinguished by a `period` field (`"3mo"` or `"6mo"`).

## Setup

### 1. Create the repository

Create a new GitHub repository and push these files to it.

### 2. Enable GitHub Pages

Go to **Settings → Pages** and set:
- **Source**: `Deploy from a branch`
- **Branch**: `main`, folder `/docs`

Your dashboard will be available at `https://<your-username>.github.io/<repo-name>/`.

### 3. Enable Actions write permissions

Go to **Settings → Actions → General → Workflow permissions** and select
**Read and write permissions**. This allows the workflow to commit data files.

### 4. Configure tracked skills

Edit `skills.json` to control which skills are scraped and how they are categorised
in the dashboard. This is the only file you need to change to add, remove, or
recategorise a skill.

```json
{
  "url_skills": ["Python", "AWS"],
  "categories": {
    "Language": [
      { "description": "Python", "exact": true }
    ],
    "Cloud Platform": [
      { "description": "AWS", "exact": true }
    ]
  }
}
```

- `url_skills` — passed to the source site as query parameters
- `categories` — groups skills into dashboard tabs; `exact: true` means the row description must match exactly (case-insensitive)

### 5. Adjust the schedule

Edit `.github/workflows/scrape.yml` and change the cron expression:

```yaml
- cron: "27 0 * * *"   # every day at 00:27 UTC
```

Use [crontab.guru](https://crontab.guru) to construct expressions.

### 6. Adjust the page limit

In the workflow file, change `--page-limit 1` to however many pages you want
to scrape per run, or use `--all-pages` to scrape everything.

## Running locally

```bash
# Normal run (first page only)
uv run scraper.py --page-limit 1

# Scrape all pages without prompting
uv run scraper.py --all-pages

# Ignore all skill filters — fetch and keep every row
uv run scraper.py --no-filter --page-limit 1

# Regenerate manifest and LLM snapshot files (does not re-scrape)
uv run generate_index.py
```

## LLM access

`docs/latest_6mo.json` and `docs/latest_3mo.json` are generated on every run and
designed to be fetched directly by a language model. Each file contains a `_meta`
block with field definitions, units, and caveats to prevent misinterpretation, and
skills are grouped by category matching the dashboard tabs.

These files are available at:
```
https://<your-username>.github.io/<repo-name>/latest_6mo.json
https://<your-username>.github.io/<repo-name>/latest_3mo.json
```
