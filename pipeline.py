"""
pipeline.py

The whole daily run in one command – free, nothing leaves this computer except
the requests to the job boards:

  1. scrape     new postings from all sources, with descriptions (scraper/)
  2. extract    facts from new descriptions with the local model (Ollama)
  3. rank       score everything from the facts (config.py weights)
  4. database   refresh data/jobs.db for the dashboard (your statuses are kept)

Each step runs even if an earlier one failed (e.g. Ollama not running → the
ranking still runs on the facts already extracted).

Usage:
    python -m pipeline                 # full run
    python -m pipeline --skip-scrape   # only extract + rank
    python -m pipeline --extract-limit 10

Scheduled daily on macOS with deploy/install_schedule.sh.
"""

import sys
import time
from datetime import datetime

from config import MAX_EXTRACTIONS_PER_RUN, SCORE_THRESHOLD_GOOD


def _step(name: str, fn):
    started = time.time()
    print(f"\n=== {name} ({datetime.now():%Y-%m-%d %H:%M}) ===", flush=True)
    try:
        result = fn()
        print(f"=== {name} finished in {time.time() - started:.0f}s", flush=True)
        return True, result
    except Exception as e:                       # one broken step must not stop the run
        print(f"=== {name} FAILED after {time.time() - started:.0f}s: {e}", flush=True)
        return False, None


def _arg(flag: str, default=None):
    return sys.argv[sys.argv.index(flag) + 1] if flag in sys.argv else default


def main() -> int:
    from scraper.scrape import scrape_all
    from enrichment.extract import run_extraction
    from enrichment.rank import run_ranking
    from storage.local_db import sync

    summary = {}
    if "--skip-scrape" not in sys.argv:
        summary["scrape"], _ = _step("scrape", scrape_all)

    ok, result = _step("extract", lambda: run_extraction(int(_arg("--extract-limit", MAX_EXTRACTIONS_PER_RUN))))
    if ok and result and result.get("problem"):
        print(f"[extract] skipped: {result['problem']}")
        ok = False
    summary["extract"] = ok

    ok, rows = _step("rank", run_ranking)
    summary["rank"] = ok

    ok, n = _step("database", sync)
    summary["database"] = ok
    if ok:
        print(f"[db] {n} jobs in data/jobs.db")

    print("\n=== summary")
    print("   " + "  ".join(f"{k}: {'ok' if v else 'FAILED'}" for k, v in summary.items()))
    if rows:
        today = datetime.now().strftime("%Y-%m-%d")
        fresh = [r for r in rows if r["scraped_at"][:10] == today and r["score"] >= SCORE_THRESHOLD_GOOD]
        print(f"   {len(rows)} jobs ranked, {sum(r['score'] >= SCORE_THRESHOLD_GOOD for r in rows)} "
              f"at {SCORE_THRESHOLD_GOOD}+ points, {len(fresh)} of them new today")
        for r in fresh[:10]:
            print(f"   {r['score']:3}  {r['title'][:55]}  @ {r['company'][:25]}")
    return 0 if all(summary.values()) else 1


if __name__ == "__main__":
    sys.exit(main())
