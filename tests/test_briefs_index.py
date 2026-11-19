# Copyright 2026 The PEA knowledge processor authors
# SPDX-License-Identifier: Apache-2.0
"""briefs-index.json (format 1.3, additive): made by every build from the items files, checked by the validator."""
import json
import os
import shutil
import tempfile
import unittest

from . import support
from pea_knowledge import briefs_index as bx, cli, validate


def items_of(folder):
    store = support.store(folder)
    return store, {s["id"]: {"items": support.items(folder, s["id"])} for s in store["sources"] if s["items_file"]}


class BriefsIndex(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.base = tempfile.mkdtemp(prefix="pea-index-")
        cls.out = os.path.join(cls.base, "dist")
        support.run(cls.out, config=support.load_strict())

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.base, ignore_errors=True)

    def index(self, folder=None):
        with open(os.path.join(folder or self.out, bx.INDEX_FILE), encoding="utf-8") as f:
            return json.load(f)

    def test_every_build_writes_an_index_that_the_validator_accepts(self):
        self.assertTrue(validate.check_folder(self.out).ok)
        index = self.index()
        store, items = items_of(self.out)
        self.assertEqual(index["generated_at"], store["generated_at"])
        self.assertEqual(index["format_version"], store["format_version"])
        listed = {s["id"]: len(i["items"]) for s, i in ((s, items[s["id"]]) for s in store["sources"] if s["id"] in items)}
        self.assertEqual({s["id"]: s["brief_count"] for s in index["shows"]}, listed, "one show per source with briefs, each with its count")
        for show in index["shows"]:
            self.assertEqual([e["item_id"] for e in show["latest"]], [i["id"] for i in items[show["id"]]["items"]][:bx.LATEST_PER_SHOW])
        newest = [s["latest"][0]["date"] for s in index["shows"]]
        self.assertEqual(newest, sorted(newest, reverse=True), "shows newest first")
        dates = [e["date"] for e in index["latest_overall"]]
        self.assertEqual(dates, sorted(dates, reverse=True))
        self.assertLessEqual(len(index["latest_overall"]), bx.LATEST_OVERALL)

    def test_the_index_is_the_same_bytes_for_the_same_output(self):
        store, items = items_of(self.out)
        with open(os.path.join(self.out, bx.INDEX_FILE), "rb") as f:
            self.assertEqual(f.read(), bx.dumps(bx.build(store, items, store["generated_at"])))

    def test_the_validator_refuses_an_index_that_disagrees_with_the_briefs_on_disk(self):
        def codes(change):
            folder = os.path.join(self.base, "tampered")
            shutil.rmtree(folder, ignore_errors=True)
            shutil.copytree(self.out, folder)
            change(folder)
            return sorted({p.code for p in validate.check_folder(folder).problems})

        def edit_index(change):
            def apply(folder):
                index = self.index(folder)
                change(index)
                with open(os.path.join(folder, bx.INDEX_FILE), "wb") as f:
                    f.write(bx.dumps(index))
            return apply
        self.assertEqual(codes(lambda f: None), [])
        self.assertEqual(codes(lambda f: os.remove(os.path.join(f, bx.INDEX_FILE))), [], "the index is optional for a reader")
        self.assertEqual(codes(edit_index(lambda x: x["shows"][0]["latest"][0].update(item_id="2026-01-01-0000000000"))), ["missing"])
        self.assertEqual(codes(edit_index(lambda x: x["shows"][0].update(brief_count=99))), ["inconsistent"])
        self.assertEqual(codes(edit_index(lambda x: x["latest_overall"].pop())), ["inconsistent"])
        self.assertEqual(codes(edit_index(lambda x: x["shows"][0]["latest"][0].update(title="Another title"))), ["inconsistent"])
        self.assertEqual(codes(edit_index(lambda x: x["shows"][0]["latest"][0].update(method="model" if x["shows"][0]["latest"][0]["method"] == "extractive" else "extractive"))), ["inconsistent"])
        self.assertEqual(codes(edit_index(lambda x: x.update(generated_at="2020-01-01T00:00:00Z"))), ["identity_mismatch"])
        self.assertEqual(codes(lambda f: open(os.path.join(f, bx.INDEX_FILE), "ab").write(b" " * 40_000)), ["too_large"])
        # A brief that is gone from the items file while the index still names it.
        index = self.index()
        sid, iid = index["shows"][0]["id"], index["shows"][0]["latest"][0]["item_id"]
        store, items = items_of(self.out)
        trimmed = dict(items, **{sid: {"items": [i for i in items[sid]["items"] if i["id"] != iid]}})
        self.assertEqual({p.code for p in validate.check_briefs_index(bx.dumps(index), store, trimmed)[1]}, {"missing"})

    def test_titles_are_cut_and_the_order_is_deterministic(self):
        store = {"generated_at": "2026-11-19T00:00:00Z", "sources": [
            {"id": "b-show", "name": "B", "kind": "podcast"}, {"id": "a-show", "name": "A", "kind": "podcast"}, {"id": "none", "name": "None", "kind": "podcast"}]}

        def item(n, date, title="An episode"):
            return {"id": "%s-%02d" % (date, n), "title": title, "date": date, "brief": {"kind": "model" if n % 2 else "extractive", "covers": "partial" if n == 3 else "whole"}}
        items = {"b-show": {"items": [item(1, "2026-11-19", "word " * 40), item(2, "2026-11-18")]},
                 "a-show": {"items": [item(3, "2026-11-19"), item(4, "2026-11-17")]}, "none": {"items": [{"id": "x", "title": "x", "date": "2026-11-19"}]}}
        index = bx.build(store, items, store["generated_at"])
        self.assertEqual([s["id"] for s in index["shows"]], ["a-show", "b-show"], "same newest date: by id; a source without briefs is not a show")
        self.assertLessEqual(len(index["shows"][1]["latest"][0]["title"]), bx.TITLE_CHARS)
        self.assertTrue(index["shows"][1]["latest"][0]["title"].endswith("…"))
        self.assertEqual([(e["show_id"], e["date"]) for e in index["latest_overall"]],
                         [("a-show", "2026-11-19"), ("b-show", "2026-11-19"), ("b-show", "2026-11-18"), ("a-show", "2026-11-17")])
        self.assertTrue(index["shows"][0]["latest"][0]["partial"])
        self.assertEqual(bx.dumps(index), bx.dumps(bx.build(store, items, store["generated_at"])))

    def test_fourteen_sources_of_five_briefs_stay_under_fifteen_kilobytes(self):
        """The size of today's feed: fourteen sources, five briefs each, titles of 56 characters (the feed's average is
        about 46, its longest about 80) and real-length ids. The published feed of 2026-11-19 (eleven shows with briefs)
        gives 11.2 KB. Even every title at the 120-character cap stays well inside what a reader accepts."""
        store = {"generated_at": "2026-11-19T00:00:00Z", "sources": [{"id": "show-number-%02d" % n, "name": "The Show Number %d Podcast" % n, "kind": "podcast"} for n in range(14)]}
        items = {s["id"]: {"items": [{"id": "2026-11-%02d-%010x" % (19 - k, n * 100 + k), "title": ("Episode %d: a guest on a subject, with a long subtitle that goes on " % k)[:56],
                                      "date": "2026-11-%02d" % (19 - k), "brief": {"kind": "model", "covers": "whole"}} for k in range(5)]}
                 for n, s in enumerate(store["sources"])}
        data = bx.dumps(bx.build(store, items, store["generated_at"]))
        self.assertLessEqual(len(data), 15_000, len(data))
        self.assertEqual(validate.read_json(data, "briefs-index", bx.INDEX_FILE, validate.INDEX_BYTES)[1], [])
        for show in items.values():
            for i in show["items"]:
                i["title"] = "x" * 200
        self.assertLess(len(bx.dumps(bx.build(store, items, store["generated_at"]))), bx.INDEX_BYTES * 3 // 4)

    def test_restore_brings_the_index_back_and_an_older_output_without_one_restores_too(self):
        for keep in (True, False):
            web = tempfile.mkdtemp(prefix="pages-", dir=self.base)
            shutil.copytree(self.out, os.path.join(web, "site"))
            files = [p for p in support.tree(self.out) if p != ".nojekyll" and (keep or p != bx.INDEX_FILE)]
            with open(os.path.join(web, "manifest.json"), "w") as f:
                json.dump({"responses": {"https://pages.example.org/kb/" + p: {"file": "site/" + p, "content_type": "application/json"} for p in files}}, f)
            back = os.path.join(self.base, "back")
            shutil.rmtree(back, ignore_errors=True)
            self.assertEqual(cli.main(["restore", "--url", "https://pages.example.org/kb/", "--out", back, "--offline-fixtures", web]), 0)
            self.assertEqual(os.path.exists(os.path.join(back, bx.INDEX_FILE)), keep)


if __name__ == "__main__":
    unittest.main()
