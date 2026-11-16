"""Offline tests for enrichment/extract.py – the Ollama call is mocked."""

import json
import unittest
from unittest import mock

import enrichment.extract as ex

DESC = "We are looking for a Senior Data Engineer. Requirements: SQL, BigQuery, dbt. " * 5


class TestCondense(unittest.TestCase):
    def test_short_text_is_only_tidied(self):
        self.assertEqual(ex.condense("a  b\n\n\n c"), "a b\n c")

    def test_long_text_keeps_start_and_end(self):
        text = "START " + "x" * 10000 + " END-REQUIREMENTS"
        out = ex.condense(text, 1000)
        self.assertLessEqual(len(out), 1000)
        self.assertTrue(out.startswith("START"))
        self.assertTrue(out.endswith("END-REQUIREMENTS"))


class TestValidate(unittest.TestCase):
    def test_bad_values_become_safe_defaults(self):
        facts = ex.validate({"role_family": "Wizard", "seniority": "Senior", "work_mode": "remote-ish",
                             "ai_focus": "maybe", "people_management": "yes",
                             "office_days_per_week": 9, "city": "  ",
                             "required_languages": ["English", "english", "Czech"],
                             "stack_required": ["SQL", "dbt", "SQL"],
                             "stack_nice_to_have": ["dbt", "Airflow"]})
        self.assertEqual(facts["role_family"], "other")
        self.assertEqual(facts["seniority"], "senior")
        self.assertEqual(facts["work_mode"], "unknown")
        self.assertEqual(facts["ai_focus"], "none")
        self.assertFalse(facts["people_management"])          # only a real true counts
        self.assertIsNone(facts["office_days_per_week"])
        self.assertIsNone(facts["city"])
        self.assertEqual(facts["required_languages"], ["english", "czech"])
        self.assertEqual(facts["stack_required"], ["SQL", "dbt"])
        self.assertEqual(facts["stack_nice_to_have"], ["Airflow"])  # dbt already required


class TestSelect(unittest.TestCase):
    def test_skips_expired_empty_and_current_and_caps_newest_first(self):
        jobs = [
            {"job_id": "old", "title": "A", "description": DESC, "scraped_at": "2026-11-01"},
            {"job_id": "new", "title": "B", "description": DESC, "scraped_at": "2026-11-10"},
            {"job_id": "mid", "title": "C", "description": DESC, "scraped_at": "2026-11-05"},
            {"job_id": "exp", "title": "D", "description": DESC, "scraped_at": "2026-11-12", "expired_at": "x"},
            {"job_id": "empty", "title": "E", "description": "short", "scraped_at": "2026-11-12"},
            {"job_id": "done", "title": "F", "description": DESC, "scraped_at": "2026-11-12"},
        ]
        done_job = jobs[-1]
        extracted = {"done": {"prompt_version": ex.EXTRACTION_PROMPT_VERSION, "input_hash": ex.input_hash(done_job)}}
        todo, skipped = ex.select_jobs(jobs, extracted, 2)
        self.assertEqual([j["job_id"] for j in todo], ["new", "mid"])
        self.assertEqual(skipped, {"expired": 1, "no_description": 1, "up_to_date": 1, "over_limit": 1})

    def test_changed_description_or_prompt_version_is_extracted_again(self):
        job = {"job_id": "a", "title": "A", "description": DESC}
        stored = {"prompt_version": ex.EXTRACTION_PROMPT_VERSION, "input_hash": ex.input_hash(job)}
        self.assertTrue(ex.is_current(stored, job))
        self.assertFalse(ex.is_current(stored, {**job, "description": DESC + " more"}))
        self.assertFalse(ex.is_current({**stored, "prompt_version": "old"}, job))


