"""
Daily Remote Job Shortlist Finder
==================================
Pulls from 4 free public job feeds (no scraping, no ToS issues):
  - RemoteOK   (JSON API)
  - Remotive   (RSS feed)
  - Jobicy     (JSON API)
  - Arbeitnow  (JSON API)

Applies your filter spec exactly:
  - Target roles      (title must contain one)
  - Tech stack         (title+description must contain one)
  - Exclusions          (hard reject if any appear anywhere)
  - Worldwide/anywhere location scope (strict mode)
  - Salary >= $18,000 USD/year (see STRICT_SALARY_REQUIRES_DISCLOSURE below)

Output: a dated CSV in the same folder, plus a printed summary.

Run:  pip install requests feedparser
      python remote_job_finder.py
"""

import csv
import json
import re
from datetime import datetime

import requests
import feedparser

SEEN_FILE = "seen_jobs.json"

# ============ FILTER CONFIG (edit here, nowhere else) ============

TARGET_ROLES = [
    "full stack", "fullstack", "full-stack", "backend", "back end", "back-end",
    "frontend", "front end", "front-end", "software engineer", "developer",
]

TECH_STACK = [
    "python", "javascript", "typescript", "react", "node", "vue",
    "angular", "django", "fastapi", "flask", "postgres",
]

EXCLUSIONS = [
    "senior", "lead", "principal", "staff", "manager", "director",
    "unpaid", "intern", "internship", "part-time", "contractor",
    "us only", "usa only", "north america only", "uk only", "eu only",
]

LOCATION_SCOPE = ["worldwide", "anywhere", "remote", "global"]

# Extra restrictive-geo terms rejected outright under strict worldwide mode,
# even if "remote" also appears in the same listing.
RESTRICTIVE_GEO_TERMS = [
    "us only", "usa only", "united states only", "north america only",
    "uk only", "european union only", "eu only", "canada only",
    "emea only", "apac only", "us residents only", "authorized to work in the us",
]

SALARY_MIN = 18000

# If True: any job with NO disclosed salary is rejected (true zero-compromise).
# If False (default): jobs with no disclosed salary pass through, tagged
#   "not disclosed" in the output, since most listings across all 4 sources
#   don't publish a figure at all — strict mode would filter out almost everything.
STRICT_SALARY_REQUIRES_DISCLOSURE = False

import os
os.makedirs("results", exist_ok=True)
OUTPUT_FILE = f"results/remote_jobs_{datetime.now().strftime('%Y%m%d')}.csv"

# ============ FILTER LOGIC ============

def contains_any(text, keywords):
    t = text.lower()
    return any(kw in t for kw in keywords)


def contains_none(text, keywords):
    t = text.lower()
    return not any(kw in t for kw in keywords)


def passes_filters(title, description, location, salary_min):
    combined = f"{title} {description} {location}"

    if not contains_any(title, TARGET_ROLES):
        return False, None

    if not contains_any(combined, TECH_STACK):
        return False, None

    if not contains_none(combined, EXCLUSIONS):
        return False, None

    if not contains_any(combined, LOCATION_SCOPE):
        return False, None

    if contains_any(combined, RESTRICTIVE_GEO_TERMS):
        return False, None

    salary_note = "not disclosed"
    if salary_min:
        try:
            salary_min_val = float(re.sub(r"[^\d.]", "", str(salary_min)) or 0)
        except ValueError:
            salary_min_val = 0
        if salary_min_val > 0:
            if salary_min_val < SALARY_MIN:
                return False, None
            salary_note = f"${int(salary_min_val):,}+"
    elif STRICT_SALARY_REQUIRES_DISCLOSURE:
        return False, None

    return True, salary_note


# ============ SOURCE FETCHERS ============

def fetch_remoteok():
    jobs = []
    try:
        r = requests.get("https://remoteok.com/api",
                          headers={"User-Agent": "Mozilla/5.0"}, timeout=15)
        for item in r.json():
            if not isinstance(item, dict) or "position" not in item:
                continue
            title = item.get("position", "")
            desc = item.get("description", "") or ""
            tags = " ".join(item.get("tags", []) or [])
            location = item.get("location", "") or ""
            ok, salary_note = passes_filters(title, f"{desc} {tags}", location, item.get("salary_min"))
            if ok:
                jobs.append({
                    "source": "RemoteOK", "title": title,
                    "company": item.get("company", ""),
                    "location": location or "Not specified",
                    "salary": salary_note,
                    "url": item.get("url", ""),
                    "posted": item.get("date", ""),
                })
    except Exception as e:
        print(f"[RemoteOK] error: {e}")
    return jobs


