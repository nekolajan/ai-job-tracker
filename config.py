"""
config.py

Central configuration for job sources, scoring, and pipeline settings.
Edit this file to add sources, adjust keywords, or change thresholds.
"""

from dataclasses import dataclass


# ── job search ────────────────────────────────────────────────────────────────

SEARCH_KEYWORDS = [
    "data analyst",
    "BI analyst",
    "business intelligence",
    "analytics engineer",
    "data engineer",
    "senior analyst",
]

LOCATIONS = ["remote", "Prague", "Praha"]

SCORE_THRESHOLD_GOOD = 75
SCORE_THRESHOLD_OK   = 50


# ── sources ───────────────────────────────────────────────────────────────────

@dataclass
class SourceConfig:
    name: str
    enabled: bool = True
    max_results_per_keyword: int = 20
    request_delay_seconds: float = 1.0


SOURCES: dict[str, SourceConfig] = {
    "remotive": SourceConfig(
        name="remotive",
        enabled=True,
        max_results_per_keyword=20,
        request_delay_seconds=1.0,
    ),
    "the_muse": SourceConfig(
        name="the_muse",
        enabled=True,
        max_results_per_keyword=15,
        request_delay_seconds=1.0,
    ),
    "jobs_cz": SourceConfig(
        name="jobs_cz",
        enabled=True,
        max_results_per_keyword=20,
        request_delay_seconds=2.0,
    ),
    "linkedin": SourceConfig(
        name="linkedin",
        enabled=True,
        max_results_per_keyword=25,
        request_delay_seconds=3.0,
    ),
}


# ── scoring ───────────────────────────────────────────────────────────────────

SCORING_MODEL = "claude-haiku-4-5"
SCORING_MAX_TOKENS = 1024
DESCRIPTION_MAX_CHARS = 3000

# Titles containing any of these are kept; others filtered out before scoring
RELEVANT_TITLE_KEYWORDS = [
    "data", "analyst", "analytics", "bi", "business intelligence",
    "insight", "reporting", "warehouse", "pipeline", "sql",
]


# ── pipeline ──────────────────────────────────────────────────────────────────

RAW_JOBS_FILENAME    = "raw_jobs.json"
SCORED_JOBS_FILENAME = "scored_jobs.json"
DATA_DIR             = "data"


# ── BigQuery ──────────────────────────────────────────────────────────────────

BQ_PARTITION_FIELD = "scraped_at"
BQ_PARTITION_TYPE  = "DAY"

JOB_STATUSES  = ["new", "saved", "applied", "rejected"]
DEFAULT_STATUS = "new"
