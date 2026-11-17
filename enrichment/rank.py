"""
enrichment/rank.py

Scores every job that has extracted facts (data/extracted_jobs.json) from 0 to
100, using only the settings in config.py – no model is called, so a re-run
takes a second. Writes data/ranked_jobs.json with the score, a breakdown of
where the points came from, and the fields the dashboard shows (match_summary,
skills_match, gaps, seniority_match, remote_match).

Usage:
    python -m enrichment.rank              # score everything, print the top 20
    python -m enrichment.rank --top 50
    python -m enrichment.rank --job-id 1a2b3c   # show the full breakdown of one job
"""

from __future__ import annotations

import json
import re
import sys
import unicodedata
from datetime import datetime, timezone
from pathlib import Path

import config as cfg
from enrichment.extract import tool_name

ROOT = Path(__file__).parent.parent
RAW_JOBS_PATH = ROOT / cfg.DATA_DIR / cfg.RAW_JOBS_FILENAME
EXTRACTED_PATH = ROOT / cfg.DATA_DIR / cfg.EXTRACTED_JOBS_FILENAME
RANKED_PATH = ROOT / cfg.DATA_DIR / cfg.RANKED_JOBS_FILENAME

_CORE = {t.lower() for t in map(tool_name, cfg.MY_SKILLS_CORE)}
_PARTIAL = {t.lower() for t in map(tool_name, cfg.MY_SKILLS_PARTIAL)} - _CORE


def _plain(text: str) -> str:
    text = unicodedata.normalize("NFKD", text or "")
    return "".join(c for c in text if not unicodedata.combining(c)).lower()


def _has_word(text: str, words: list[str]) -> bool:
    t = _plain(text)
    return any(re.search(rf"\b{re.escape(w)}\b", t) for w in words)


_SOFTWARE_RE = [re.compile(p) for p in cfg.SOFTWARE_TITLE_PATTERNS]
_DATA_WORD_RE = [re.compile(p) for p in cfg.SOFTWARE_TITLE_DATA_WORDS]


def role_family(facts: dict, job: dict) -> str:
    """The model's role family, overridden to software_engineer when the title
    clearly names software development without any data word."""
    title = _plain(job.get("title", ""))
    if any(r.search(title) for r in _SOFTWARE_RE) and not any(r.search(title) for r in _DATA_WORD_RE):
        return "software_engineer"
    return facts.get("role_family", "other")


def tool_level(tool: str) -> float:
    """1 = core skill, 0.5 = partial, 0 = not known."""
    t = tool_name(tool).lower()
    return 1.0 if t in _CORE else 0.5 if t in _PARTIAL else 0.0


def place_key(facts: dict, job: dict) -> str:
    mode = facts.get("work_mode", "unknown")
    if mode == "remote":
        return "remote"
    if mode not in ("hybrid", "onsite"):
        return "unknown"
    where = " ".join(filter(None, [facts.get("city") or "", job.get("location") or ""]))
    return f"{mode}_{'home' if _has_word(where, cfg.HOME_CITIES) else 'elsewhere'}"


def score_job(facts: dict, job: dict) -> dict:
    """Score one job. Returns score, excluded reason (or None), point breakdown,
    and the dashboard fields."""
    points: dict[str, float] = {}
    excluded = None

    if cfg.EXCLUDE_JUNIOR and facts.get("seniority") == "junior":
        excluded = "junior role"
    in_home_country = _has_word(job.get("location", "") + " " + (facts.get("city") or ""),
                                cfg.HOME_COUNTRY_KEYWORDS)
    if cfg.EXCLUDE_RESIDENCY_ABROAD and facts.get("residency_required") and not in_home_country:
        excluded = excluded or "requires living / work permit in another country"

    role = role_family(facts, job)
    points["role"] = cfg.SCORE_ROLE.get(role, 0)
    points["seniority"] = cfg.SCORE_SENIORITY.get(facts.get("seniority"), 0)

    required = facts.get("stack_required") or []
    if required:
        coverage = sum(tool_level(t) for t in required) / len(required)
        k = cfg.SCORE_STACK_PRIOR_TOOLS
        weighted = (sum(tool_level(t) for t in required) + 0.5 * k) / (len(required) + k)
        points["stack"] = round(cfg.SCORE_STACK_MAX * weighted, 1)
    else:
        coverage = None
        points["stack"] = cfg.SCORE_STACK_UNKNOWN
    known_nice = [t for t in facts.get("stack_nice_to_have") or [] if tool_level(t) > 0]
    points["nice_to_have"] = min(len(known_nice) * cfg.SCORE_NICE_TO_HAVE_EACH, cfg.SCORE_NICE_TO_HAVE_MAX)

    points["ai"] = cfg.SCORE_AI.get(facts.get("ai_focus"), 0)
    points["work_type"] = cfg.SCORE_WORK_TYPE.get(facts.get("work_type"), 0)
    place = place_key(facts, job)
    points["place"] = cfg.SCORE_PLACE.get(place, 0)
    points["contract"] = cfg.SCORE_CONTRACTOR_OK if facts.get("employment") in ("contractor", "either") else 0

    langs = [l.lower() for l in facts.get("required_languages") or []]
    if any(l in ("german", "nemcina", "deutsch") for l in langs):
        points["german_required"] = -cfg.PENALTY_GERMAN_REQUIRED
    if facts.get("people_management"):
        points["people_management"] = -cfg.PENALTY_PEOPLE_MANAGEMENT

    score = 0 if excluded else int(round(max(0, min(100, sum(points.values())))))

    skills_match = [tool_name(t) for t in required if tool_level(t) > 0] + \
                   [tool_name(t) for t in known_nice]
    gaps = [tool_name(t) for t in required if tool_level(t) == 0]
    return {
        "score": score,
        "excluded": excluded,
        "points": points,
        "stack_coverage": None if coverage is None else round(coverage, 2),
        "role_family": role,
        "match_summary": summary({**facts, "role_family": role}, place, coverage, excluded, points),
        "skills_match": skills_match,
        "gaps": gaps,
        "seniority_match": facts.get("seniority") in ("senior", "lead"),
        "remote_match": place in ("remote", "hybrid_home"),
    }


