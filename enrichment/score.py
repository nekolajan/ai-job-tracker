"""
enrichment/score.py

Reads data/raw_jobs.json, scores each new job using Claude Haiku,
and writes results to data/scored_jobs.json.

Usage:
    python -m enrichment.score
"""

import json
import os
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import anthropic
from dotenv import load_dotenv

load_dotenv()

# ── paths ─────────────────────────────────────────────────────────────────────

ROOT_DIR         = Path(__file__).parent.parent
RAW_JOBS_PATH    = ROOT_DIR / "data" / "raw_jobs.json"
SCORED_JOBS_PATH = ROOT_DIR / "data" / "scored_jobs.json"
CV_PATH          = ROOT_DIR / "cv" / "profile.md"

# ── config ────────────────────────────────────────────────────────────────────

try:
    from config import (
        SCORING_MODEL,
        SCORING_MAX_TOKENS,
        DESCRIPTION_MAX_CHARS,
        RELEVANT_TITLE_KEYWORDS,
        DEFAULT_STATUS,
    )
except ImportError:
    SCORING_MODEL          = "claude-haiku-4-5"
    SCORING_MAX_TOKENS     = 1024
    DESCRIPTION_MAX_CHARS  = 3000
    RELEVANT_TITLE_KEYWORDS = [
        "data", "analyst", "analytics", "bi", "business intelligence",
        "insight", "reporting", "warehouse", "pipeline", "sql",
    ]
    DEFAULT_STATUS = "new"

# ── CV profile ────────────────────────────────────────────────────────────────
# Edit this to match your actual background, or put your CV text in cv/cv.txt

FALLBACK_CV_PROFILE = """
Name: Jan Novák
Role: Data Analyst / BI Analyst

Experience:
- 4 years as Data Analyst at mid-size e-commerce company
- Built and maintained dashboards in Tableau and Power BI
- Strong SQL (PostgreSQL, MySQL), Python (pandas, numpy)
- Experience with dbt for data transformations
- BigQuery and Google Analytics experience
- Basic knowledge of Airflow for pipeline scheduling

Education:
- MSc Economics, Charles University Prague

Languages:
- Czech (native), English (fluent)

Preferences:
- Looking for remote or Prague-based roles
- Prefer medior/senior analyst or analytics engineer positions
- Target salary: 80,000–110,000 CZK/month or equivalent
- Not interested in pure software engineering or Java/Scala roles
"""

def load_cv() -> str:
    """Load CV from file if it exists, otherwise use the fallback profile."""
    if CV_PATH.exists():
        return CV_PATH.read_text(encoding="utf-8").strip()
    return FALLBACK_CV_PROFILE.strip()


# ── scoring prompt ────────────────────────────────────────────────────────────

SYSTEM_PROMPT = """You are a job matching assistant. Given a candidate profile and a job posting,
you evaluate how well the job matches the candidate.

You must respond with valid JSON only — no explanation, no markdown, no extra text.

Return exactly this structure:
{
  "score": <integer 0-100>,
  "match_summary": "<one sentence explaining the score>",
  "skills_match": ["skill1", "skill2"],
  "gaps": ["gap1", "gap2"],
  "seniority_match": <true|false>,
  "remote_match": <true|false>
}

Scoring guide:
- 85-100: Excellent match — candidate clearly qualified, role fits preferences
- 70-84:  Good match — most requirements met, minor gaps
- 50-69:  Partial match — relevant field but missing key skills or wrong seniority
- 30-49:  Weak match — tangentially related
- 0-29:   Poor match — wrong field or clearly unqualified
"""

def build_user_prompt(cv: str, job: dict) -> str:
    description = (job.get("description") or "")[:DESCRIPTION_MAX_CHARS]
    return f"""CANDIDATE PROFILE:
{cv}

JOB POSTING:
Title: {job.get('title', '')}
Company: {job.get('company', '')}
Location: {job.get('location', '')}
Salary: {job.get('salary', 'not specified')}
Source: {job.get('source', '')}

Description:
{description}

Score this job for the candidate."""


# ── helpers ───────────────────────────────────────────────────────────────────

