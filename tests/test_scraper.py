"""
Offline tests for scraper helpers, ATS parsers and description extraction.
Run:  python -m unittest discover tests   (or: pytest tests)
"""

import html
import json
import unittest

from scraper.utils import canonical_url, make_id, fingerprint, is_allowed, is_relevant
from scraper.ats import parse_greenhouse, parse_lever, parse_ashby, location_ok
from scraper.details import extract_description, _detail_url
from scraper.scrape import merge_new

LONG = "We are looking for a senior data engineer to build BigQuery pipelines. " * 6


class TestUtils(unittest.TestCase):
    def test_jobs_cz_search_params_do_not_change_id(self):
        a = "https://www.jobs.cz/rpd/2001386551/?searchId=aaa&rps=233"
        b = "https://www.jobs.cz/rpd/2001386551/?searchId=bbb&rps=233"
        self.assertEqual(canonical_url(a), "https://www.jobs.cz/rpd/2001386551/")
        self.assertEqual(make_id(a), make_id(b))

    def test_other_hosts_keep_query(self):
        url = "https://example.com/job?id=5"
        self.assertEqual(canonical_url(url), url)

    def test_fingerprint_ignores_gender_tags_and_legal_forms(self):
        a = {"title": "Data Engineer (m/ž)", "company": "Alza.cz a.s."}
        b = {"title": "Data engineer", "company": "Alza.cz"}
        self.assertEqual(fingerprint(a), fingerprint(b))

    def test_blocked_spam(self):
        self.assertFalse(is_allowed({"title": "Fold Laundry (Paid Data Task)", "company": "Kled AI",
                                     "source": "himalayas", "location": "Worldwide"}))

    def test_location_filter_for_remote_boards(self):
        base = {"title": "Data Analyst", "company": "X", "source": "himalayas"}
        self.assertFalse(is_allowed({**base, "location": "United States"}))
        self.assertTrue(is_allowed({**base, "location": "Europe"}))
        self.assertTrue(is_allowed({**base, "location": "Remote (EU)"}))
        self.assertFalse(is_allowed({**base, "location": "Seoul"}))
        # sources outside the filter list are never location-filtered
        self.assertTrue(is_allowed({**base, "source": "jobs_cz", "location": "Brno"}))

    def test_relevance_includes_ai(self):
        self.assertTrue(is_relevant("AI Engineer - Memory"))
        self.assertFalse(is_relevant("Key Account Manager"))


class TestAtsParsers(unittest.TestCase):
    def test_greenhouse(self):
        data = {"jobs": [{
            "title": "Staff Data Engineer", "absolute_url": "https://boards.greenhouse.io/x/jobs/1",
            "location": {"name": "Prague, Czechia"},
            "content": html.escape(f"<p>{LONG}</p><ul><li>BigQuery</li></ul>"),
        }]}
        [job] = parse_greenhouse(data, "SentinelOne")
        self.assertEqual(job["source"], "greenhouse")
        self.assertEqual(job["location"], "Prague, Czechia")
        self.assertIn("BigQuery", job["description"])
        self.assertNotIn("&lt;", job["description"])

    def test_lever(self):
        data = [{
            "text": "Senior Analytics Engineer", "hostedUrl": "https://jobs.lever.co/x/1",
            "categories": {"location": "Prague", "allLocations": ["Prague", "Brno"]},
            "workplaceType": "hybrid", "descriptionPlain": LONG,
            "lists": [{"text": "Requirements", "content": "<li>SQL</li><li>dbt</li>"}],
            "salaryRange": {"currency": "CZK", "min": 100000, "max": 140000},
        }]
        [job] = parse_lever(data, "Pipedrive")
        self.assertEqual(job["location"], "Prague, Brno")
        self.assertIn("dbt", job["description"])
        self.assertEqual(job["salary"], "CZK 100000 – 140000")

    def test_ashby(self):
        data = {"jobs": [
            {"title": "Senior Product Data Engineer", "jobUrl": "https://jobs.ashbyhq.com/x/1",
             "location": "Europe", "isRemote": True, "descriptionPlain": LONG,
             "compensation": {"compensationTierSummary": "€100K – €130K"}},
            {"title": "Hidden", "jobUrl": "https://jobs.ashbyhq.com/x/2", "isListed": False},
        ]}
        jobs = parse_ashby(data, "Modash")
        self.assertEqual(len(jobs), 1)
        self.assertEqual(jobs[0]["location"], "Europe (Remote)")
        self.assertEqual(jobs[0]["salary"], "€100K – €130K")

    def test_location_ok(self):
        self.assertTrue(location_ok("Prague, Czechia"))
        self.assertTrue(location_ok("Remote - EMEA"))
        self.assertFalse(location_ok("New York, NY"))


