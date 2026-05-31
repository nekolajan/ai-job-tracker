"""
scraper/scrape.py

Fetches job listings from Remotive, The Muse, jobs.cz, LinkedIn, and Jobstack.it.
Saves deduplicated results to data/raw_jobs.json.
"""

import json
import hashlib
import time
from pathlib import Path
from datetime import datetime, timezone

import requests
from bs4 import BeautifulSoup

from config import (
    SEARCH_KEYWORDS, SOURCES, DATA_DIR, RAW_JOBS_FILENAME,
    DESCRIPTION_MAX_CHARS, RELEVANT_TITLE_KEYWORDS,
)

RAW_JOBS_PATH = Path(__file__).parent.parent / DATA_DIR / RAW_JOBS_FILENAME

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
}


# ── helpers ───────────────────────────────────────────────────────────────────

def make_id(url: str) -> str:
    return hashlib.md5(url.encode()).hexdigest()[:12]


def is_relevant(title: str) -> bool:
    t = title.lower()
    return any(kw in t for kw in RELEVANT_TITLE_KEYWORDS)


def load_existing(path: Path) -> dict:
    if path.exists():
        jobs = json.loads(path.read_text(encoding="utf-8"))
        return {j["job_id"]: j for j in jobs}
    return {}


def save_jobs(path: Path, jobs: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(list(jobs.values()), indent=2, ensure_ascii=False),
        encoding="utf-8",
    )


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


# ── source: Remotive ─────────────────────────────────────────────────────────

def fetch_remotive() -> list[dict]:
    cfg = SOURCES["remotive"]
    if not cfg.enabled:
        return []

    results = []
    for kw in SEARCH_KEYWORDS:
        try:
            resp = requests.get(
                "https://remotive.com/api/remote-jobs",
                params={"search": kw, "limit": cfg.max_results_per_keyword},
                timeout=15,
            )
            resp.raise_for_status()
            for job in resp.json().get("jobs", []):
                title = job.get("title", "")
                if not is_relevant(title):
                    continue
                results.append({
                    "job_id":      make_id(job["url"]),
                    "title":       title,
                    "company":     job.get("company_name", ""),
                    "location":    job.get("candidate_required_location", "Worldwide"),
                    "description": job.get("description", "")[:DESCRIPTION_MAX_CHARS],
                    "url":         job.get("url", ""),
                    "source":      "remotive",
                    "salary":      job.get("salary", ""),
                    "scraped_at":  _now(),
                })
            time.sleep(cfg.request_delay_seconds)
        except Exception as e:
            print(f"[remotive] error for '{kw}': {e}")
    return results


# ── source: The Muse ─────────────────────────────────────────────────────────

def fetch_the_muse() -> list[dict]:
    cfg = SOURCES["the_muse"]
    if not cfg.enabled:
        return []

    results = []
    categories = ["Data Science", "Data Analytics", "Business Intelligence"]
    try:
        for cat in categories:
            resp = requests.get(
                "https://www.themuse.com/api/public/jobs",
                params={"category": cat, "level": "Senior Level", "page": 0},
                timeout=15,
            )
            resp.raise_for_status()
            for job in resp.json().get("results", []):
                locations = [loc.get("name", "") for loc in job.get("locations", [])]
                url = job.get("refs", {}).get("landing_page", "")
                if not url:
                    continue
                results.append({
                    "job_id":      make_id(url),
                    "title":       job.get("name", ""),
                    "company":     job.get("company", {}).get("name", ""),
                    "location":    ", ".join(locations) if locations else "Remote",
                    "description": BeautifulSoup(
                        job.get("contents", ""), "html.parser"
                    ).get_text()[:DESCRIPTION_MAX_CHARS],
                    "url":         url,
                    "source":      "the_muse",
                    "salary":      "",
                    "scraped_at":  _now(),
                })
            time.sleep(cfg.request_delay_seconds)
    except Exception as e:
        print(f"[the_muse] error: {e}")
    return results


# ── source: jobs.cz ──────────────────────────────────────────────────────────

