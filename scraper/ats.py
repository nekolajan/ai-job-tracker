"""
scraper/ats.py

Fetches open positions straight from company career boards (applicant tracking
systems) via their public JSON APIs – with full job descriptions:

  Greenhouse  https://boards-api.greenhouse.io/v1/boards/{slug}/jobs?content=true
  Lever       https://api.lever.co/v0/postings/{slug}?mode=json   (EU: api.eu.lever.co)
  Ashby       https://api.ashbyhq.com/posting-api/job-board/{slug}?includeCompensation=true

Companies are listed in config.ATS_COMPANIES. To find a company's ATS and slug,
open its careers page and look at the apply link (boards.greenhouse.io/<slug>,
jobs.lever.co/<slug>, jobs.ashbyhq.com/<slug>) or run:

  python -m scraper.ats discover gooddata modash productboard
"""

import html
import sys
import time

import requests

from config import ATS_COMPANIES, ATS_LOCATION_KEYWORDS, DESCRIPTION_STORE_MAX_CHARS, SOURCES
from scraper.utils import make_id, is_relevant, now, html_to_text

TIMEOUT = 20


def _job(title, company, location, description, url, salary, source) -> dict:
    return {
        "job_id":      make_id(url),
        "title":       title.strip(),
        "company":     company,
        "location":    location,
        "description": description[:DESCRIPTION_STORE_MAX_CHARS],
        "url":         url,
        "source":      source,
        "salary":      salary or "",
        "scraped_at":  now(),
    }


# ── parsers (pure functions, unit-tested with fixtures) ──────────────────────

def parse_greenhouse(data: dict, company: str) -> list[dict]:
    out = []
    for j in data.get("jobs", []):
        url = j.get("absolute_url", "")
        if not url:
            continue
        # Greenhouse returns HTML-escaped HTML in `content`
        desc = html_to_text(html.unescape(j.get("content", "") or ""))
        out.append(_job(
            j.get("title", ""), company, (j.get("location") or {}).get("name", ""),
            desc, url, "", "greenhouse",
        ))
    return out


def parse_lever(data: list, company: str) -> list[dict]:
    out = []
    for j in data or []:
        url = j.get("hostedUrl", "")
        if not url:
            continue
        cats = j.get("categories") or {}
        locs = cats.get("allLocations") or [cats.get("location", "")]
        location = ", ".join(l for l in locs if l)
        if j.get("workplaceType") == "remote" and "remote" not in location.lower():
            location = f"{location} (Remote)".strip()
        parts = [j.get("descriptionPlain", "")]
        for lst in j.get("lists") or []:
            parts.append(lst.get("text", ""))
            parts.append(html_to_text(lst.get("content", "")))
        parts.append(j.get("additionalPlain", ""))
        sal = j.get("salaryRange") or {}
        salary = (
            f"{sal.get('currency', '')} {sal.get('min', '')} – {sal.get('max', '')}".strip()
            if sal.get("min") else ""
        )
        out.append(_job(
            j.get("text", ""), company, location,
            "\n".join(p for p in parts if p), url, salary, "lever",
        ))
    return out


def parse_ashby(data: dict, company: str) -> list[dict]:
    out = []
    for j in data.get("jobs", []):
        if j.get("isListed") is False:
            continue
        url = j.get("jobUrl") or j.get("applyUrl") or ""
        if not url:
            continue
        locs = [j.get("location", "")] + [
            s.get("location", "") for s in j.get("secondaryLocations") or []
        ]
        location = ", ".join(l for l in locs if l)
        if j.get("isRemote") and "remote" not in location.lower():
            location = f"{location} (Remote)".strip()
        desc = j.get("descriptionPlain") or html_to_text(j.get("descriptionHtml", ""))
        salary = (j.get("compensation") or {}).get("compensationTierSummary", "")
        out.append(_job(j.get("title", ""), company, location, desc, url, salary, "ashby"))
    return out


# ── fetch ────────────────────────────────────────────────────────────────────

def _get_json(url: str, params: dict | None = None):
    resp = requests.get(url, params=params, timeout=TIMEOUT)
    resp.raise_for_status()
    return resp.json()


def fetch_company(ats: str, slug: str, company: str) -> list[dict]:
    if ats == "greenhouse":
        data = _get_json(f"https://boards-api.greenhouse.io/v1/boards/{slug}/jobs",
                         {"content": "true"})
        return parse_greenhouse(data, company)
    if ats == "lever":
        try:
            data = _get_json(f"https://api.lever.co/v0/postings/{slug}", {"mode": "json"})
        except requests.HTTPError:
            data = _get_json(f"https://api.eu.lever.co/v0/postings/{slug}", {"mode": "json"})
        return parse_lever(data, company)
    if ats == "ashby":
        data = _get_json(f"https://api.ashbyhq.com/posting-api/job-board/{slug}",
                         {"includeCompensation": "true"})
        return parse_ashby(data, company)
    raise ValueError(f"unknown ATS '{ats}'")


def location_ok(location: str) -> bool:
    loc = (location or "").lower()
    return any(k in loc for k in ATS_LOCATION_KEYWORDS)


def fetch_ats() -> list[dict]:
    if not SOURCES["ats"].enabled:
        return []
    results = []
    for c in ATS_COMPANIES:
        if not c.get("enabled", True):
            continue
        name = c.get("name") or c["slug"]
        try:
            jobs = fetch_company(c["ats"], c["slug"], name)
            kept = [j for j in jobs if is_relevant(j["title"]) and location_ok(j["location"])]
            print(f"[ats] {name} ({c['ats']}): {len(jobs)} open, {len(kept)} relevant")
            results.extend(kept)
        except Exception as e:
            print(f"[ats] {name} ({c['ats']}/{c['slug']}) error: {e}")
        time.sleep(1.0)
    return results


def discover(slugs: list[str]) -> None:
    """Try each slug on every supported ATS and report where it exists."""
    for slug in slugs:
        hits = []
        for ats in ("greenhouse", "lever", "ashby"):
            try:
                jobs = fetch_company(ats, slug, slug)
                hits.append(f"{ats} ({len(jobs)} jobs)")
            except Exception:
                pass
        print(f"{slug}: {', '.join(hits) if hits else 'not found'}")


if __name__ == "__main__":
    if len(sys.argv) > 2 and sys.argv[1] == "discover":
        discover(sys.argv[2:])
    else:
        for j in fetch_ats():
            print(f"- {j['company']}: {j['title']} | {j['location']}")
