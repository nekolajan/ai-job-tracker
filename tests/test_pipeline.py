"""Tests for the once-a-day scrape logic in pipeline.py."""

import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from unittest import mock

import pipeline


class TestScrapeOncePerDay(unittest.TestCase):
    def test_marker(self):
        path = Path(tempfile.mkdtemp()) / "logs" / "last_scrape.txt"
        with mock.patch.object(pipeline, "LAST_SCRAPE_PATH", path):
            self.assertFalse(pipeline.scraped_today())
            pipeline.mark_scraped()
            self.assertTrue(pipeline.scraped_today())
            path.write_text((datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d"))
            self.assertFalse(pipeline.scraped_today())


if __name__ == "__main__":
    unittest.main()
