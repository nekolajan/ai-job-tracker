"""
scraper/details.py

Fills in missing job descriptions for listing-only sources (jobs.cz, LinkedIn,
Jobstack) by opening each job's detail page. Only new jobs are fetched, with a
per-run cap and polite delays, so the boards are not hammered.

Extraction order:
  1. schema.org JobPosting in <script type="application/ld+json"> (most boards)
  2. site-specific selectors (LinkedIn guest API, jobs.cz)
  3. generic fallback: the page block with the most paragraph / list text

Backfill jobs without a (complete) description, newest first, only those scraped
in the last config.DETAIL_BACKFILL_DAYS days:
  python -m scraper.details --backfill 100
  python -m scraper.details --backfill 100 --days 14
"""

import json
import re
import sys
import time

import requests
from bs4 import BeautifulSoup

from datetime import datetime, timedelta, timezone

from config import (
    MAX_DETAIL_FETCHES_PER_RUN, DESCRIPTION_STORE_MAX_CHARS, DETAIL_BACKFILL_DAYS,
)
from scraper.utils import HEADERS, html_to_text, is_boilerplate, needs_description

TIMEOUT = 20
MAX_CONSECUTIVE_ERRORS = 3
_DELAY = {"linkedin": 4.0, "jobs_cz": 2.0, "jobstack": 2.0}

_SITE_SELECTORS = {
    "linkedin": [".show-more-less-html__markup", ".description__text"],
    "jobs_cz": [
        "[data-test='jd-body-richtext']", "[data-jobad='body']",
        ".JobDescriptionSection", ".RichContent", ".typography-body-large-text-regular",
    ],
    "jobstack": [".job-description", ".jobDetail__description", "article"],
}


def _from_json_ld(soup: BeautifulSoup) -> str:
    for script in soup.find_all("script", type="application/ld+json"):
        try:
            data = json.loads(script.string or "")
        except (json.JSONDecodeError, TypeError):
            continue
        items = data if isinstance(data, list) else data.get("@graph", [data])
        for item in items:
            if isinstance(item, dict) and item.get("@type") == "JobPosting":
                desc = html_to_text(item.get("description", ""))
                if len(desc) > 200:
                    return desc
    return ""


def _from_selectors(soup: BeautifulSoup, source: str) -> str:
    for sel in _SITE_SELECTORS.get(source, []):
        el = soup.select_one(sel)
        if el:
            text = html_to_text(str(el))
            if len(text) > 200:
                return text
    return ""


_NOISE = re.compile(r"footer|cookie|copyright|consent|navbar|menu", re.I)


def _largest_text_block(soup: BeautifulSoup) -> str:
    for tag in soup(["script", "style", "nav", "header", "footer", "form", "noscript", "iframe"]):
        tag.decompose()
    for tag in soup.find_all(attrs={"class": _NOISE}) + soup.find_all(attrs={"id": _NOISE}):
        tag.decompose()
    best, best_len = None, 0
    for el in soup.find_all(["article", "section", "div", "main"]):
        direct = el.find_all(["p", "li"], recursive=False) + [
            c for child in el.find_all(["ul", "ol"], recursive=False)
            for c in child.find_all("li", recursive=False)
        ]
        length = sum(len(x.get_text(strip=True)) for x in direct)
        if length > best_len:
            best, best_len = el, length
    return html_to_text(str(best)) if best is not None and best_len > 200 else ""


def extract_description(page_html: str, source: str) -> str:
    soup = BeautifulSoup(page_html, "html.parser")
    text = _from_json_ld(soup) or _from_selectors(soup, source) or _largest_text_block(soup)
    if is_boilerplate(text):
        return ""
    return text[:DESCRIPTION_STORE_MAX_CHARS]


def _detail_url(job: dict) -> str:
    url = job.get("url", "")
    if job.get("source") == "linkedin":
        # Guest endpoint returns a light HTML fragment with the full description
        m = re.search(r"(\d{8,})/?$", url.rstrip("/"))
        if m:
            return f"https://www.linkedin.com/jobs-guest/jobs/api/jobPosting/{m.group(1)}"
    return url


