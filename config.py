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

SCORE_THRESHOLD_GOOD = 70   # worth reading; see enrichment/rank.py
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
        enabled=False,  # 403 Forbidden since 10/2026, US-only jobs anyway
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
    "jobstack": SourceConfig(
        name="jobstack",
        enabled=True,
        max_results_per_keyword=20,
        request_delay_seconds=2.0,
    ),
    "himalayas": SourceConfig(
        name="himalayas",
        enabled=True,
        max_results_per_keyword=20,
        request_delay_seconds=1.0,
    ),
    "remoteok": SourceConfig(
        name="remoteok",
        enabled=True,
        max_results_per_keyword=20,
        request_delay_seconds=2.0,
    ),
    "startupjobs": SourceConfig(
        name="startupjobs",
        enabled=False,  # listing is rendered by JavaScript – plain requests get no jobs
        max_results_per_keyword=20,
        request_delay_seconds=2.0,
    ),
    "ats": SourceConfig(
        name="ats",
        enabled=True,
    ),
}

# LinkedIn public search: (keywords, location, remote flag "2" = remote or "")
# f_TPR=r604800 limits results to the last 7 days, so each run sees fresh postings.
LINKEDIN_SEARCHES = [
    ("data analyst BI", "Prague", ""),
    ("data engineer", "Prague", ""),
    ("analytics engineer", "Czechia", ""),
    ("business intelligence", "Czechia", ""),
    ("AI engineer data", "Czechia", ""),
    ("data engineer", "Czechia", "2"),      # remote roles open to CZ
    ("data analyst", "Czechia", "2"),
]
LINKEDIN_TIME_FILTER = "r604800"


# ── company career boards (ATS) ───────────────────────────────────────────────
# Public JSON APIs with full descriptions. Find the slug in the company's apply
# link or run:  python -m scraper.ats discover <slug> [<slug> ...]
# Entries marked "verify" are guesses – run discover once and fix or remove them.

ATS_COMPANIES = [
    # verified with `discover` (Nov 2026)
    {"ats": "greenhouse", "slug": "sentinelonecz", "name": "SentinelOne"},
    {"ats": "lever",      "slug": "keboola",       "name": "Keboola"},
    {"ats": "greenhouse", "slug": "make",          "name": "Make"},
    {"ats": "greenhouse", "slug": "bloomreach",    "name": "Bloomreach"},
    {"ats": "ashby",      "slug": "rohlik",        "name": "Rohlik Group"},
    {"ats": "ashby",      "slug": "apify",         "name": "Apify"},
    {"ats": "ashby",      "slug": "gooddata",      "name": "GoodData"},
    {"ats": "greenhouse", "slug": "shipmonk",      "name": "ShipMonk"},
    {"ats": "lever",      "slug": "ataccama",      "name": "Ataccama"},
    {"ats": "greenhouse", "slug": "emplifi",       "name": "Emplifi"},
    {"ats": "greenhouse", "slug": "groupon",       "name": "Groupon"},
    {"ats": "lever",      "slug": "pipedrive",     "name": "Pipedrive"},   # 0 open jobs at check time
    {"ats": "greenhouse", "slug": "purestorage",   "name": "Pure Storage"},
    {"ats": "greenhouse", "slug": "jetbrains",     "name": "JetBrains"},
    {"ats": "greenhouse", "slug": "gitlab",        "name": "GitLab"},
    {"ats": "greenhouse", "slug": "canonical",     "name": "Canonical"},
    {"ats": "greenhouse", "slug": "elastic",       "name": "Elastic"},
    {"ats": "ashby",      "slug": "e2b",           "name": "E2B"},
    {"ats": "ashby",      "slug": "qonto",         "name": "Qonto"},
    {"ats": "ashby",      "slug": "duck-duck-go",  "name": "DuckDuckGo"},
    # not on Greenhouse / Lever / Ashby under these names: productboard, kiwicom, mews,
    # resistantai, modash, pricefx, rapid7, veeam, rossum, betterstack, livesport,
    # kentico, fnz, twisto, smartlook – they come in through LinkedIn / jobs.cz instead
]

