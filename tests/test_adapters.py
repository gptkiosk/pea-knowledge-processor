# Copyright 2026 The PEA knowledge processor authors
# SPDX-License-Identifier: Apache-2.0
import json
import os
import time
import unittest

from . import support
from pea_knowledge import adapters, textrules


def saved(name):
    with open(os.path.join(support.WEB, *name.split("/")), "rb") as f:
        return f.read()


def rss(items, channel="<title>T</title>"):
    return ('<rss version="2.0" xmlns:itunes="http://www.itunes.com/dtds/podcast-1.0.dtd" xmlns:podcast="https://podcastindex.org/namespace/1.0">'
            "<channel>%s%s</channel></rss>" % (channel, items)).encode("utf-8")


ITEM = "<item><title>%s</title><guid>%s</guid><link>https://x.example.org/%s</link><pubDate>Thu, 12 Nov 2026 06:00:00 +0000</pubDate>%s</item>"


class AgentIndex(unittest.TestCase):
    def test_reads_the_saved_index(self):
        listing = adapters.parse_agent_index(saved("harbor/agent.json"))
        self.assertEqual(listing.title, "Harbor Voices")
        self.assertEqual([e.date for e in listing.entries], ["2026-11-12", "2026-11-11", "2026-11-10", "2026-11-09"])
        first = listing.entries[0]
        self.assertEqual((first.link, first.duration, first.tags), ("https://harbor.example.org/e/2026-11-12", 540, ["harbour", "lighthouses"]))
        self.assertEqual(first.transcripts, [("https://harbor.example.org/e/2026-11-12/transcript.md", "text/markdown")])
        self.assertEqual(listing.entries[3].transcripts, [])
        self.assertIn("1 episodes skipped: 'date' missing", listing.notes)
        self.assertIn("transcript", listing.fingerprint)

    def test_what_is_not_an_index_is_a_typed_failure(self):
        for data, code in ((b"<html><body>Sign in</body></html>", "format_changed"), (b"", "format_changed"), (b"[1, 2]", "format_changed"),
                           (b'{"episodes": []}', "format_changed"), (b'{"editions": []}', "empty"), (b'{"editions": [{"title": "x"}, 5, null]}', "format_changed"),
                           (b'{"editions": [{"date": "2026-11-12", "title": "x", "markdown": "http://plain.example.org/x"}]}', "format_changed"),
                           (b"\xff\xfe\x00\x01", "format_changed"), (b'{"editions": NaN}', "format_changed"), (b"{" * 100_000, "format_changed")):
            with self.assertRaises(adapters.AdapterError) as e:
                adapters.parse_agent_index(data)
            self.assertEqual(e.exception.code, code, data[:40])
            self.assertIsNone(textrules.check(textrules.clean(e.exception.detail, 200)))

    def test_hostile_values_are_dropped_or_cleaned(self):
        row = {"date": "2026-11-12", "title": "<b>Bold</b> title https://evil.example.org", "html": "https://harbor.example.org/e/1", "teaser": "x" * 5000,
               "durationMin": float("1e300"), "tags": ["<script>", "ok tag", 7, None] + ["t%d" % n for n in range(20)], "transcript": "https://10.0.0.1/t.md"}
        data = json.dumps({"editions": [row, dict(row, durationMin="nan"), dict(row, html="https://harbor.example.org/e/2", durationMin=-5)]}).encode()
        listing = adapters.parse_agent_index(data)
        self.assertEqual(len(listing.entries), 2, "two rows share a page, so they share an id: the first wins")
        self.assertIn("1 episodes skipped: the same id as an earlier one", listing.notes)
        for e in listing.entries:
            self.assertEqual(e.title, "Bold title")
            self.assertIsNone(e.duration)
            self.assertEqual(e.transcripts, [])
            self.assertLessEqual(len(e.summary), 400)
            self.assertLessEqual(len(e.tags), 6)
            self.assertEqual(e.tags[0], "ok-tag", "a tag that is only markup is dropped")


