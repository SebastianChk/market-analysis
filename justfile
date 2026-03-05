# List available recipes
default:
    @just --list

# ── Real data ────────────────────────────────────────────────────────────────

# Scrape fresh data (prompts if more than 2 pages are detected)
scrape:
    uv run scraper.py

# Scrape all pages without prompting
scrape-all:
    uv run scraper.py --all-pages

# ── Index ────────────────────────────────────────────────────────────────────

# Regenerate manifest.json and sync skills.json → docs/
index:
    uv run generate_index.py

# ── Mock data ────────────────────────────────────────────────────────────────

# Generate mock data for local testing
mock:
    uv run generate_mock_data.py

# Delete all mock data files (identified by the "mock" field in the JSON)
clean-mock:
    uv run python -c "import json,os,glob; [os.remove(f) for f in glob.glob('docs/data/jobdata_*.json') if json.load(open(f))[0].get('mock')]"

# ── Serving ──────────────────────────────────────────────────────────────────

# Serve the dashboard locally at http://localhost:8000
serve:
    uv run python -m http.server 8000

# ── Workflows ────────────────────────────────────────────────────────────────

# Local dev: generate mock data, rebuild index, then serve
dev: mock index
    python -m http.server 8000

# After editing skills.json: scrape fresh data and rebuild (real data workflow)
# Note: also update SKILLS in generate_mock_data.py if you want mock data for new skills
refresh: scrape index

# After editing skills.json: rebuild with mock data only (local dev workflow)
rebuild: clean-mock mock index
