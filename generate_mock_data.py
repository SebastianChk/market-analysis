# /// script
# requires-python = ">=3.13"
# dependencies = []
# ///
"""Generates mock weekly job data for local dashboard testing.
Run once with: uv run generate_mock_data.py
Delete the generated data files before going live.

Reads the skill list from skills.json so it stays in sync with the scraper.
Anchor values (week 0 = most recent real scrape) are hardcoded below — add an
entry to ANCHORS whenever a new skill is added to skills.json, otherwise that
skill is skipped with a warning.

Historical weeks (1–6) are derived from the anchor values and the annual rank
trend, so you only need to maintain one set of numbers per skill.
"""

import json
import os
from datetime import date, timedelta

SKILLS_CONFIG_PATH = "skills.json"
OUTPUT_DIR = "docs/data"
NUM_WEEKS = 7

SOURCE_URLS = {
    "3mo": "https://www.itjobswatch.co.uk/default.aspx?q=&l=&ll=&id=0&p=3&e=5&sortby=&orderby=",
    "6mo": "https://www.itjobswatch.co.uk/default.aspx?q=&l=&ll=&id=0&p=6&e=5&sortby=&orderby=",
}

# 7 weekly dates ending on the most recent real scrape (index 0 = most recent).
END_DATE = date(2026, 3, 5)
DATES = [END_DATE - timedelta(weeks=i) for i in range(NUM_WEEKS)]