# ATS boards list global jobs – keep only these locations (lower-case substrings)
ATS_LOCATION_KEYWORDS = [
    "prague", "praha", "czech", "czechia", "brno", "remote", "europe", "emea", "anywhere",
]


# ── job details ───────────────────────────────────────────────────────────────

# Listing-only sources whose detail pages are opened to get the description
DETAIL_SOURCES = ["jobs_cz", "linkedin", "jobstack"]
MAX_DETAIL_FETCHES_PER_RUN = 80

# `python -m scraper.details --backfill N` only looks at jobs scraped within this
# many days – older postings have usually expired, so fetching them is wasted work
DETAIL_BACKFILL_DAYS = 30

# A detail page that loads but yields no description is retried this many times
# in total, then left alone (its text is probably rendered by JavaScript)
MAX_DETAIL_ATTEMPTS = 2

# Descriptions are stored (almost) whole and only shortened when sent to the LLM.
# Requirements often sit at the end of a posting, so cutting at save time loses them.
DESCRIPTION_STORE_MAX_CHARS = 20000

# Older versions cut stored descriptions at exactly this length; such descriptions
# from DETAIL_SOURCES are treated as incomplete and fetched again
LEGACY_TRUNCATED_LENGTH = 3000


# ── filters ───────────────────────────────────────────────────────────────────

BLOCKED_COMPANIES = ["kled ai"]
BLOCKED_TITLE_PATTERNS = ["paid data task", "data labeling", "data annotation"]

# Title gates – applied before a job is stored, i.e. before its detail page is
# opened and before any LLM call. Regular expressions matched against the
# lower-cased title with accents removed ("Stážista" → "stazista").
EXCLUDED_TITLE_PATTERNS = [
    # entry level
    r"\bjunior\w*", r"\bintern(ship)?\b", r"\bstaz\w*", r"\btrainee\w*",
    r"\babsolvent\w*", r"\bgraduate\b", r"\bworking student\b", r"\bwerkstudent\w*",
    r"\bpraktikant\w*", r"\bbrigad\w*",
    # classic (IT) business analyst roles – remove these lines to keep them
    r"\bbusiness analy(st|tik)\w*", r"\bbyznys analytik\w*", r"\bit analy(st|tik)\w*",
]
# A title that also matches one of these is kept ("Junior/Medior Data Engineer")
TITLE_GATE_OVERRIDES = [r"\bsenior\w*", r"\bmedior\w*", r"\blead\b", r"\bprincipal\b", r"\bstaff\b"]

# Global remote boards: keep only jobs open to CZ / Europe
LOCATION_FILTERED_SOURCES = ["himalayas", "remoteok", "remotive", "the_muse"]
ALLOWED_LOCATION_KEYWORDS = [
    "worldwide", "anywhere", "europe", "emea", "eu", "czech", "czechia", "prague", "praha",
    "global",
]

# LinkedIn search returns on-site jobs from other countries too – keep CZ or remote only
LINKEDIN_ALLOWED_LOCATIONS = ["czech", "czechia", "prague", "praha", "brno", "remote"]

# Text that means the "description" is really page boilerplate (e.g. jobs.cz
# employer pages whose content is not in the HTML) – such text is discarded
DESCRIPTION_BOILERPLATE = ["alma career czechia", "vizuální podoba webové stránky"]

# Different names for the same company on different sites (lower-case, without
# accents and legal forms). Used to spot the same posting across sources.
COMPANY_ALIASES = {
    "everpure": "pure storage",
    "rohlik group": "rohlik",
    "rohlik cz": "rohlik",
}

# Same title + company already stored within this many days → treat as duplicate
DEDUP_WINDOW_DAYS = 60




# ── scoring ───────────────────────────────────────────────────────────────────