class TestExtractJob(unittest.TestCase):
    def test_calls_ollama_with_schema_and_no_thinking(self):
        answer = {"role_family": "data_engineer", "seniority": "senior", "people_management": False,
                  "work_mode": "hybrid", "office_days_per_week": 2, "city": "Prague",
                  "residency_required": False, "required_languages": ["english"],
                  "stack_required": ["SQL", "BigQuery"], "stack_nice_to_have": ["dbt"],
                  "employment": "employee", "ai_focus": "none", "work_type": "greenfield",
                  "evidence": "Build our new data platform."}
        resp = mock.Mock()
        resp.json.return_value = {"message": {"content": json.dumps(answer)}}
        with mock.patch.object(ex.requests, "post", return_value=resp) as post:
            out = ex.extract_job({"job_id": "a", "title": "Senior Data Engineer", "description": DESC})
        body = post.call_args.kwargs["json"]
        self.assertIs(body["think"], False)
        self.assertEqual(body["format"], ex.SCHEMA)
        self.assertEqual(body["options"]["temperature"], 0)
        self.assertEqual(out["seniority"], "senior")
        self.assertEqual(out["office_days_per_week"], 2)
        self.assertEqual(out["model"], ex.OLLAMA_MODEL)

    def setUp(self):
        ex._schema_supported = True

    def tearDown(self):
        ex._schema_supported = True

    def _resp(self, content=None, status=200, text=""):
        r = mock.Mock(status_code=status, text=text)
        r.json.return_value = {"message": {"content": content}}
        r.raise_for_status.return_value = None
        return r

    def test_non_json_answer_raises(self):
        with mock.patch.object(ex.requests, "post", return_value=self._resp("Sure! Here is the JSON")):
            with self.assertRaises(ex.ExtractionError):
                ex.extract_job({"job_id": "a", "title": "X", "description": DESC})

    def test_falls_back_to_prompt_json_when_schema_is_unavailable(self):
        fenced = '```json\n{"seniority": "Senior", "work_mode": "Hybrid", "role_family": "Data_Engineer"}\n```'
        replies = [self._resp(status=501, text='{"error":"structured output is unavailable"}'),
                   self._resp(fenced)]
        with mock.patch.object(ex.requests, "post", side_effect=replies) as post:
            out = ex.extract_job({"job_id": "a", "title": "Senior Data Engineer", "description": DESC})
        second = post.call_args_list[1].kwargs["json"]
        self.assertNotIn("format", second)
        self.assertIn("Allowed values", second["messages"][0]["content"])
        self.assertEqual((out["seniority"], out["work_mode"], out["role_family"]),
                         ("senior", "hybrid", "data_engineer"))
        self.assertFalse(ex._schema_supported)          # later jobs skip the failing call

    def test_one_retry_when_fallback_answer_is_not_json(self):
        ex._schema_supported = False
        replies = [self._resp("I think this is a senior role."), self._resp('{"seniority": "senior"}')]
        with mock.patch.object(ex.requests, "post", side_effect=replies) as post:
            out = ex.extract_job({"job_id": "a", "title": "X", "description": DESC})
        self.assertEqual(post.call_count, 2)
        self.assertEqual(out["seniority"], "senior")


class TestToolNames(unittest.TestCase):
    def test_spelling_is_unified(self):
        self.assertEqual(ex.tool_name("azure_openai"), "Azure OpenAI")
        self.assertEqual(ex.tool_name("powerbi"), "Power BI")
        self.assertEqual(ex.tool_name("python"), "Python")
        self.assertEqual(ex.tool_name("azure_ai_search"), "azure ai search")   # unknown: only "_" fixed
        facts = ex.validate({"stack_required": ["python", "Python", "BigQuery"],
                             "stack_nice_to_have": ["PYTHON", "dbt"]})
        self.assertEqual(facts["stack_required"], ["Python", "BigQuery"])
        self.assertEqual(facts["stack_nice_to_have"], ["dbt"])


class TestLimits(unittest.TestCase):
    def test_answer_length_is_capped_and_languages_leave_the_stack(self):
        r = mock.Mock(status_code=200, text="")
        r.json.return_value = {"message": {"content": '{"stack_nice_to_have": ["German", ".NET"]}'}}
        with mock.patch.object(ex.requests, "post", return_value=r) as post:
            out = ex.extract_job({"job_id": "a", "title": "X", "description": DESC})
        self.assertEqual(post.call_args.kwargs["json"]["options"]["num_predict"], ex.MAX_ANSWER_TOKENS)
        self.assertEqual(out["stack_nice_to_have"], [".NET"])


class TestParse(unittest.TestCase):
    def test_text_around_json_is_ignored(self):
        self.assertEqual(ex.parse_json_answer('Here: {"a": 1} hope it helps'), {"a": 1})


if __name__ == "__main__":
    unittest.main()
