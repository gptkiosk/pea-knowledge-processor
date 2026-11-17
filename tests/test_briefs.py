# Copyright 2026 The PEA knowledge processor authors
# SPDX-License-Identifier: Apache-2.0
"""Format 1.3 briefs: the writer, its checks, the caps and the pipeline, against a local stand-in model server only.
No real service and no real key are involved."""
import contextlib
import datetime
import http.server
import io
import json
import os
import re
import shutil
import tempfile
import threading
import unittest
from unittest import mock

from . import support, test_digest as model_tests
from pea_knowledge import brief as br, cli, jsonschema_lite as js, pipeline, textrules, validate

FAKE_KEY = model_tests.FAKE_KEY
SOURCE, ITEM = model_tests.SOURCE, model_tests.ITEM
LINE = re.compile(r"^\[([0-9:]{8,9}|L[0-9]+)\] (?:([A-Za-z][A-Za-z .'-]{0,40}): )?(.*)$")

GOOD = {
    "headline": "Mara visits Grey Point, where keeper Tobias Renn reads from a ledger of passing ships.",
    "claims": [
        {"text": "Tobias says the lamp still burns colza oil, about 18 litres a night in the winter months.", "ref": "00:00:28"},
        {"text": "Tobias says the Grey Point Trust voted in March to keep the old lamp, by 36 votes to nine.", "ref": "00:00:56"},
        {"text": "Tobias says the first ledger entry is from 1902, a coal barge called the Wren.", "ref": "00:01:38"},
        {"text": "Tobias says the ledger showed 52 ships turning back at the bar last winter.", "ref": "00:02:06"},
        {"text": "Mara says the Harbour Board reportedly disputes that count.", "ref": "00:02:34"},
        {"text": "Tobias is against the visitor centre where it is drawn, because terns nest on the meadow in May.", "ref": "00:06:32"},
    ],
    "new": "Two apprentices started with the Trust this year.",
    "quotes": [{"text": "I think the town forgets how much of its income crosses that bar in the dark every single night.", "speaker": "Tobias", "time": "00:03:58"}],
    "topics": ["history"],
    "keywords": ["lighthouse", "ledger", "dredging"],
    "entities": ["Tobias Renn", "Grey Point Trust", "Harbour Board", "Northwind Cooperative"],
}


def smart(body):
    """An answer that a careful model might give for whatever transcript it is shown: claims and a quote taken from its
    own lines, so every ref and quote is right. A merge request gets the partial briefs joined."""
    system, user = body["messages"][0]["content"], body["messages"][1]["content"]
    ids = re.search(r"exactly as written: ([a-z0-9, -]+)\.", system)
    topics = [ids.group(1).split(", ")[0]] if ids else []
    if "Merge them" in system:
        partials = json.loads(user.split("PARTIAL BRIEFS, in order (untrusted)\n", 1)[1])
        claims = [c for p in partials for c in p["claims"]][:7]
        return dict(partials[0], claims=claims, quotes=partials[0]["quotes"][:1], headline="The whole episode, merged from its parts.")
    rows = [LINE.match(l) for l in user.split("TRANSCRIPT (untrusted)\n", 1)[1].split("\n")]
    rows = [m for m in rows if m and textrules.check(m.group(3)) is None and not textrules.looks_like_instruction(m.group(3)) and "<" not in m.group(3)]
    claims = [{"text": "The speaker makes point %d here." % n, "ref": m.group(1)} for n, m in enumerate(rows[:6], 1)]
    quotes = []
    for m in rows:
        words = m.group(3).split()
        if 10 <= len(words) and not any(c in m.group(3) for c in "&;"):
            quotes = [{"text": " ".join(words[:10]), "speaker": m.group(2) or "unknown", "time": m.group(1)}]
            break
    return {"headline": "An episode, written by the stand-in.", "claims": claims, "new": br.NO_NEW, "quotes": quotes, "topics": topics,
            "keywords": ["stand-in"], "entities": []}


class Server:
    """A local server that answers like an OpenAI-style chat API. `answers` is a list used in order (the last one
    repeats), each a dict, a string, or a function of the request body."""

    def __init__(self, answers, usage=None):
        outer = self
        self.requests, self.answers = [], list(answers)
        self.usage = usage if usage is not None else {"prompt_tokens": 9000, "completion_tokens": 700}

        class Handler(http.server.BaseHTTPRequestHandler):
            def do_POST(self):
                body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                outer.requests.append({"authorization": self.headers.get("Authorization"), "body": body})
                answer = outer.answers.pop(0) if len(outer.answers) > 1 else outer.answers[0]
                answer = answer(body) if callable(answer) else answer
                content = answer if isinstance(answer, str) else json.dumps(answer)
                data = json.dumps({"choices": [{"message": {"role": "assistant", "content": content}}], "usage": outer.usage}).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def log_message(self, *args):
                pass
        self.server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.url = "http://127.0.0.1:%d/api/v1" % self.server.server_address[1]

    def close(self):
        self.server.shutdown()
        self.server.server_close()