def fetch_jobs_cz() -> list[dict]:
    cfg = SOURCES["jobs_cz"]
    if not cfg.enabled:
        return []

    results = []
    for kw in SEARCH_KEYWORDS:
        try:
            resp = requests.get(
                "https://www.jobs.cz/prace/",
                params={"q[]": kw},
                headers={**_HEADERS, "Accept-Language": "cs,en;q=0.9"},
                timeout=15,
            )
            resp.raise_for_status()
            soup = BeautifulSoup(resp.text, "html.parser")

            for card in soup.select("article.SearchResultCard")[:cfg.max_results_per_keyword]:
                title_el = card.select_one(".SearchResultCard__title a")
                logo_el  = card.select_one(".CompanyLogo img")
                footer   = card.select(".SearchResultCard__footerItem")

                if not title_el:
                    continue

                title = title_el.get_text(strip=True)
                if not is_relevant(title):
                    continue

                url     = title_el.get("href", "")
                company = logo_el["alt"] if logo_el and logo_el.get("alt") else (
                    footer[0].get_text(strip=True) if footer else ""
                )
                location = footer[1].get_text(strip=True) if len(footer) > 1 else "Praha"

                salary_el = card.select_one(".Tag--success")
                salary = salary_el.get_text(strip=True) if salary_el else ""

                results.append({
                    "job_id":      make_id(url),
                    "title":       title,
                    "company":     company,
                    "location":    location,
                    "description": "",
                    "url":         url,
                    "source":      "jobs_cz",
                    "salary":      salary,
                    "scraped_at":  _now(),
                })
            time.sleep(cfg.request_delay_seconds)
        except Exception as e:
            print(f"[jobs_cz] error for '{kw}': {e}")
    return results


# ── source: LinkedIn (public, no login) ──────────────────────────────────────

def fetch_linkedin() -> list[dict]:
    cfg = SOURCES["linkedin"]
    if not cfg.enabled:
        return []

    searches = [
        ("data analyst BI", "Worldwide", "2"),
        ("data analyst BI", "Prague", ""),
        ("business intelligence", "Worldwide", "2"),
    ]

    results = []
    for keywords, location, remote in searches:
        try:
            params = {
                "keywords": keywords,
                "location": location,
                "f_E":      "4",
                "sortBy":   "DD",
            }
            if remote:
                params["f_WT"] = remote

            resp = requests.get(
                "https://www.linkedin.com/jobs/search/",
                params=params,
                headers=_HEADERS,
                timeout=15,
            )
            resp.raise_for_status()
            soup = BeautifulSoup(resp.text, "html.parser")

            for card in soup.select(".jobs-search__results-list li")[:cfg.max_results_per_keyword]:
                title_el    = card.select_one(".base-search-card__title")
                company_el  = card.select_one(".base-search-card__subtitle")
                location_el = card.select_one(".job-search-card__location")
                link_el     = card.select_one("a.base-card__full-link")

                if not title_el or not link_el:
                    continue

                title = title_el.get_text(strip=True)
                if not is_relevant(title):
                    continue

                url = link_el["href"].split("?")[0]
                results.append({
                    "job_id":      make_id(url),
                    "title":       title,
                    "company":     company_el.get_text(strip=True) if company_el else "",
                    "location":    location_el.get_text(strip=True) if location_el else location,
                    "description": "",
                    "url":         url,
                    "source":      "linkedin",
                    "salary":      "",
                    "scraped_at":  _now(),
                })
            time.sleep(cfg.request_delay_seconds)
        except Exception as e:
            print(f"[linkedin] error for '{keywords}' / '{location}': {e}")
    return results


# ── source: Jobstack.it ───────────────────────────────────────────────────────

# Role/contract tags that appear in the link text — used to find title boundary
_JOBSTACK_TAGS = {
    "Specialista Data", "Analytik", "Procesní analytik", "Data developer",
    "Freelancer", "HPP", "Hybrid", "Remote", "Junior", "Medior", "Senior",
    "Expert", "ML/AI", "ETL", "DevOps", "Elastic", "Architekt",
}

