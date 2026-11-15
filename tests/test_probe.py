# Copyright 2026 The PEA knowledge processor authors
# SPDX-License-Identifier: Apache-2.0
"""The phone-style probe: one request made the way the app makes it, and what a source does when its newest item fails it."""
import datetime
import json
import os
import re
import shutil
import tempfile
import unittest

from . import support
from .test_fetch import Web, page
from .test_pipeline import Base, LATER
from pea_knowledge import fetch, jsonschema_lite as js, pipeline, probe, textrules, validate

LINK = "https://media.tide.example.org/ep6.vtt"
EP6 = LINK
with open(os.path.join(support.WEB, "tide", "ep6.vtt"), "rb") as f:
    VTT = f.read()


def tide():
    """The tide-tables source of the fixtures and a made-up item and origin for it."""
    config = support.load_config()
    source = next(s for s in config["sources"] if s["id"] == "tide-tables")
    item = {"title": "The keeper's ledger, read aloud", "date": "2026-11-12", "duration_seconds": 518}
    return source, item, {"link": LINK, "format": "vtt", "route": "feed_tag", "bytes": len(VTT)}


class TheRequest(unittest.TestCase):
    def run_probe(self, pages, origin=None):
        source, item, found = tide()
        origin = origin or found
        web = Web(pages)
        return web, probe.probe(web.fetcher(), origin, pipeline.phone_read(source, item, origin))

    def good(self, **more):
        return page(VTT, **dict({"Content-Type": "text/vtt"}, **more))

    def test_the_headers_are_the_apps_and_robots_txt_is_not_read(self):
        web, result = self.run_probe({LINK: self.good()})
        self.assertEqual(result, {"result": "ok", "reason": None})
        self.assertEqual(web.asked(), [LINK], "one request, and not even robots.txt")
        headers = web.calls[0][2]
        self.assertEqual((headers["User-Agent"], headers["Accept"]), (probe.PHONE_USER_AGENT, probe.PHONE_ACCEPT))
        self.assertTrue(headers["User-Agent"].startswith("PEA/"))
        self.assertNotIn("pea-knowledge-processor", headers["User-Agent"], "it must not announce itself as the pipeline")
        self.assertEqual(sorted(headers), ["Accept", "Accept-Encoding", "Connection", "User-Agent"], "nothing else is added, and nothing conditional")

    def test_the_phone_does_not_read_robots_txt_so_the_probe_does_not_either(self):
        everything_closed = {"https://media.tide.example.org/robots.txt": page(b"User-agent: *\nDisallow: /\n", **{"Content-Type": "text/plain"}), LINK: self.good()}
        web = Web(everything_closed)
        with self.assertRaises(fetch.FetchError) as e:
            web.fetcher().get(LINK, 1_500_000)
        self.assertEqual(e.exception.code, "robots_disallowed", "the pipeline itself obeys it")
        source, item, origin = tide()
        web = Web(everything_closed)
        self.assertEqual(probe.probe(web.fetcher(), origin, pipeline.phone_read(source, item, origin))["result"], "ok")
        self.assertEqual(web.asked(), [LINK])

    def test_the_apps_time_limits_and_size_cap_are_used_and_nothing_is_retried(self):
        seen = {}
        calls = []

        def opener(url, address, headers, maximum_bytes, seconds=None, total_seconds=None):
            calls.append(url)
            seen.update(maximum_bytes=maximum_bytes, seconds=seconds, total_seconds=total_seconds)
            return fetch.Raw(503, {})
        fetcher = fetch.Fetcher(opener=opener, resolver=lambda host: ["93.184.216.34"], sleep=lambda s: None, clock=lambda: 0.0, pause=0)
        source, item, origin = tide()
        result = probe.probe(fetcher, origin, pipeline.phone_read(source, item, origin))
        self.assertEqual((result["result"], result["reason"]["code"]), ("failed", "http_status"))
        self.assertEqual(calls, [LINK], "a 503 is not asked again: one request per source per run")
        self.assertEqual(seen, {"maximum_bytes": 1_500_000, "seconds": 10, "total_seconds": 25})

    def test_what_the_probe_accepts(self):
        for ctype in ("text/vtt", "text/vtt; charset=utf-8", "text/plain", "application/octet-stream", "text/x-vtt", ""):
            web, result = self.run_probe({LINK: self.good(**{"Content-Type": ctype})})
            self.assertEqual(result["result"], "ok", ctype)

    def test_every_way_the_phone_cannot_fetch_it(self):
        cases = [
            ("403: a bot wall", {LINK: page(b"Just a moment...", 403, **{"Content-Type": "text/html"})}, "refused"),
            ("401", {LINK: page(b"", 401)}, "refused"),
            ("402", {LINK: page(b"", 402)}, "refused"),
            ("404", {LINK: page(b"", 404)}, "not_found"),
            ("429", {LINK: page(b"", 429)}, "rate_limited"),
            ("500", {LINK: page(b"", 500)}, "http_status"),
            ("204: not a 200", {LINK: page(b"", 204)}, "http_status"),
            ("a redirect that goes nowhere", {LINK: page(b"", 302)}, "http_status"),
            ("timeout", {LINK: fetch.FetchError("timeout", "no answer within 10 seconds")}, "timeout"),
            ("no connection", {LINK: fetch.FetchError("network", "the request failed (ConnectionResetError)")}, "network"),
            ("an image", {LINK: page(VTT, **{"Content-Type": "image/png"})}, "content_type"),
            ("a web page where a vtt file should be", {LINK: page(VTT, **{"Content-Type": "text/html"})}, "content_type"),
            ("a json file where a vtt file should be", {LINK: page(VTT, **{"Content-Type": "application/json"})}, "content_type"),
            ("too large", {LINK: fetch.Raw(200, {"Content-Type": "text/vtt"}, VTT, truncated=True)}, "too_large"),
            ("not text", {LINK: page(bytes(range(256)) * 10, **{"Content-Type": "text/vtt"})}, "unreadable"),
            ("a sign-in page served as vtt", {LINK: page(b"<html><body>Sign in to continue</body></html>", **{"Content-Type": "text/vtt"})}, "unreadable"),
            ("nothing in it", {LINK: page(b"WEBVTT\n\n", **{"Content-Type": "text/vtt"})}, "unreadable"),
        ]
        for name, pages, code in cases:
            if isinstance(pages[LINK], fetch.FetchError):
                error = pages[LINK]

                def opener(url, address, headers, maximum_bytes, seconds=None, total_seconds=None, error=error):
                    raise error
                source, item, origin = tide()
                fetcher = fetch.Fetcher(opener=opener, resolver=lambda host: ["93.184.216.34"], sleep=lambda s: None, clock=lambda: 0.0, pause=0)
                result = probe.probe(fetcher, origin, pipeline.phone_read(source, item, origin))
            else:
                web, result = self.run_probe(pages)
            self.assertEqual((name, result["result"], result["reason"]["code"]), (name, "failed", code))
            self.assertIn(result["reason"]["code"], probe.CODES)
            self.assertLessEqual(len(result["reason"]["detail"]), 200)
            self.assertIsNone(textrules.check(result["reason"]["detail"]), name)

    def test_an_html_page_is_read_with_the_page_reader_and_must_be_html(self):
        source = next(s for s in support.load_config()["sources"] if s["id"] == "lamp-room")
        item = {"title": "The night the lamp went out", "date": "2026-11-12", "duration_seconds": 300}
        with open(os.path.join(support.WEB, "lamp", "ep4-transcript.html"), "rb") as f:
            html = f.read()
        link = "https://lamp.example.org/e/ep4/transcript"
        origin = {"link": link, "format": "html", "route": "page", "bytes": len(html), "extract": {}}
        for ctype, expect in (("text/html; charset=utf-8", "ok"), ("text/plain", "content_type")):
            web = Web({link: page(html, **{"Content-Type": ctype})})
            result = probe.probe(web.fetcher(), origin, pipeline.phone_read(source, item, origin))
            self.assertEqual(result["result"] == "ok" or result["reason"]["code"], True if expect == "ok" else expect, ctype)
        web = Web({link: page(b"<html><body><p>Too short.</p></body></html>", **{"Content-Type": "text/html"})})
        result = probe.probe(web.fetcher(), origin, pipeline.phone_read(source, item, origin))
        self.assertEqual((result["result"], result["reason"]["code"]), ("failed", "unreadable"), "the page reader refuses a page with too little text")

    def test_the_constants_are_documented_as_copied_from_the_app(self):
        with open(probe.__file__, encoding="utf-8") as f:
            text = f.read()
        self.assertIn("Research.swift", text)
        self.assertIn("PublicFetcher", text)
        self.assertEqual(probe.PHONE_MAXIMUM_BYTES, fetch.TRANSCRIPT_BYTES, "the same cap as the pipeline's own transcript reads")


