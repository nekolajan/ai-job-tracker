"""
scraper/scrape.py

Fetches job listings from:
  - Remotive (API)
  - The Muse (API)
  - jobs.cz (scrape)
  - LinkedIn (scrape)
  - Jobstack.it (scrape)
  - Himalayas (API)        ← new
  - RemoteOK (API)         ← new
  - StartupJobs.cz (scrape)
  - Company career boards: Greenhouse / Lever / Ashby (API, see scraper/ats.py)

Filters spam, skips reposts of postings already stored (same title + company),
fetches missing descriptions for new jobs (scraper/details.py) and saves the
result to data/raw_jobs.json.
"""

import json
import time
from pathlib import Path
from datetime import datetime, timedelta, timezone

import requests
from bs4 import BeautifulSoup

from config import (
    SEARCH_KEYWORDS, SOURCES, DATA_DIR, RAW_JOBS_FILENAME, DESCRIPTION_STORE_MAX_CHARS,
    LINKEDIN_SEARCHES, LINKEDIN_TIME_FILTER, DEDUP_WINDOW_DAYS, DETAIL_BACKFILL_DAYS,
)
from scraper.utils import (
    HEADERS as _HEADERS, make_id, canonical_url, is_relevant, is_allowed,
    fingerprint, now as _now, to_date,
)
from scraper.ats import fetch_ats
from scraper.details import enrich_descriptions, recent_jobs

RAW_JOBS_PATH = Path(__file__).parent.parent / DATA_DIR / RAW_JOBS_FILENAME


# ── helpers ───────────────────────────────────────────────────────────────────

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


def _strip_html(html: str) -> str:
    return BeautifulSoup(html or "", "html.parser").get_text()[:DESCRIPTION_STORE_MAX_CHARS]


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
                    "description": job.get("description", "")[:DESCRIPTION_STORE_MAX_CHARS],
                    "url":         job.get("url", ""),
                    "source":      "remotive",
                    "salary":      job.get("salary", ""),
                    "posted_at":   to_date(job.get("publication_date")),
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
                    "description": _strip_html(job.get("contents", "")),
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

                url     = canonical_url(title_el.get("href", ""))
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


# ── source: LinkedIn ─────────────────────────────────────────────────────────