# Master switch for paid LLM calls. While False, `python -m enrichment.score`
# exits without calling the API – scraping and everything else keeps working.
SCORING_ENABLED = False

# Hard cap on LLM calls in one run (newest jobs first); the rest waits for the next run
MAX_LLM_CALLS_PER_RUN = 30

SCORING_MODEL = "claude-haiku-4-5"
SCORING_MAX_TOKENS = 1024
DESCRIPTION_MAX_CHARS = 3000   # characters of the description sent to the LLM

# A title is kept if it matches at least one of these; others are dropped before
# anything is stored. Regular expressions matched as whole words against the
# lower-cased title with accents removed, so "BI" no longer matches "mobile" or
# "Bidder" and "AI" is found in "AI/ML Engineer" as well as "Head of AI".
RELEVANT_TITLE_PATTERNS = [
    r"\bdata\b", r"\bdatov\w*",
    r"\banalyst\w*", r"\banalytik\w*", r"\banalyticka\b", r"\banalytics\b",
    r"\bbi\b", r"\bpbi\b", r"\bbusiness intelligence\b", r"\btableau\b",
    r"\binsights?\b", r"\breporting\w*",
    r"\bdwh\b", r"\bwarehouse\b", r"\betl\b", r"\bpipelines?\b", r"\bsql\b",
    r"\bdatabricks\b", r"\bsnowflake\b", r"\bbigquery\b", r"\bdbt\b",
    r"\bai\b", r"\bml\b", r"\bmachine learning\b", r"\bllms?\b", r"\bgenai\b", r"\bnlp\b",
    r"\bumel\w* inteligenc\w*",
]


# ── extraction (free, local LLM) ──────────────────────────────────────────────
# `python -m enrichment.extract` reads each job description with a small local
# model and stores plain facts (seniority, stack, remote, languages …) in
# data/extracted_jobs.json. The score is then computed from those facts in code,
# so it can be re-weighted any time without calling the model again.

EXTRACTION_ENABLED = True
LLM_PROVIDER = "ollama"                      # runs on this computer, costs nothing
OLLAMA_URL = "http://localhost:11434"
OLLAMA_MODEL = "qwen3.5:4b"
OLLAMA_CONTEXT_TOKENS = 4096
OLLAMA_TIMEOUT_SECONDS = 180               # one job; a slower answer counts as failed
EXTRACTION_TIME_BUDGET_MINUTES = 30        # stop extracting after this; ranking still runs

MAX_EXTRACTIONS_PER_RUN = 40                 # newest first; the rest waits for the next run
EXTRACT_DESCRIPTION_MAX_CHARS = 6000         # longer texts keep their start and end
EXTRACTION_PROMPT_VERSION = "v2"             # bump to re-extract everything after a prompt change
EXTRACTED_JOBS_FILENAME = "extracted_jobs.json"


# ── ranking (no model, computed from the extracted facts) ─────────────────────
# `python -m enrichment.rank` scores every extracted job 0–100 from the facts in
# data/extracted_jobs.json. Change anything here and run it again – it takes a
# second and never calls a model.

# Your tools. "core" = you use them confidently, "partial" = you know them a bit.
MY_SKILLS_CORE = [
    "SQL", "Python", "BigQuery", "Power BI", "DAX", "Power Query", "Tableau", "Airflow",
    "Keboola", "Looker Studio", "Redshift", "Athena", "AWS", "SQL Server", "T-SQL", "Excel",
    "Git", "GitHub", "GitHub Actions", "Google Analytics", "GCP",
]
MY_SKILLS_PARTIAL = [
    "dbt", "Snowflake", "Databricks", "Microsoft Fabric", "Azure", "PySpark", "Spark",
    "Looker", "Docker", "LangChain", "pandas", "PostgreSQL", "MySQL", "Streamlit",
]