_ROLE_LABEL = {
    "data_engineer": "data engineering", "analytics_engineer": "analytics engineering",
    "bi_developer": "BI development", "data_architect": "data architecture",
    "ml_ai_engineer": "AI/ML engineering", "data_analyst": "data analysis",
    "product_analyst": "product analytics", "data_manager": "data team lead",
    "data_scientist": "data science", "software_engineer": "software development",
    "other": "other role",
}
_PLACE_LABEL = {"remote": "remote", "hybrid_home": "hybrid in Prague", "onsite_home": "on-site in Prague",
                "hybrid_elsewhere": "hybrid outside Prague", "onsite_elsewhere": "on-site outside Prague",
                "unknown": "work mode not stated"}


def summary(facts: dict, place: str, coverage, excluded, points: dict) -> str:
    if excluded:
        return f"Excluded: {excluded}."
    parts = [f"{facts.get('seniority', 'unknown')} {_ROLE_LABEL.get(facts.get('role_family'), 'role')}",
             _PLACE_LABEL.get(place, "")]
    if coverage is not None:
        parts.append(f"you know {round(coverage * 100)}% of the required stack")
    if facts.get("ai_focus") == "core":
        parts.append("AI is the core of the job")
    if facts.get("work_type") == "greenfield" and points.get("work_type", 0) > 0:
        parts.append("greenfield")
    if "german_required" in points:
        parts.append("German required")
    if "people_management" in points:
        parts.append("people management")
    return "; ".join(p for p in parts if p) + "."


def rank_all(jobs: list[dict], extracted: dict) -> list[dict]:
    """Ranked rows for every live job that has facts, best first."""
    rows = []
    for job in jobs:
        facts = extracted.get(job["job_id"])
        if not facts or job.get("expired_at"):
            continue
        rows.append({
            "job_id": job["job_id"], "title": job.get("title", ""), "company": job.get("company", ""),
            "location": job.get("location", ""), "url": job.get("url", ""),
            "source": job.get("source", ""), "salary": job.get("salary", ""),
            "scraped_at": job.get("scraped_at", ""), "first_seen_at": job.get("first_seen_at"),
            "times_seen": job.get("times_seen", 1),
            **score_job(facts, job),
            "facts": {k: facts.get(k) for k in ("role_family", "seniority", "work_mode", "city",
                                                 "required_languages", "stack_required",
                                                 "stack_nice_to_have", "employment", "ai_focus",
                                                 "work_type", "people_management", "evidence")},
            "ranked_at": datetime.now(timezone.utc).isoformat(),
        })
    rows.sort(key=lambda r: (r["score"], r["scraped_at"]), reverse=True)
    return rows


def _arg(flag: str, default=None):
    return sys.argv[sys.argv.index(flag) + 1] if flag in sys.argv else default


def run_ranking() -> list[dict]:
    """Score every extracted job and save data/ranked_jobs.json. Returns the rows, best first."""
    jobs = json.loads(RAW_JOBS_PATH.read_text(encoding="utf-8")) if RAW_JOBS_PATH.exists() else []
    extracted = json.loads(EXTRACTED_PATH.read_text(encoding="utf-8")) if EXTRACTED_PATH.exists() else {}
    rows = rank_all(jobs, extracted)
    RANKED_PATH.write_text(json.dumps(rows, ensure_ascii=False, indent=1), encoding="utf-8")
    return rows


def main() -> None:
    jobs = json.loads(RAW_JOBS_PATH.read_text(encoding="utf-8"))
    rows = run_ranking()

    if _arg("--job-id"):
        row = next((r for r in rows if r["job_id"] == _arg("--job-id")), None)
        print(json.dumps(row, ensure_ascii=False, indent=2) if row else "job not found or not extracted")
        return

    live = [j for j in jobs if not j.get("expired_at")]
    excluded = sum(1 for r in rows if r["excluded"])
    print(f"[rank] {len(rows)} jobs scored ({excluded} excluded), "
          f"{len(live) - len(rows)} live jobs have no facts yet (no description)")
    print(f"[rank] saved to {RANKED_PATH.relative_to(ROOT)}\n")
    for r in rows[:int(_arg("--top", 20))]:
        print(f"{r['score']:3}  {r['title'][:52]:52}  {r['company'][:24]:24}  {r['match_summary']}")


if __name__ == "__main__":
    main()
