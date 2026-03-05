# Job Market Scraper

Automated weekly scraper for job market data, storing results as CSV, JSON,
and HTML snapshots. Data is committed directly to this repository on each run.

## Output files

Each run produces the following files in `data/`:

| File | Contents |
|------|----------|
| `jobdata_YYYY-MM-DD.csv` | Filtered rows, clean column names |
| `jobdata_YYYY-MM-DD.json` | Same, as JSON |
| `jobdata_YYYY-MM-DD_raw.csv` | Filtered rows, original column names from site |
| `jobdata_YYYY-MM-DD_raw.json` | Same, as JSON |
| `jobdata_YYYY-MM-DD_p1.html` | Full page HTML snapshot (one per page scraped) |

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

### 4. Configure the scraper

Edit the config section at the top of `scraper.py`:

```python
URL_SKILLS = ["Alteryx", "Python", "AI"]   # skills sent to the site as URL params

TABLE_SKILLS = [                            # skills used to filter the returned rows
    {"skill": "Python", "exact": True},
    ...
]
```

### 5. Adjust the schedule

Edit `.github/workflows/scrape.yml` and change the cron expression:

```yaml
- cron: "0 8 * * 1"   # every Monday at 08:00 UTC
```

Use [crontab.guru](https://crontab.guru) to construct expressions.

### 6. Adjust the page limit

In the workflow file, change `--page-limit 1` to however many pages you want
to scrape per run, or use `--all-pages` to scrape everything.

## Running locally

```bash
# Normal run (uses configured skills, up to 1 page by default)
uv run scraper.py --page-limit 3

# Scrape all pages without prompting
uv run scraper.py --all-pages

# Ignore all skill filters
uv run scraper.py --no-filter --page-limit 3

# Regenerate the GitHub Pages index locally
uv run generate_index.py
```