VOCABULARY = ["technology", "history", "science"]


class Writer(unittest.TestCase):
    def write(self, answers, config=None, transcript=None, vocabulary=VOCABULARY, ledger=None):
        server = Server(answers)
        self.addCleanup(server.close)
        self.server = server
        raw = {"briefs": dict({"base_url": server.url, "model": "test/brief-model"}, **(config or {}).get("briefs", {})),
               "brief_budget": (config or {}).get("brief_budget", {})}
        s = br.Settings(raw, {br.KEY_VARIABLE: FAKE_KEY})
        self.spend, self.report, self.log = br.Spend(s, ledger or {"month": "2026-11", "spent_cents": 0.0, "calls": 0}), br.Report(), []
        return br.write_model(s, self.spend, self.report, SOURCE, ITEM, transcript or model_tests.transcript(), vocabulary, self.log.append)

    def test_a_good_answer_is_kept_and_makes_a_valid_file(self):
        fields, covers, note = self.write([GOOD])
        self.assertEqual((covers, note, len(fields["claims"]), fields["topics"]), ("whole", None, 6, ["history"]))
        self.assertEqual((self.spend.calls, self.report.retried, self.spend.prompt_tokens), (1, 0, 9000))
        self.assertAlmostEqual(self.spend.cents, (9000 * 0.10 + 700 * 0.50) / 10_000)
        doc = br.document(SOURCE, ITEM, fields, "model", "test/brief-model", covers, note, "a" * 64)
        value, problems = validate.read_json(js.dumps(doc).encode(), "brief", "b", validate.BRIEF_BYTES)
        self.assertEqual(problems, [])
        self.assertLessEqual(br.visible_chars(value), br.VISIBLE_CHARS)
        body = self.server.requests[0]["body"]
        self.assertEqual(self.server.requests[0]["authorization"], "Bearer " + FAKE_KEY)
        self.assertNotIn("temperature", body, "not sent unless the config names one")
        self.assertEqual((body["model"], body["response_format"]), ("test/brief-model", {"type": "json_object"}))
        self.assertIn("[00:03:58] Tobias: I think the town forgets", body["messages"][1]["content"])
        self.assertNotIn(FAKE_KEY, json.dumps(body))

    def test_malformed_json_is_asked_for_once_more(self):
        fields, _, _ = self.write(["{not json", GOOD])
        self.assertEqual((self.spend.calls, self.report.retried), (2, 1))
        last = self.server.requests[1]["body"]["messages"]
        self.assertEqual([m["role"] for m in last], ["system", "user", "assistant", "user"])
        self.assertIn("not JSON", last[3]["content"])
        self.assertEqual(len(fields["claims"]), 6)

    def test_a_garbled_retry_falls_back(self):
        self.assertIsNone(self.write(["{not json", "```json\n[1, 2]\n```"]))
        self.assertEqual((self.spend.calls, self.report.retried), (2, 1))

    def test_over_the_cap_is_refused_and_fixed_on_the_retry(self):
        long = dict(GOOD, claims=[dict(c, text=c["text"] + " " + "And so on, at length." * 6) for c in GOOD["claims"]], new="x " * 140 + "end.")
        long["claims"] = [dict(c, text=c["text"][:220]) for c in long["claims"]]
        long["entities"] = GOOD["entities"] + ["Mara", "Tobias", "Wren", "North Quay", "Halden and Sons", "Saturday market"]
        self.assertGreater(br.visible_chars(long), br.VISIBLE_CHARS)
        fields, _, _ = self.write([long, GOOD])
        self.assertIn("cap is 1800", self.server.requests[1]["body"]["messages"][3]["content"])
        self.assertEqual(fields["headline"], GOOD["headline"])
        self.assertIsNone(self.write([long]), "over the cap twice: the extractive brief is used")

    def test_an_invented_quote_is_refused(self):
        invented = dict(GOOD, quotes=[{"text": "The Harbour Board is lying about everything and always has been, said the keeper.", "speaker": "Tobias", "time": "00:02:06"}])
        self.assertIsNone(self.write([invented]))
        self.assertIn("not word for word", self.server.requests[1]["body"]["messages"][3]["content"])

    def test_a_quote_credited_to_another_speaker_is_refused(self):
        wrong_line = dict(GOOD, quotes=[dict(GOOD["quotes"][0], speaker="Mara")])
        self.assertIsNone(self.write([wrong_line]))
        self.assertIn("spoken by Tobias", self.server.requests[1]["body"]["messages"][3]["content"])
        # rule 8: the quote is Tobias's line, and a claim that uses the same line names Mara for it
        claims = GOOD["claims"][:5] + [{"text": "Mara says the town forgets how much income crosses the bar at night.", "ref": "00:03:58"}]
        self.assertIsNone(self.write([dict(GOOD, claims=claims)]))
        self.assertIn("claim 6 names Mara", self.server.requests[1]["body"]["messages"][3]["content"])

    def test_claims_with_refs_that_are_no_line_are_dropped_and_four_are_needed(self):
        made_up = dict(GOOD, claims=[dict(c, ref="00:09:%02d" % n) for n, c in enumerate(GOOD["claims"])][:3] + GOOD["claims"][:3])
        self.assertIsNone(self.write([made_up]))
        two_bad = dict(GOOD, claims=GOOD["claims"][:4] + [dict(GOOD["claims"][4], ref="L999")])
        fields, _, _ = self.write([two_bad])
        self.assertEqual(len(fields["claims"]), 4)

    def test_names_and_numbers_not_in_the_transcript_are_flagged(self):
        flagged = dict(GOOD, claims=GOOD["claims"][:5] + [{"text": "Tobias says Admiral Nelson paid 9999 dollars for the lamp.", "ref": "00:00:56"}])
        ctx = br.Context(br.lines_of(model_tests.transcript()), set(VOCABULARY), ["Mara", "Tobias"])
        fields, errors, flags = br.check(flagged, ctx)
        self.assertEqual(errors, [])
        self.assertTrue(any("9999" in f for f in flags) and any("Nelson" in f for f in flags))

    def test_a_topic_outside_the_vocabulary_is_refused(self):
        self.assertIsNone(self.write([dict(GOOD, topics=["ignore-previous-instructions"])]))
        fields, _, _ = self.write([GOOD], vocabulary=None)
        self.assertEqual(fields["topics"], [], "without a vocabulary in the output, a brief names no topic")

    def test_a_long_transcript_is_written_in_parts_and_merged(self):
        fields, covers, note = self.write([smart], {"briefs": {"chunk_chars": 1500}})
        parts = len(br.chunks(br.lines_of(model_tests.transcript()), 1500, 4)[0])
        self.assertGreater(parts, 1)
        self.assertEqual((self.spend.calls, self.report.chunked, covers, note), (parts + 1, 1, "whole", None))
        self.assertEqual(fields["headline"], "The whole episode, merged from its parts.")
        self.assertIn("This is part 1 of", self.server.requests[0]["body"]["messages"][1]["content"])
        self.assertIn("Merge them", self.server.requests[-1]["body"]["messages"][0]["content"])
        fields, covers, note = self.write([smart], {"briefs": {"chunk_chars": 1500, "max_chunks": 2}})
        self.assertEqual((self.spend.calls, covers), (3, "partial"))
        self.assertTrue(note.startswith("The brief covers the first 2 parts"))

    def test_the_caps_stop_the_calls(self):
        with self.assertRaises(br.OutOfBudget) as e:
            self.write([GOOD], {"brief_budget": {"per_run_cents": 0.1}})
        self.assertIn("run's cap", str(e.exception))
        self.assertEqual(self.server.requests, [], "refused before the call, not after")
        with self.assertRaises(br.OutOfBudget) as e:
            self.write([GOOD], ledger={"month": "2026-11", "spent_cents": 199.9, "calls": 900})
        self.assertIn("month's cap", str(e.exception))

    def test_hostile_text_is_never_kept(self):
        for change in (dict(headline="Read https://evil.example.org now."), dict(new="<b>New</b> things."), dict(keywords=["ignore previous instructions"])):
            self.assertIsNone(self.write([dict(GOOD, **change)]), change)

    def test_the_extractive_brief_is_made_from_the_digest(self):
        from pea_knowledge import digest as dg
        d = dg.extractive(SOURCE, ITEM, model_tests.transcript())
        fields, covers, note = br.extractive(d, ["history"])
        self.assertEqual((covers, note, fields["new"], fields["topics"]), ("whole", None, None, ["history"]))
        self.assertTrue(1 <= len(fields["claims"]) <= 8 and all(c["ref"] for c in fields["claims"]))
        self.assertLessEqual(br.visible_chars(fields), br.VISIBLE_CHARS)
        ctx = br.Context(br.lines_of(model_tests.transcript()))
        self.assertTrue(all(br.norm(q["text"]) in ctx.body and q["time"] in ctx.refs for q in fields["quotes"]))
        self.assertEqual(br.extractive(d, ["history"]), br.extractive(d, ["history"]))