def tide_with_a_newer_item(responses, folder):
    """The saved web, plus one newer tide-tables episode (tide-7, 13 November) whose transcript is a copy of the newest one's."""
    feed = os.path.join(folder, "tide", "feed.xml")
    with open(feed, encoding="utf-8") as f:
        text = f.read()
    newer = ('<item><title>Seven bells</title><guid isPermaLink="false">tide-7</guid><link>https://tide.example.org/episodes/7</link><pubDate>Fri, 13 Nov 2026 06:00:00 +0000</pubDate>'
             '<itunes:duration>08:38</itunes:duration><category>harbour</category><description><![CDATA[<p>Mara and Tobias at the Grey Point lighthouse.</p>]]></description>'
             '<podcast:transcript url="https://media.tide.example.org/ep7.vtt" type="text/vtt"/></item>')
    with open(feed, "w", encoding="utf-8") as f:
        f.write(text.replace("<item>", newer + "<item>", 1))
    shutil.copy(os.path.join(folder, "tide", "ep6.vtt"), os.path.join(folder, "tide", "ep7.vtt"))
    responses["https://media.tide.example.org/ep7.vtt"] = {"content_type": "text/vtt", "file": "tide/ep7.vtt"}
    responses["https://tide.example.org/feed.xml"]["etag"] = '"tide-2"'


