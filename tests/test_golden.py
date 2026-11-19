# Copyright 2026 The PEA knowledge processor authors
# SPDX-License-Identifier: Apache-2.0
"""The golden samples under tests/golden are what an app's own tests can copy. These tests keep them true."""
import json
import os
import re
import shutil
import tempfile
import unittest

from . import support, make_golden
from pea_knowledge import brief as br, digest as dg, validate

DIST = os.path.join(support.GOLDEN, "dist")
REMAKE = "run python3 tests/make_golden.py, read the diff, and commit it if the change is meant"


class Golden(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.base = tempfile.mkdtemp(prefix="pea-golden-test-")
        cls.out = os.path.join(cls.base, "dist")
        support.run(cls.out, config=support.load_strict())
        cls.states = {}
        walk = os.path.join(cls.base, "walk")
        os.makedirs(walk)
        support.walk_lifecycle(walk, lambda name, folder: cls.states.__setitem__(name, {f: support.tree(folder)[f] for f in ("store.json", "health.json")}))

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.base, ignore_errors=True)

    def test_the_golden_output_is_what_the_pipeline_writes_from_the_fixtures(self):
        made, kept = support.tree(self.out), support.tree(DIST)
        self.assertEqual(sorted(made), sorted(kept), REMAKE)
        for path in made:
            self.assertEqual(made[path], kept[path], "%s: %s" % (path, REMAKE))

    def test_the_golden_output_validates(self):
        report = validate.check_folder(DIST)
        self.assertEqual(report.problems, [])
        self.assertEqual((report.sources, report.items), (5, 9))

    def test_the_golden_lifecycle_states_are_what_the_pipeline_writes(self):
        folder = os.path.join(support.GOLDEN, "lifecycle")
        self.assertEqual(sorted(os.listdir(folder)), sorted(self.states), REMAKE)
        for name, files in self.states.items():
            for file, data in files.items():
                with open(os.path.join(folder, name, file), "rb") as f:
                    self.assertEqual(f.read(), data, "%s/%s: %s" % (name, file, REMAKE))
            store, problems = validate.check_store(files["store.json"])
            self.assertEqual(problems, [], name)
        states = {name: {s["id"]: (s["state"], s["purge"]) for s in json.loads(files["store.json"])["sources"]} for name, files in self.states.items()}
        self.assertEqual(states["03-paused-automatically"]["tide-tables"], ("paused", False))
        self.assertEqual(states["07-withdrawn-with-purge"]["port-gazette"], ("withdrawn", True))
        self.assertNotIn("harbor-voices", states["09-notices-expired"])

    def test_every_hostile_sample_is_refused_with_its_typed_reason(self):
        folder = os.path.join(support.GOLDEN, "hostile")
        with open(os.path.join(folder, "manifest.json"), encoding="utf-8") as f:
            manifest = json.load(f)["files"]
        self.assertEqual(sorted(manifest), sorted(n for n in os.listdir(folder) if n != "manifest.json"))
        self.assertGreaterEqual(len(manifest), 30)
        for name, case in sorted(manifest.items()):
            with open(os.path.join(folder, name), "rb") as f:
                data = f.read()
            if case["kind"] == "store":
                value, problems = validate.check_store(data)
            elif case["kind"] == "briefs-index":
                value, problems = validate.check_briefs_index(data, support.store(DIST), {s["id"]: {"items": support.items(DIST, s["id"])} for s in support.store(DIST)["sources"] if s["items_file"]})
            elif case["kind"] == "brief":
                value, problems = validate.read_json(data, "brief", name, validate.BRIEF_BYTES)
                if value is not None and br.visible_chars(value) > br.VISIBLE_CHARS:
                    value, problems = None, [validate.Problem("brief_too_long", name, "over the limit")]
            else:
                value, problems = validate.read_json(data, "digest", name, validate.DIGEST_BYTES)
                if value is not None and dg.brief_chars(value["brief"]) > dg.BRIEF_CHARS:
                    value, problems = None, [validate.Problem("brief_too_long", name, "over the limit")]
            if case["expect"] == "ok":
                self.assertEqual(problems, [], name)
                self.assertIsNotNone(value)
            else:
                self.assertIsNone(value, name)
                self.assertIn(case["expect"], {p.code for p in problems}, "%s gave %s" % (name, problems[:2]))
        self.assertEqual({c["expect"] for c in manifest.values()},
                         {"ok", "text_rule", "schema", "inconsistent", "path_invalid", "address", "unsupported_version", "not_json", "brief_too_long", "missing", "identity_mismatch"})

    def test_the_hostile_samples_are_the_ones_the_generator_writes(self):
        paused = json.loads(self.states["05-paused-by-the-curator"]["store.json"])
        item = support.items(self.out, "tide-tables")[0]
        with open(os.path.join(self.out, *item["brief"]["path"].split("/")), encoding="utf-8") as f:
            brief = json.load(f)
        with open(os.path.join(self.out, "briefs-index.json"), encoding="utf-8") as f:
            index = json.load(f)
        for name, kind, text, code in make_golden.hostile(paused, support.digest_of(self.out, "tide-tables", item["id"]), support.store(self.out), brief, index):
            with open(os.path.join(support.GOLDEN, "hostile", "%s.%s.json" % (name, kind)), encoding="utf-8", newline="") as f:
                self.assertEqual(f.read(), text, "%s: %s" % (name, REMAKE))

    def test_what_offline_use_needs_is_in_the_golden_output(self):
        store = support.store(DIST)
        for listing in store["sources"]:
            self.assertGreaterEqual(listing["suggested_keep"], 1)
            if listing["item_count"] == 0:   # a source with nothing discussable lists no items and no files
                self.assertEqual((listing["avg_bytes"], listing["items_file"], listing["available"]), (0, None, {"digest": 0, "transcript": 0, "link_back": True}))
                continue
            self.assertGreater(listing["avg_bytes"], 0)
            total = 0
            for item in support.items(DIST, listing["id"]):
                files = [item["digest"]] + ([item["transcript"]["file"]] if item["transcript"]["file"] else [])
                for file in files:
                    with open(os.path.join(DIST, *file["path"].split("/")), "rb") as f:
                        data = f.read()
                    self.assertEqual(validate.check_file(data, file, file["path"]), [])
                self.assertEqual(item["bytes"], sum(f["bytes"] for f in files))
                total += item["bytes"]
                d = support.digest_of(DIST, listing["id"], item["id"])
                self.assertTrue(d["about"] and d["title"] and d["link"] and d["brief"]["about"], "the digest stands on its own: no second download to talk about the item")
            self.assertEqual(listing["avg_bytes"], total // listing["item_count"])
        full = next(s for s in store["sources"] if s["publish"] == "full")
        self.assertGreater(full["available"]["transcript"], 0)

    def test_a_reader_refuses_tampered_or_misplaced_files(self):
        def codes(change):
            folder = os.path.join(self.base, "tampered")
            shutil.rmtree(folder, ignore_errors=True)
            shutil.copytree(DIST, folder)
            change(folder)
            return sorted({p.code for p in validate.check_folder(folder).problems})
        item = support.items(DIST, "tide-tables")[0]
        digest, transcript = item["digest"]["path"], item["transcript"]["file"]["path"]

        def edit(path, old, new):
            def change(folder):
                full = os.path.join(folder, *path.split("/"))
                with open(full, "rb") as f:
                    data = f.read()
                self.assertIn(old, data)
                with open(full, "wb") as f:
                    f.write(data.replace(old, new, 1))
            return change
        self.assertEqual(codes(edit(digest, b"keeper", b"KEEPER")), ["hash_mismatch"])
        self.assertEqual(codes(edit(digest, b"keeper", b"keepers")), ["size_mismatch"])
        self.assertEqual(codes(edit(transcript, b"Mara", b"Sara")), ["hash_mismatch"])
        self.assertEqual(codes(lambda f: os.remove(os.path.join(f, *digest.split("/")))), ["missing"])
        self.assertEqual(codes(lambda f: os.remove(os.path.join(f, "sources", "harbor-voices", "items.json"))), ["missing", "unlisted_file"])
        self.assertEqual(codes(lambda f: open(os.path.join(f, "sources", "tide-tables", "extra.json"), "w").close()), ["unlisted_file"])
        self.assertEqual(codes(lambda f: os.makedirs(os.path.join(f, "sources", "stranger"))), ["unlisted_file"])
        self.assertEqual(codes(lambda f: os.remove(os.path.join(f, "store.json"))), ["missing"])
        self.assertEqual(codes(edit("store.json", b'"item_count": 4', b'"item_count": 3')), ["inconsistent"])
        self.assertEqual(codes(edit("sources/tide-tables/items.json", b'"stale": false', b'"stale": true ')), ["hash_mismatch", "missing", "unlisted_file"],
                         "an items file that is refused takes its briefs with it, so the briefs index names briefs that are not listed")
        self.assertEqual(codes(lambda f: open(os.path.join(f, "store.json"), "ab").write(b" " * 600_000)), ["too_large"])

    def test_a_digest_is_checked_against_the_index_and_the_transcript(self):
        listing = support.listing(DIST, "tide-tables")
        item = support.items(DIST, "tide-tables")[0]
        files = support.tree(DIST)
        raw = files[item["digest"]["path"]]
        transcript, problems = validate.check_transcript(files[item["transcript"]["file"]["path"]], item)
        self.assertEqual(problems, [])

        def check(change):
            d = json.loads(raw)
            change(d)
            data = json.dumps(d).encode()
            entry = dict(item, digest=dict(item["digest"], sha256=__import__("hashlib").sha256(data).hexdigest(), bytes=len(data)))
            return sorted({p.code for p in validate.check_digest(data, listing, entry, transcript, item["transcript"]["file"]["sha256"])[1]})
        self.assertEqual(check(lambda d: None), [])
        self.assertEqual(check(lambda d: d.update(title="Another title")), ["identity_mismatch"])
        self.assertEqual(check(lambda d: d.update(link="https://elsewhere.example.org/")), ["identity_mismatch"])
        self.assertEqual(check(lambda d: d.update(source_id="quay-notes")), ["identity_mismatch"])
        self.assertEqual(check(lambda d: d["provenance"].update(transcript_sha256="0" * 64)), ["identity_mismatch"])
        self.assertEqual(check(lambda d: d["quotes"][0].update(text="Words nobody said in this episode at all.")), ["inconsistent"])
        self.assertEqual(check(lambda d: d["talking_points"][0]["at"].update(segment=9999)), ["inconsistent"])
        self.assertEqual(check(lambda d: d["provenance"].update(method="model")), ["identity_mismatch", "inconsistent"])
        self.assertEqual(check(lambda d: d["brief"].update(points=["p" * 170] * 3, about="a" * 240, hook="h" * 140, quote={"text": "q" * 170, "speaker": None, "time_seconds": 1})), ["brief_too_long"])
        self.assertEqual(check(lambda d: d.update(format_version="3.0")), ["unsupported_version"])
        self.assertEqual(check(lambda d: d.update(format_version="1.9", later_addition={"x": 1})), [], "a newer minor version may add members; they are ignored")
        self.assertEqual(check(lambda d: d.update(later_addition=1)), ["schema"])

    def test_nothing_private_and_nothing_real_is_in_the_samples(self):
        for folder in (support.GOLDEN, os.path.join(support.HERE, "fixtures")):
            for path, data in support.tree(folder).items():
                self.assertFalse(re.search(rb"/Users/|/home/|\.local\b(?!/admin)|@gmail|sk-or-|Bearer ", data), path)
                hosts = set(re.findall(rb"https?://([A-Za-z0-9.-]+)", data))
                self.assertTrue(all(h.endswith((b"example.org", b"example.net")) or h in (b"jsonfeed.org", b"podcastindex.org", b"localhost", b"router.local", b"192.168.1.10", b"192.168.0.10",
                                                                                           b"www.itunes.com", b"www.w3.org", b"podlove.org") for h in hosts), (path, hosts))


class Workflows(unittest.TestCase):
    def read(self, name):
        with open(os.path.join(support.ROOT, ".github", "workflows", name), encoding="utf-8") as f:
            return f.read()

    def jobs(self, text):
        body = text.split("\njobs:\n", 1)[1]
        parts = re.split(r"(?m)^  ([a-z-]+):\n", body)
        return dict(zip(parts[1::2], parts[2::2]))

    def test_every_action_is_pinned_to_a_full_commit(self):
        for name in ("process.yml", "test.yml"):
            uses = re.findall(r"uses:\s*(\S+)(.*)", self.read(name))
            self.assertTrue(uses)
            for action, rest in uses:
                self.assertRegex(action, r"^actions/[a-z-]+@[0-9a-f]{40}$", name)
                self.assertRegex(rest, r"#\s*v\d+\.\d+\.\d+", "a comment gives the version")

    def test_only_the_digest_job_gets_the_key_and_nothing_else_has_secrets(self):
        text = self.read("process.yml")
        jobs = self.jobs(text)
        self.assertEqual(list(jobs), ["fetch-and-normalize", "digest", "publish", "keep-alive"])
        self.assertNotIn("secrets.", jobs["keep-alive"])
        self.assertNotIn("${{ secrets", text.split("\njobs:\n")[0])
        self.assertNotIn("secrets.", jobs["fetch-and-normalize"])
        self.assertNotIn("secrets.", jobs["publish"])
        self.assertEqual(re.findall(r"secrets\.([A-Z_]+)", jobs["digest"]), ["OPENROUTER_API_KEY"])
        self.assertNotIn("secrets.", self.read("test.yml"))
        self.assertNotIn("pull_request_target", text + self.read("test.yml"))

    def test_the_keep_alive_job_can_do_one_thing_only(self):
        """It may enable this workflow again, which resets GitHub's 60-day clock for schedules. Nothing else."""
        job = self.jobs(self.read("process.yml"))["keep-alive"]
        self.assertEqual(re.findall(r"(?m)^      ([a-z-]+): (\w+)$", job.split("steps:")[0]), [("actions", "write")])
        self.assertNotIn("uses:", job, "no action to pin, no checkout: the job never sees the code or the output")
        self.assertNotIn("git ", job.split("steps:")[1], "no commit and no push, so it cannot start a run of itself")
        self.assertIn("github.event_name == 'schedule'", job)
        self.assertIn("always()", job, "also after a failed run, so failures cannot let the schedule lapse")
        self.assertEqual(re.findall(r"api\.github\.com/\S+", job), ['api.github.com/repos/$REPOSITORY/actions/workflows/process.yml/enable"'])
        self.assertIn("timeout-minutes: 2", job)

    def test_rights_schedule_and_order(self):
        text = self.read("process.yml")
        jobs = self.jobs(text)
        self.assertIn("\npermissions: {}\n", text)
        self.assertIn('cron: "17 */6 * * *"', text)
        self.assertIn("workflow_dispatch:", text)
        self.assertRegex(text, r"concurrency:\n  group: process-and-publish\n  cancel-in-progress: false")
        for name in ("fetch-and-normalize", "digest"):
            self.assertEqual(re.findall(r"(?m)^      ([a-z-]+): (\w+)$", jobs[name].split("steps:")[0]), [("contents", "read")], name)
        self.assertEqual(re.findall(r"(?m)^      ([a-z-]+): (\w+)$", jobs["publish"].split("steps:")[0].split("environment:")[0]),
                         [("contents", "read"), ("pages", "write"), ("id-token", "write")])
        self.assertIn("name: github-pages", jobs["publish"])
        self.assertIn("needs: fetch-and-normalize", jobs["digest"])
        self.assertIn("needs: digest", jobs["publish"])
        publish = jobs["publish"]
        self.assertLess(publish.index("pea_knowledge build"), publish.index("pea_knowledge validate dist"))
        self.assertLess(publish.index("pea_knowledge validate dist"), publish.index("upload-pages-artifact"))
        self.assertLess(publish.index("upload-pages-artifact"), publish.index("deploy-pages"))
        self.assertIn("GITHUB_STEP_SUMMARY", publish)
        self.assertEqual(text.count("persist-credentials: false"), 3)
        self.assertEqual(text.count("retention-days: 1"), 2)
        self.assertNotIn("continue-on-error", text)
        test = self.read("test.yml")
        self.assertIn("pull_request:", test)
        self.assertIn("python3 -I -m unittest", test)


class TranscriptCopy(unittest.TestCase):
    def test_the_package_uses_the_same_reader_and_converter_as_the_specification(self):
        for name in ("pea_transcript.py", "convert.py"):
            with open(os.path.join(support.ROOT, "spec", "transcript-v1", name), encoding="utf-8") as f:
                spec = f.read()
            with open(os.path.join(support.ROOT, "src", "pea_knowledge", "transcript", name), encoding="utf-8") as f:
                package = f.read()
            spec = spec.replace("sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))\nimport pea_transcript as pt  # noqa: E402\n"
                                "from pea_transcript import Segment, Transcript, seconds, trim, trim_lines, is_ad  # noqa: E402\n",
                                "from . import pea_transcript as pt\nfrom .pea_transcript import Segment, Transcript, seconds, trim, trim_lines, is_ad\n")
            self.assertEqual(spec, package, name)

    def test_the_specification_copy_has_no_internal_notes(self):
        with open(os.path.join(support.ROOT, "spec", "transcript-v1", "SPEC.md"), encoding="utf-8") as f:
            text = f.read()
        self.assertNotIn("REMOVE BEFORE PUBLISHING", text)
        self.assertNotIn("Appendix D", text)


if __name__ == "__main__":
    unittest.main()
