import copy, json, os, sys, unittest
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import validate_brief as v

TRANSCRIPT = """PEA-TRANSCRIPT v1
show: Test
title: T
date: 2026-11-01
source: https://example.org/t
duration: 10:00
language: en
format: plain text
provenance: publisher transcript
quality: full
speakers: none
segments: 4
---
[00:00:05] Anna Berg: Acme Corp raised 40 million dollars in March and plans to hire two hundred engineers.
[00:01:10] Anna Berg: We think the new   chip will ship in 2027, and nobody expected that.
[--:--:--] Carl Dunn: The regulator in Brussels said it will open an inquiry next month into the pricing.
[00:03:00] Carl Dunn: It is a very long way from where we started with this project.
"""

GOOD = {
    "headline": "Acme Corp funding and chip plans.",
    "claims": [
        {"text": "Acme Corp raised 40 million dollars in March.", "ref": "00:00:05"},
        {"text": "Anna Berg says Acme plans to hire two hundred engineers.", "ref": "00:00:05"},
        {"text": "Anna Berg says the new chip will ship in 2027.", "ref": "00:01:10"},
        {"text": "A regulator in Brussels will open an inquiry next month into pricing.", "ref": "L3"},
        {"text": "Carl Dunn says the project is far from where it started.", "ref": "00:03:00"},
    ],
    "new": "A Brussels inquiry into pricing is announced.",
    "quotes": [{"text": "We think the new chip will ship in 2027, and nobody expected that.", "speaker": "Anna Berg", "time": "00:01:10"}],
    "topics": ["technology", "business"],
    "keywords": ["chip", "funding"],
    "entities": ["Acme Corp", "Anna Berg", "Carl Dunn", "Brussels"],
}
VOC = {"technology", "business", "ai"}


def check(brief):
    return v.validate(brief, TRANSCRIPT, VOC)


class Tests(unittest.TestCase):
    def test_good_brief_passes(self):
        r = check(GOOD)
        self.assertEqual(r["errors"], [])
        self.assertEqual(r["flags"], [])
        self.assertEqual((r["claims_ok"], r["quotes_ok"]), (5, 1))
        self.assertEqual(v.verdict(r), "PASS")

    def test_quote_with_changed_word_fails(self):
        b = copy.deepcopy(GOOD)
        b["quotes"][0]["text"] = "We think the new chip will ship in 2028, and nobody expected that."
        self.assertTrue(any("quote 1" in e for e in check(b)["errors"]))

    def test_quote_whitespace_and_case_tolerated(self):
        b = copy.deepcopy(GOOD)
        b["quotes"][0]["text"] = "we think the NEW chip will ship in 2027,  and nobody expected that."
        self.assertEqual(check(b)["errors"], [])

    def test_bad_refs_fail(self):
        b = copy.deepcopy(GOOD)
        b["claims"][0]["ref"] = "09:09:09"
        b["claims"][1]["ref"] = "L99"
        r = check(b)
        self.assertEqual(r["claims_ok"], 3)
        self.assertTrue(any("ref" in e for e in r["errors"]))
        self.assertTrue(any("fewer than 4" in e for e in r["errors"]))

    def test_invented_number_and_name_are_flagged_not_failed(self):
        b = copy.deepcopy(GOOD)
        b["claims"][0]["text"] = "Acme Corp raised 90 million dollars from Sequoia in March."
        r = check(b)
        self.assertEqual(r["errors"], [])
        self.assertTrue(any("number 90" in f for f in r["flags"]))
        self.assertTrue(any("Sequoia" in f for f in r["flags"]))
        self.assertEqual(v.verdict(r), "PASS (flags)")

    def test_number_word_matches_digit(self):
        b = copy.deepcopy(GOOD)
        b["claims"][1]["text"] = "Anna Berg says Acme plans to hire 200 engineers."   # "two hundred" in the text
        self.assertEqual([f for f in check(b)["flags"] if "number" in f], [])

    def test_size_and_schema_caps(self):
        b = copy.deepcopy(GOOD)
        b["claims"] = b["claims"][:3]
        b["topics"] = ["technology", "sports"]
        b["entities"] = ["X"] * 13
        errors = " ".join(check(b)["errors"])
        self.assertIn("claims has 3", errors)
        self.assertIn("not in the vocabulary", errors)
        self.assertIn("entities has 13", errors)
        b = copy.deepcopy(GOOD)
        b["new"] = "x" * 290
        b["headline"] = "h" * 150
        b["claims"][0]["text"] = "Acme " + "y" * 210
        b["entities"] = ["e" * 100] * 10
        errors = " ".join(check(b)["errors"])
        self.assertIn("visible text is", errors)

    def test_missing_and_extra_keys(self):
        b = copy.deepcopy(GOOD)
        del b["new"]
        b["extra"] = 1
        errors = " ".join(check(b)["errors"])
        self.assertIn("missing keys: new", errors)
        self.assertIn("unexpected keys: extra", errors)

    def test_real_vocabulary_has_thirty_terms(self):
        self.assertEqual(len(v.load_vocabulary()), 30)

    def test_cli_report_text(self):
        text = v.report("x", check(GOOD))
        self.assertIn("x: PASS", text)


if __name__ == "__main__":
    unittest.main()