class TestDetails(unittest.TestCase):
    def test_json_ld_job_posting(self):
        ld = json.dumps({"@context": "https://schema.org", "@type": "JobPosting",
                         "title": "Data Engineer", "description": f"<p>{LONG}</p>"})
        page = f'<html><head><script type="application/ld+json">{ld}</script></head><body></body></html>'
        self.assertIn("BigQuery pipelines", extract_description(page, "jobs_cz"))

    def test_linkedin_guest_fragment(self):
        page = f'<section><div class="show-more-less-html__markup"><p>{LONG}</p></div></section>'
        self.assertIn("senior data engineer", extract_description(page, "linkedin"))

    def test_generic_fallback_picks_main_block(self):
        page = (f"<html><body><nav><p>Menu item</p></nav>"
                f"<div class='content'><p>{LONG}</p><ul><li>Python</li><li>SQL</li></ul></div>"
                f"<footer><p>Cookies</p></footer></body></html>")
        text = extract_description(page, "jobstack")
        self.assertIn("Python", text)
        self.assertNotIn("Cookies", text)

    def test_linkedin_detail_url(self):
        job = {"source": "linkedin",
               "url": "https://cz.linkedin.com/jobs/view/sr-analytics-developer-at-idc-4454116870"}
        self.assertEqual(_detail_url(job),
                         "https://www.linkedin.com/jobs-guest/jobs/api/jobPosting/4454116870")


class TestEnrich(unittest.TestCase):
    def test_interleaves_sources_and_stops_failing_source(self):
        from unittest import mock
        import scraper.details as d
        jobs = ([{"source": "linkedin", "url": f"https://x/{i}", "description": ""} for i in range(10)]
                + [{"source": "jobs_cz", "url": f"https://y/{i}", "description": ""} for i in range(3)])
        calls = []

        def fake(job):
            calls.append(job["source"])
            if job["source"] == "linkedin":
                raise ConnectionError("Remote end closed connection")
            return "text"

        with mock.patch.object(d, "fetch_description", fake), mock.patch.object(d.time, "sleep"):
            filled = d.enrich_descriptions(jobs, limit=13)
        self.assertEqual(filled, 3)
        self.assertEqual(calls.count("linkedin"), d.MAX_CONSECUTIVE_ERRORS)
        self.assertEqual(calls[:2], ["linkedin", "jobs_cz"])