# ── Anchor values from the real 2026-03-05 scrape ────────────────────────────
# rank_yoy: integer, positive = rank improved (more in demand) YoY.
# salary_yoy / hist_rel: kept as strings (constant across all mock weeks).
# Google Cloud Platform is estimated (not yet in the real data file).
ANCHORS: dict[str, dict] = {
    "AI": {
        "live_jobs": 3838,
        "3mo": {"rank": 5,   "rank_yoy": 28,  "salary": 70000, "salary_yoy": "+5.50%",  "hist_abs": 5173, "hist_rel": "12.70%"},
        "6mo": {"rank": 4,   "rank_yoy": 34,  "salary": 70000, "salary_yoy": "-6.66%",  "hist_abs": 9991, "hist_rel": "13.91%"},
    },
    "Cybersecurity": {
        "live_jobs": 1860,
        "3mo": {"rank": 3,   "rank_yoy": 36,  "salary": 57239, "salary_yoy": "-10.35%", "hist_abs": 5223, "hist_rel": "12.82%"},
        "6mo": {"rank": 7,   "rank_yoy": 30,  "salary": 50000, "salary_yoy": "-22.17%", "hist_abs": 8780, "hist_rel": "12.23%"},
    },
    "Azure": {
        "live_jobs": 3820,
        "3mo": {"rank": 7,   "rank_yoy": 0,   "salary": 65000, "salary_yoy": "-",       "hist_abs": 4988, "hist_rel": "12.24%"},
        "6mo": {"rank": 6,   "rank_yoy": 1,   "salary": 62500, "salary_yoy": "-3.84%",  "hist_abs": 9166, "hist_rel": "12.76%"},
    },
    "Python": {
        "live_jobs": 3764,
        "3mo": {"rank": 18,  "rank_yoy": -5,  "salary": 65000, "salary_yoy": "-10.34%", "hist_abs": 2926, "hist_rel": "7.18%"},
        "6mo": {"rank": 17,  "rank_yoy": -5,  "salary": 67500, "salary_yoy": "-10.00%", "hist_abs": 5328, "hist_rel": "7.42%"},
    },
    "AWS": {
        "live_jobs": 2989,
        "3mo": {"rank": 31,  "rank_yoy": -17, "salary": 70000, "salary_yoy": "-3.44%",  "hist_abs": 2479, "hist_rel": "6.08%"},
        "6mo": {"rank": 24,  "rank_yoy": -14, "salary": 70932, "salary_yoy": "-5.42%",  "hist_abs": 4780, "hist_rel": "6.66%"},
    },
    "SQL": {
        "live_jobs": 2529,
        "3mo": {"rank": 30,  "rank_yoy": -19, "salary": 60000, "salary_yoy": "-4.00%",  "hist_abs": 2497, "hist_rel": "6.13%"},
        "6mo": {"rank": 22,  "rank_yoy": -13, "salary": 57500, "salary_yoy": "-4.16%",  "hist_abs": 4951, "hist_rel": "6.89%"},
    },
    "Software Engineering": {
        "live_jobs": 2162,
        "3mo": {"rank": 26,  "rank_yoy": -7,  "salary": 72500, "salary_yoy": "-",       "hist_abs": 2627, "hist_rel": "6.45%"},
        "6mo": {"rank": 28,  "rank_yoy": -12, "salary": 70000, "salary_yoy": "-2.09%",  "hist_abs": 4506, "hist_rel": "6.28%"},
    },
    "Java": {
        "live_jobs": 963,
        "3mo": {"rank": 68,  "rank_yoy": -26, "salary": 72500, "salary_yoy": "-9.37%",  "hist_abs": 1145, "hist_rel": "2.81%"},
        "6mo": {"rank": 70,  "rank_yoy": -24, "salary": 75000, "salary_yoy": "-",       "hist_abs": 2121, "hist_rel": "2.95%"},
    },
    "JavaScript": {
        "live_jobs": 1564,
        "3mo": {"rank": 76,  "rank_yoy": -49, "salary": 60000, "salary_yoy": "-9.36%",  "hist_abs": 997,  "hist_rel": "2.45%"},
        "6mo": {"rank": 68,  "rank_yoy": -46, "salary": 60000, "salary_yoy": "-9.22%",  "hist_abs": 2166, "hist_rel": "3.02%"},
    },
    "Data Science": {
        "live_jobs": 1058,
        "3mo": {"rank": 138, "rank_yoy": -25, "salary": 70000, "salary_yoy": "-2.76%",  "hist_abs": 553,  "hist_rel": "1.36%"},
        "6mo": {"rank": 158, "rank_yoy": -26, "salary": 70000, "salary_yoy": "-",       "hist_abs": 1001, "hist_rel": "1.39%"},
    },
    "Databricks": {
        "live_jobs": 383,
        "3mo": {"rank": 229, "rank_yoy": -41, "salary": 85000, "salary_yoy": "+9.67%",  "hist_abs": 314,  "hist_rel": "0.77%"},
        "6mo": {"rank": 251, "rank_yoy": -13, "salary": 85000, "salary_yoy": "+13.33%", "hist_abs": 577,  "hist_rel": "0.80%"},
    },
    "Snowflake": {
        "live_jobs": 253,
        "3mo": {"rank": 324, "rank_yoy": -62, "salary": 80000, "salary_yoy": "-5.88%",  "hist_abs": 176,  "hist_rel": "0.43%"},
        "6mo": {"rank": 315, "rank_yoy": 28,  "salary": 80000, "salary_yoy": "-15.78%", "hist_abs": 425,  "hist_rel": "0.59%"},
    },
    "R": {
        "live_jobs": 409,
        "3mo": {"rank": 361, "rank_yoy": -66, "salary": 37500, "salary_yoy": "-41.40%", "hist_abs": 137,  "hist_rel": "0.34%"},
        "6mo": {"rank": 409, "rank_yoy": -41, "salary": 30500, "salary_yoy": "-50.80%", "hist_abs": 286,  "hist_rel": "0.40%"},
    },
    # Estimated — not yet in the real data file.
    "Google Cloud Platform": {
        "live_jobs": 820,
        "3mo": {"rank": 55,  "rank_yoy": -10, "salary": 70000, "salary_yoy": "-5.00%",  "hist_abs": 830,  "hist_rel": "2.04%"},
        "6mo": {"rank": 50,  "rank_yoy": -8,  "salary": 70000, "salary_yoy": "-4.00%",  "hist_abs": 1560, "hist_rel": "2.17%"},
    },
}


