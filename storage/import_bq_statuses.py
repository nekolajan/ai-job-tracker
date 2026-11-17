"""
storage/import_bq_statuses.py

One-off: copies your Kanban statuses from BigQuery (status_overrides) into the
local database, so nothing is lost when the dashboard switches to SQLite.

Older runs stored some jobs under a different id (jobs.cz links still had
tracking parameters), so each BigQuery job is matched to a local one by:
  1. the same job_id
  2. the id of its cleaned-up link
  3. the same title + company

Usage (needs the BigQuery settings in .env, as the old dashboard did):
    python -m storage.import_bq_statuses           # dry run – shows what would be imported
    python -m storage.import_bq_statuses --apply
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

from scraper.utils import make_id, fingerprint
from storage.local_db import add_status, RAW_JOBS_PATH


def fetch_bigquery_statuses() -> list[dict]:
    from google.cloud import bigquery
    from google.oauth2 import service_account
    project = os.environ["GCP_PROJECT_ID"]
    creds_json = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS_JSON")
    if creds_json:
        creds = service_account.Credentials.from_service_account_info(
            json.loads(creds_json), scopes=["https://www.googleapis.com/auth/cloud-platform"])
        client = bigquery.Client(project=project, credentials=creds)
    else:
        client = bigquery.Client(project=project)
    ds = f"{project}.{os.environ['BQ_DATASET']}"
    query = f"""
        SELECT o.job_id, o.status, CAST(o.updated_at AS STRING) AS updated_at,
               j.title, j.company, j.url
        FROM `{ds}.status_overrides` o
        LEFT JOIN (SELECT job_id, ANY_VALUE(title) title, ANY_VALUE(company) company, ANY_VALUE(url) url
                   FROM `{ds}.{os.environ['BQ_TABLE']}` GROUP BY job_id) j USING (job_id)
        ORDER BY o.updated_at
    """
    return [dict(row) for row in client.query(query).result()]


def match_statuses(bq_rows: list[dict], local_jobs: list[dict]) -> tuple[list[tuple], list[dict]]:
    """Returns ([(local_job_id, status, updated_at)], [bq rows with no local match])."""
    by_id = {j["job_id"] for j in local_jobs}
    by_fp = {fingerprint(j): j["job_id"] for j in local_jobs}
    matched, missing = [], []
    for row in bq_rows:
        local = None
        if row["job_id"] in by_id:
            local = row["job_id"]
        elif row.get("url") and make_id(row["url"]) in by_id:
            local = make_id(row["url"])
        elif row.get("title") and fingerprint(row) in by_fp:
            local = by_fp[fingerprint(row)]
        if local:
            matched.append((local, row["status"], row["updated_at"]))
        else:
            missing.append(row)
    return matched, missing


def main() -> None:
    from dotenv import load_dotenv
    load_dotenv()
    rows = fetch_bigquery_statuses()
    local_jobs = json.loads(Path(RAW_JOBS_PATH).read_text(encoding="utf-8"))
    matched, missing = match_statuses(rows, local_jobs)
    print(f"[import] {len(rows)} status changes in BigQuery: {len(matched)} matched to local jobs, "
          f"{len(missing)} without a local job")
    for m in missing[:15]:
        print(f"   not found: {m.get('title')} @ {m.get('company')} → {m['status']}")
    if "--apply" not in sys.argv:
        print("[import] dry run – add --apply to copy them into data/jobs.db")
        return
    for job_id, status, updated_at in matched:
        add_status(job_id, status, updated_at, source="bigquery")
    print(f"[import] {len(matched)} status changes copied")


if __name__ == "__main__":
    main()