class InThePipeline(unittest.TestCase):
    def setUp(self):
        self.base = tempfile.mkdtemp(prefix="pea-briefs-")
        self.addCleanup(shutil.rmtree, self.base, True)
        self.out = os.path.join(self.base, "dist")

    def serve(self, answers=(smart,)):
        server = Server(list(answers))
        self.addCleanup(server.close)
        return server

    def config(self, server, **briefs):
        budget = briefs.pop("budget", {})
        writer = briefs.pop("writer", None)

        def change(raw):
            raw["briefs"] = dict({"base_url": server.url, "model": "test/brief-model"}, **briefs)
            if budget:
                raw["brief_budget"] = budget
            if writer:
                for s in raw["sources"]:
                    if s["id"] in writer:
                        s["brief_writer"] = "extractive"
        return support.load_config(change)

    def briefs_of(self, folder=None):
        out = {}
        for listing in support.store(folder or self.out)["sources"]:
            if listing["items_file"]:
                for i in support.items(folder or self.out, listing["id"]):
                    with open(os.path.join(folder or self.out, *i["brief"]["path"].split("/")), encoding="utf-8") as f:
                        out[(listing["id"], i["id"])] = (i, json.load(f))
        return out

    def test_end_to_end_on_the_fixtures_with_the_stand_in_model(self):
        server = self.serve()
        health = support.run(self.out, config=self.config(server), environment={br.KEY_VARIABLE: FAKE_KEY})
        report = validate.check_folder(self.out)
        self.assertEqual(report.problems, [])
        b = health["briefs"]
        self.assertTrue(b["used"] and b["key"])
        self.assertEqual(b["calls"], len(server.requests))
        self.assertEqual((b["written"], b["listed"]["model"], b["fell_back"]), (9, 9, 0), "every item with a transcript gets a model brief")
        self.assertEqual(b["listed"]["model"] + b["listed"]["extractive"], health["totals"]["items"], "every listed item has a brief")
        self.assertAlmostEqual(b["run_cents"], 9 * 0.125)
        for (sid, iid), (entry, brief) in self.briefs_of().items():
            self.assertEqual((brief["brief_kind"], entry["brief"]["kind"]), (entry["brief"]["kind"], brief["brief_kind"]))
            if brief["brief_kind"] == "model":
                self.assertEqual((brief["model"], len(brief["claims"]) >= 4), ("test/brief-model", True))
            else:
                self.assertEqual(entry["digest"]["basis"] != "transcript", True, "extractive only where there was no transcript")
        for path, data in support.tree(self.out).items():
            self.assertNotIn(FAKE_KEY.encode(), data, path)
        with open(os.path.join(self.out, "state.json"), encoding="utf-8") as f:
            ledger = json.load(f)["briefs"]
        self.assertEqual(ledger, {"month": "2026-11", "spent_cents": b["run_cents"], "calls": 9, "key": True})
        self.assertIn("Briefs: 9 model", pipeline.health_summary(health))

        # The next run: nothing new, nothing paid; the month's spend is carried.
        again = support.run(self.out, now=support.T0.replace(hour=18), config=self.config(server), environment={br.KEY_VARIABLE: FAKE_KEY})
        self.assertEqual((again["briefs"]["calls"], again["briefs"]["listed"]["model"], again["briefs"]["month_cents"]), (0, 9, b["run_cents"]))

    def test_an_unchanged_transcript_costs_nothing_when_an_item_is_made_again(self):
        server = self.serve()
        support.run(self.out, config=self.config(server), environment={br.KEY_VARIABLE: FAKE_KEY})
        calls = len(server.requests)

        def anew(raw):   # model topics on: every item key changes, so every item is fetched and digested again; the transcripts are the same
            raw["briefs"] = {"base_url": server.url, "model": "test/brief-model"}
            raw["model"]["topics"] = True
        health = support.run(self.out, now=support.T0.replace(hour=18), config=support.load_config(anew), environment={br.KEY_VARIABLE: FAKE_KEY})
        self.assertEqual((len(server.requests), health["briefs"]["cached"], health["briefs"]["listed"]["model"]), (calls, 9, 9))
        self.assertEqual(validate.check_folder(self.out).problems, [])

    def test_without_a_key_every_brief_is_extractive_and_nothing_is_called(self):
        server = self.serve()
        health = support.run(self.out, config=self.config(server), environment={})
        self.assertEqual(server.requests, [])
        self.assertEqual((health["briefs"]["used"], health["briefs"]["listed"]["model"], health["briefs"]["listed"]["extractive"]), (False, 0, 20))
        self.assertIn("no key", health["briefs"]["note"])
        self.assertEqual(validate.check_folder(self.out).problems, [])

    def test_a_reached_cap_leaves_the_rest_extractive(self):
        server = self.serve()
        health = support.run(self.out, config=self.config(server, budget={"per_run_cents": 0.5}), environment={br.KEY_VARIABLE: FAKE_KEY})
        b = health["briefs"]
        self.assertGreater(b["written"], 0)
        self.assertGreater(b["skipped_for_budget"], 0)
        self.assertLessEqual(b["run_cents"], 0.5)
        self.assertEqual(b["written"] + b["skipped_for_budget"], 9)
        self.assertIn("cap", b["note"])
        self.assertEqual(b["listed"]["model"] + b["listed"]["extractive"], 20)
        self.assertEqual(validate.check_folder(self.out).problems, [])

    def test_the_monthly_cap_holds_across_runs(self):
        server = self.serve()
        support.run(self.out, config=self.config(server, budget={"monthly_cents": 0.6}), environment={br.KEY_VARIABLE: FAKE_KEY})
        with open(os.path.join(self.out, "state.json"), encoding="utf-8") as f:
            spent = json.load(f)["briefs"]["spent_cents"]
        self.assertLessEqual(spent, 0.6)
        calls = len(server.requests)
        later = support.run(self.out, now=support.T0.replace(hour=18), config=self.config(server, budget={"monthly_cents": 0.6}), environment={br.KEY_VARIABLE: FAKE_KEY})
        self.assertEqual(len(server.requests), calls, "the month's cap is spent: no call and no fetch to upgrade")
        self.assertEqual(later["briefs"]["month_cents"], spent)
        december = support.run(self.out, now=datetime.datetime(2026, 12, 1, 0, 0, 0), config=self.config(server, budget={"monthly_cents": 0.6}), environment={br.KEY_VARIABLE: FAKE_KEY})
        self.assertEqual(december["briefs"]["month"], "2026-12")
        self.assertGreater(len(server.requests), calls, "a new month starts a new ledger, and the extractive briefs are upgraded")

    def test_a_source_whose_terms_say_so_is_never_sent_to_a_model(self):
        server = self.serve()
        health = support.run(self.out, config=self.config(server, writer=("harbor-voices",)), environment={br.KEY_VARIABLE: FAKE_KEY})
        self.assertGreater(health["briefs"]["skipped_by_terms"], 0)
        self.assertFalse(any("Show: Harbor Voices" in r["body"]["messages"][1]["content"] for r in server.requests))
        kinds = {i["brief"]["kind"] for i in support.items(self.out, "harbor-voices")}
        self.assertEqual(kinds, {"extractive"})

    def test_a_brief_that_fails_its_checks_falls_back_and_is_not_asked_for_again(self):
        server = self.serve(["{broken"])
        health = support.run(self.out, config=self.config(server), environment={br.KEY_VARIABLE: FAKE_KEY})
        self.assertEqual((health["briefs"]["fell_back"], health["briefs"]["retried"], health["briefs"]["listed"]["model"]), (9, 9, 0))
        self.assertEqual(len(server.requests), 18)
        self.assertEqual(validate.check_folder(self.out).problems, [])
        support.run(self.out, now=support.T0.replace(hour=18), config=self.config(server), environment={br.KEY_VARIABLE: FAKE_KEY})
        self.assertEqual(len(server.requests), 18, "an item whose model brief failed is not fetched again for one")

    def test_extractive_briefs_are_upgraded_a_few_per_run_once_a_key_is_there(self):
        server = self.serve()
        support.run(self.out, config=self.config(server), environment={})
        health = support.run(self.out, now=support.T0.replace(hour=18), config=self.config(server, upgrade_per_run=4),
                             environment={br.KEY_VARIABLE: FAKE_KEY})
        self.assertEqual((health["briefs"]["written"], health["briefs"]["listed"]["model"]), (4, 4))
        self.assertEqual(validate.check_folder(self.out).problems, [])
        fetch_only = os.path.join(self.base, "work")
        os.makedirs(fetch_only)
        state = pipeline.fetch_stage(self.config(server), fetch_only, __import__("pea_knowledge").fetch.fixture_fetcher(support.WEB, log=support.QUIET),
                                     pipeline.Previous(self.out), support.T0.replace(hour=23), "offline", support.QUIET, {})
        refetched = sum(1 for r in state["sources"].values() for i in r["items"] if not i["reuse"] and i["transcript"]["file"])
        self.assertEqual(refetched, 5, "the fetch job has no key; the last run's ledger says the brief step had one, so it fetches again the five items still without a model brief")
        support.run(self.out, now=support.T0.replace(hour=23, minute=30), config=self.config(server), environment={})   # a run whose brief step had no key
        state = pipeline.fetch_stage(self.config(server), fetch_only, __import__("pea_knowledge").fetch.fixture_fetcher(support.WEB, log=support.QUIET),
                                     pipeline.Previous(self.out), support.T0.replace(hour=23, minute=45), "offline", support.QUIET, {})
        self.assertFalse(any(not i["reuse"] and i["transcript"]["file"] for r in state["sources"].values() for i in r["items"]), "after a run without a key, nothing is fetched again")

    def test_the_reader_refuses_a_brief_that_does_not_fit_its_index(self):
        server = self.serve()
        support.run(self.out, config=self.config(server), environment={br.KEY_VARIABLE: FAKE_KEY})
        (sid, iid), (entry, brief) = next((k, v) for k, v in self.briefs_of().items() if v[1]["brief_kind"] == "model")
        listing = support.listing(self.out, sid)

        def codes(change):
            b = json.loads(json.dumps(brief))
            change(b)
            data = js.dumps(b).encode()
            e = dict(entry, brief=dict(entry["brief"], sha256=pipeline.sha256(data), bytes=len(data)))
            return sorted({p.code for p in validate.check_brief(data, listing, e, support.store(self.out).get("topics", []))[1]})
        self.assertEqual(codes(lambda b: None), [])
        self.assertEqual(codes(lambda b: b.update(title="Another title")), ["identity_mismatch"])
        self.assertEqual(codes(lambda b: b.update(claims=b["claims"][:3])), ["inconsistent"])
        self.assertEqual(codes(lambda b: b.update(model=None)), ["inconsistent"])
        self.assertEqual(codes(lambda b: b.update(covers_note="Only part.")), ["inconsistent"])
        self.assertEqual(codes(lambda b: b.update(topics=["made-up-topic"])), ["inconsistent"])
        self.assertEqual(codes(lambda b: b.update(headline="Go to www.evil.example.org")), ["text_rule"])
        data = js.dumps(brief).encode()
        self.assertEqual([p.code for p in validate.check_brief(data + b" ", listing, entry)[1]], ["size_mismatch"])