class InThePipeline(Base):
    def config(self, **more):
        values = dict(dict(min_full_transcript_share=0, min_discussable_items=0, phone_probe=True), **more)
        return support.load_config(lambda c: (support.strict(c), c["defaults"].update(values)))

    def refuse(self, **phone):
        return lambda r: r[EP6].update(phone=phone)

    def test_the_result_is_in_health_for_each_source(self):
        health = support.run(self.out, config=self.config())
        self.assertEqual(js.validate(health, validate.schema("health")), [])
        tide_report = self.health_of(health, "tide-tables")["phone_probe"]
        self.assertEqual((tide_report["item"][:10], tide_report["result"], tide_report["reason"], tide_report["reused"]), ("2026-11-12", "ok", None, False))
        newest = support.items(self.out, "tide-tables")[0]["id"]
        self.assertEqual(tide_report["item"], newest, "the newest discussable item is the one probed")
        harbor = self.health_of(health, "harbor-voices")["phone_probe"]
        self.assertEqual(harbor["item"], support.items(self.out, "harbor-voices")[0]["id"])
        self.assertIsNone(self.health_of(health, "quay-notes")["phone_probe"], "nothing discussable, nothing to probe")
        probed = sum(1 for s in health["sources"] if s["phone_probe"])
        self.assertEqual(probed, 3, "one request each for the three sources that have a discussable item")

    def test_an_ok_result_is_reused_while_it_is_fresh_and_the_item_has_not_changed(self):
        config = self.config()
        first = support.run(self.out, config=config)
        feed_read_again = self.web(lambda r: r["https://tide.example.org/feed.xml"].update(etag='"tide-2"'))
        second = support.run(self.out, support.T0 + datetime.timedelta(hours=1), config, feed_read_again)
        report = self.health_of(second, "tide-tables")
        self.assertEqual((report["outcome"], report["phone_probe"]["result"], report["phone_probe"]["reused"]), ("ok", "ok", True))
        self.assertEqual(report["phone_probe"]["checked_at"], self.health_of(first, "tide-tables")["phone_probe"]["checked_at"])
        later = self.web(lambda r: r["https://tide.example.org/feed.xml"].update(etag='"tide-3"'), "web-3")
        third = support.run(self.out, support.T0 + datetime.timedelta(hours=25), config, later)
        report = self.health_of(third, "tide-tables")
        self.assertEqual((report["phone_probe"]["reused"], report["phone_probe"]["checked_at"]), (False, "2026-11-15T13:00:00Z"), "after a day it is asked again")
        unchanged = support.run(self.out, support.T0 + datetime.timedelta(hours=26), config, later)
        again = self.health_of(unchanged, "tide-tables")
        self.assertEqual((again["outcome"], again["phone_probe"]["result"], again["phone_probe"]["reused"]), ("unchanged", "ok", True), "an unchanged feed costs nothing")

    def test_a_host_that_refuses_the_apps_request_pauses_the_source(self):
        config = self.config()
        web = self.web(self.refuse(status=403))
        health = support.run(self.out, config=config, web=web)
        report = self.health_of(health, "tide-tables")
        self.assertEqual((report["outcome"], report["reason"]["code"]), ("failed", "fetch_failed"))
        self.assertTrue(report["reason"]["detail"].startswith("the publisher refuses requests like the app's"))
        self.assertEqual((report["phone_probe"]["result"], report["phone_probe"]["reason"]["code"], report["dropped"]["phone_probe"]), ("failed", "refused", 1))
        self.assertEqual(support.listing(self.out, "tide-tables")["item_count"], 0, "nothing is offered that the phone cannot fetch")
        self.assertEqual(self.health_of(health, "harbor-voices")["phone_probe"]["result"], "ok", "the other sources are not touched")
        self.assertEqual(support.listing(self.out, "harbor-voices")["state"], "active")
        for n in (1, 2):
            support.run(self.out, support.T0 + datetime.timedelta(hours=6 * n), config, web)
        tide = support.listing(self.out, "tide-tables")
        self.assertEqual((tide["state"], tide["state_reason"]["code"], tide["freshness"]["failed_runs"]), ("paused", "fetch_failed", 3))
        self.assertEqual(tide["state_reason"]["detail"][:45], "the publisher refuses requests like the app's")
        self.assertIn("refuses requests like the app's", tide["message"])
        self.assertIsNone(textrules.check(tide["message"]))
        self.assertEqual(self.codes(), [])
        gone = support.run(self.out, support.T0 + datetime.timedelta(days=31), config, web)
        tide = support.listing(self.out, "tide-tables")
        self.assertEqual((tide["state"], tide["state_reason"]["code"], tide["item_count"]), ("withdrawn", "quality", 0))
        self.assertIn("refuses requests like the app's", tide["message"])
        self.assertEqual(self.health_of(gone, "tide-tables")["state"], "withdrawn")
        support.run(self.out, support.T0 + datetime.timedelta(days=32), config)
        tide = support.listing(self.out, "tide-tables")
        self.assertEqual((tide["state"], tide["item_count"]), ("active", 4), "when the publisher lets the app in again the source comes back by itself")
        self.assertEqual(self.codes(), [])

    def test_each_kind_of_failure_is_typed(self):
        for phone, code in (({"status": 403}, "refused"), ({"content_type": "image/png"}, "content_type"), ({"pad_bytes": 1_600_000}, "too_large"),
                            ({"error": "timeout"}, "timeout"), ({"status": 404}, "not_found"), ({"status": 429}, "rate_limited"), ({"status": 503}, "http_status")):
            out = os.path.join(self.base, "dist-" + code + str(len(str(phone))))
            health = support.run(out, config=self.config(), web=self.web(self.refuse(**phone), "web-" + code + str(len(str(phone)))))
            report = self.health_of(health, "tide-tables")
            self.assertEqual((report["phone_probe"]["reason"]["code"], report["reason"]["code"]), (code, "fetch_failed"), str(phone))

    def test_a_source_that_lets_only_the_pipeline_in_is_the_case_the_probe_exists_for(self):
        health = support.run(self.out, config=self.config(), web=self.web(self.refuse(status=403)))
        report = self.health_of(health, "tide-tables")
        self.assertEqual(report["items"], 0, "the pipeline read the transcript with its own User-Agent, and still nothing is offered")
        self.assertEqual(report["transcripts"]["yes"], 0)

    def test_an_older_item_that_failed_is_dropped_and_the_source_goes_on(self):
        config = self.config()
        support.run(self.out, config=config, web=self.web(self.refuse(status=403), "web-1"))
        self.assertEqual(support.listing(self.out, "tide-tables")["item_count"], 0)
        newer = self.web(lambda r: (tide_with_a_newer_item(r, os.path.join(self.base, "web-2")), self.refuse(status=403)(r)), "web-2")
        health = support.run(self.out, LATER, config, newer)
        tide = self.health_of(health, "tide-tables")
        self.assertEqual((tide["outcome"], tide["phone_probe"]["result"], tide["state"]), ("ok", "ok", "active"), "the newest item passes, so the source is active again")
        self.assertEqual(tide["dropped"]["phone_probe"], 1)
        ids = [i["id"] for i in support.items(self.out, "tide-tables")]
        self.assertEqual(len(ids), 4)
        self.assertTrue(ids[0].startswith("2026-11-13"))
        self.assertFalse(any(i.startswith("2026-11-12") for i in ids), "the older item that the phone cannot fetch is not listed")
        self.assertEqual(self.codes(), [])

    def test_the_probe_can_be_switched_off(self):
        health = support.run(self.out, config=self.config(phone_probe=False), web=self.web(self.refuse(status=403)))
        self.assertIsNone(self.health_of(health, "tide-tables")["phone_probe"])
        self.assertEqual(support.listing(self.out, "tide-tables")["item_count"], 4)

    def test_the_probe_does_not_look_at_a_source_that_already_fails_the_minimum(self):
        config = self.config(min_full_transcript_share=0.6, min_discussable_items=2)
        health = support.run(self.out, config=config)
        quay = self.health_of(health, "quay-notes")
        self.assertEqual((quay["reason"]["code"], quay["phone_probe"]), ("empty", None))


if __name__ == "__main__":
    unittest.main()
