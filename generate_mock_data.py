# /// script
# requires-python = ">=3.13"
# dependencies = []
# ///
"""Generates mock weekly job data for local dashboard testing.
Run once with: python generate_mock_data.py
Delete this file and the generated data files before going live.
"""

import json
import os
from datetime import date, timedelta

SOURCE_URL = "https://www.itjobswatch.co.uk/default.aspx?q=&l=&ll=&id=0&p=6&e=5&sortby=&orderby=&ql=Alteryx%2CPython%2CAI"
OUTPUT_DIR = "data"

# Anchor values from the real 2026-03-05 scrape.
# Each skill has per-week deltas applied going BACK in time,
# so the chart shows a trend leading up to today.
SKILLS = [
    {
        "description": "AI",
        "rank":        [4,   5,   6,   7,   8,   9,  11],   # improving each week
        "rank_yoy":    ["+34", "+31", "+29", "+27", "+24", "+21", "+18"],
        "salary":      [70000, 69500, 69000, 68500, 68000, 67500, 67000],
        "salary_yoy":  ["-6.66%", "-7.00%", "-7.50%", "-8.00%", "-8.50%", "-9.00%", "-9.50%"],
        "live_jobs":   [3838, 3700, 3550, 3400, 3250, 3100, 2950],
        "hist_abs":    [9991, 9600, 9200, 8800, 8400, 8000, 7600],
        "hist_rel":    ["13.91%", "13.50%", "13.00%", "12.50%", "12.00%", "11.50%", "11.00%"],
    },
    {
        "description": "Python",
        "rank":        [17, 16, 16, 15, 15, 14, 14],
        "rank_yoy":    ["-5", "-4", "-4", "-3", "-3", "-2", "-1"],
        "salary":      [67500, 67000, 66500, 66000, 65500, 65000, 65000],
        "salary_yoy":  ["-10.00%", "-10.50%", "-11.00%", "-11.50%", "-12.00%", "-12.50%", "-13.00%"],
        "live_jobs":   [3760, 3680, 3600, 3520, 3450, 3380, 3300],
        "hist_abs":    [5328, 5200, 5080, 4960, 4840, 4720, 4600],
        "hist_rel":    ["7.42%", "7.30%", "7.15%", "7.00%", "6.85%", "6.70%", "6.55%"],
    },
    {
        "description": "Alteryx",
        "rank":        [607, 590, 572, 555, 538, 520, 505],  # declining (rank rising = less demand)
        "rank_yoy":    ["-30", "-28", "-25", "-22", "-19", "-16", "-13"],
        "salary":      [79000, 78000, 77000, 76500, 76000, 75500, 75000],
        "salary_yoy":  ["+31.66%", "+29.00%", "+26.00%", "+23.00%", "+20.00%", "+17.00%", "+14.00%"],
        "live_jobs":   [6, 7, 8, 9, 10, 11, 13],
        "hist_abs":    [69, 72, 76, 80, 85, 90, 96],
        "hist_rel":    ["0.096%", "0.100%", "0.106%", "0.111%", "0.118%", "0.125%", "0.134%"],
    },
    {
        "description": "Python Engineer",
        "rank":        [405, 398, 390, 382, 374, 366, 358],
        "rank_yoy":    ["-109", "-102", "-95", "-88", "-81", "-74", "-67"],
        "salary":      [90000, 89500, 89000, 88500, 88000, 87500, 87000],
        "salary_yoy":  ["-10.00%", "-10.50%", "-11.00%", "-11.50%", "-12.00%", "-12.50%", "-13.00%"],
        "live_jobs":   [104, 100, 96, 92, 88, 84, 80],
        "hist_abs":    [292, 283, 274, 265, 256, 247, 238],
        "hist_rel":    ["0.41%", "0.39%", "0.38%", "0.37%", "0.36%", "0.34%", "0.33%"],
    },
    {
        "description": "Python Developer",
        "rank":        [387, 382, 377, 372, 368, 363, 358],
        "rank_yoy":    ["+15", "+13", "+11", "+9", "+7", "+5", "+3"],
        "salary":      [76000, 75500, 75000, 74500, 74000, 73500, 73000],
        "salary_yoy":  ["-5.00%", "-5.50%", "-6.00%", "-6.50%", "-7.00%", "-7.50%", "-8.00%"],
        "live_jobs":   [155, 150, 145, 140, 135, 130, 125],
        "hist_abs":    [321, 311, 301, 291, 281, 271, 261],
        "hist_rel":    ["0.45%", "0.43%", "0.42%", "0.41%", "0.39%", "0.38%", "0.36%"],
    },
    {
        "description": "PySpark - Spark Python API",
        "rank":        [512, 505, 498, 491, 484, 477, 470],
        "rank_yoy":    ["-115", "-108", "-101", "-94", "-87", "-80", "-73"],
        "salary":      [74250, 76000, 77000, 76500, 75500, 74000, 73000],
        "salary_yoy":  ["-32.50%", "-30.00%", "-27.50%", "-25.00%", "-22.50%", "-20.00%", "-17.50%"],
        "live_jobs":   [121, 118, 115, 112, 109, 106, 103],
        "hist_abs":    [166, 161, 156, 151, 146, 141, 136],
        "hist_rel":    ["0.23%", "0.22%", "0.22%", "0.21%", "0.20%", "0.20%", "0.19%"],
    },
    {
        "description": "Senior Python Developer",
        "rank":        [596, 590, 584, 578, 572, 566, 560],
        "rank_yoy":    ["+16", "+14", "+12", "+10", "+8", "+6", "+4"],
        "salary":      [80000, 79500, 79000, 78500, 78000, 77500, 77000],
        "salary_yoy":  ["+14.28%", "+12.00%", "+10.00%", "+8.00%", "+6.00%", "+4.00%", "+2.00%"],
        "live_jobs":   [42, 40, 38, 36, 34, 32, 30],
        "hist_abs":    [80, 77, 74, 71, 68, 65, 62],
        "hist_rel":    ["0.11%", "0.11%", "0.10%", "0.10%", "0.09%", "0.09%", "0.09%"],
    },
]

# 7 weekly dates ending on the real scrape date (index 0 = most recent)
END_DATE = date(2026, 3, 5)
DATES = [END_DATE - timedelta(weeks=i) for i in range(7)]  # [2026-03-05, ..., 2026-01-22]

os.makedirs(OUTPUT_DIR, exist_ok=True)

for week_idx, run_date in enumerate(DATES):
    date_str = run_date.isoformat()
    rows = []
    for skill in SKILLS:
        salary = skill["salary"][week_idx]
        rows.append({
            "description":                       skill["description"],
            "rank_6mo":                          str(skill["rank"][week_idx]),
            "rank_yoy_change":                   skill["rank_yoy"][week_idx],
            "median_salary":                     f"£{salary:,}",
            "median_salary_yoy_change":          skill["salary_yoy"][week_idx],
            "live_jobs":                         f"{skill['live_jobs'][week_idx]:,}",
            "historical_vacancies_absolute":     f"{skill['hist_abs'][week_idx]:,}",
            "historical_vacancies_relative":     skill["hist_rel"][week_idx],
            "date_scraped":                      date_str,
            "source_url":                        SOURCE_URL,
            "page":                              1,
        })

    # Skip 2026-03-05 — real file already exists
    path = os.path.join(OUTPUT_DIR, f"jobdata_{date_str}.json")
    if os.path.exists(path):
        print(f"Skipped (already exists): {path}")
        continue

    with open(path, "w", encoding="utf-8") as f:
        json.dump(rows, f, indent=2, ensure_ascii=False)
    print(f"Written: {path}")

print("Done.")