def derive_week(anchor: dict, live_jobs_anchor: int, week_idx: int) -> dict:
    """Derive values for a given week offset going back in time from the anchor.

    week_idx=0 returns the anchor values exactly.
    For rank: positive rank_yoy means rank was worse (higher number) in the past.
    For live_jobs / hist_abs: trend in the same direction as rank improvement.
    Salary, salary_yoy, hist_rel, and rank_yoy_change are held constant —
    they are year-over-year or market-share figures that don't shift week-to-week.
    """
    rank_yoy = anchor["rank_yoy"]

    # Rank going back i weeks (rank_yoy is annual, so divide by 52).
    rank = max(1, round(anchor["rank"] + week_idx * rank_yoy / 52))

    # Live jobs and hist_abs trend with demand direction (±0.8% / ±1.0% per week).
    direction = 1 if rank_yoy > 0 else (-1 if rank_yoy < 0 else 0)
    live_jobs = max(1, round(live_jobs_anchor * (1 - week_idx * 0.008 * direction)))
    hist_abs  = max(1, round(anchor["hist_abs"]  * (1 - week_idx * 0.010 * direction)))

    # Format rank_yoy_change as a signed string.
    rank_yoy_str = f"+{rank_yoy}" if rank_yoy > 0 else str(rank_yoy)

    return {
        "rank":      rank,
        "rank_yoy":  rank_yoy_str,
        "salary":    anchor["salary"],
        "salary_yoy": anchor["salary_yoy"],
        "live_jobs": live_jobs,
        "hist_abs":  hist_abs,
        "hist_rel":  anchor["hist_rel"],
    }


# ── Load skill list from skills.json ─────────────────────────────────────────

with open(SKILLS_CONFIG_PATH, encoding="utf-8") as f:
    skills_config = json.load(f)

skill_descriptions = [
    entry["description"]
    for entries in skills_config["categories"].values()
    for entry in entries
]

missing = [s for s in skill_descriptions if s not in ANCHORS]
if missing:
    print(f"Warning: no anchor data for the following skills — they will be skipped:")
    for s in missing:
        print(f"  • {s}")

skills_to_generate = [s for s in skill_descriptions if s in ANCHORS]

# ── Generate files ────────────────────────────────────────────────────────────

os.makedirs(OUTPUT_DIR, exist_ok=True)

for week_idx, run_date in enumerate(DATES):
    date_str = run_date.isoformat()

    rows = []
    for period in ("3mo", "6mo"):
        for description in skills_to_generate:
            anchor      = ANCHORS[description]
            period_data = derive_week(anchor[period], anchor["live_jobs"], week_idx)

            rows.append({
                "description":                   description,
                "rank":                          str(period_data["rank"]),
                "rank_yoy_change":               period_data["rank_yoy"],
                "median_salary":                 f"£{period_data['salary']:,}",
                "median_salary_yoy_change":      period_data["salary_yoy"],
                "live_jobs":                     f"{period_data['live_jobs']:,}",
                "historical_vacancies_absolute": f"{period_data['hist_abs']:,}",
                "historical_vacancies_relative": period_data["hist_rel"],
                "period":                        period,
                "date_scraped":                  date_str,
                "source_url":                    SOURCE_URLS[period],
                "page":                          1,
                "mock":                          True,
            })

    path = os.path.join(OUTPUT_DIR, f"jobdata_{date_str}.json")
    if os.path.exists(path):
        print(f"Skipped (already exists): {path}")
        continue

    with open(path, "w", encoding="utf-8") as f:
        json.dump(rows, f, indent=2, ensure_ascii=False)
    print(f"Written: {path}")

print("Done.")
