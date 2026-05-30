"""
storage/bigquery.py

Loads scored jobs from data/scored_jobs.json into BigQuery.
Idempotent — safe to re-run, skips already-loaded job_ids.
"""

import json
import os
from pathlib import Path
from datetime import datetime, timezone

from google.cloud import bigquery
from google.oauth2 import service_account
from dotenv import load_dotenv

load_dotenv()

SCORED_JOBS_PATH = Path(__file__).parent.parent / "data" / "scored_jobs.json"

TABLE_SCHEMA = [
    bigquery.SchemaField("job_id",          "STRING",    mode="REQUIRED"),
    bigquery.SchemaField("title",           "STRING",    mode="NULLABLE"),
    bigquery.SchemaField("company",         "STRING",    mode="NULLABLE"),
    bigquery.SchemaField("location",        "STRING",    mode="NULLABLE"),
    bigquery.SchemaField("url",             "STRING",    mode="NULLABLE"),
    bigquery.SchemaField("source",          "STRING",    mode="NULLABLE"),
    bigquery.SchemaField("salary",          "STRING",    mode="NULLABLE"),
    bigquery.SchemaField("scraped_at",      "TIMESTAMP", mode="NULLABLE"),
    bigquery.SchemaField("score",           "INTEGER",   mode="NULLABLE"),
    bigquery.SchemaField("match_summary",   "STRING",    mode="NULLABLE"),
    bigquery.SchemaField("skills_match",    "STRING",    mode="REPEATED"),
    bigquery.SchemaField("gaps",            "STRING",    mode="REPEATED"),
    bigquery.SchemaField("seniority_match", "BOOLEAN",   mode="NULLABLE"),
    bigquery.SchemaField("remote_match",    "BOOLEAN",   mode="NULLABLE"),
    bigquery.SchemaField("status",          "STRING",    mode="NULLABLE"),
    bigquery.SchemaField("loaded_at",       "TIMESTAMP", mode="REQUIRED"),
]


def get_client() -> bigquery.Client:
    project = os.environ["GCP_PROJECT_ID"]
    creds_json = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS_JSON")
    if creds_json:
        info = json.loads(creds_json)
        creds = service_account.Credentials.from_service_account_info(
            info,
            scopes=["https://www.googleapis.com/auth/cloud-platform"],
        )
        return bigquery.Client(project=project, credentials=creds)
    return bigquery.Client(project=project)


def ensure_table(client: bigquery.Client, table_ref: str) -> None:
    dataset_id = os.environ["BQ_DATASET"]
    dataset_ref = bigquery.DatasetReference(client.project, dataset_id)

    try:
        client.get_dataset(dataset_ref)
    except Exception:
        client.create_dataset(bigquery.Dataset(dataset_ref))
        print(f"[bigquery] created dataset {dataset_id}")

    try:
        client.get_table(table_ref)
    except Exception:
        table = bigquery.Table(table_ref, schema=TABLE_SCHEMA)
        table.time_partitioning = bigquery.TimePartitioning(
            type_=bigquery.TimePartitioningType.DAY,
            field="scraped_at",
        )
        client.create_table(table)
        print(f"[bigquery] created table {table_ref}")


def get_existing_ids(client: bigquery.Client, table_ref: str) -> set[str]:
    try:
        result = client.query(f"SELECT job_id FROM `{table_ref}`")
        return {row.job_id for row in result}
    except Exception:
        return set()


def load_jobs(jobs: list[dict], client: bigquery.Client, table_ref: str) -> int:
    if not jobs:
        print("[bigquery] no jobs to load")
        return 0

    now = datetime.now(timezone.utc).isoformat()
    rows = [
        {
            "job_id":          j.get("job_id", ""),
            "title":           j.get("title", ""),
            "company":         j.get("company", ""),
            "location":        j.get("location", ""),
            "url":             j.get("url", ""),
            "source":          j.get("source", ""),
            "salary":          j.get("salary", ""),
            "scraped_at":      j.get("scraped_at", now),
            "score":           j.get("score"),
            "match_summary":   j.get("match_summary", ""),
            "skills_match":    j.get("skills_match", []),
            "gaps":            j.get("gaps", []),
            "seniority_match": j.get("seniority_match"),
            "remote_match":    j.get("remote_match"),
            "status":          j.get("status", "new"),
            "loaded_at":       now,
        }
        for j in jobs
    ]

    errors = client.insert_rows_json(table_ref, rows)
    if errors:
        print(f"[bigquery] insert errors: {errors}")
        raise RuntimeError("BigQuery insert failed")

    print(f"[bigquery] inserted {len(rows)} rows into {table_ref}")
    return len(rows)


def run() -> None:
    if not SCORED_JOBS_PATH.exists():
        print("[bigquery] no scored_jobs.json found — skipping")
        return

    jobs = json.loads(SCORED_JOBS_PATH.read_text(encoding="utf-8"))
    print(f"[bigquery] loaded {len(jobs)} scored jobs from file")

    client = get_client()
    table_ref = f"{client.project}.{os.environ['BQ_DATASET']}.{os.environ['BQ_TABLE']}"

    ensure_table(client, table_ref)

    existing_ids = get_existing_ids(client, table_ref)
    new_jobs = [j for j in jobs if j.get("job_id") not in existing_ids]
    print(f"[bigquery] {len(new_jobs)} new jobs to insert (skipping {len(jobs) - len(new_jobs)} already loaded)")

    load_jobs(new_jobs, client, table_ref)


if __name__ == "__main__":
    run()