def fetch_description(job: dict) -> str:
    resp = requests.get(
        _detail_url(job),
        headers={**HEADERS, "Accept-Language": "cs,en;q=0.9"},
        timeout=TIMEOUT,
    )
    resp.raise_for_status()
    return extract_description(resp.text, job.get("source", ""))


def enrich_descriptions(jobs: list[dict], limit: int = MAX_DETAIL_FETCHES_PER_RUN) -> int:
    """Fetch descriptions in place for jobs from DETAIL_SOURCES that have none
    (or only boilerplate / a text cut at the old storage limit).

    Sources are interleaved so one big source (LinkedIn) cannot use up the whole
    limit, and a source is skipped for the rest of the run after
    MAX_CONSECUTIVE_ERRORS failures in a row (rate limiting / blocking).

    A 404 / 410 means the posting was taken down, not that the site is blocking us:
    the job gets `expired_at` and is never fetched again, and it does not count
    towards the error limit. A page that loads but has no usable text gets
    `detail_attempts` +1 and is given up after config.MAX_DETAIL_ATTEMPTS.
    """
    queues: dict[str, list[dict]] = {}
    for j in jobs:
        if needs_description(j):
            queues.setdefault(j["source"], []).append(j)

    todo = []
    while len(todo) < limit and any(queues.values()):
        for q in queues.values():
            if q and len(todo) < limit:
                todo.append(q.pop(0))

    filled, expired, errors, blocked = 0, 0, {}, set()
    for job in todo:
        source = job.get("source")
        if source in blocked:
            continue
        try:
            desc = fetch_description(job)
            errors[source] = 0
            if desc:
                job["description"] = desc
                job.pop("detail_attempts", None)
                filled += 1
            else:
                job["detail_attempts"] = job.get("detail_attempts", 0) + 1
                if is_boilerplate(job.get("description", "")):
                    job["description"] = ""
        except requests.HTTPError as e:
            status = e.response.status_code if e.response is not None else None
            if status in (404, 410):
                job["expired_at"] = datetime.now(timezone.utc).isoformat()
                expired += 1
            else:
                errors[source] = errors.get(source, 0) + 1
                print(f"[details] {source} {job.get('url')}: {e}")
                if errors[source] >= MAX_CONSECUTIVE_ERRORS or status == 429:
                    blocked.add(source)
                    print(f"[details] {source}: too many errors, skipping it for this run")
        except Exception as e:
            errors[source] = errors.get(source, 0) + 1
            print(f"[details] {source} {job.get('url')}: {e}")
            if errors[source] >= MAX_CONSECUTIVE_ERRORS or "429" in str(e):
                blocked.add(source)
                print(f"[details] {source}: too many errors, skipping it for this run")
        time.sleep(_DELAY.get(source, 2.0))
    print(f"[details] filled {filled}/{len(todo)} descriptions, {expired} postings expired"
          + (f" (skipped: {', '.join(sorted(blocked))})" if blocked else ""))
    return filled


def recent_jobs(jobs: list[dict], days: int) -> list[dict]:
    """Jobs scraped within the last `days` days, newest first."""
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    recent = [j for j in jobs if j.get("scraped_at", "") >= cutoff]
    return sorted(recent, key=lambda j: j.get("scraped_at", ""), reverse=True)


def _arg(flag: str, default: int) -> int:
    return int(sys.argv[sys.argv.index(flag) + 1]) if flag in sys.argv else default


if __name__ == "__main__":
    from scraper.scrape import RAW_JOBS_PATH, load_existing, save_jobs

    limit = _arg("--backfill", 50)
    days = _arg("--days", DETAIL_BACKFILL_DAYS)
    existing = load_existing(RAW_JOBS_PATH)
    candidates = recent_jobs(list(existing.values()), days)
    waiting = sum(1 for j in candidates if needs_description(j))
    print(f"[details] {waiting} jobs from the last {days} days need a description (limit {limit})")
    enrich_descriptions(candidates, limit)
    save_jobs(RAW_JOBS_PATH, existing)
