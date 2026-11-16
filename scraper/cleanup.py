"""
scraper/cleanup.py

One-off clean-up of data/raw_jobs.json after filters change:
  - removes stored jobs that no longer pass is_allowed() (spam, excluded titles
    such as junior / internship, foreign on-site LinkedIn jobs, non-EU remote jobs)
  - removes stored jobs whose title is no longer relevant (config.RELEVANT_TITLE_PATTERNS)
  - clears descriptions that are only page boilerplate, so the next
    `python -m scraper.details --backfill N` fetches them again
  - merges repeated postings (same title + company) into the newest one; older
    versions stored the same jobs.cz posting under a new id on every run

  python -m scraper.cleanup            # dry run – prints what would change
  python -m scraper.cleanup --apply    # writes the cleaned file (keeps a .bak copy)
"""

import shutil
import sys
from collections import Counter
from datetime import datetime

from scraper.scrape import RAW_JOBS_PATH, load_existing, save_jobs
from scraper.utils import is_allowed, is_boilerplate, is_relevant, fingerprint


def cleanup(jobs: dict) -> tuple[dict, Counter, int]:
    kept, removed, cleared = {}, Counter(), 0
    for job_id, job in jobs.items():
        if not is_allowed(job) or not is_relevant(job.get("title", "")):
            removed[job.get("source", "?")] += 1
            continue
        if is_boilerplate(job.get("description", "")):
            job["description"] = ""
            cleared += 1
        kept[job_id] = job
    return kept, removed, cleared


def _usable(text: str) -> str:
    text = (text or "").strip()
    return "" if is_boilerplate(text) else text


def dedupe(jobs: dict) -> tuple[dict, int]:
    """Merge postings with the same title + company into one record.

    The newest record wins (its link is the one most likely still open). If it
    has no description, the longest one found in the group is used. The kept
    record gets `first_seen_at` (oldest scrape date in the group) and
    `times_seen` (how many records were merged), so long-running reposts stay visible.
    """
    groups: dict[str, list[dict]] = {}
    for job in jobs.values():
        groups.setdefault(fingerprint(job), []).append(job)

    kept = {}
    for group in groups.values():
        group.sort(key=lambda j: j.get("scraped_at", ""), reverse=True)
        best = group[0]
        if len(group) > 1:
            if not _usable(best.get("description")):
                best["description"] = max((_usable(j.get("description")) for j in group), key=len)
            dates = [j.get("first_seen_at") or j.get("scraped_at", "") for j in group]
            best["first_seen_at"] = min((d for d in dates if d), default="")
            best["times_seen"] = sum(j.get("times_seen", 1) for j in group)
        kept[best["job_id"]] = best
    return kept, len(jobs) - len(kept)


if __name__ == "__main__":
    apply = "--apply" in sys.argv
    jobs = load_existing(RAW_JOBS_PATH)
    kept, removed, cleared = cleanup(jobs)
    print(f"[cleanup] {len(jobs)} jobs → {len(kept)} kept, "
          f"{sum(removed.values())} removed {dict(removed)}, {cleared} boilerplate descriptions cleared")
    kept, merged = dedupe(kept)
    print(f"[cleanup] {merged} repeated postings merged → {len(kept)} unique jobs")
    if apply:
        backup = RAW_JOBS_PATH.with_name(f"raw_jobs.{datetime.now():%Y%m%d-%H%M%S}.json.bak")
        shutil.copy(RAW_JOBS_PATH, backup)
        save_jobs(RAW_JOBS_PATH, kept)
        print(f"[cleanup] saved (backup: {backup.name})")
    else:
        print("[cleanup] dry run – add --apply to save")