def fetch_remotive():
    jobs = []
    try:
        feed = feedparser.parse("https://remotive.com/remote-jobs/feed")
        for entry in feed.entries:
            title = entry.get("title", "")
            desc = entry.get("summary", "") or ""
            ok, salary_note = passes_filters(title, desc, "", None)
            if ok:
                jobs.append({
                    "source": "Remotive", "title": title,
                    "company": entry.get("author", ""),
                    "location": "See listing (not machine-checked)",
                    "salary": salary_note,
                    "url": entry.get("link", ""),
                    "posted": entry.get("published", ""),
                })
    except Exception as e:
        print(f"[Remotive] error: {e}")
    return jobs


def fetch_jobicy():
    jobs = []
    try:
        r = requests.get("https://jobicy.com/api/v2/remote-jobs?count=50", timeout=15)
        data = r.json()
        for item in data.get("jobs", []):
            title = item.get("jobTitle", "")
            desc = item.get("jobExcerpt", "") or item.get("jobDescription", "") or ""
            location = item.get("jobGeo", "") or ""
            ok, salary_note = passes_filters(title, desc, location, item.get("annualSalaryMin"))
            if ok:
                jobs.append({
                    "source": "Jobicy", "title": title,
                    "company": item.get("companyName", ""),
                    "location": location or "Not specified",
                    "salary": salary_note,
                    "url": item.get("url", ""),
                    "posted": item.get("pubDate", ""),
                })
    except Exception as e:
        print(f"[Jobicy] error: {e}")
    return jobs


def fetch_arbeitnow():
    jobs = []
    try:
        r = requests.get("https://www.arbeitnow.com/api/job-board-api", timeout=15)
        data = r.json()
        for item in data.get("data", []):
            if not item.get("remote"):
                continue
            title = item.get("title", "")
            desc = item.get("description", "") or ""
            tags = " ".join(item.get("tags", []) or [])
            location = item.get("location", "") or ""
            ok, salary_note = passes_filters(title, f"{desc} {tags}", location, None)
            if ok:
                jobs.append({
                    "source": "Arbeitnow", "title": title,
                    "company": item.get("company_name", ""),
                    "location": location or "Remote",
                    "salary": salary_note,
                    "url": item.get("url", ""),
                    "posted": item.get("created_at", ""),
                })
    except Exception as e:
        print(f"[Arbeitnow] error: {e}")
    return jobs


# ============ MAIN ============

def load_seen():
    try:
        with open(SEEN_FILE, "r", encoding="utf-8") as f:
            return set(json.load(f))
    except (FileNotFoundError, json.JSONDecodeError):
        return set()


def save_seen(seen_keys):
    with open(SEEN_FILE, "w", encoding="utf-8") as f:
        json.dump(sorted(seen_keys), f, indent=2)


def main():
    all_jobs = fetch_remoteok() + fetch_remotive() + fetch_jobicy() + fetch_arbeitnow()

    previously_seen = load_seen()

    seen_today = set()
    new_jobs = []
    for j in all_jobs:
        key = f"{j['title'].strip().lower()}|{j['company'].strip().lower()}"
        if key in seen_today:
            continue  # duplicate within this same run (e.g. cross-posted)
        seen_today.add(key)
        if key not in previously_seen:
            new_jobs.append(j)

    with open(OUTPUT_FILE, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["source", "title", "company", "location", "salary", "url", "posted"])
        writer.writeheader()
        writer.writerows(new_jobs)

    # Remember everything seen today (old + new) so tomorrow's run only shows fresh ones
    save_seen(previously_seen | seen_today)

    print(f"\n{len(new_jobs)} NEW matching jobs today (not seen in previous runs). Saved to {OUTPUT_FILE}\n")
    for j in new_jobs:
        print(f"[{j['source']}] {j['title']} @ {j['company']} | {j['salary']} | {j['url']}")
    if not new_jobs:
        print("No new matches today — the filters are strict by design, this is expected some days.")


if __name__ == "__main__":
    main()
