# Copyright 2026 The PEA knowledge processor authors
# SPDX-License-Identifier: Apache-2.0
"""Offline tests for podcast source request parsing, automated ingestion testing, and workflow security."""
import os
import re
import unittest

from pea_knowledge import fetch, intake
from . import support


class IntakeTests(unittest.TestCase):
    def test_parse_issue_body(self):
        body = (
            "### Podcast name\n\n"
            "Harbor Voices\n\n"
            "### RSS feed or agent.json URL\n\n"
            "https://harbor.example.org/feed.xml\n\n"
            "### Official website URL\n\n"
            "_No response_\n\n"
            "### Notes (optional)\n\n"
            "Transcripts are linked in RSS tags.\n"
        )
        parsed = intake.parse_issue_body(body)
        self.assertEqual(parsed["show_name"], "Harbor Voices")
        self.assertEqual(parsed["feed_url"], "https://harbor.example.org/feed.xml")
        self.assertEqual(parsed["website_url"], "")
        self.assertEqual(parsed["notes"], "Transcripts are linked in RSS tags.")

    def test_candidate_passes_on_fixture_podcast_with_transcripts(self):
        fetcher = fetch.fixture_fetcher(support.WEB, log=lambda *_: None)
        report = intake.test_candidate(
            fetcher,
            name="Tide Tables",
            feed_url="https://tide.example.org/feed.xml",
            website_url="https://tide.example.org/",
            today="2026-11-21",
        )
        self.assertEqual(report["verdict"], "PASS", report["checks"])
        self.assertEqual(report["adapter"], "feed")
        self.assertGreaterEqual(report["discussable_episodes"], 2)
        self.assertEqual(report["phone_probe"]["result"], "ok")
        self.assertTrue(report["brief_contract"]["ok"])
        self.assertEqual(report["starter_config"]["publish"], "digest_only")
        self.assertEqual(report["starter_config"]["id"], "tide-tables")
        md = intake.format_markdown(report)
        self.assertIn("Automated Source Ingestion Test: PASS", md)
        self.assertIn('"publish": "digest_only"', md)

    def test_candidate_rejects_private_or_http_url(self):
        fetcher = fetch.fixture_fetcher(support.WEB, log=lambda *_: None)
        report = intake.test_candidate(fetcher, name="Local Bad", feed_url="http://127.0.0.1/feed.xml")
        self.assertEqual(report["verdict"], "FAIL")
        self.assertIn("public https://", report["checks"][0][2])

    def test_candidate_autodiscovers_rss_from_html_site(self):
        base_fetcher = fetch.fixture_fetcher(support.WEB, log=lambda *_: None)
        html_page = b'<!doctype html><html><head><link rel="alternate" type="application/rss+xml" href="/feed.xml"></head><body>Tide</body></html>'

        class Wrapper:
            def get(self, url, limit):
                if url == "https://tide.example.org/":
                    return fetch.Response(url, fetch.Raw(200, {"content-type": "text/html"}, html_page, False))
                return base_fetcher.get(url, limit)

            def get_like_the_app(self, url, limit, headers, req_s, file_s):
                return base_fetcher.get_like_the_app(url, limit, headers, req_s, file_s)

        report = intake.test_candidate(Wrapper(), name="Tide Tables", website_url="https://tide.example.org/")
        self.assertEqual(report["verdict"], "PASS", report["checks"])
        self.assertEqual(report["feed_url"], "https://tide.example.org/feed.xml")
        self.assertTrue(any("Auto-discovered" in n for n in report["discovery_notes"]))

    def test_candidate_without_inline_transcripts_reports_needs_transcript_rule(self):
        rss_no_transcripts = b"""<?xml version="1.0" encoding="UTF-8"?>
        <rss version="2.0"><channel><title>No Transcripts Show</title><link>https://notranscripts.example.org/</link>
        <item><title>Ep 1</title><link>https://notranscripts.example.org/1</link><pubDate>Thu, 19 Nov 2026 12:00:00 GMT</pubDate><description>Desc 1</description></item>
        <item><title>Ep 2</title><link>https://notranscripts.example.org/2</link><pubDate>Wed, 18 Nov 2026 12:00:00 GMT</pubDate><description>Desc 2</description></item>
        </channel></rss>"""

        class OnlyRSS:
            def get(self, url, limit):
                return fetch.Response(url, fetch.Raw(200, {"content-type": "application/rss+xml"}, rss_no_transcripts, False))

        report = intake.test_candidate(OnlyRSS(), name="No Transcripts Show", feed_url="https://notranscripts.example.org/feed.xml")
        self.assertEqual(report["verdict"], "NEEDS_TRANSCRIPT_RULE")
        self.assertEqual(report["episodes_found"], 2)
        self.assertEqual(report["discussable_episodes"], 0)

    def test_source_request_workflow_security(self):
        wf_path = os.path.join(support.ROOT, ".github", "workflows", "test-source-request.yml")
        with open(wf_path, encoding="utf-8") as f:
            text = f.read()
        self.assertNotIn("secrets.", text)
        self.assertNotIn("pull_request_target", text)
        self.assertIn("\npermissions: {}\n", text)
        self.assertIn("persist-credentials: false", text)
        # Never interpolate raw issue body directly into a shell command.
        self.assertNotIn('run: |\n          ${{ github.event.issue.body', text)
        self.assertIn("ISSUE_BODY: ${{ github.event.issue.body }}", text)
        uses = re.findall(r"uses:\s*(\S+)(.*)", text)
        self.assertTrue(uses)
        for action, rest in uses:
            self.assertRegex(action, r"^actions/[a-z-]+@[0-9a-f]{40}$")
            self.assertRegex(rest, r"#\s*v\d+\.\d+\.\d+")


if __name__ == "__main__":
    unittest.main()
