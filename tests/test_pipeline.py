# Copyright 2026 The PEA knowledge processor authors
# SPDX-License-Identifier: Apache-2.0
import contextlib
import datetime
import io
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest

from . import support, make_fixtures
from pea_knowledge import cli, jsonschema_lite as js, pipeline, textrules, validate
from pea_knowledge.transcript import pea_transcript as pt

LATER = support.T0 + datetime.timedelta(hours=6)


class Base(unittest.TestCase):
    def setUp(self):
        self.base = tempfile.mkdtemp(prefix="pea-test-")
        self.addCleanup(shutil.rmtree, self.base, True)
        self.out = os.path.join(self.base, "dist")

    def web(self, change, name="web"):
        return support.web_copy(os.path.join(self.base, name), change)

    def codes(self, folder=None):
        return sorted({p.code for p in validate.check_folder(folder or self.out).problems})

    def health_of(self, health, sid):
        return next(s for s in health["sources"] if s["id"] == sid)


class OneRun(Base):
    def test_the_output_validates_and_says_what_it_holds(self):
        health = support.run(self.out)
        report = validate.check_folder(self.out)
        self.assertEqual(report.problems, [])
        self.assertEqual((report.sources, report.items), (5, 20))
        self.assertEqual((health["mode"], health["totals"]["items"], health["model"]["used"]), ("offline", 20, False))
        self.assertEqual(js.validate(health, validate.schema("health")), [])
        tide = {i["date"]: i for i in support.items(self.out, "tide-tables")}
        self.assertEqual({d: (i["transcript"]["available"], i["transcript"]["reason"], i["digest"]["basis"]) for d, i in tide.items()}, {
            "2026-11-12": ("yes", None, "transcript"), "2026-11-11": ("yes", None, "transcript"), "2026-11-10": ("yes", None, "transcript"),
            "2026-11-09": ("no", "none_published", "notes"), "2026-11-08": ("no", "fetch_failed", "headline"), "2026-11-07": ("yes", None, "transcript")})
        self.assertNotIn("2026-01-01", tide, "older than the retention window")
        harbor = support.items(self.out, "harbor-voices")
        self.assertEqual([(i["transcript"]["available"], i["transcript"]["reason"]) for i in harbor],
                         [("no", "withheld_terms")] * 3 + [("no", "none_published")], "digest_only: the transcript is used for the digest and never published")
        self.assertEqual([i["digest"]["basis"] for i in harbor], ["transcript"] * 3 + ["headline"])
        self.assertFalse([p for p in support.tree(self.out) if p.startswith("sources/harbor-voices/") and p.endswith(".pea.txt")])
        self.assertEqual(self.health_of(health, "tide-tables")["transcripts"], {"yes": 4, "partial": 0, "none_published": 1, "fetch_failed": 1, "unreadable": 0, "withheld_terms": 0})

    def test_every_item_links_to_its_own_page_or_says_that_it_links_to_the_show(self):
        health = support.run(self.out)
        for sid in ("harbor-voices", "tide-tables", "quay-notes", "port-gazette"):
            items = support.items(self.out, sid)
            self.assertEqual(len({i["id"] for i in items}), len(items))
            pages = [i["link"] for i in items if i["link_kind"] == "episode"]
            self.assertEqual(len(set(pages)), len(pages), "%s: every item with a page of its own has a different one" % sid)
            for i in items:
                d = support.digest_of(self.out, sid, i["id"])
                self.assertEqual((d["link"], d["link_kind"]), (i["link"], i["link_kind"]))
                if i["link_kind"] == "show":
                    self.assertEqual(i["link"], support.listing(self.out, sid)["site"])
        tide = {i["date"]: i for i in support.items(self.out, "tide-tables")}
        self.assertEqual({d: i["link_kind"] for d, i in tide.items() if i["link_kind"] != "episode"}, {"2026-11-11": "show"})
        self.assertTrue(any("no page of their own" in n for n in self.health_of(health, "tide-tables")["notes"]))
        again = support.run(self.out, LATER)
        self.assertEqual([i["id"] for i in support.items(self.out, "tide-tables")], [i["id"] for i in tide.values()], "ids are the same on the next run")
        self.assertEqual(self.health_of(again, "tide-tables")["new"], 0)

    def test_the_publishers_chapter_file_is_read_and_a_missing_one_costs_nothing(self):
        support.run(self.out)
        item = next(i for i in support.items(self.out, "tide-tables") if i["date"] == "2026-11-10")
        d = support.digest_of(self.out, "tide-tables", item["id"])
        self.assertEqual([(c["title"], c["start_seconds"], c["origin"]) for c in d["chapters"]],
                         [("Opening", 0, "publisher"), ("The ledger", 140, "publisher"), ("Out of order, after sorting it is in order", 300, "publisher"), ("The visitor centre", 400, "publisher")])
        gone = os.path.join(self.base, "gone")
        health = support.run(gone, web=self.web(lambda r: r.update({"https://media.tide.example.org/ep4-chapters.json": {"status": 500}})))
        self.assertEqual(self.codes(gone), [])
        item = next(i for i in support.items(gone, "tide-tables") if i["date"] == "2026-11-10")
        d = support.digest_of(gone, "tide-tables", item["id"])
        self.assertEqual((d["basis"], {c["origin"] for c in d["chapters"]} <= {"transcript"}), ("transcript", True), "the digest is made all the same")
        self.assertTrue(any("chapter file could not be read" in n for n in self.health_of(health, "tide-tables")["notes"]))

    def test_an_output_of_format_1_0_is_still_read_and_its_items_are_rebuilt(self):
        """The first run of this version finds an output written by 0.1.0: no link_kind, none of the 1.1 members."""
        support.run(self.out)
        for path, data in support.tree(self.out).items():
            if path.endswith(".brief.json") or path == "briefs-index.json":   # 1.0 had no briefs nor their index (1.3)
                os.remove(os.path.join(self.out, *path.split("/")))
                continue
            if path.endswith(".json") and path not in ("health.json",):
                value = json.loads(data)
                value["format_version"] = "1.0"
                value.pop("briefs", None)
                for item in value.get("items", []) if isinstance(value.get("items"), list) else []:
                    for key in ("link_kind", "transcript_source", "topics", "topics_by", "brief"):
                        item.pop(key, None)
                if path == "store.json":   # 1.0 had no vocabulary of topics
                    value.pop("topics")
                    for listing in value["sources"]:
                        listing.pop("topics")
                for key in ("link_kind", "guests", "mentioned_resources", "chapters", "snippable_moments", "recap_cards"):
                    value.pop(key, None)
                if path == "state.json":   # 0.1.0 made its item keys another way, so none of them is the key of today
                    for memory in value["sources"].values():
                        for kept in memory["items"].values():
                            kept["key"] = "0" * 64
                        memory["config"] = "0" * 64
                with open(os.path.join(self.out, *path.split("/")), "w", encoding="utf-8") as f:
                    f.write(js.dumps(value))
        for sid in ("harbor-voices", "tide-tables", "quay-notes", "port-gazette", "lamp-room"):   # the hashes follow the rewritten files
            folder = os.path.join(self.out, "sources", sid)
            with open(os.path.join(folder, "items.json"), encoding="utf-8") as f:
                index = json.load(f)
            for item in index["items"]:
                with open(os.path.join(self.out, *item["digest"]["path"].split("/")), "rb") as f:
                    data = f.read()
                size = len(data) - item["digest"]["bytes"]
                item["digest"].update(sha256=pipeline.sha256(data), bytes=len(data))
                item["bytes"] += size
            data = js.dumps(index).encode()
            with open(os.path.join(folder, "items.json"), "wb") as f:
                f.write(data)
            store = support.store(self.out)
            for listing in store["sources"]:
                if listing["id"] == sid:
                    listing["items_file"].update(sha256=pipeline.sha256(data), bytes=len(data))
                    listing["avg_bytes"] = sum(i["bytes"] for i in index["items"]) // len(index["items"])
            with open(os.path.join(self.out, "store.json"), "w", encoding="utf-8") as f:
                f.write(js.dumps(store))
        self.assertEqual(self.codes(), [], "a 1.0 output is valid for a reader of 1.3")
        health = support.run(self.out, LATER)
        self.assertEqual(self.codes(), [])
        self.assertTrue(all(i["brief"]["kind"] == "extractive" for sid in ("harbor-voices", "tide-tables") for i in support.items(self.out, sid)),
                        "an item kept from an output without briefs gets an extractive one")
        self.assertTrue(all("link_kind" in i and "topics" in i for sid in ("harbor-voices", "tide-tables") for i in support.items(self.out, sid)))
        self.assertEqual(health["totals"]["items"], 20)

    def test_the_store_listing_has_what_a_store_card_and_the_storage_choice_need(self):
        support.run(self.out)
        raw = support.tree(self.out)["store.json"]
        listed = json.loads(raw)
        vocabulary = listed.pop("topics")
        self.assertLess(len(js.dumps(listed)), 16_000, "the listing is small: the store screen needs nothing else")
        self.assertLess(len(js.dumps(vocabulary)), 16_000, "and so is the vocabulary of topics it carries since 1.2")
        tide = support.listing(self.out, "tide-tables")
        self.assertEqual((tide["state"], tide["freshness"], tide["purge"], tide["message"]), ("active", {"status": "fresh", "last_ok": None, "failed_runs": 0}, False, None))
        self.assertEqual((tide["item_count"], tide["latest_date"], tide["cadence"], tide["typical_duration_seconds"]), (6, "2026-11-12", "daily", 518))
        self.assertEqual(tide["latest_titles"], ["The keeper's ledger, read aloud", "Colza oil and clockwork", "Times that are not times"])
        self.assertEqual(tide["available"], {"digest": 6, "transcript": 4, "link_back": True})
        self.assertEqual((tide["suggested_keep"], tide["publish"], tide["icon"]), (3, "full", {"symbol": "waveform", "colour": "teal"}))
        items = support.items(self.out, "tide-tables")
        self.assertEqual(tide["avg_bytes"], sum(i["bytes"] for i in items) // len(items))
        self.assertTrue(tide["whats_new"].startswith("Newest: The keeper's ledger, read aloud (2026-11-12). Before that: Colza oil"))
        self.assertLessEqual(len(tide["overview"]), 600)
        gazette = support.listing(self.out, "port-gazette")
        self.assertEqual((gazette["kind"], gazette["typical_duration_seconds"], gazette["available"]["transcript"]), ("news", None, 0))

    def test_every_item_can_be_talked_about_from_its_own_files(self):
        support.run(self.out)
        files = support.tree(self.out)
        for listing in support.store(self.out)["sources"]:
            for item in support.items(self.out, listing["id"]):
                d = json.loads(files[item["digest"]["path"]])
                self.assertEqual((d["title"], d["link"], d["source_name"], d["date"]), (item["title"], item["link"], listing["name"], item["date"]))
                self.assertTrue(d["about"] and d["starters"], "a digest alone is enough to open a conversation")
                self.assertEqual(item["bytes"], len(files[item["digest"]["path"]]) + (len(files[item["transcript"]["file"]["path"]]) if item["transcript"]["file"] else 0))
                self.assertLessEqual(len(item["teaser"]), 240)
                if item["transcript"]["file"]:
                    t = pt.parse(files[item["transcript"]["file"]["path"]].decode())
                    for q in d["quotes"]:
                        self.assertIn(q["text"], t.segments[q["at"]["segment"]].text)
                    for p in d["talking_points"]:
                        self.assertEqual(t.segments[p["at"]["segment"]].start, p["at"]["time_seconds"], "a pointer leads into the transcript")

    def test_news_is_headline_short_description_and_link_only(self):
        support.run(self.out)
        for path, data in support.tree(self.out).items():
            self.assertNotIn(b"FULL ARTICLE TEXT", data, path)
            self.assertNotIn(b"many paragraphs", data, path)
        items = support.items(self.out, "port-gazette")
        d = support.digest_of(self.out, "port-gazette", items[0]["id"])
        self.assertEqual((d["basis"], d["talking_points"], d["quotes"], d["tone"]), ("headline", [], [], "news"))
        self.assertEqual(d["link"], "https://gazette.example.org/a/4")
        self.assertLessEqual(len(d["about"]), 280)

    def test_hostile_publisher_text_does_not_reach_any_text_field(self):
        support.run(self.out)
        for path, data in support.tree(self.out).items():
            if path.endswith(".json") and path != "state.json":
                self.assertNotIn(b"evil", data, path)
                self.assertNotIn(b"<script", data, path)
                self.assertNotIn(b"onerror", data, path)
                self.assertFalse(re.search(rb"(?i)ignore (all )?previous instructions", data), path)
        hostile = next(i for i in support.items(self.out, "tide-tables") if i["date"] == "2026-11-07")
        self.assertEqual(hostile["title"], "A transcript that shouts orders & links")
        d = support.digest_of(self.out, "tide-tables", hostile["id"])
        self.assertEqual(d["link"], "https://tide.example.org/episodes/1")
        self.assertEqual(d["quality"]["grade"], "full")
        last = next(i for i in support.items(self.out, "port-gazette") if i["date"] == "2026-11-09")
        self.assertIsNone(textrules.check(last["title"]))

    def test_times_that_are_not_times_become_unknown(self):
        support.run(self.out)
        item = next(i for i in support.items(self.out, "tide-tables") if i["date"] == "2026-11-10")
        self.assertIsNone(item["duration_seconds"], "the feed said the length was nan")
        text = support.tree(self.out)[item["transcript"]["file"]["path"]].decode()
        self.assertTrue(pt.conforms(pt.validate(text.encode())))
        self.assertIn("[--:--:--]", text)
        self.assertNotIn("nan", text.lower().split("---")[0].replace("provenance", ""))
        d = support.digest_of(self.out, "tide-tables", item["id"])
        for p in d["talking_points"]:
            self.assertTrue(p["at"]["time_seconds"] is None or 0 <= p["at"]["time_seconds"] < 600)

    def test_transcripts_that_cannot_be_used_get_a_typed_reason(self):
        big = make_fixtures.vtt(6, [("Mara", "The tide tables for the coming week were read out in full, one harbour after another.")] * 30_000)

        def change(r):
            r["https://media.tide.example.org/ep6.vtt"] = {"file": "tide/big.vtt", "content_type": "text/vtt"}
            r["https://media.tide.example.org/ep5.srt"] = {"file": "tide/latin1.srt", "content_type": "application/x-subrip"}
            r["https://media.tide.example.org/ep4.json"] = {"status": 302, "location": "https://192.168.0.10/ep4.json"}
            r["https://media.tide.example.org/ep1-hostile.vtt"] = {"file": "tide/page.html", "content_type": "text/html"}
        web = self.web(change)
        for name, data in (("big.vtt", big.encode()), ("latin1.srt", make_fixtures.srt(5).replace("Thanks", "Café thanks").encode("latin-1")),
                           ("page.html", b"<!DOCTYPE html><html><body><p>Please sign in to read the transcript.</p></body></html>")):
            with open(os.path.join(web, "tide", name), "wb") as f:
                f.write(data)
        self.assertGreater(len(big), 1_500_000)
        health = support.run(self.out, web=web)
        self.assertEqual(self.codes(), [])
        tide = {i["date"]: i for i in support.items(self.out, "tide-tables")}
        self.assertEqual((tide["2026-11-12"]["transcript"]["available"], tide["2026-11-12"]["transcript"]["reason"]), ("partial", "cut"))
        cut = support.tree(self.out)[tide["2026-11-12"]["transcript"]["file"]["path"]].decode()
        self.assertTrue(cut.endswith(pt.CUT_MARK) and "quality: partial (" in cut)
        self.assertEqual(support.digest_of(self.out, "tide-tables", tide["2026-11-12"]["id"])["quality"]["grade"], "partial")
        self.assertEqual(tide["2026-11-11"]["transcript"]["reason"], "unreadable")
        self.assertEqual(tide["2026-11-10"]["transcript"]["reason"], "fetch_failed")
        self.assertEqual(tide["2026-11-07"]["transcript"]["reason"], "unreadable")
        notes = " ".join(self.health_of(health, "tide-tables")["notes"])
        self.assertIn("not UTF-8 text", notes)
        self.assertIn("not a public https address", notes)

    def test_running_twice_gives_the_same_output(self):
        other = os.path.join(self.base, "other")
        support.run(self.out)
        support.run(other)
        self.assertEqual(support.tree(self.out), support.tree(other), "two runs at the same time of day are the same byte for byte")
        first = support.tree(self.out)
        health = support.run(self.out, LATER)
        second = support.tree(self.out)
        self.assertEqual(set(first), set(second))
        for path in first:
            if path == "health.json":
                continue
            a, b = first[path], second[path]
            if path in ("store.json", "briefs-index.json"):
                a, b = a.replace(b"2026-11-14T12:00:00Z", b"T"), b.replace(b"2026-11-14T18:00:00Z", b"T")
            self.assertEqual(a, b, path + " differs only by generated_at")
        self.assertEqual([(s["new"], s["outcome"]) for s in health["sources"]], [(0, "unchanged"), (0, "ok"), (0, "ok"), (0, "unchanged"), (0, "unchanged")],
                         "a feed that answers 'not modified' is not read again; the feed with a failed transcript is")
        self.assertLess(health["totals"]["requests"], 14)

    def test_the_run_can_be_split_into_three_jobs(self):
        work = os.path.join(self.base, "work")
        args = ["--config", support.CONFIG]
        self.assertEqual(cli.main(["fetch", *args, "--work", work, "--offline-fixtures", support.WEB, "--now", "2026-11-14T12:00:00Z"]), 0)
        self.assertEqual(cli.main(["digest", *args, "--work", work]), 0)
        with contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(cli.main(["briefs", *args, "--work", work]), 0)   # no key: writes nothing, the build makes extractive briefs
        summary = os.path.join(self.base, "summary.md")
        self.assertEqual(cli.main(["build", *args, "--work", work, "--out", self.out, "--summary", summary]), 0)
        other = os.path.join(self.base, "other")
        support.run(other)
        self.assertEqual(support.tree(self.out), support.tree(other))
        with open(summary, encoding="utf-8") as f:
            text = f.read()
        self.assertIn("| tide-tables | ok | active | 6 |", text)
        with contextlib.redirect_stdout(io.StringIO()) as said:
            self.assertEqual(cli.main(["validate", self.out]), 0)
        self.assertTrue(said.getvalue().startswith("valid: 5 sources, 20 items"))


class KeepingWhatIsGood(Base):
    def test_a_failed_source_keeps_its_last_good_items_and_the_rest_still_publishes(self):
        support.run(self.out)
        before = support.tree(self.out)
        for change, code in ((support.broken_tide, "fetch_failed"),
                             (lambda r: r.update({"https://tide.example.org/feed.xml": {"file": "gazette/robots.txt", "content_type": "text/html"}}), "format_changed"),
                             (lambda r: r.update({"https://tide.example.org/feed.xml": {"error": "timeout"}}), "fetch_failed"),
                             (lambda r: r.update({"https://tide.example.org/robots.txt": {"status": 500}}), "robots_disallowed")):
            out = os.path.join(self.base, code + str(len(os.listdir(self.base))))
            shutil.copytree(self.out, out)
            health = support.run(out, LATER, web=self.web(change, "web-" + os.path.basename(out)))
            self.assertEqual(self.codes(out), [])
            tide = support.listing(out, "tide-tables")
            self.assertEqual((tide["state"], tide["state_reason"]["code"], tide["item_count"]), ("active", code, 6))
            self.assertEqual(tide["freshness"], {"status": "stale", "last_ok": "2026-11-14T12:00:00Z", "failed_runs": 1})
            after = support.tree(out)
            self.assertEqual({p: d for p, d in before.items() if p.startswith("sources/")}, {p: d for p, d in after.items() if p.startswith("sources/")},
                             "no good file is deleted or changed by a failed run")
            self.assertEqual(self.health_of(health, "tide-tables")["outcome"], "failed")
            self.assertEqual([s["outcome"] for s in health["sources"] if s["id"] != "tide-tables"], ["unchanged", "ok", "unchanged", "unchanged"])

    def test_an_item_whose_refresh_fails_keeps_its_earlier_copy_and_is_marked_stale(self):
        support.run(self.out)
        before = {i["date"]: i for i in support.items(self.out, "tide-tables")}

        def change(r):
            path = os.path.join(self.base, "web", "tide", "feed.xml")
            with open(path, encoding="utf-8") as f:
                text = f.read()
            with open(path, "w", encoding="utf-8") as f:
                f.write(text.replace("ep6.vtt", "ep6-moved.vtt"))
            r["https://tide.example.org/feed.xml"]["etag"] = '"tide-2"'
        health = support.run(self.out, LATER, web=self.web(change))
        self.assertEqual(self.codes(), [])
        after = {i["date"]: i for i in support.items(self.out, "tide-tables")}
        self.assertEqual((after["2026-11-12"]["stale"], after["2026-11-12"]["stale_reason"]), (True, "fetch_failed"))
        self.assertEqual(after["2026-11-12"]["digest"], before["2026-11-12"]["digest"])
        self.assertEqual(after["2026-11-12"]["transcript"], before["2026-11-12"]["transcript"])
        self.assertEqual(self.health_of(health, "tide-tables")["stale"], 1)
        self.assertEqual(support.listing(self.out, "tide-tables")["state"], "active")
        support.run(self.out, LATER + datetime.timedelta(hours=6))
        self.assertFalse(next(i for i in support.items(self.out, "tide-tables") if i["date"] == "2026-11-12")["stale"], "and it recovers when the file is back")

    def test_a_source_that_does_not_validate_is_not_published_and_the_others_are(self):
        real = pipeline._new_item

        def broken(config, source, work, item):
            entry, files = real(config, source, work, item)
            if source["id"] == "quay-notes":
                entry["digest"]["sha256"] = "0" * 64
            return entry, files
        pipeline._new_item = broken
        self.addCleanup(setattr, pipeline, "_new_item", real)
        health = support.run(self.out)
        self.assertEqual(self.codes(), [])
        quay = support.listing(self.out, "quay-notes")
        self.assertEqual((quay["state"], quay["item_count"], quay["items_file"], quay["state_reason"]["code"], quay["freshness"]["failed_runs"]), ("active", 0, None, "invalid_output", 1))
        self.assertFalse(os.path.exists(os.path.join(self.out, "sources", "quay-notes")))
        self.assertEqual(support.listing(self.out, "tide-tables")["item_count"], 6)
        self.assertEqual(self.health_of(health, "quay-notes")["outcome"], "failed")
        pipeline._new_item = real
        support.run(self.out, LATER)
        self.assertEqual((support.listing(self.out, "quay-notes")["item_count"], support.listing(self.out, "quay-notes")["freshness"]["failed_runs"]), (2, 0))

    def test_an_output_that_does_not_validate_never_replaces_the_previous_one(self):
        support.run(self.out)
        before = support.tree(self.out)
        tiny = support.load_config(lambda c: c["defaults"].update(max_total_bytes=100_000))
        with self.assertRaises(RuntimeError):
            support.run(self.out, LATER, config=tiny, web=self.web(lambda r: r["https://tide.example.org/feed.xml"].update(etag='"x"')))
        self.assertEqual(support.tree(self.out), before)
        self.assertFalse(os.path.exists(self.out + ".building"))

    def test_a_damaged_previous_output_is_not_trusted(self):
        support.run(self.out)
        item = support.items(self.out, "tide-tables")[0]
        with open(os.path.join(self.out, *item["digest"]["path"].split("/")), "ab") as f:
            f.write(b" ")
        self.assertEqual(self.codes(), ["size_mismatch"])
        health = support.run(self.out, LATER)
        self.assertEqual(self.codes(), [])
        self.assertEqual(self.health_of(health, "tide-tables")["new"], 6, "the source is rebuilt from the publisher, not from the damaged copy")
        with open(os.path.join(self.out, "store.json"), "w") as f:
            f.write("{not json")
        support.run(self.out, LATER)
        self.assertEqual(self.codes(), [])

    def test_old_items_are_pruned_and_the_newest_are_kept(self):
        few = support.load_config(lambda c: c["defaults"].update(max_items=2))
        health = support.run(self.out, config=few)
        self.assertEqual([s["item_count"] for s in support.store(self.out)["sources"]], [2, 2, 2, 2, 2])
        self.assertEqual([i["date"] for i in support.items(self.out, "tide-tables")], ["2026-11-12", "2026-11-11"])
        support.run(self.out, config=support.load_config())
        self.assertEqual([s["item_count"] for s in support.store(self.out)["sources"]], [4, 6, 2, 4, 4])
        gone = support.run(self.out, support.T0 + datetime.timedelta(days=60), config=support.load_config(lambda c: c["defaults"].update(retention_days=40)))
        self.assertEqual(self.codes(), [])
        self.assertEqual([s["item_count"] for s in support.store(self.out)["sources"]], [0, 0, 0, 0, 0])
        self.assertEqual(self.health_of(gone, "tide-tables")["pruned"], 6)
        self.assertEqual(sorted(p for p in support.tree(self.out) if p.startswith("sources/")), [])

    def test_a_feed_that_changes_shape_is_noticed(self):
        support.run(self.out)

        def change(r):
            path = os.path.join(self.base, "web", "tide", "feed.xml")
            with open(path, encoding="utf-8") as f:
                text = f.read()
            with open(path, "w", encoding="utf-8") as f:
                f.write(re.sub(r"<podcast:transcript[^>]*/>", "", text))
            r["https://tide.example.org/feed.xml"]["etag"] = '"tide-3"'
        health = support.run(self.out, LATER, web=self.web(change))
        self.assertEqual(self.codes(), [])
        self.assertTrue(any("changed shape: no longer has podcast:transcript" in n for n in self.health_of(health, "tide-tables")["notes"]))
        self.assertEqual(support.listing(self.out, "tide-tables")["state"], "active")


class Lifecycle(Base):
    def test_every_state_change(self):
        seen = {}
        out = support.walk_lifecycle(self.base, lambda name, folder: seen.__setitem__(name, (support.store(folder), validate.check_folder(folder).problems,
                                                                                               sorted(os.listdir(os.path.join(folder, "sources"))) if os.path.isdir(os.path.join(folder, "sources")) else [])))
        for name, (store, problems, folders) in seen.items():
            self.assertEqual(problems, [], name)

        def source(name, sid):
            return next((s for s in seen[name][0]["sources"] if s["id"] == sid), None)
        tide = source("02-stale-after-one-failure", "tide-tables")
        self.assertEqual((tide["state"], tide["freshness"]["status"], tide["freshness"]["failed_runs"], tide["item_count"], tide["message"]), ("active", "stale", 1, 4, None))
        tide = source("03-paused-automatically", "tide-tables")
        self.assertEqual((tide["state"], tide["state_reason"]["code"], tide["freshness"]["failed_runs"], tide["item_count"], tide["purge"]), ("paused", "fetch_failed", 3, 4, False))
        self.assertEqual(tide["message"], "This source could not be read 3 times in a row. What is shown is the last good copy.")
        self.assertEqual((tide["state_since"], tide["freshness"]["last_ok"]), ("2026-11-15T06:00:00Z", "2026-11-14T12:00:00Z"))
        self.assertEqual(source("03-paused-automatically", "harbor-voices")["state"], "active", "the other sources are not touched")
        tide = source("04-recovered", "tide-tables")
        self.assertEqual((tide["state"], tide["state_since"], tide["message"], tide["freshness"]), ("active", None, None, {"status": "fresh", "last_ok": None, "failed_runs": 0}))
        harbor = source("05-paused-by-the-curator", "harbor-voices")
        self.assertEqual((harbor["state"], harbor["state_reason"]["code"], harbor["item_count"], harbor["freshness"]["status"]), ("paused", "manual", 3, "stale"))
        self.assertTrue(harbor["message"].startswith("Paused while the publisher"))
        self.assertEqual(source("06-withdrawn", "harbor-voices")["state_since"], harbor["state_since"], "the time a state began does not move")
        quay = source("06-withdrawn", "quay-notes")
        self.assertEqual((quay["state"], quay["state_reason"]["code"], quay["item_count"], quay["items_file"], quay["latest_titles"], quay["purge"]), ("withdrawn", "quality", 0, None, [], False))
        self.assertNotIn("quay-notes", seen["06-withdrawn"][2], "a withdrawn source's files are gone from the output")
        gazette = source("07-withdrawn-with-purge", "port-gazette")
        self.assertEqual((gazette["state"], gazette["purge"], gazette["state_reason"]["code"]), ("withdrawn", True, "takedown"))
        removed = source("08-removed-from-the-config", "harbor-voices")
        self.assertEqual((removed["state"], removed["state_reason"]["code"], removed["message"], removed["purge"], removed["item_count"]),
                         ("withdrawn", "removed", "The curator removed this source.", False, 0))
        self.assertEqual((removed["name"], removed["site"]), ("Harbor Voices", "https://harbor.example.org/"), "the notice still says which source it was")
        self.assertEqual(seen["08-removed-from-the-config"][2], ["lamp-room", "tide-tables"])
        self.assertEqual([s["id"] for s in seen["09-notices-expired"][0]["sources"]], ["tide-tables", "lamp-room"], "after the notice period the withdrawn sources are dropped")

    def test_a_manual_state_always_wins(self):
        broken = self.web(support.broken_tide)
        keep_active = support.load_config(lambda c: c["sources"][1].update(state="active"))
        support.run(self.out)
        for n in range(5):
            support.run(self.out, support.T0 + datetime.timedelta(hours=6 * (n + 1)), config=keep_active, web=broken)
        tide = support.listing(self.out, "tide-tables")
        self.assertEqual((tide["state"], tide["freshness"]["status"], tide["freshness"]["failed_runs"]), ("active", "stale", 5))
        paused = support.load_config(lambda c: c["sources"][1].update(state="paused", message="Paused by hand."))
        health = support.run(self.out, support.T0 + datetime.timedelta(days=3), config=paused)
        tide = support.listing(self.out, "tide-tables")
        self.assertEqual((tide["state"], tide["state_reason"]["code"], tide["message"], tide["item_count"]), ("paused", "manual", "Paused by hand.", 6))
        self.assertEqual(self.health_of(health, "tide-tables")["outcome"], "skipped", "a source paused by hand is not fetched")
        self.assertEqual(self.codes(), [])

    def test_the_number_of_failed_runs_before_a_pause_is_configurable(self):
        broken = self.web(support.broken_tide)
        once = support.load_config(lambda c: c["defaults"].update(auto_pause_after_failed_runs=1))
        support.run(self.out, config=once)
        support.run(self.out, LATER, config=once, web=broken)
        self.assertEqual(support.listing(self.out, "tide-tables")["state"], "paused")

    def test_a_source_that_fails_from_its_first_run_is_listed_without_items(self):
        support.run(self.out, web=self.web(support.broken_tide))
        tide = support.listing(self.out, "tide-tables")
        self.assertEqual((tide["state"], tide["item_count"], tide["items_file"], tide["freshness"]), ("active", 0, None, {"status": "stale", "last_ok": None, "failed_runs": 1}))
        self.assertEqual(self.codes(), [])


class OnlyFullTranscripts(Base):
    """The rule of the catalog. An item is listed only when the assistant has a full path to its whole text (`discussable`: the transcript was
    read in full or in part and the item carries `transcript_source`). A source with too few discussable items among its newest is counted as
    failed, so it is paused like any source that cannot be read, and later withdrawn."""

    def strict(self, **more):
        values = dict(dict(min_full_transcript_share=0.6, min_discussable_items=2, transcript_check_items=5, phone_probe=False), **more)
        return support.load_config(lambda c: (support.strict(c), c["defaults"].update(values)))

    def test_an_item_without_a_path_to_its_whole_text_is_not_listed(self):
        health = support.run(self.out, config=self.strict(min_discussable_items=0, min_full_transcript_share=0))
        self.assertEqual(self.codes(), [])
        tide = {i["date"]: i for i in support.items(self.out, "tide-tables")}
        self.assertEqual(sorted(tide), ["2026-11-07", "2026-11-10", "2026-11-11", "2026-11-12"], "the item with no transcript (11-09) and the one that failed to fetch (11-08) are out")
        for item in tide.values():
            self.assertIn(item["transcript"]["read"], ("full", "partial"))
            self.assertIn("transcript_source", item)
        harbor = support.items(self.out, "harbor-voices")
        self.assertEqual(len(harbor), 3, "read and withheld, with an address to fetch the whole text from: listed; the one without a transcript is not")
        self.assertTrue(all(i["transcript"]["read"] == "full" and "transcript_source" in i for i in harbor))
        listing = support.listing(self.out, "tide-tables")
        self.assertEqual((listing["item_count"], listing["available"]["digest"], len(listing["latest_titles"])), (4, 4, 3), "the card counts discussable items only")
        report = self.health_of(health, "tide-tables")
        self.assertEqual((report["items"], report["dropped"]), (4, {"none_published": 1, "fetch_failed": 1, "unreadable": 0, "no_source": 0, "phone_probe": 0}))
        self.assertEqual(self.health_of(health, "harbor-voices")["dropped"]["none_published"], 1)
        self.assertEqual(sum(1 for p in support.tree(self.out) if p.endswith(".digest.json")), health["totals"]["items"], "a dropped item has no digest in the output either")
        self.assertEqual(js.validate(health, validate.schema("health")), [])

    def test_what_was_skipped_is_remembered_and_shown_again_when_the_feed_is_unchanged(self):
        config = self.strict(min_discussable_items=0, min_full_transcript_share=0)
        first = support.run(self.out, config=config)
        again = support.run(self.out, LATER, config=config)   # the feed answers "not modified"
        report = self.health_of(again, "harbor-voices")
        self.assertEqual((report["outcome"], report["items"], report["new"], report["dropped"]["none_published"]), ("unchanged", 3, 0, 1))
        self.assertEqual(self.health_of(again, "tide-tables")["dropped"], self.health_of(first, "tide-tables")["dropped"])
        self.assertEqual(self.health_of(again, "tide-tables")["items"], 4)

    def test_a_feed_read_again_does_not_bring_a_dropped_item_back(self):
        config = self.strict(min_discussable_items=0, min_full_transcript_share=0)
        support.run(self.out, config=config)
        changed = self.web(lambda r: r["https://tide.example.org/feed.xml"].update(etag='"tide-2"'))
        health = support.run(self.out, support.T0 + datetime.timedelta(days=10), config, changed)
        tide = self.health_of(health, "tide-tables")
        self.assertEqual((tide["outcome"], tide["items"], tide["new"], tide["dropped"]["none_published"], tide["dropped"]["fetch_failed"]), ("ok", 4, 0, 1, 1))
        self.assertEqual(sorted(i["date"] for i in support.items(self.out, "tide-tables")), ["2026-11-07", "2026-11-10", "2026-11-11", "2026-11-12"])
        self.assertEqual(self.codes(), [])

    def test_an_output_written_before_the_rule_loses_its_undiscussable_items_without_new_requests(self):
        support.run(self.out)   # the fixtures' own config keeps every item, as the generator did before 0.5.0
        self.assertEqual(len(support.items(self.out, "tide-tables")), 6)
        before = {p: d for p, d in support.tree(self.out).items() if p.startswith("sources/tide-tables/") and p.endswith(".digest.json")}
        health = support.run(self.out, LATER, self.strict(min_discussable_items=0, min_full_transcript_share=0))
        self.assertEqual(self.codes(), [])
        tide = self.health_of(health, "tide-tables")
        self.assertEqual((tide["items"], tide["reused"], tide["new"], tide["dropped"]["none_published"]), (4, 4, 0, 1))
        self.assertEqual(sorted(i["date"] for i in support.items(self.out, "tide-tables")), ["2026-11-07", "2026-11-10", "2026-11-11", "2026-11-12"])
        kept = {p for p in support.tree(self.out) if p.startswith("sources/tide-tables/") and p.endswith(".digest.json")}
        self.assertEqual(len(kept), 4, "the digests of the items that left are gone too")
        self.assertTrue(all(support.tree(self.out)[p] == before[p] for p in kept), "what stays is exactly what it was")

    def test_a_source_below_the_minimum_is_not_published_and_the_others_are(self):
        health = support.run(self.out, config=self.strict())
        self.assertEqual(self.codes(), [])
        states = {s["id"]: (s["state"], s["freshness"]["status"], s["item_count"]) for s in support.store(self.out)["sources"]}
        self.assertEqual(states, {"harbor-voices": ("active", "fresh", 3), "tide-tables": ("active", "fresh", 4), "quay-notes": ("active", "stale", 0), "port-gazette": ("active", "stale", 0),
                                  "lamp-room": ("active", "stale", 0)},
                         "three of four and three of five are enough; show notes alone and headlines alone are not")
        quay = self.health_of(health, "quay-notes")
        self.assertEqual((quay["outcome"], quay["reason"]["code"]), ("failed", "empty"))
        self.assertIn("full transcripts for 0 of the newest 2 items", quay["reason"]["detail"])
        self.assertEqual(quay["dropped"]["none_published"], 2, "what was skipped is counted, with its reason")
        self.assertFalse(os.path.exists(os.path.join(self.out, "sources", "quay-notes")))
        self.assertEqual({i["transcript"]["read"] for i in support.items(self.out, "harbor-voices")}, {"full"}, "what was read is said, and only what was read is listed")

    def test_it_is_paused_after_the_usual_number_of_runs_and_then_withdrawn(self):
        config = self.strict(withdraw_without_transcripts_days=30)
        for n in range(3):
            support.run(self.out, support.T0 + datetime.timedelta(hours=6 * n), config)
        quay = support.listing(self.out, "quay-notes")
        self.assertEqual((quay["state"], quay["state_reason"]["code"], quay["freshness"]["failed_runs"]), ("paused", "empty", 3))
        self.assertIn("no longer publishes full transcripts", quay["message"])
        self.assertIsNone(textrules.check(quay["message"]))
        self.assertEqual(self.codes(), [])
        support.run(self.out, support.T0 + datetime.timedelta(days=29), config)
        self.assertEqual(support.listing(self.out, "quay-notes")["state"], "paused")
        health = support.run(self.out, support.T0 + datetime.timedelta(days=31), config)
        quay = support.listing(self.out, "quay-notes")
        self.assertEqual((quay["state"], quay["state_reason"]["code"], quay["purge"], quay["item_count"]), ("withdrawn", "quality", False, 0))
        self.assertIn("stopped publishing full transcripts", quay["message"])
        self.assertEqual(self.health_of(health, "quay-notes")["state"], "withdrawn")
        self.assertEqual(self.codes(), [])
        support.run(self.out, support.T0 + datetime.timedelta(days=32), config)
        self.assertEqual(support.listing(self.out, "quay-notes")["state"], "withdrawn", "it stays withdrawn while nothing changes")
        self.assertEqual(support.listing(self.out, "tide-tables")["state"], "active")

    def test_a_source_that_stops_publishing_transcripts_keeps_its_last_good_items_and_comes_back(self):
        config = self.strict()
        support.run(self.out, config=config)
        before = support.tree(self.out)

        def none_published(responses):   # the same feed, but no entry lists a transcript any more
            with open(os.path.join(support.WEB, "tide", "feed.xml"), encoding="utf-8") as f:
                feed = re.sub(r"<podcast:transcript [^>]*/>", "", f.read())
            with open(os.path.join(self.base, "web", "tide", "feed.xml"), "w", encoding="utf-8") as f:
                f.write(feed)
            responses["https://tide.example.org/feed.xml"]["etag"] = '"tide-2"'
        web = self.web(lambda r: None)
        support.web_copy(os.path.join(self.base, "web2"), None)
        with open(os.path.join(web, "manifest.json"), encoding="utf-8") as f:
            manifest = json.load(f)
        none_published(manifest["responses"])
        with open(os.path.join(web, "manifest.json"), "w", encoding="utf-8") as f:
            json.dump(manifest, f)
        for n in range(1, 4):
            health = support.run(self.out, support.T0 + datetime.timedelta(hours=6 * n), config, web)
            self.assertEqual(self.codes(), [])
        tide = support.listing(self.out, "tide-tables")
        self.assertEqual((tide["state"], tide["state_reason"]["code"], tide["item_count"]), ("paused", "format_changed", 4), "it used to have items, so the reason says it changed")
        self.assertEqual({p: d for p, d in support.tree(self.out).items() if p.startswith("sources/tide-tables/")},
                         {p: d for p, d in before.items() if p.startswith("sources/tide-tables/")}, "the last good items are kept exactly as they were")
        self.assertEqual(support.listing(self.out, "harbor-voices")["state"], "active", "one source never holds up another")
        support.run(self.out, support.T0 + datetime.timedelta(hours=30), config)
        tide = support.listing(self.out, "tide-tables")
        self.assertEqual((tide["state"], tide["freshness"]["status"]), ("active", "fresh"), "the transcripts are back, and so is the source")

    def test_what_counts_as_discussable_and_how_many_are_enough(self):
        config = self.strict()
        source = config["sources"][0]

        def item(ok):
            return {"discussable": ok}
        judge = lambda items, before=None: pipeline.judge(config, source, {"items": items}, before or {})   # noqa: E731
        self.assertIsNone(judge([item(True)] * 3 + [item(False)] * 2), "three of five: 60 percent and at least two")
        self.assertIn("2 of the newest 5", judge([item(True)] * 2 + [item(False)] * 3 + [item(True)] * 9)["detail"], "only the newest five are looked at")
        self.assertEqual(judge([item(True)] * 2 + [item(False)] * 3)["code"], "format_changed", "two of five is below 60 percent although it is not below two")
        self.assertIsNone(judge([item(True)] * 2), "two of two")
        self.assertEqual(judge([item(True)])["code"], "format_changed", "one is below the minimum of two, however few items the source has")
        self.assertEqual(judge([])["code"], "empty", "nothing at all is not a source")
        self.assertEqual(judge([item(False)] * 5)["code"], "empty", "nothing now and never before")
        had = {"a": {"transcript": {"available": "no", "reason": "withheld_terms", "file": None, "read": "full"}, "transcript_source": {"link": "https://x.example.org/t.vtt"}}}
        self.assertEqual(judge([item(False)] * 5, had)["code"], "format_changed", "it used to have items: the source changed")
        floor = self.strict(min_full_transcript_share=0)
        self.assertIsNone(pipeline.judge(floor, floor["sources"][0], {"items": [item(True)] * 2 + [item(False)] * 3}, {}), "the floor of two alone: two of five is enough")
        self.assertIsNotNone(pipeline.judge(floor, floor["sources"][0], {"items": [item(True)] + [item(False)] * 4}, {}))
        off = support.load_config(lambda c: c["defaults"].update(min_full_transcript_share=0, min_discussable_items=0))
        self.assertIsNone(pipeline.judge(off, off["sources"][0], {"items": [item(False)] * 5}, {}), "both at zero switches the check off")
        entry = lambda **t: {"transcript": dict({"available": "no", "reason": "none_published", "file": None}, **t), "digest": {"basis": "notes", "grade": "partial"}}   # noqa: E731
        self.assertTrue(pipeline.discussable(dict(entry(read="full"), transcript_source={"link": "https://x.example.org/t"})))
        self.assertFalse(pipeline.discussable(entry(read="full")), "read, but nowhere to fetch the whole text: not discussable")
        self.assertFalse(pipeline.discussable(dict(entry(read="none"), transcript_source={"link": "https://x.example.org/t"})))
        self.assertEqual((pipeline.drop_reason(entry(read="none")), pipeline.drop_reason(entry(read="none", reason="fetch_failed")), pipeline.drop_reason(entry(read="full"))),
                         ("none_published", "fetch_failed", "no_source"))


class Restore(Base):
    def published(self, change=None):
        shutil.rmtree(self.out, ignore_errors=True)
        support.run(self.out)
        web = tempfile.mkdtemp(prefix="pages-", dir=self.base)
        shutil.copytree(self.out, os.path.join(web, "site"))
        responses = {"https://pages.example.org/kb/" + p: {"file": "site/" + p, "content_type": "application/json"} for p in support.tree(self.out) if p != ".nojekyll"}
        if change:
            change(responses, os.path.join(web, "site"))
        with open(os.path.join(web, "manifest.json"), "w") as f:
            json.dump({"responses": responses}, f)
        return web

    def test_the_published_output_comes_back_file_for_file(self):
        back = os.path.join(self.base, "back")
        self.assertEqual(cli.main(["restore", "--url", "https://pages.example.org/kb/", "--out", back, "--offline-fixtures", self.published()]), 0)
        want = support.tree(self.out)
        want.pop(".nojekyll")
        self.assertEqual(support.tree(back), want)
        health = support.run(back, LATER)
        self.assertEqual(sum(s["new"] for s in health["sources"]), 0, "the restored output is the pipeline's memory")

    def test_nothing_published_yet_is_an_empty_start_and_other_failures_stop_the_run(self):
        back = os.path.join(self.base, "back")
        self.assertEqual(cli.main(["restore", "--url", "https://pages.example.org/other/", "--out", back, "--offline-fixtures", self.published()]), 0)
        self.assertEqual(os.listdir(back), [])
        web = self.published(lambda r, site: r.update({"https://pages.example.org/kb/store.json": {"status": 503}}))
        shutil.rmtree(back)
        self.assertEqual(cli.main(["restore", "--url", "https://pages.example.org/kb/", "--out", back, "--offline-fixtures", web]), 2)

    def test_a_file_that_does_not_match_its_hash_is_not_restored(self):
        def tamper(responses, site):
            path = next(p for p in sorted(support.tree(site)) if p.endswith(".digest.json") and "tide-tables" in p)
            with open(os.path.join(site, path), "ab") as f:
                f.write(b"\n")
            self.tampered = path
        back = os.path.join(self.base, "back")
        self.assertEqual(cli.main(["restore", "--url", "https://pages.example.org/kb/", "--out", back, "--offline-fixtures", self.published(tamper)]), 0)
        self.assertNotIn(self.tampered, support.tree(back))
        health = support.run(back, LATER)
        self.assertEqual(self.codes(back), [])
        self.assertEqual(self.health_of(health, "tide-tables")["new"], 6)


class CommandLine(Base):
    def test_run_and_validate_from_a_checkout(self):
        def go(*args):
            return subprocess.run([sys.executable, "-m", "pea_knowledge", *args], cwd=support.ROOT, capture_output=True, text=True, timeout=120,
                                  env={"PATH": os.environ.get("PATH", ""), "SOURCE_DATE_EPOCH": "1794657600"})
        done = go("run", "--config", "tests/fixtures/sources.json", "--out", self.out, "--offline-fixtures", "tests/fixtures/web")
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertIn("5 sources, 20 items", done.stdout)
        self.assertEqual(support.store(self.out)["generated_at"], "2026-11-14T12:00:00Z")
        done = go("validate", self.out)
        self.assertEqual((done.returncode, done.stdout.strip().split(":")[0]), (0, "valid"))
        self.assertIn("| tide-tables | ok | active |", go("summary", self.out).stdout)
        with open(os.path.join(self.out, "sources", "tide-tables", "items.json"), "ab") as f:
            f.write(b" ")
        done = go("validate", self.out)
        self.assertEqual(done.returncode, 1)
        self.assertIn("size_mismatch", done.stdout)
        self.assertIn("NOT VALID", done.stdout)
        done = go("run", "--config", "tests/fixtures/web/manifest.json", "--out", self.out, "--offline-fixtures", "tests/fixtures/web")
        self.assertEqual(done.returncode, 2)
        self.assertIn("error:", done.stderr)


if __name__ == "__main__":
    unittest.main()