class TestFixes(unittest.TestCase):
    FOOTER = ("© Alma Career Czechia s.r.o. Vizuální podoba webové stránky může být rovněž "
              "předmětem autorských práv třetích stran. Webovou stránku pro klienta vytvořila "
              "a provozuje Alma Career Czechia s.r.o., IČO 26441381, Menclova 2538/2, Praha 8.")

    def test_footer_only_page_gives_empty_description(self):
        page = f"<html><body><div class='brand'><p>{self.FOOTER}</p><p>{self.FOOTER}</p></div></body></html>"
        self.assertEqual(extract_description(page, "jobs_cz"), "")

    def test_footer_next_to_content_is_ignored(self):
        page = (f"<html><body><div class='content'><p>{LONG}</p></div>"
                f"<div class='page-footer'><p>{self.FOOTER}</p><p>{self.FOOTER}</p></div></body></html>")
        text = extract_description(page, "jobs_cz")
        self.assertIn("BigQuery", text)
        self.assertNotIn("Alma Career", text)

    def test_linkedin_location_filter(self):
        base = {"title": "Analytics Engineer", "company": "X", "source": "linkedin"}
        self.assertTrue(is_allowed({**base, "location": "Prague, Prague, Czechia"}))
        self.assertTrue(is_allowed({**base, "location": "Czechia"}))
        self.assertFalse(is_allowed({**base, "location": "Lisbon, Lisbon, Portugal"}))

    def test_cleanup(self):
        from scraper.cleanup import cleanup
        jobs = {
            "1": {"source": "linkedin", "title": "Data Analyst", "company": "A", "location": "Paris, France"},
            "2": {"source": "jobs_cz", "title": "Datový analytik", "company": "O2",
                  "location": "Praha", "description": self.FOOTER},
            "3": {"source": "jobs_cz", "title": "Data Engineer", "company": "B",
                  "location": "Praha", "description": LONG},
        }
        kept, removed, cleared = cleanup(jobs)
        self.assertEqual(sorted(kept), ["2", "3"])
        self.assertEqual(removed["linkedin"], 1)
        self.assertEqual(cleared, 1)
        self.assertEqual(kept["2"]["description"], "")


class TestMerge(unittest.TestCase):
    def test_reposts_and_spam_are_skipped(self):
        existing = {"a1": {"job_id": "a1", "title": "Data Engineer (m/ž)", "company": "Alza.cz a.s."}}
        seen = {fingerprint(existing["a1"])}
        incoming = [
            {"job_id": "b2", "title": "Data Engineer", "company": "Alza.cz", "source": "jobs_cz"},
            {"job_id": "c3", "title": "Analytics Engineer", "company": "ISOS", "source": "jobs_cz"},
            {"job_id": "d4", "title": "Wash the Dishes (Paid Data Task)", "company": "Kled AI",
             "source": "himalayas", "location": "Worldwide"},
            {"job_id": "a1", "title": "Data Engineer", "company": "Alza.cz", "source": "jobs_cz"},
        ]
        added, skipped = merge_new(existing, incoming, seen)
        self.assertEqual([j["job_id"] for j in added], ["c3"])
        self.assertEqual(skipped, {"duplicate": 1, "repost": 1, "filtered": 1})


class TestTitleGate(unittest.TestCase):
    def test_entry_level_titles_are_excluded(self):
        from scraper.utils import title_excluded
        for t in ["Junior Data Analyst", "Data Analyst Intern", "Stážista – reporting",
                  "Data Analytics Trainee", "Absolvent/ka: datový analytik", "BI Analyst (Internship)",
                  "Werkstudent Data Engineering", "Brigáda: datová analytika"]:
            self.assertTrue(title_excluded(t), t)

    def test_business_analyst_roles_are_excluded_but_bi_is_kept(self):
        from scraper.utils import title_excluded
        self.assertTrue(title_excluded("IT Business Analyst"))
        self.assertTrue(title_excluded("Business analytik pro bankovní projekt"))
        self.assertTrue(title_excluded("IT analytik"))
        self.assertFalse(title_excluded("Business Intelligence Analyst"))
        self.assertFalse(title_excluded("BI analytik"))
        self.assertFalse(title_excluded("Datový analytik"))

    def test_similar_words_and_mixed_levels_are_kept(self):
        from scraper.utils import title_excluded
        for t in ["Internal Audit Data Analyst", "International Data Engineer",
                  "Senior Data Engineer", "Junior/Medior Data Engineer",
                  "Senior Business Analyst – Data", "AI Engineer"]:
            self.assertFalse(title_excluded(t), t)

    def test_gate_is_part_of_is_allowed(self):
        base = {"company": "X", "source": "jobs_cz", "location": "Praha"}
        self.assertFalse(is_allowed({**base, "title": "Junior BI Analyst"}))
        self.assertTrue(is_allowed({**base, "title": "Senior BI Analyst"}))