class DryRun(unittest.TestCase):
    def test_the_dry_run_lists_items_and_cost_and_calls_no_model(self):
        server = Server([smart])
        self.addCleanup(server.close)
        base = tempfile.mkdtemp(prefix="pea-dry-")
        self.addCleanup(shutil.rmtree, base, True)
        env = {br.KEY_VARIABLE: FAKE_KEY, "PEA_MODEL_BASE_URL": server.url}
        with mock.patch.dict(os.environ, env), contextlib.redirect_stdout(io.StringIO()) as said, contextlib.redirect_stderr(io.StringIO()):
            code = cli.main(["briefs", "--dry-run", "--limit", "3", "--config", support.CONFIG, "--offline-fixtures", support.WEB,
                             "--now", "2026-11-14T12:00:00Z", "--work", os.path.join(base, "none")])
        text = said.getvalue()
        self.assertEqual(code, 0)
        self.assertEqual(server.requests, [], "a dry run never calls the model")
        self.assertIn("Dry run: no model was called", text)
        self.assertEqual(len([l for l in text.splitlines() if l.startswith("  ")]), 3)
        self.assertIn("3 items listed (limit 3)", text)
        self.assertIn("a key is set", text)
        self.assertNotIn(FAKE_KEY, text)
        self.assertFalse(os.path.exists(os.path.join(base, "none")))


if __name__ == "__main__":
    unittest.main()
