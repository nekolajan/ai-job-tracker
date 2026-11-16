"""Tests for enrichment/rank.py – pure functions, no model."""

import unittest

from enrichment.rank import score_job, tool_level, place_key, rank_all

BASE = {"role_family": "data_engineer", "seniority": "senior", "people_management": False,
        "work_mode": "hybrid", "office_days_per_week": 2, "city": "Prague",
        "residency_required": False, "required_languages": ["english"],
        "stack_required": ["SQL", "Python", "BigQuery"], "stack_nice_to_have": ["dbt"],
        "employment": "employee", "ai_focus": "core", "work_type": "greenfield", "evidence": ""}
JOB = {"job_id": "a", "title": "Senior Data Engineer", "location": "Prague, Czechia"}


class TestRank(unittest.TestCase):
    def test_tool_levels(self):
        self.assertEqual(tool_level("bigquery"), 1.0)
        self.assertEqual(tool_level("Snowflake"), 0.5)
        self.assertEqual(tool_level("Java"), 0.0)
        self.assertEqual(tool_level("Microsoft Excel"), 1.0)      # alias → Excel

    def test_strong_match_scores_high_with_breakdown(self):
        r = score_job(BASE, JOB)
        self.assertGreaterEqual(r["score"], 80)
        self.assertEqual(r["points"]["work_type"], 0)        # greenfield is not scored
        self.assertNotIn("greenfield", r["match_summary"])
        self.assertEqual(r["points"]["stack"], 20)          # (3 + 1) / 5 × 25
        self.assertIsNone(r["excluded"])
        self.assertEqual(r["gaps"], [])
        self.assertTrue(r["remote_match"])
        self.assertIn("hybrid in Prague", r["match_summary"])

    def test_short_tool_list_does_not_give_full_points(self):
        one = score_job({**BASE, "stack_required": ["Python"]}, JOB)["points"]["stack"]
        many = score_job({**BASE, "stack_required": ["SQL", "Python", "BigQuery", "Airflow",
                                                      "Power BI", "Tableau", "Keboola", "Git"]}, JOB)["points"]["stack"]
        self.assertAlmostEqual(one, 16.7, places=1)
        self.assertGreater(many, 22)

    def test_penalties(self):
        r = score_job({**BASE, "required_languages": ["english", "german"], "people_management": True}, JOB)
        self.assertEqual(r["points"]["german_required"], -25)
        self.assertEqual(r["points"]["people_management"], -10)
        self.assertLess(r["score"], score_job(BASE, JOB)["score"] - 30)

    def test_gaps_and_partial_skills(self):
        r = score_job({**BASE, "stack_required": ["SQL", "Snowflake", "Java", "Scala"]}, JOB)
        self.assertEqual(r["stack_coverage"], 0.38)              # (1 + 0.5 + 0 + 0) / 4
        self.assertEqual(r["gaps"], ["Java", "Scala"])

    def test_exclusions(self):
        self.assertEqual(score_job({**BASE, "seniority": "junior"}, JOB)["score"], 0)
        abroad = {**JOB, "location": "Berlin, Germany"}
        r = score_job({**BASE, "residency_required": True, "city": "Berlin"}, abroad)
        self.assertEqual(r["score"], 0)
        self.assertIn("another country", r["excluded"])
        # residency in Czechia is fine
        self.assertIsNone(score_job({**BASE, "residency_required": True}, JOB)["excluded"])

    def test_software_titles_score_as_development(self):
        from enrichment.rank import role_family
        ai = {**BASE, "role_family": "ml_ai_engineer"}
        for title in ["Staff Software Engineer | AI", "Senior Software Engineer, AI Search",
                      "AI Software Developer", "(Sr.) AI Python Developer", "Programátor / Analytik",
                      "Senior genAI/LLM application developer", "Software Engineer, AI Coding Tasks"]:
            self.assertEqual(role_family(ai, {"title": title}), "software_engineer", title)
        for title in ["Data Engineer / Software Engineer", "Senior Software Engineer, Data Pipeline",
                      "BI Developer", "SQL Developer LOGISTIKA", "Senior AI Engineer", "Power BI Developer/Analyst",
                      "SENIOR DATOVÝ ANALYTIK/PROGRAMÁTOR"]:
            self.assertNotEqual(role_family(ai, {"title": title}), "software_engineer", title)
        dev = score_job(ai, {**JOB, "title": "Staff Software Engineer | AI"})
        self.assertEqual(dev["points"]["role"], 5)
        self.assertIn("software development", dev["match_summary"])

    def test_place(self):
        self.assertEqual(place_key({"work_mode": "hybrid", "city": "Brno"}, {"location": "Brno"}), "hybrid_elsewhere")
        self.assertEqual(place_key({"work_mode": "onsite", "city": None}, {"location": "Praha – Karlín"}), "onsite_home")
        self.assertEqual(place_key({"work_mode": "remote"}, {}), "remote")

    def test_rank_all_skips_expired_and_unextracted_and_sorts(self):
        jobs = [JOB, {**JOB, "job_id": "b"}, {**JOB, "job_id": "c", "expired_at": "x"}, {**JOB, "job_id": "d"}]
        extracted = {"a": {**BASE, "ai_focus": "none"}, "b": BASE, "c": BASE}
        rows = rank_all(jobs, extracted)
        self.assertEqual([r["job_id"] for r in rows], ["b", "a"])


if __name__ == "__main__":
    unittest.main()