class TestDescriptions(unittest.TestCase):
    def test_long_description_is_stored_whole(self):
        long_text = "Requirement: SQL and BigQuery experience. " * 200      # ~8 400 chars
        page = f"<html><body><div class='content'><p>{long_text}</p><p>LAST LINE dbt</p></div></body></html>"
        text = extract_description(page, "jobs_cz")
        self.assertGreater(len(text), 8000)
        self.assertIn("LAST LINE dbt", text)

    def test_ats_description_is_not_cut_at_3000(self):
        data = {"jobs": [{"title": "Data Engineer", "absolute_url": "https://boards.greenhouse.io/x/jobs/2",
                          "location": {"name": "Prague"}, "content": html.escape(f"<p>{LONG * 20}</p>")}]}
        [job] = parse_greenhouse(data, "X")
        self.assertGreater(len(job["description"]), 3000)

    def test_needs_description(self):
        from scraper.utils import needs_description
        self.assertTrue(needs_description({"source": "jobs_cz", "description": ""}))
        self.assertTrue(needs_description({"source": "linkedin", "description": "x" * 3000}))   # old cut
        self.assertFalse(needs_description({"source": "linkedin", "description": "x" * 2999}))
        self.assertFalse(needs_description({"source": "jobs_cz", "description": LONG}))
        self.assertFalse(needs_description({"source": "remoteok", "description": ""}))          # no detail page

    def test_backfill_only_takes_recent_jobs_newest_first(self):
        from datetime import datetime, timedelta, timezone
        from scraper.details import recent_jobs
        now = datetime.now(timezone.utc)
        jobs = [{"job_id": "old", "scraped_at": (now - timedelta(days=45)).isoformat()},
                {"job_id": "mid", "scraped_at": (now - timedelta(days=10)).isoformat()},
                {"job_id": "new", "scraped_at": (now - timedelta(days=1)).isoformat()},
                {"job_id": "nodate"}]
        self.assertEqual([j["job_id"] for j in recent_jobs(jobs, 30)], ["new", "mid"])


class TestScoringLimits(unittest.TestCase):
    def setUp(self):
        try:
            import enrichment.score as score
        except ImportError as e:            # anthropic / dotenv not installed
            self.skipTest(str(e))
        self.score = score

    def test_cap_takes_newest_and_reports_the_rest(self):
        raw = [{"job_id": str(i), "title": "Data Engineer", "scraped_at": f"2026-11-{i:02d}"} for i in range(1, 11)]
        raw.append({"job_id": "x", "title": "Key Account Manager", "scraped_at": "2026-11-11"})
        jobs, irrelevant, deferred = self.score.select_jobs_to_score(raw, {"10"}, 3)
        self.assertEqual([j["job_id"] for j in jobs], ["9", "8", "7"])
        self.assertEqual((irrelevant, deferred), (1, 6))

    def test_switch_off_makes_no_api_call(self):
        from unittest import mock
        with mock.patch.object(self.score, "SCORING_ENABLED", False), \
             mock.patch.object(self.score.anthropic, "Anthropic") as client:
            self.score.main()
        client.assert_not_called()


class TestRelevance(unittest.TestCase):
    def test_short_words_match_whole_words_only(self):
        for t in ["Online Bidder", "Software Engineer III Mobile", "Presales Engineer (mobile private network)",
                  "Bid and Proposal Engineer", "Database administrator (MySQL)", "Key Account Manager"]:
            self.assertFalse(is_relevant(t), t)

    def test_data_bi_ai_titles_are_kept(self):
        for t in ["Fabric/PBI Consultant", "Senior AI/ML Engineer", "Head of AI", "BI konzultant",
                  "Datový inženýr", "Datová analytička", "Analytics Engineer", "LLM Engineer",
                  "Specialista reportingu", "DWH Developer", "Product Analyst", "Pricing Analyst",
                  "HR Data Analyst", "Vedoucí týmu umělé inteligence"]:
            self.assertTrue(is_relevant(t), t)


