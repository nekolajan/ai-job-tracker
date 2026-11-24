"""
scraper/utils.py

Shared helpers for all scrapers: stable job ids, relevance and spam filters,
HTML-to-text and title/company fingerprints for cross-run deduplication.
"""

from __future__ import annotations

import hashlib
import re
import unicodedata
from datetime import datetime, timezone
from urllib.parse import urlsplit, urlunsplit

from bs4 import BeautifulSoup

from config import (
    RELEVANT_TITLE_PATTERNS, BLOCKED_COMPANIES, BLOCKED_TITLE_PATTERNS,
    LOCATION_FILTERED_SOURCES, ALLOWED_LOCATION_KEYWORDS, LINKEDIN_ALLOWED_LOCATIONS,
    DESCRIPTION_BOILERPLATE, EXCLUDED_TITLE_PATTERNS, TITLE_GATE_OVERRIDES,
    ALWAYS_EXCLUDED_TITLE_PATTERNS,
    DETAIL_SOURCES, LEGACY_TRUNCATED_LENGTH, MAX_DETAIL_ATTEMPTS, COMPANY_ALIASES,
)

_RELEVANT_TITLE_RE = [re.compile(p) for p in RELEVANT_TITLE_PATTERNS]
_EXCLUDED_TITLE_RE = [re.compile(p) for p in EXCLUDED_TITLE_PATTERNS]
_ALWAYS_EXCLUDED_RE = [re.compile(p) for p in ALWAYS_EXCLUDED_TITLE_PATTERNS]
_TITLE_OVERRIDE_RE = [re.compile(p) for p in TITLE_GATE_OVERRIDES]

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
}

# Hosts whose job URLs carry per-search tracking params (e.g. jobs.cz ?searchId=...).
# Without stripping them, the same posting gets a new job_id on every run.
_STRIP_QUERY_HOSTS = ("jobs.cz", "linkedin.com", "jobstack.it", "startupjobs.cz")


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def canonical_url(url: str) -> str:
    """Drop tracking query/fragment for known boards so the same job keeps one id."""
    if not url:
        return url
    parts = urlsplit(url)
    if any(h in parts.netloc for h in _STRIP_QUERY_HOSTS):
        return urlunsplit((parts.scheme, parts.netloc, parts.path, "", ""))
    return url


def make_id(url: str) -> str:
    return hashlib.md5(canonical_url(url).encode()).hexdigest()[:12]


def _norm(text: str) -> str:
    text = unicodedata.normalize("NFKD", text or "")
    text = "".join(c for c in text if not unicodedata.combining(c)).lower()
    text = re.sub(r"\(.*?\)|\[.*?\]", " ", text)          # (m/ž), (f/m/d), [remote] ...
    text = re.sub(r"[^a-z0-9]+", " ", text)
    text = re.sub(r"\b(s r o|a s|spol|inc|ltd|llc|gmbh|group)\b", " ", text)
    return " ".join(text.split())


def company_key(name: str) -> str:
    """'GoodData.AI' → 'gooddata', 'Everpure' → 'pure storage' (config.COMPANY_ALIASES)."""
    name = re.sub(r"\.(ai|io|com|cz|eu|co)\b", " ", name or "", flags=re.I)
    key = _norm(name)
    return COMPANY_ALIASES.get(key, key)


def fingerprint(job: dict) -> str:
    """Title + company key used to spot the same posting under a different URL/source."""
    return f"{_norm(job.get('title', ''))}|{company_key(job.get('company', ''))}"


def to_date(value) -> str | None:
    """Publication date from an API value → 'YYYY-MM-DD'. Accepts ISO strings
    ('2026-11-03T10:00:00Z'), epoch seconds or milliseconds; None if unusable."""
    if value in (None, "", 0):
        return None
    if isinstance(value, (int, float)) or (isinstance(value, str) and value.isdigit()):
        ts = float(value)
        if ts > 1e11:                     # milliseconds
            ts /= 1000
        try:
            return datetime.fromtimestamp(ts, timezone.utc).strftime("%Y-%m-%d")
        except (OverflowError, OSError, ValueError):
            return None
    m = re.match(r"(\d{4}-\d{2}-\d{2})", str(value).strip())
    return m.group(1) if m else None


def is_relevant(title: str) -> bool:
    """Title names a data / BI / analytics / AI role (config.RELEVANT_TITLE_PATTERNS)."""
    t = _plain(title)
    return any(r.search(t) for r in _RELEVANT_TITLE_RE)


def _plain(text: str) -> str:
    """Lower-case, accents removed – 'Stážista' → 'stazista'."""
    text = unicodedata.normalize("NFKD", text or "")
    return "".join(c for c in text if not unicodedata.combining(c)).lower()


def title_excluded(title: str) -> bool:
    """Title gate: entry-level and other unwanted roles (config.EXCLUDED_TITLE_PATTERNS),
    unless the title also names a wanted level (config.TITLE_GATE_OVERRIDES)."""
    t = _plain(title)
    if any(r.search(t) for r in _ALWAYS_EXCLUDED_RE):
        return True
    if not any(r.search(t) for r in _EXCLUDED_TITLE_RE):
        return False
    return not any(r.search(t) for r in _TITLE_OVERRIDE_RE)


def is_allowed(job: dict) -> bool:
    """Spam / title / location filter applied to every source before a job is stored."""
    company = (job.get("company") or "").lower()
    title = (job.get("title") or "").lower()
    if any(b in company for b in BLOCKED_COMPANIES):
        return False
    if any(p in title for p in BLOCKED_TITLE_PATTERNS):
        return False
    if title_excluded(job.get("title") or ""):
        return False
    loc = (job.get("location") or "").lower()
    if job.get("source") in LOCATION_FILTERED_SOURCES:
        if not any(re.search(rf"\b{re.escape(k)}\b", loc) for k in ALLOWED_LOCATION_KEYWORDS):
            return False
    if job.get("source") == "linkedin":
        if not any(k in loc for k in LINKEDIN_ALLOWED_LOCATIONS):
            return False
    return True


def is_boilerplate(text: str) -> bool:
    """True if a stored description is only site footer / copyright text."""
    t = (text or "").lower()
    return bool(t) and any(m in t for m in DESCRIPTION_BOILERPLATE) and len(t) < 1000


def needs_description(job: dict) -> bool:
    """True if a job from a listing-only source has no usable description yet:
    empty, page boilerplate, or cut at the old storage limit."""
    if job.get("source") not in DETAIL_SOURCES:
        return False
    if job.get("expired_at"):                      # posting taken down (404 / 410)
        return False
    if job.get("detail_attempts", 0) >= MAX_DETAIL_ATTEMPTS:   # page loads, text not found
        return False
    desc = (job.get("description") or "").strip()
    if not desc or is_boilerplate(desc):
        return True
    return len(job.get("description") or "") == LEGACY_TRUNCATED_LENGTH


def html_to_text(html: str) -> str:
    if not html:
        return ""
    text = BeautifulSoup(html, "html.parser").get_text(separator="\n")
    lines = [ln.strip() for ln in text.splitlines()]
    return "\n".join(ln for ln in lines if ln)
