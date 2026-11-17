"""
storage/local_db.py

Local SQLite database (data/jobs.db) behind the dashboard – free, one file, no
server. Two tables:

  jobs            rebuilt from data/raw_jobs.json + data/ranked_jobs.json after
                  every pipeline run (those files stay the source of truth)
  status_history  your status changes from the dashboard, append-only, never
                  rebuilt – the newest row per job wins

Usage:
    python -m storage.local_db          # rebuild the jobs table now
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).parent.parent
DB_PATH = ROOT / "data" / "jobs.db"
RAW_JOBS_PATH = ROOT / "data" / "raw_jobs.json"
RANKED_PATH = ROOT / "data" / "ranked_jobs.json"

SCHEMA = """
CREATE TABLE IF NOT EXISTS jobs (
    job_id          TEXT PRIMARY KEY,
    title           TEXT,
    company         TEXT,
    location        TEXT,
    url             TEXT,
    source          TEXT,
    salary          TEXT,
    scraped_at      TEXT,
    first_seen_at   TEXT,
    times_seen      INTEGER,
    has_description INTEGER,
    score           INTEGER,          -- NULL = not scored yet (no description)
    excluded        TEXT,             -- reason, or NULL
    role_family     TEXT,
    match_summary   TEXT,
    skills_match    TEXT,             -- JSON list
    gaps            TEXT,             -- JSON list
    seniority_match INTEGER,
    remote_match    INTEGER,
    points          TEXT,             -- JSON: where the score came from
    facts           TEXT,             -- JSON: what the model extracted
    ranked_at       TEXT
);
CREATE TABLE IF NOT EXISTS status_history (
    job_id     TEXT NOT NULL,
    status     TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    source     TEXT DEFAULT 'dashboard',
    UNIQUE (job_id, status, updated_at)
);
CREATE INDEX IF NOT EXISTS ix_status_job ON status_history (job_id, updated_at);
"""


def connect(path: Path = DB_PATH) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(path)
    con.executescript(SCHEMA)
    return con


def _load(path: Path):
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else []


def sync(raw_path: Path = RAW_JOBS_PATH, ranked_path: Path = RANKED_PATH,
         db_path: Path = DB_PATH) -> int:
    """Rebuild the jobs table from the JSON files. Status history is not touched.
    Expired postings are left out unless you gave them a status."""
    raw = _load(raw_path)
    ranked = {r["job_id"]: r for r in _load(ranked_path)}
    with connect(db_path) as con:
        with_status = {row[0] for row in con.execute("SELECT DISTINCT job_id FROM status_history")}
        rows = []
        for j in raw:
            if j.get("expired_at") and j["job_id"] not in with_status:
                continue
            r = ranked.get(j["job_id"], {})
            rows.append((
                j["job_id"], j.get("title", ""), j.get("company", ""), j.get("location", ""),
                j.get("url", ""), j.get("source", ""), j.get("salary") or "", j.get("scraped_at", ""),
                j.get("first_seen_at") or j.get("scraped_at", ""), j.get("times_seen", 1),
                int(bool((j.get("description") or "").strip())),
                r.get("score"), r.get("excluded"), r.get("role_family"), r.get("match_summary"),
                json.dumps(r.get("skills_match") or [], ensure_ascii=False),
                json.dumps(r.get("gaps") or [], ensure_ascii=False),
                None if not r else int(bool(r.get("seniority_match"))),
                None if not r else int(bool(r.get("remote_match"))),
                json.dumps(r.get("points") or {}, ensure_ascii=False),
                json.dumps(r.get("facts") or {}, ensure_ascii=False),
                r.get("ranked_at"),
            ))
        con.execute("DELETE FROM jobs")
        con.executemany(f"INSERT INTO jobs VALUES ({','.join('?' * 22)})", rows)
    return len(rows)


def add_status(job_id: str, status: str, updated_at: str | None = None,
               source: str = "dashboard", db_path: Path = DB_PATH) -> None:
    with connect(db_path) as con:
        con.execute(
            "INSERT OR IGNORE INTO status_history (job_id, status, updated_at, source) VALUES (?, ?, ?, ?)",
            (job_id, status, updated_at or datetime.now(timezone.utc).isoformat(), source),
        )


DASHBOARD_QUERY = """
WITH latest AS (
    SELECT job_id, status,
           ROW_NUMBER() OVER (PARTITION BY job_id ORDER BY updated_at DESC) AS rn
    FROM status_history
)
SELECT j.job_id, j.title, j.company, j.location, j.url, j.source, j.salary,
       j.score, j.excluded, j.role_family, j.match_summary, j.skills_match, j.gaps,
       j.seniority_match, j.remote_match, j.points, j.facts, j.times_seen,
       COALESCE(l.status, 'new') AS status,
       substr(j.scraped_at, 1, 10)   AS date_scraped,
       substr(j.first_seen_at, 1, 10) AS first_seen
FROM jobs j
LEFT JOIN latest l ON l.job_id = j.job_id AND l.rn = 1
ORDER BY j.score IS NULL, j.score DESC, j.scraped_at DESC
"""


def load_for_dashboard(db_path: Path = DB_PATH):
    import pandas as pd
    with connect(db_path) as con:
        df = pd.read_sql_query(DASHBOARD_QUERY, con)
    for col in ("seniority_match", "remote_match"):
        df[col] = df[col].map(lambda v: None if v is None or v != v else bool(v))
    return df


if __name__ == "__main__":
    n = sync()
    with connect() as con:
        scored = con.execute("SELECT COUNT(*) FROM jobs WHERE score IS NOT NULL").fetchone()[0]
        statuses = con.execute("SELECT COUNT(DISTINCT job_id) FROM status_history").fetchone()[0]
    print(f"[db] {n} jobs in {DB_PATH.relative_to(ROOT)} ({scored} scored), {statuses} with a status")
