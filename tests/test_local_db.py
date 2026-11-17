"""Tests for the local SQLite storage and the BigQuery status import matching."""

import json
import tempfile
import unittest
from pathlib import Path

from storage import local_db
from storage.import_bq_statuses import match_statuses


class TestLocalDb(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())
        self.db = self.dir / "jobs.db"
        self.raw = self.dir / "raw.json"
        self.ranked = self.dir / "ranked.json"
        self.raw.write_text(json.dumps([
            {"job_id": "a", "title": "Data Engineer", "company": "X", "scraped_at": "2026-11-10T08:00", "description": "text"},
            {"job_id": "b", "title": "BI Analyst", "company": "Y", "scraped_at": "2026-11-12T08:00", "description": ""},
            {"job_id": "c", "title": "Old", "company": "Z", "scraped_at": "2026-10-01", "expired_at": "2026-11-01"},
        ]))
        self.ranked.write_text(json.dumps([
            {"job_id": "a", "score": 81, "excluded": None, "role_family": "data_engineer",
             "match_summary": "senior data engineering.", "skills_match": ["SQL"], "gaps": ["Java"],
             "seniority_match": True, "remote_match": False, "points": {"role": 25}, "facts": {}},
        ]))

    def test_sync_and_load(self):
        try:
            import pandas  # noqa: F401
        except ImportError:
            self.skipTest("pandas not installed")
        n = local_db.sync(self.raw, self.ranked, self.db)
        self.assertEqual(n, 2)                                    # expired job left out
        local_db.add_status("a", "saved", "2026-11-11T10:00", db_path=self.db)
        local_db.add_status("a", "applied", "2026-11-12T10:00", db_path=self.db)
        df = local_db.load_for_dashboard(self.db)
        a = df[df.job_id == "a"].iloc[0]
        self.assertEqual(a.status, "applied")                     # newest status wins
        self.assertEqual(a.score, 81)
        self.assertEqual(json.loads(a.gaps), ["Java"])
        self.assertIs(a.seniority_match, True)
        b = df[df.job_id == "b"].iloc[0]
        self.assertEqual(b.status, "new")
        self.assertTrue(b.score != b.score)                       # NaN: not scored
        self.assertEqual(list(df.job_id), ["a", "b"])             # scored first

    def test_statuses_survive_rebuild_and_keep_expired_jobs(self):
        try:
            import pandas  # noqa: F401
        except ImportError:
            self.skipTest("pandas not installed")
        local_db.sync(self.raw, self.ranked, self.db)
        local_db.add_status("c", "applied", "2026-10-05", db_path=self.db)
        local_db.add_status("c", "applied", "2026-10-05", db_path=self.db)   # duplicate ignored
        local_db.sync(self.raw, self.ranked, self.db)
        df = local_db.load_for_dashboard(self.db)
        self.assertIn("c", set(df.job_id))                        # has a status → kept
        with local_db.connect(self.db) as con:
            self.assertEqual(con.execute("SELECT COUNT(*) FROM status_history").fetchone()[0], 1)


class TestImportMatching(unittest.TestCase):
    def test_match_by_id_link_and_title(self):
        local = [{"job_id": "id1", "title": "Data Engineer", "company": "Alza", "url": "u1"},
                 {"job_id": "f5d2c1a0b3e4", "title": "BI Analyst", "company": "ČEZ", "url": "https://www.jobs.cz/rpd/1/"},
                 {"job_id": "id3", "title": "Analytics Engineer (m/ž)", "company": "Make s.r.o.", "url": "u3"}]
        from scraper.utils import make_id
        local[1]["job_id"] = make_id("https://www.jobs.cz/rpd/1/")
        bq = [{"job_id": "id1", "status": "saved", "updated_at": "t1"},
              {"job_id": "old", "status": "applied", "updated_at": "t2", "url": "https://www.jobs.cz/rpd/1/?searchId=x"},
              {"job_id": "old2", "status": "rejected", "updated_at": "t3", "title": "Analytics Engineer", "company": "Make"},
              {"job_id": "gone", "status": "saved", "updated_at": "t4", "title": "Nothing", "company": "Nobody"}]
        matched, missing = match_statuses(bq, local)
        self.assertEqual(matched, [("id1", "saved", "t1"), (local[1]["job_id"], "applied", "t2"),
                                   ("id3", "rejected", "t3")])
        self.assertEqual([m["job_id"] for m in missing], ["gone"])


if __name__ == "__main__":
    unittest.main()