# Cities that count as "Prague" for hybrid / on-site jobs (lower-case, no accents)
HOME_CITIES = ["prague", "praha", "prag"]
# Location text that means the job is in Czechia (for residency requirements)
HOME_COUNTRY_KEYWORDS = ["czech", "czechia", "cesko", "cr", "prague", "praha", "brno", "ostrava",
                         "plzen", "olomouc", "liberec", "kladno", "beroun", "pardubice"]

# Points per fact. The total is capped at 100.
SCORE_ROLE = {                       # what kind of work
    "data_engineer": 25, "analytics_engineer": 25, "bi_developer": 22, "data_architect": 20,
    "ml_ai_engineer": 20, "data_analyst": 18, "product_analyst": 18, "data_manager": 15,
    "data_scientist": 12, "software_engineer": 5, "other": 0,
}
# Titles that mean software development (building product / application code),
# unless they also contain one of SOFTWARE_TITLE_DATA_WORDS. Such jobs are scored
# as "software_engineer" whatever the model said. Regular expressions, matched
# against the lower-cased title without accents.
SOFTWARE_TITLE_PATTERNS = [
    r"\bsoftware (engineer|developer|analytik)\w*", r"\bfull[- ]?stack\b", r"\bback[- ]?end\b",
    r"\bfront[- ]?end\b", r"\bprogramator\w*", r"\b(ai|python|java|\.net|c#|llm|genai) (\w+ )?developer\b",
    r"\bapplication (developer|engineer)\b", r"\bai software\b",
]
SOFTWARE_TITLE_DATA_WORDS = [
    r"\bdata\b", r"\bdatov\w*", r"\bbi\b", r"\bsql\b", r"\bdwh\b", r"\banalytics\b",
    r"\bpower bi\b", r"\betl\b", r"\bwarehouse\b",
]
SCORE_SENIORITY = {"senior": 15, "lead": 12, "medior": 8, "unknown": 8, "junior": 0}
SCORE_STACK_MAX = 25                 # × share of required tools you know (core 1, partial 0.5)
SCORE_STACK_UNKNOWN = 12             # no tools listed in the posting
# A short tool list says little ("Python" alone would give 100 %). The coverage is
# therefore computed as if this many extra tools at half-knowledge were listed:
# ["Python"] → (1 + 2 × 0.5) / 3 = 67 %, a list of 8 tools barely moves.
SCORE_STACK_PRIOR_TOOLS = 2
SCORE_NICE_TO_HAVE_EACH = 1          # per known "nice to have" tool …
SCORE_NICE_TO_HAVE_MAX = 3           # … up to this
SCORE_AI = {"core": 15, "some": 8, "none": 0}
# greenfield vs. maintenance is not taken into account (set points here to use it)
SCORE_WORK_TYPE = {"greenfield": 0, "mixed": 0, "unknown": 0, "maintenance": 0}
SCORE_PLACE = {                      # where you work
    "remote": 8, "hybrid_home": 8, "onsite_home": 4, "hybrid_elsewhere": 3,
    "onsite_elsewhere": 0, "unknown": 4,
}
SCORE_CONTRACTOR_OK = 4              # contract / IČO possible

# Penalties (points taken off)
PENALTY_GERMAN_REQUIRED = 25
PENALTY_PEOPLE_MANAGEMENT = 10

# Hard exclusions: the job gets score 0 and the reason is shown
EXCLUDE_JUNIOR = True
EXCLUDE_RESIDENCY_ABROAD = True      # must live / have work permit in another country

RANKED_JOBS_FILENAME = "ranked_jobs.json"


# ── pipeline ──────────────────────────────────────────────────────────────────

RAW_JOBS_FILENAME    = "raw_jobs.json"
SCORED_JOBS_FILENAME = "scored_jobs.json"
DATA_DIR             = "data"


# ── BigQuery ──────────────────────────────────────────────────────────────────

BQ_PARTITION_FIELD = "scraped_at"
BQ_PARTITION_TYPE  = "DAY"

JOB_STATUSES  = ["new", "saved", "applied", "rejected"]
DEFAULT_STATUS = "new"