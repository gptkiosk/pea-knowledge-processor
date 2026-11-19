# Copyright 2026 The PEA knowledge processor authors
# SPDX-License-Identifier: Apache-2.0
"""The brief contract (contract/README.md): what every published brief guarantees, so a reading app can stay thin.

The processor is the thorough side. Every brief it writes passes these rules before it is kept (the writer's check and
the extractive builder use the same text rule), the reader's check in validate.py applies them to every brief of an
output folder, and the publish job refuses to publish when any brief fails. The app runs the same rules over the same
golden corpus (contract/golden) and assumes nothing beyond them.

The numbers here are tied to the app's request budget: at most three briefs go into one prompt block of
APP_BLOCK_BUDGET characters, and a brief's "talk size" (what the block shows of it, with its first two claims, the
fewest the app ever shows) is capped at TALK_CHARS, so three briefs of the largest allowed talk size, with the app's
labels and the longest line that can travel with them, fit the block without cutting text (the margin is worked out
in contract/README.md and checked by the app's contract check).
"""
import hashlib
import json
import os
import re

from . import textrules

CONTRACT_VERSION = 1
APP_BLOCK_BUDGET = 4_200     # BriefBlock.budget in the app (Sources/PEACore/BriefTalk.swift)
APP_BRIEFS_PER_TURN = 3      # BriefSearch.maximum in the app
APP_TITLE_SHOWN = 120        # the app's label shows at most this much of the title
APP_CLAIMS_SHOWN_MIN = 2     # the app's block trims claims down to two, never fewer
TALK_CHARS = 1_050           # the talk size cap; see the module text and contract/README.md

# Markdown and list markup a voice app would read out or a chat would render: bold or underline marks, code marks, a
# link written as [text](...), or a heading, quote or bullet mark at the start.
_MARKUP = re.compile(r"\*\*|__|`|\[[^\]]{0,200}\]\(|^(?:#{1,6}\s|>\s|[-*+]\s)")
# The labels of the app's own prompt block: a brief must never look like one of them.
_LABEL = re.compile(r"\[B\d{1,2}\]|\b(?:BRIEFS?|BRIEF RULES|WEB BRIEFS|LAYERS|AGE|MORE|HAVE)\s*:")

# The fields a brief's writer controls (a model or the extractive builder). Identity fields (title, source name) come
# from the publisher through the items file and are held to the ordinary text rules only, so one odd title can never
# stop a whole publish.
AUTHORED = ("headline", "new", "covers_note")


def text_reason(text):
    """None when `text` may stand in an authored brief field, else "markup", "label" or "instruction"."""
    if _MARKUP.search(text):
        return "markup"
    if _LABEL.search(text):
        return "label"
    if textrules.looks_like_instruction(text):
        return "instruction"
    return None


def authored_texts(b):
    """(where, text) of every authored text of a parsed brief."""
    out = [(k, b.get(k)) for k in AUTHORED]
    out += [("claims[%d].text" % n, c.get("text")) for n, c in enumerate(b.get("claims") or []) if isinstance(c, dict)]
    for n, q in enumerate(b.get("quotes") or []):
        if isinstance(q, dict):
            out += [("quotes[%d].text" % n, q.get("text")), ("quotes[%d].speaker" % n, q.get("speaker"))]
    out += [("%s[%d]" % (k, n), x) for k in ("keywords", "entities") for n, x in enumerate(b.get(k) or [])]
    return [(w, t) for w, t in out if isinstance(t, str)]


def talk_chars(b):
    """What the app's block shows of a brief, counted in code points: source name, title (to APP_TITLE_SHOWN), the
    coverage note, headline, the first two claims, what is new, and the quotes with their speakers."""
    def s(v):
        return v if isinstance(v, str) else ""
    claims = [c for c in b.get("claims") or [] if isinstance(c, dict)][:APP_CLAIMS_SHOWN_MIN]
    quotes = [q for q in b.get("quotes") or [] if isinstance(q, dict)]
    return (len(s(b.get("source_name"))) + min(len(s(b.get("title"))), APP_TITLE_SHOWN) + len(s(b.get("covers_note"))) + len(s(b.get("headline")))
            + sum(len(s(c.get("text"))) for c in claims) + len(s(b.get("new"))) + sum(len(s(q.get("text"))) + len(s(q.get("speaker"))) for q in quotes))


def real_date(text):
    """True for a calendar date YYYY-MM-DD that exists (the schema's pattern lets 2026-02-30 through)."""
    import datetime
    try:
        datetime.date.fromisoformat(text)
        return True
    except (TypeError, ValueError):
        return False


# --- The golden corpus ---------------------------------------------------------------------------------------------------
def corpus_sha256(cases):
    """One hash over the corpus: each case's file name and SHA-256, in file-name order."""
    lines = "".join("%s  %s\n" % (c["sha256"], c["file"]) for c in sorted(cases, key=lambda c: c["file"]))
    return hashlib.sha256(lines.encode("utf-8")).hexdigest()


def check_corpus(folder):
    """Runs the reader's brief check over every file of a golden corpus and compares with its manifest. Returns a list of
    mismatches (empty when the corpus holds): wrong hash, a missing or unlisted file, or a result other than expected."""
    from . import validate
    mismatches = []
    with open(os.path.join(folder, "manifest.json"), "rb") as f:
        manifest = json.loads(f.read().decode("utf-8"))
    if manifest.get("corpus_sha256") != corpus_sha256(manifest["cases"]):
        mismatches.append("manifest.json: corpus_sha256 does not match its cases")
    listed = set()
    for case in manifest["cases"]:
        name = case["file"]
        listed.add(name)
        path = os.path.join(folder, name)
        if not os.path.isfile(path):
            mismatches.append("%s: missing" % name)
            continue
        with open(path, "rb") as f:
            data = f.read()
        if hashlib.sha256(data).hexdigest() != case["sha256"]:
            mismatches.append("%s: the SHA-256 differs from the manifest (the file was edited)" % name)
        _, problems = validate.check_brief_alone(data, name)
        codes = sorted({p.code for p in problems})
        want = [] if case["expect"] == "pass" else [case["reason"]]
        if codes != want:
            mismatches.append("%s: got %s, the manifest expects %s (%s)" % (name, codes or "pass", want or "pass", "; ".join(map(repr, problems[:3]))))
    for name in sorted(os.listdir(folder)):
        if name.endswith(".json") and name != "manifest.json" and name not in listed:
            mismatches.append("%s: in the folder but not in the manifest" % name)
    return mismatches