def is_relevant_title(title: str) -> bool:
    """Pre-filter: skip jobs that are clearly not data/analytics roles."""
    t = title.lower()
    return any(kw in t for kw in RELEVANT_TITLE_KEYWORDS)


def parse_score_response(text: str) -> dict:
    """Parse Claude's JSON response, with fallback for minor formatting issues."""
    # Strip markdown code fences if present
    text = re.sub(r"```(?:json)?", "", text).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        # Try to extract JSON object
        match = re.search(r"\{.*\}", text, re.DOTALL)
        if match:
            return json.loads(match.group())
        raise


def score_job(client: anthropic.Anthropic, cv: str, job: dict) -> dict:
    """Call Claude to score a single job. Returns scoring fields."""
    response = client.messages.create(
        model=SCORING_MODEL,
        max_tokens=SCORING_MAX_TOKENS,
        system=SYSTEM_PROMPT,
        messages=[
            {"role": "user", "content": build_user_prompt(cv, job)}
        ],
    )
    raw = response.content[0].text
    result = parse_score_response(raw)

    return {
        "score":           int(result.get("score", 0)),
        "match_summary":   str(result.get("match_summary", "")),
        "skills_match":    json.dumps(result.get("skills_match", [])),
        "gaps":            json.dumps(result.get("gaps", [])),
        "seniority_match": bool(result.get("seniority_match", False)),
        "remote_match":    bool(result.get("remote_match", False)),
    }


# ── main ──────────────────────────────────────────────────────────────────────

def main():
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        print("[score] ERROR: ANTHROPIC_API_KEY not set in environment", file=sys.stderr)
        sys.exit(1)

    # Load raw jobs
    if not RAW_JOBS_PATH.exists():
        print(f"[score] ERROR: {RAW_JOBS_PATH} not found — run scraper first", file=sys.stderr)
        sys.exit(1)

    raw_jobs = json.loads(RAW_JOBS_PATH.read_text(encoding="utf-8"))
    print(f"[score] loaded {len(raw_jobs)} raw jobs")

    # Load already-scored jobs
    if SCORED_JOBS_PATH.exists():
        scored_jobs = json.loads(SCORED_JOBS_PATH.read_text(encoding="utf-8"))
    else:
        scored_jobs = []

    scored_ids = {j["job_id"] for j in scored_jobs}
    print(f"[score] already scored: {len(scored_ids)}")

    # Find new jobs to score
    to_score = [
        j for j in raw_jobs
        if j["job_id"] not in scored_ids and is_relevant_title(j.get("title", ""))
    ]
    skipped_irrelevant = len([
        j for j in raw_jobs
        if j["job_id"] not in scored_ids and not is_relevant_title(j.get("title", ""))
    ])

    print(f"[score] to score: {len(to_score)} new jobs ({skipped_irrelevant} skipped as irrelevant)")

    if not to_score:
        print("[score] nothing to do — all jobs already scored")
        return

    # Load CV
    cv = load_cv()
    print(f"[score] CV loaded ({'from file' if CV_PATH.exists() else 'using fallback profile'})")

    # Score each job
    client    = anthropic.Anthropic(api_key=api_key)
    succeeded = 0
    failed    = 0

    for i, job in enumerate(to_score, 1):
        print(f"[score] {i}/{len(to_score)} scoring: {job['title']} @ {job['company']} ... ", end="", flush=True)
        try:
            scoring = score_job(client, cv, job)
            scored_job = {
                **job,
                **scoring,
                "status":      DEFAULT_STATUS,
                "date_scraped": job.get("scraped_at", "")[:10],
            }
            scored_jobs.append(scored_job)
            succeeded += 1
            print(f"score={scoring['score']}")

            # Save after every job so progress isn't lost on failure
            SCORED_JOBS_PATH.write_text(
                json.dumps(scored_jobs, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )

            # Brief delay to avoid rate limits
            if i < len(to_score):
                time.sleep(0.5)

        except Exception as e:
            failed += 1
            print(f"FAILED: {e}")
            continue

    print(f"[score] done. scored={succeeded} failed={failed} total_in_file={len(scored_jobs)}")


if __name__ == "__main__":
    main()