class TestDedupe(unittest.TestCase):
    def test_reposts_merge_into_newest_and_borrow_description(self):
        from scraper.cleanup import dedupe
        jobs = {
            "a": {"job_id": "a", "title": "Business Data Analyst", "company": "Skupina ČEZ",
                  "scraped_at": "2026-10-01T08:00:00", "description": LONG},
            "b": {"job_id": "b", "title": "Business Data Analyst (m/ž)", "company": "Skupina ČEZ, a.s.",
                  "scraped_at": "2026-11-10T08:00:00", "description": ""},
            "c": {"job_id": "c", "title": "Business Data Analyst", "company": "Skupina ČEZ",
                  "scraped_at": "2026-10-20T08:00:00", "description": ""},
            "d": {"job_id": "d", "title": "Data Engineer", "company": "Alza",
                  "scraped_at": "2026-11-01T08:00:00", "description": "short"},
        }
        kept, merged = dedupe(jobs)
        self.assertEqual(sorted(kept), ["b", "d"])
        self.assertEqual(merged, 2)
        self.assertEqual(kept["b"]["description"], LONG.strip())
        self.assertEqual(kept["b"]["first_seen_at"], "2026-10-01T08:00:00")
        self.assertEqual(kept["b"]["times_seen"], 3)
        self.assertNotIn("times_seen", kept["d"])

    def test_newest_description_is_not_replaced(self):
        from scraper.cleanup import dedupe
        jobs = {
            "a": {"job_id": "a", "title": "BI Analyst", "company": "X", "scraped_at": "2026-10-01", "description": LONG},
            "b": {"job_id": "b", "title": "BI Analyst", "company": "X", "scraped_at": "2026-11-01", "description": "new text"},
        }
        kept, _ = dedupe(jobs)
        self.assertEqual(kept["b"]["description"], "new text")


class TestExpired(unittest.TestCase):
    def _http_error(self, code):
        import requests
        resp = requests.Response(); resp.status_code = code
        return requests.HTTPError(f"{code} Client Error", response=resp)

    def test_404_marks_expired_and_does_not_block_source(self):
        from unittest import mock
        import scraper.details as d
        jobs = [{"source": "jobs_cz", "url": f"https://y/{i}", "description": ""} for i in range(6)]

        def fake(job):
            if job["url"] != "https://y/5":
                raise self._http_error(404)
            return "text"

        with mock.patch.object(d, "fetch_description", fake), mock.patch.object(d.time, "sleep"):
            filled = d.enrich_descriptions(jobs, limit=6)
        self.assertEqual(filled, 1)                                   # last job still reached
        self.assertTrue(all(j.get("expired_at") for j in jobs[:5]))
        from scraper.utils import needs_description
        self.assertFalse(any(needs_description(j) for j in jobs))

    def test_429_still_blocks(self):
        from unittest import mock
        import scraper.details as d
        jobs = [{"source": "linkedin", "url": f"https://x/{i}", "description": ""} for i in range(4)]
        calls = []
        def fake(job):
            calls.append(job["url"]); raise self._http_error(429)
        with mock.patch.object(d, "fetch_description", fake), mock.patch.object(d.time, "sleep"):
            d.enrich_descriptions(jobs, limit=4)
        self.assertEqual(len(calls), 1)
        self.assertFalse(any(j.get("expired_at") for j in jobs))

    def test_empty_page_is_given_up_after_attempts(self):
        from unittest import mock
        import scraper.details as d
        from scraper.utils import needs_description
        job = {"source": "jobs_cz", "url": "https://y/1", "description": ""}
        with mock.patch.object(d, "fetch_description", lambda j: ""), mock.patch.object(d.time, "sleep"):
            d.enrich_descriptions([job], limit=1)
            self.assertTrue(needs_description(job))
            d.enrich_descriptions([job], limit=1)
        self.assertFalse(needs_description(job))


if __name__ == "__main__":
    unittest.main()