class Feeds(unittest.TestCase):
    def test_reads_the_saved_rss_feed(self):
        listing = adapters.parse_feed(saved("tide/feed.xml"))
        self.assertEqual((listing.title, listing.language), ("Tide Tables", "en"))
        self.assertEqual(len(listing.entries), 7)
        first = listing.entries[0]
        self.assertEqual((first.title, first.date, first.link, first.duration), ("The keeper's ledger, read aloud", "2026-11-12", "https://tide.example.org/episodes/6", 518))
        self.assertEqual([t[1] for t in first.transcripts], ["text/html", "text/vtt"])
        self.assertEqual(listing.entries[2].duration, None, "a duration of nan is no duration")
        hostile = next(e for e in listing.entries if e.date == "2026-11-07")
        self.assertEqual(hostile.title, "A transcript that shouts orders & links")
        self.assertNotIn("evil", hostile.notes)
        self.assertIn("1 entries skipped: no date", listing.notes)
        self.assertIn("1 entries skipped: the same id as an earlier one", listing.notes)
        self.assertEqual(listing.fingerprint, "link,podcast:transcript,title")

    def test_reads_the_saved_atom_feed(self):
        listing = adapters.parse_feed(saved("gazette/feed.atom"))
        self.assertEqual(listing.title, "The Port Gazette")
        self.assertEqual([e.date for e in listing.entries], ["2026-11-12", "2026-11-11", "2026-11-10", "2026-11-09"])
        self.assertEqual(listing.entries[0].link, "https://gazette.example.org/a/4")
        self.assertTrue(listing.entries[0].summary.startswith("The Harbour Board said on Thursday"))
        for e in listing.entries:
            self.assertIsNone(textrules.check(e.title), e.title)
            self.assertIsNone(textrules.check(e.summary), e.summary)

    def test_reads_the_saved_json_feed(self):
        listing = adapters.parse_feed(saved("quay/feed.json"))
        self.assertEqual((listing.title, len(listing.entries)), ("Quay Notes", 2))
        first = listing.entries[0]
        self.assertEqual((first.title, first.date, first.link, first.duration, first.tags), ("Four generations of ice", "2026-11-11", "https://quay.example.org/notes/2", 1502, ["quay-life", "ice"]))
        self.assertGreater(len(first.notes), 400)

    def test_what_is_not_a_feed_is_a_typed_failure(self):
        bomb = b'<?xml version="1.0"?><!DOCTYPE lolz [<!ENTITY a "aaaaaaaaaa"><!ENTITY b "&a;&a;&a;&a;&a;&a;&a;&a;">]><rss><channel><item><title>&b;</title></item></channel></rss>'
        outside = b'<?xml version="1.0"?><!DOCTYPE r [<!ENTITY x SYSTEM "file:///etc/passwd">]><rss><channel><item><title>&x;</title></item></channel></rss>'
        for data, code in ((b"<!DOCTYPE html><html><body>Blocked</body></html>", "format_changed"), (b"", "format_changed"), (b"plain words", "format_changed"),
                           (b"<rss><channel><item><title>never closed", "format_changed"), (rss(""), "empty"), (b"<rss></rss>", "format_changed"),
                           (b'<?xml version="1.0"?><svg xmlns="http://www.w3.org/2000/svg"/>', "format_changed"), (bomb, "format_changed"), (outside, "format_changed"),
                           (rss("<item><title>no link or date</title></item>" * 3), "format_changed"),
                           (b'<?xml version="1.0" encoding="utf-8"?><rss><channel><item><title>\xff\xfe bad bytes</title></item></channel></rss>', "format_changed"),
                           (b'<?xml version="1.0" encoding="no-such-encoding"?><rss><channel/></rss>', "format_changed"),
                           (b'{"version": "https://jsonfeed.org/version/1.1", "items": []}', "empty"), (b'{"version": "1", "items": [{}]}', "format_changed"),
                           (b'{"version": "https://jsonfeed.org/version/1.1", "items": [{"title": "x"}, 4]}', "format_changed")):
            with self.assertRaises(adapters.AdapterError) as e:
                adapters.parse_feed(data)
            self.assertEqual(e.exception.code, code, data[:60])

    def test_a_feed_that_changes_shape_has_another_fingerprint(self):
        with_transcripts = adapters.parse_feed(rss(ITEM % ("A", "g1", "a", '<podcast:transcript url="https://x.example.org/a.vtt" type="text/vtt"/>')))
        without = adapters.parse_feed(rss(ITEM % ("A", "g1", "a", "")))
        self.assertNotEqual(with_transcripts.fingerprint, without.fingerprint)
        self.assertEqual(with_transcripts.entries[0].id, without.entries[0].id, "the id depends on the guid alone")

    def test_duplicate_ids_and_odd_values(self):
        extra = ('<itunes:duration>inf</itunes:duration><podcast:transcript url="https://127.0.0.1/a.vtt" type="text/vtt"/>'
                 '<podcast:transcript url="javascript:alert(1)" type="text/vtt"/><podcast:transcript type="text/vtt"/>')
        listing = adapters.parse_feed(rss(ITEM % ("A", "same", "a", extra) + ITEM % ("B", "same", "b", "") + ITEM % ("C", "", "c", "")
                                          + "<item><title>D</title><guid>d</guid><link>http://plain.example.org/d</link><pubDate>31 Feb 2026</pubDate></item>"
                                          + "<item><title>E</title><guid>e</guid><pubDate>Thu, 12 Nov 9999 06:00:00 +0000</pubDate></item>"))
        self.assertEqual(sorted(e.title for e in listing.entries), ["A", "C"])
        listing.entries.sort(key=lambda e: e.title)
        self.assertEqual((listing.entries[0].duration, listing.entries[0].transcripts), (None, []))
        self.assertEqual(len({e.id for e in listing.entries}), 2)
        for e in listing.entries:
            self.assertRegex(e.id, r"^\d{4}-\d{2}-\d{2}-[0-9a-f]{10}$")

    def test_a_huge_feed_is_read_in_bounded_time(self):
        data = rss("".join(ITEM % ("Title %d" % n, "g%d" % n, n, "<description>" + "words " * 300 + "</description>") for n in range(4000)))
        self.assertGreater(len(data), 7_000_000)
        start = time.monotonic()
        listing = adapters.parse_feed(data)
        self.assertLess(time.monotonic() - start, 20)
        self.assertEqual(len(listing.entries), adapters.MAXIMUM_ENTRIES)
        self.assertLessEqual(max(len(e.notes) for e in listing.entries), adapters.NOTES_CHARS)


if __name__ == "__main__":
    unittest.main()