def fetch_linkedin() -> list[dict]:
    cfg = SOURCES["linkedin"]
    if not cfg.enabled:
        return []

    results = []
    for keywords, location, remote in LINKEDIN_SEARCHES:
        try:
            params = {
                "keywords": keywords,
                "location": location,
                "f_E":      "4",
                "sortBy":   "DD",
                "f_TPR":    LINKEDIN_TIME_FILTER,
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
                time_el = card.select_one("time[datetime]")
                results.append({
                    "job_id":      make_id(url),
                    "title":       title,
                    "company":     company_el.get_text(strip=True) if company_el else "",
                    "location":    location_el.get_text(strip=True) if location_el else location,
                    "description": "",
                    "url":         url,
                    "source":      "linkedin",
                    "salary":      "",
                    "posted_at":   to_date(time_el["datetime"]) if time_el else None,
                    "scraped_at":  _now(),
                })
            time.sleep(cfg.request_delay_seconds)
        except Exception as e:
            print(f"[linkedin] error for '{keywords}' / '{location}': {e}")
    return results


# ── source: Jobstack.it ───────────────────────────────────────────────────────

_JOBSTACK_TAGS = {
    "Specialista Data", "Analytik", "Procesní analytik", "Data developer",
    "Freelancer", "HPP", "Hybrid", "Remote", "Junior", "Medior", "Senior",
    "Expert", "ML/AI", "ETL", "DevOps", "Elastic", "Architekt",
}

def _parse_jobstack_link(link) -> dict | None:
    href = link.get("href", "")
    if not href:
        return None

    BASE_URL = "https://www.jobstack.it"
    full_url = href if href.startswith("http") else f"{BASE_URL}{href}"

    raw   = link.get_text(separator="\n", strip=True)
    parts = [p.strip() for p in raw.split("\n") if p.strip()]

    if not parts:
        return None

    title_parts = []
    rest_start  = 0
    for i, part in enumerate(parts):
        if any(tag in part for tag in _JOBSTACK_TAGS):
            rest_start = i
            break
        title_parts.append(part)
        rest_start = i + 1

    title = " ".join(title_parts).strip() or parts[0]
    rest  = parts[rest_start:]

    salary = ""
    for part in rest:
        if any(kw in part for kw in ["Kč", "Navrhni", "Nadstandardní", "mzdu"]):
            salary = part
            break

    location = "Praha"
    for part in rest:
        if any(city in part for city in ["Praha", "Brno", "Ostrava", "Plzeň", "Liberec",
                                          "Olomouc", "Remote", "remote", "Homeoffice"]):
            location = part
            break

    skip = set(_JOBSTACK_TAGS) | {"HPP", "Hybrid", "Remote", "Junior", "Medior",
                                    "Senior", "Expert", "Freelancer"}
    company_candidates = [
        p for p in rest
        if not any(tag in p for tag in skip)
        and not any(kw in p for kw in ["Kč", "Navrhni", "Nadstandardní", "mzdu"])
        and len(p) > 2
    ]
    company = company_candidates[0] if company_candidates else ""

    return {"title": title, "company": company, "location": location,
            "salary": salary, "url": full_url}


def fetch_jobstack() -> list[dict]:
    BASE_URL   = "https://www.jobstack.it"
    CATEGORIES = [
        "/it-jobs/specialista-data-bi-dwh-bigdata",
        "/it-jobs/analytik",
    ]
    results  = []
    seen_ids = set()

    for category in CATEGORIES:
        page      = 1
        max_pages = 5

        while page <= max_pages:
            try:
                url  = f"{BASE_URL}{category}" if page == 1 else f"{BASE_URL}{category}?page={page}"
                resp = requests.get(url, headers={**_HEADERS, "Accept-Language": "cs,en;q=0.9"}, timeout=15)
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
                    if job_id in seen_ids or not is_relevant(parsed["title"]):
                        continue
                    seen_ids.add(job_id)
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

                if not soup.select_one(f"a[href*='page={page + 1}']"):
                    break
                page += 1
                time.sleep(2.0)

            except Exception as e:
                print(f"[jobstack] error on {category} page {page}: {e}")
                break

    return results


# ── source: Himalayas (API) ───────────────────────────────────────────────────

def fetch_himalayas() -> list[dict]:
    """
    Uses Himalayas public JSON API.
    Searches for each keyword, remote-only, returns up to max_results_per_keyword.
    """
    cfg = SOURCES.get("himalayas")
    if not cfg or not cfg.enabled:
        return []

    results  = []
    seen_ids = set()

    for kw in SEARCH_KEYWORDS:
        try:
            resp = requests.get(
                "https://himalayas.app/jobs/api",
                params={"q": kw, "remote": "true", "limit": cfg.max_results_per_keyword},
                headers=_HEADERS,
                timeout=15,
            )
            resp.raise_for_status()
            data = resp.json()

            for job in data.get("jobs", []):
                title = job.get("title", "")
                if not is_relevant(title):
                    continue

                url    = job.get("applicationLink") or job.get("guid", "")
                job_id = make_id(url)
                if job_id in seen_ids:
                    continue
                seen_ids.add(job_id)

                # Build salary string
                salary = ""
                min_s  = job.get("minSalary")
                max_s  = job.get("maxSalary")
                curr   = job.get("currency", "USD")
                if min_s and max_s:
                    salary = f"{curr} {min_s:,} – {max_s:,}"
                elif min_s:
                    salary = f"{curr} {min_s:,}+"

                # Location from restrictions list
                restrictions = job.get("locationRestrictions") or []
                location = ", ".join(restrictions) if restrictions else "Worldwide (Remote)"

                results.append({
                    "job_id":      job_id,
                    "title":       title,
                    "company":     job.get("companyName", ""),
                    "location":    location,
                    "description": _strip_html(job.get("description", "")),
                    "url":         url,
                    "source":      "himalayas",
                    "salary":      salary,
                    "posted_at":   to_date(job.get("pubDate")),
                    "scraped_at":  _now(),
                })

            time.sleep(cfg.request_delay_seconds)

        except Exception as e:
            print(f"[himalayas] error for '{kw}': {e}")

    return results


# ── source: RemoteOK (API) ────────────────────────────────────────────────────

def fetch_remoteok() -> list[dict]:
    """
    Uses RemoteOK public JSON API.
    Note: RemoteOK requires a User-Agent that isn't a bot; adding a small delay.
    """
    cfg = SOURCES.get("remoteok")
    if not cfg or not cfg.enabled:
        return []

    results  = []
    seen_ids = set()
    tags     = ["data-analyst", "bi", "data-engineer", "business-intelligence", "analytics"]

    for tag in tags:
        try:
            resp = requests.get(
                f"https://remoteok.com/api?tag={tag}",
                headers={
                    **_HEADERS,
                    "Accept": "application/json",
                },
                timeout=15,
            )
            resp.raise_for_status()
            data = resp.json()

            # First item is metadata, skip it
            jobs = [j for j in data if isinstance(j, dict) and "position" in j]

            for job in jobs[:cfg.max_results_per_keyword]:
                title = job.get("position", "")
                if not is_relevant(title):
                    continue

                url    = job.get("url", "")
                if not url:
                    continue
                job_id = make_id(url)
                if job_id in seen_ids:
                    continue
                seen_ids.add(job_id)

                salary = ""
                if job.get("salary_min") and job.get("salary_max"):
                    salary = f"USD {job['salary_min']:,} – {job['salary_max']:,}"

                results.append({
                    "job_id":      job_id,
                    "title":       title,
                    "company":     job.get("company", ""),
                    "location":    "Worldwide (Remote)",
                    "description": BeautifulSoup(job.get("description", ""), "html.parser").get_text()[:DESCRIPTION_STORE_MAX_CHARS],
                    "url":         url,
                    "source":      "remoteok",
                    "salary":      salary,
                    "posted_at":   to_date(job.get("date") or job.get("epoch")),
                    "scraped_at":  _now(),
                })

            time.sleep(cfg.request_delay_seconds)

        except Exception as e:
            print(f"[remoteok] error for tag '{tag}': {e}")

    return results


# ── source: StartupJobs.cz (scrape) ──────────────────────────────────────────

def fetch_startupjobs() -> list[dict]:
    """
    Scrapes startupjobs.cz for Czech/Slovak tech positions.
    Searches data/analytics related positions.
    """
    cfg = SOURCES.get("startupjobs")
    if not cfg or not cfg.enabled:
        return []

    BASE_URL = "https://www.startupjobs.cz"
    results  = []
    seen_ids = set()

    search_terms = ["data analyst", "business intelligence", "data engineer", "analytik"]

    for term in search_terms:
        try:
            resp = requests.get(
                f"{BASE_URL}/nabidky",
                params={"q": term},
                headers={**_HEADERS, "Accept-Language": "cs,en;q=0.9"},
                timeout=15,
            )
            resp.raise_for_status()
            soup = BeautifulSoup(resp.text, "html.parser")

            # Job detail links are /nabidka/<id>/<slug> (singular); the listing is /nabidky
            cards = [
                c for c in soup.select("article, div.offer-card, [data-id]")
                if c.select_one("a[href*='/nabidka/']")
            ]
            if not cards:
                cards = soup.select("a[href*='/nabidka/']")
            if not cards:
                print(f"[startupjobs] no job links for '{term}' – page is likely rendered "
                      f"by JavaScript; consider disabling this source")

            for card in cards[:cfg.max_results_per_keyword]:
                # Handle both article cards and direct links
                if card.name == "a":
                    link_el = card
                    title   = card.get_text(strip=True)
                    url     = card.get("href", "")
                else:
                    link_el = card.select_one("a[href*='/nabidka/']")
                    if not link_el:
                        continue
                    title = (
                        card.select_one("h2, h3, .title, .offer-title, [class*='title']") or link_el
                    ).get_text(strip=True)
                    url = link_el.get("href", "")

                if not url or not title or not is_relevant(title):
                    continue

                full_url = canonical_url(url if url.startswith("http") else f"{BASE_URL}{url}")
                job_id   = make_id(full_url)
                if job_id in seen_ids:
                    continue
                seen_ids.add(job_id)

                company_el  = card.select_one(".company, .company-name, [class*='company']") if card.name != "a" else None
                location_el = card.select_one(".location, [class*='location']") if card.name != "a" else None
                salary_el   = card.select_one(".salary, [class*='salary']") if card.name != "a" else None

                results.append({
                    "job_id":      job_id,
                    "title":       title,
                    "company":     company_el.get_text(strip=True) if company_el else "",
                    "location":    location_el.get_text(strip=True) if location_el else "Czech Republic",
                    "description": "",
                    "url":         full_url,
                    "source":      "startupjobs",
                    "salary":      salary_el.get_text(strip=True) if salary_el else "",
                    "scraped_at":  _now(),
                })

            time.sleep(cfg.request_delay_seconds)

        except Exception as e:
            print(f"[startupjobs] error for '{term}': {e}")

    return results


# ── main ─────────────────────────────────────────────────────────────────────

def recent_fingerprints(existing: dict, days: int = DEDUP_WINDOW_DAYS) -> set:
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    return {fingerprint(j) for j in existing.values() if j.get("scraped_at", "") >= cutoff}


def merge_new(existing: dict, jobs: list[dict], seen_fps: set) -> tuple[list[dict], dict]:
    """Add jobs that pass filters and are neither the same URL nor the same
    title+company as a recently stored posting. Returns (added, skip counts)."""
    added, skipped = [], {"duplicate": 0, "repost": 0, "filtered": 0}
    for job in jobs:
        if not is_allowed(job):
            skipped["filtered"] += 1
            continue
        if job["job_id"] in existing:
            skipped["duplicate"] += 1
            if job.get("posted_at") and not existing[job["job_id"]].get("posted_at"):
                existing[job["job_id"]]["posted_at"] = job["posted_at"]   # date learned later
            continue
        fp = fingerprint(job)
        if fp in seen_fps:
            skipped["repost"] += 1
            continue
        existing[job["job_id"]] = job
        seen_fps.add(fp)
        added.append(job)
    return added, skipped


def scrape_all() -> None:
    existing = load_existing(RAW_JOBS_PATH)
    before   = len(existing)
    seen_fps = recent_fingerprints(existing)

    # ATS first: the same job found later on LinkedIn/jobs.cz is then skipped as a
    # repost, and the ATS version already carries the full description.
    sources = [
        ("ats",         fetch_ats),
        ("remotive",    fetch_remotive),
        ("the_muse",    fetch_the_muse),
        ("jobs_cz",     fetch_jobs_cz),
        ("linkedin",    fetch_linkedin),
        ("jobstack",    fetch_jobstack),
        ("himalayas",   fetch_himalayas),
        ("remoteok",    fetch_remoteok),
        ("startupjobs", fetch_startupjobs),
    ]

    new_jobs = []
    for name, fetch_fn in sources:
        print(f"[scraper] fetching {name}...")
        try:
            jobs = fetch_fn()
            added, skipped = merge_new(existing, jobs, seen_fps)
            new_jobs.extend(added)
            print(f"[scraper] {name}: {len(added)} new | skipped {skipped}")
        except Exception as e:
            print(f"[scraper] {name}: FAILED — {e}")

    # Descriptions for today's new jobs and for recent ones that are still missing
    # one (e.g. LinkedIn answered 429 yesterday) – newest first, capped per run.
    try:
        enrich_descriptions(recent_jobs(list(existing.values()), DETAIL_BACKFILL_DAYS))
    except Exception as e:
        print(f"[details] FAILED — {e}")

    save_jobs(RAW_JOBS_PATH, existing)
    print(f"[scraper] done. total: {len(existing)} jobs (+{len(existing) - before} new)")


if __name__ == "__main__":
    scrape_all()