def _parse_jobstack_link(link) -> dict | None:
    """
    Parse a single job link from jobstack.it listing page.
    Link text format (space-separated):
      <title>  <role tag(s)>  <contract>  <work mode>  <seniority>  <company>  <location>  <salary>  [<company repeat>]
    """
    href = link.get("href", "")
    if not href:
        return None

    BASE_URL = "https://www.jobstack.it"
    full_url = href if href.startswith("http") else f"{BASE_URL}{href}"

    # Split text into non-empty parts
    raw = link.get_text(separator="\n", strip=True)
    parts = [p.strip() for p in raw.split("\n") if p.strip()]

    if not parts:
        return None

    # Title = everything before the first known role/contract tag
    title_parts = []
    rest_start = 0
    for i, part in enumerate(parts):
        if any(tag in part for tag in _JOBSTACK_TAGS):
            rest_start = i
            break
        title_parts.append(part)
        rest_start = i + 1

    title = " ".join(title_parts).strip()
    if not title or len(title) < 3:
        title = parts[0]  # fallback to first part

    rest = parts[rest_start:]

    # Salary — contains "Kč", "Navrhni", "Nadstandardní"
    salary = ""
    salary_keywords = ["Kč", "Navrhni", "Nadstandardní", "mzdu"]
    for part in rest:
        if any(kw in part for kw in salary_keywords):
            salary = part
            break

    # Location — contains city names or work mode
    location = "Praha"
    location_keywords = ["Praha", "Brno", "Ostrava", "Plzeň", "Liberec",
                         "Olomouc", "Zlín", "Remote", "remote", "Bratislava",
                         "Wroclaw", "Poland", "Slovakia", "EU", "Homeoffice"]
    for part in rest:
        if any(kw in part for kw in location_keywords):
            location = part
            break

    # Company — typically right before the location or salary
    # Find parts that are NOT tags, NOT salary, NOT location
    skip = set(_JOBSTACK_TAGS) | {"HPP", "Hybrid", "Remote", "Junior",
                                   "Medior", "Senior", "Expert", "Freelancer"}
    company_candidates = [
        p for p in rest
        if not any(tag in p for tag in skip)
        and not any(kw in p for kw in salary_keywords)
        and len(p) > 2
    ]
    company = company_candidates[0] if company_candidates else ""

    return {
        "title":    title,
        "company":  company,
        "location": location,
        "salary":   salary,
        "url":      full_url,
    }


def fetch_jobstack() -> list[dict]:
    """
    Scrapes jobstack.it Data (BI, DWH, BigData) + Analytik categories.
    """
    BASE_URL    = "https://www.jobstack.it"
    CATEGORIES  = [
        "/it-jobs/specialista-data-bi-dwh-bigdata",
        "/it-jobs/analytik",
    ]
    results  = []
    seen_ids = set()

    for category in CATEGORIES:
        page     = 1
        max_pages = 5

        while page <= max_pages:
            try:
                url = f"{BASE_URL}{category}" if page == 1 else f"{BASE_URL}{category}?page={page}"
                resp = requests.get(
                    url,
                    headers={**_HEADERS, "Accept-Language": "cs,en;q=0.9"},
                    timeout=15,
                )
                resp.raise_for_status()
                soup = BeautifulSoup(resp.text, "html.parser")

                job_links = soup.select("ul li a[href*='/it-job/']")
                if not job_links:
                    break

                new_on_page = 0
                for link in job_links:
                    parsed = _parse_jobstack_link(link)
                    if not parsed:
                        continue

                    job_id = make_id(parsed["url"])
                    if job_id in seen_ids:
                        continue
                    seen_ids.add(job_id)

                    if not is_relevant(parsed["title"]):
                        continue

                    results.append({
                        "job_id":      job_id,
                        "title":       parsed["title"],
                        "company":     parsed["company"],
                        "location":    parsed["location"],
                        "description": "",
                        "url":         parsed["url"],
                        "source":      "jobstack",
                        "salary":      parsed["salary"],
                        "scraped_at":  _now(),
                    })
                    new_on_page += 1

                print(f"[jobstack] {category} page {page}: {new_on_page} jobs")

                next_link = soup.select_one(f"a[href*='page={page + 1}']")
                if not next_link:
                    break

                page += 1
                time.sleep(2.0)

            except Exception as e:
                print(f"[jobstack] error on {category} page {page}: {e}")
                break

    return results


# ── main ─────────────────────────────────────────────────────────────────────

def scrape_all() -> None:
    existing = load_existing(RAW_JOBS_PATH)
    before = len(existing)

    sources = [
        ("remotive",  fetch_remotive),
        ("the_muse",  fetch_the_muse),
        ("jobs_cz",   fetch_jobs_cz),
        ("linkedin",  fetch_linkedin),
        ("jobstack",  fetch_jobstack),
    ]

    for name, fetch_fn in sources:
        print(f"[scraper] fetching {name}...")
        jobs = fetch_fn()
        new = 0
        for job in jobs:
            if job["job_id"] not in existing:
                existing[job["job_id"]] = job
                new += 1
        print(f"[scraper] {name}: {new} new jobs (skipped {len(jobs) - new} duplicates)")

    save_jobs(RAW_JOBS_PATH, existing)
    print(f"[scraper] done. total: {len(existing)} jobs (+{len(existing) - before} new)")


if __name__ == "__main__":
    scrape_all()