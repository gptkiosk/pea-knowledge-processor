# Copyright 2026 The PEA knowledge processor authors
# SPDX-License-Identifier: Apache-2.0
"""The reader's checks: what an output folder (or one downloaded file) must satisfy before anything in it is used.

This is the reference for the checks of the iPhone app (docs/APP-CONTRACT.md). Each function takes the bytes of one
file and what the reader already trusts (the entry that named the file), and returns the parsed value with a list of
`Problem`: a typed code, where, and one sentence. A file with any problem is not used.
"""
import hashlib
import json
import os
import re

from . import FORMAT_MAJOR, FORMAT_MINOR, brief as br, briefs_index as bx, digest as dg, jsonschema_lite, textrules, topics as tp
from .fetch import validate_url
from .transcript import pea_transcript as pt

STORE_BYTES = 512_000
ITEMS_BYTES = 512_000
HEALTH_BYTES = 512_000
TRANSCRIPT_BYTES = 1_000_000
DIGEST_BYTES = dg.DIGEST_BYTES
BRIEF_BYTES = br.BRIEF_BYTES
INDEX_BYTES = bx.INDEX_BYTES

CODES = (
    "missing",               # a file that must be there is not
    "too_large",             # larger than the limit for its kind: refused unread
    "not_json",              # not strict JSON (also: NaN, a key written twice, not UTF-8)
    "unsupported_version",   # a major version this reader does not know
    "schema",                # does not have the shape the schema states
    "text_rule",             # a text holds markup, an address, a control character or bad spacing
    "address",               # `site` or `link` is not a public https address
    "path_invalid",          # a path that is not exactly where that file belongs
    "size_mismatch",         # the bytes differ from the size the index states
    "hash_mismatch",         # the bytes differ from the SHA-256 the index states
    "identity_mismatch",     # a file says it is something other than what the index says
    "inconsistent",          # members that contradict one another
    "brief_too_long",        # the brief form of a digest, or a brief file (1.3), is over its limit
    "transcript_invalid",    # not a conforming PEA transcript v1 file
    "unlisted_file",         # a file in the folder that no index names
)

_SCHEMAS = {}
_URL_KEYS = ("site", "link")


class Problem:
    __slots__ = ("code", "where", "detail")

    def __init__(self, code, where, detail):
        assert code in CODES, code
        self.code, self.where, self.detail = code, where, detail

    def __repr__(self):
        return "%s  %s: %s" % (self.code, self.where, self.detail)


def schema(name):
    if name not in _SCHEMAS:
        here = os.path.dirname(os.path.abspath(__file__))
        for folder in (os.path.join(here, "schema"), os.path.join(here, "..", "..", "schema")):
            path = os.path.join(folder, name + ".schema.json")
            if os.path.exists(path):
                with open(path, encoding="utf-8") as f:
                    _SCHEMAS[name] = json.load(f)
                break
        else:
            raise FileNotFoundError("schema/%s.schema.json is not beside the code" % name)
    return _SCHEMAS[name]


def _texts(value, where, problems):
    """Every string in a parsed file is checked: `site` and `link` as addresses, everything else as text."""
    if isinstance(value, dict):
        for key, item in value.items():
            if key in _URL_KEYS and isinstance(item, str):
                if validate_url(item) != item:
                    problems.append(Problem("address", "%s.%s" % (where, key), "not a normalized public https address"))
            else:
                _texts(item, "%s.%s" % (where, key), problems)
    elif isinstance(value, list):
        for i, item in enumerate(value):
            _texts(item, "%s[%d]" % (where, i), problems)
    elif isinstance(value, str):
        why = textrules.check(value)
        if why is not None:
            problems.append(Problem("text_rule", where, why))


def read_json(data, kind, where, limit):
    """Bytes to a checked value: size, strict JSON, version, schema, text rules. Returns (value or None, problems)."""
    if len(data) > limit:
        return None, [Problem("too_large", where, "%d bytes, the limit is %d" % (len(data), limit))]
    try:
        value = jsonschema_lite.loads(data)
    except jsonschema_lite.NotJSON as e:
        return None, [Problem("not_json", where, str(e))]
    if not isinstance(value, dict):
        return None, [Problem("schema", where, "not a JSON object")]
    version = value.get("format_version")
    m = re.fullmatch(r"(\d{1,4})\.(\d{1,4})", version) if isinstance(version, str) else None
    if m is None:
        return None, [Problem("schema", where, "no readable format_version")]
    if int(m.group(1)) != FORMAT_MAJOR:
        return None, [Problem("unsupported_version", where, "format %s; this reader knows major %d" % (version, FORMAT_MAJOR))]
    newer = int(m.group(2)) > FORMAT_MINOR
    problems = [Problem("schema", where + path[1:], message) for path, message in jsonschema_lite.validate(value, schema(kind), ignore_unknown=newer)[:20]]
    if problems:
        return None, problems
    _texts(value, where, problems)
    return (None if problems else value), problems


def check_file(data, ref, where):
    """The size and SHA-256 an index entry states for a file, against the bytes that arrived."""
    if len(data) != ref["bytes"]:
        return [Problem("size_mismatch", where, "%d bytes, the index says %d" % (len(data), ref["bytes"]))]
    if hashlib.sha256(data).hexdigest() != ref["sha256"]:
        return [Problem("hash_mismatch", where, "the SHA-256 differs from the one the index states")]
    return []


def check_store(data):
    store, problems = read_json(data, "store", "store.json", STORE_BYTES)
    if store is None:
        return None, problems
    seen = set()
    vocabulary = store.get("topics", [])
    known = {t["id"] for t in vocabulary}
    if tp.duplicate_id(vocabulary):
        problems.append(Problem("inconsistent", "store.json.topics", "the topic id %s is listed twice" % tp.duplicate_id(vocabulary)))
    for n, s in enumerate(store["sources"]):
        where = "store.json.sources[%d]" % n
        if any(t not in known for t in s.get("topics", [])):
            problems.append(Problem("inconsistent", where, "the topic %s is not in the vocabulary of this file" % next(t for t in s["topics"] if t not in known)))
        if s["id"] in seen:
            problems.append(Problem("inconsistent", where, "the id %s is listed twice" % s["id"]))
        seen.add(s["id"])
        ref = s["items_file"]
        if ref is not None and ref["path"] != "sources/%s/items.json" % s["id"]:
            problems.append(Problem("path_invalid", where, "the items file is not at sources/%s/items.json" % s["id"]))
        if s["state"] == "withdrawn" and (ref is not None or s["item_count"] != 0 or s["latest_titles"]):
            problems.append(Problem("inconsistent", where, "a withdrawn source lists items"))
        if s["state"] != "active" and (s["message"] is None or s["state_since"] is None or s["state_reason"] is None):
            problems.append(Problem("inconsistent", where, "a %s source needs a message, a reason and a time" % s["state"]))
        if s["state"] == "active" and s["state_since"] is not None:
            problems.append(Problem("inconsistent", where, "an active source has a state_since"))
        if s["purge"] and s["state"] != "withdrawn":
            problems.append(Problem("inconsistent", where, "purge is set on a source that is not withdrawn"))
        if (ref is None) != (s["item_count"] == 0):
            problems.append(Problem("inconsistent", where, "item_count and items_file disagree"))
        if s["state"] == "paused" and s["freshness"]["status"] != "stale":
            problems.append(Problem("inconsistent", where, "a paused source must be marked stale"))
        if s["available"]["digest"] != s["item_count"] or s["available"]["transcript"] > s["item_count"]:
            problems.append(Problem("inconsistent", where, "the availability counts do not fit item_count"))
    return (None if problems else store), problems


def check_items(data, listing, topics=None):
    """A source's items file, against its store listing. `topics` is the vocabulary of the store.json that named the
    file (its `topics`, or an empty list when it has none): an item may only hold its ids. None skips that check,
    for a caller that holds no store listing."""
    known = None if topics is None else {t["id"] for t in topics}
    where = "sources/%s/items.json" % listing["id"]
    problems = check_file(data, listing["items_file"], where)
    if problems:
        return None, problems
    items, problems = read_json(data, "items", where, ITEMS_BYTES)
    if items is None:
        return None, problems
    sid = listing["id"]
    if items["source_id"] != sid:
        problems.append(Problem("identity_mismatch", where, "the file is for %s" % items["source_id"]))
    if len(items["items"]) != listing["item_count"]:
        problems.append(Problem("inconsistent", where, "%d items, the store says %d" % (len(items["items"]), listing["item_count"])))
    seen = set()
    for n, item in enumerate(items["items"]):
        at = "%s.items[%d]" % (where, n)
        if item["id"] in seen:
            problems.append(Problem("inconsistent", at, "the id %s is listed twice" % item["id"]))
        seen.add(item["id"])
        if item["digest"]["path"] != "sources/%s/%s.digest.json" % (sid, item["id"]):
            problems.append(Problem("path_invalid", at, "the digest is not where it belongs"))
        t = item["transcript"]
        size = item["digest"]["bytes"]
        if t["file"] is not None:
            size += t["file"]["bytes"]
            if t["file"]["path"] != "sources/%s/%s.transcript.pea.txt" % (sid, item["id"]):
                problems.append(Problem("path_invalid", at, "the transcript is not where it belongs"))
        b = item.get("brief")
        if b is not None and b["path"] != "sources/%s/%s.brief.json" % (sid, item["id"]):
            problems.append(Problem("path_invalid", at, "the brief is not where it belongs"))
        if item["bytes"] != size:
            problems.append(Problem("inconsistent", at, "bytes is not the size of the item's files"))
        fits = {"yes": t["reason"] is None and t["file"] is not None, "partial": t["reason"] == "cut" and t["file"] is not None,
                "no": t["reason"] is not None and t["reason"] != "cut" and t["file"] is None}[t["available"]]
        if not fits:
            problems.append(Problem("inconsistent", at, "transcript.available, reason and file disagree"))
        if t["file"] is not None and listing["publish"] != "full":
            problems.append(Problem("inconsistent", at, "a transcript file in a source that publishes digests only"))
        if "read" in t and t["read"] != {"yes": "full", "partial": "partial"}.get(t["available"], t["read"]):
            problems.append(Problem("inconsistent", at, "transcript.read and transcript.available disagree"))
        origin = item.get("transcript_source")
        if origin is not None:
            if t.get("read", "none") == "none":
                problems.append(Problem("inconsistent", at, "a transcript_source on an item whose transcript was not read"))
            if ("extract" in origin) != (origin["format"] == "html"):
                problems.append(Problem("inconsistent", at, "transcript_source.extract goes with format html, and only with it"))
        if item["stale"] != (item["stale_reason"] is not None):
            problems.append(Problem("inconsistent", at, "stale and stale_reason disagree"))
        for why in tp.check_item(item.get("topics"), item.get("topics_by"), known):
            problems.append(Problem("inconsistent", at, why))
    dates = [(i["date"], i["id"]) for i in items["items"]]
    if dates != sorted(dates, reverse=True):
        problems.append(Problem("inconsistent", where, "the items are not newest first"))
    return (None if problems else items), problems


def check_transcript(data, item, where=None):
    ref = item["transcript"]["file"]
    where = where or ref["path"]
    if len(data) > TRANSCRIPT_BYTES:
        return None, [Problem("too_large", where, "%d bytes, the limit is %d" % (len(data), TRANSCRIPT_BYTES))]
    problems = check_file(data, ref, where)
    if problems:
        return None, problems
    results = pt.validate(data)
    if not pt.conforms(results):
        broken = [r.rule for r in results if r.level == "error" and r.status == "fail"]
        return None, [Problem("transcript_invalid", where, "breaks rule %s of PEA transcript v1" % ", ".join(broken[:5]))]
    transcript = pt.parse(data.decode("utf-8"))
    if (transcript.partial is not None) != (item["transcript"]["available"] == "partial"):
        return None, [Problem("inconsistent", where, "the file and the index disagree on whether the transcript is cut")]
    return transcript, []


def check_digest(data, listing, item, transcript=None, transcript_sha256=None):
    """An item's digest, against its entry in the items file and, when the output carries one, its transcript."""
    where = item["digest"]["path"]
    problems = check_file(data, item["digest"], where)
    if problems:
        return None, problems
    d, problems = read_json(data, "digest", where, DIGEST_BYTES)
    if d is None:
        return None, problems
    same = (("source_id", listing["id"]), ("source_name", listing["name"]), ("item_id", item["id"]), ("title", item["title"]), ("date", item["date"]),
            ("link", item["link"]), ("duration_seconds", item["duration_seconds"]), ("basis", item["digest"]["basis"]))
    for key, expected in same:
        if d[key] != expected:
            problems.append(Problem("identity_mismatch", "%s.%s" % (where, key), "differs from the index"))
    if "link_kind" in d and "link_kind" in item and d["link_kind"] != item["link_kind"]:
        problems.append(Problem("identity_mismatch", where + ".link_kind", "differs from the index"))
    chapters = d.get("chapters", [])
    if any(b["start_seconds"] <= a["start_seconds"] or (a["end_seconds"] is not None and a["end_seconds"] > b["start_seconds"]) for a, b in zip(chapters, chapters[1:])) \
            or any(c["end_seconds"] is not None and c["end_seconds"] <= c["start_seconds"] for c in chapters):
        problems.append(Problem("inconsistent", where + ".chapters", "the chapters are not in order of time"))
    if d["basis"] != "transcript" and d.get("snippable_moments"):
        problems.append(Problem("inconsistent", where + ".snippable_moments", "moments without a transcript"))
    if d["quality"]["grade"] != item["digest"]["grade"] or d["provenance"]["method"] != item["digest"]["method"]:
        problems.append(Problem("identity_mismatch", where, "grade or method differs from the index"))
    if dg.brief_chars(d["brief"]) > dg.BRIEF_CHARS:
        problems.append(Problem("brief_too_long", where + ".brief", "%d characters, the limit is %d" % (dg.brief_chars(d["brief"]), dg.BRIEF_CHARS)))
    if (d["provenance"]["method"] == "model") != (d["provenance"]["model"] is not None):
        problems.append(Problem("inconsistent", where + ".provenance", "method and model disagree"))
    if d["basis"] != "transcript" and (d["quotes"] or d["provenance"]["transcript_sha256"] is not None):
        problems.append(Problem("inconsistent", where, "quotes or a transcript hash without a transcript"))
    if d["basis"] == "headline" and d["quality"]["grade"] != "headline":
        problems.append(Problem("inconsistent", where, "a headline digest with another grade"))
    if transcript is not None:
        if transcript_sha256 is not None and d["provenance"]["transcript_sha256"] != transcript_sha256:
            problems.append(Problem("identity_mismatch", where + ".provenance", "the digest was not made from the transcript in the output"))
        count = len(transcript.segments)
        pointers = [p["at"] for p in d["talking_points"]] + [q["at"] for q in d["quotes"]] + [n["at"] for n in d["numbers"]]
        if d["strongest_claim"]:
            pointers.append(d["strongest_claim"]["at"])
        pointers += [r["at"] for r in d.get("mentioned_resources", [])] + [m["at"] for m in d.get("snippable_moments", [])]
        pointers += [{"segment": c["segment"]} for c in d.get("chapters", [])]
        if any(at["segment"] is not None and at["segment"] >= count for at in pointers):
            problems.append(Problem("inconsistent", where, "a pointer names a segment the transcript does not have"))
        for n, q in enumerate(d["quotes"]):
            number = q["at"]["segment"]
            if q["exact"] and (number is None or number >= count or q["text"] not in transcript.segments[number].text):
                problems.append(Problem("inconsistent", "%s.quotes[%d]" % (where, n), "marked exact but not in the segment it points to"))
        for n, m in enumerate(d.get("snippable_moments", [])):
            number = m["at"]["segment"]
            if number is None or number >= count or m["quote"] not in transcript.segments[number].text:
                problems.append(Problem("inconsistent", "%s.snippable_moments[%d]" % (where, n), "not in the segment it points to"))
    return (None if problems else d), problems


def check_brief(data, listing, item, topics=None, transcript=None):
    """An item's brief file (format 1.3), against its entry in the items file. `topics` is the vocabulary of the
    store.json (None skips that check). With the transcript (only where the output carries it), every ref must name a
    line of it and every quote must be in it word for word."""
    ref = item["brief"]
    where = ref["path"]
    problems = check_file(data, ref, where)
    if problems:
        return None, problems
    b, problems = read_json(data, "brief", where, BRIEF_BYTES)
    if b is None:
        return None, problems
    same = (("source_id", listing["id"]), ("source_name", listing["name"]), ("item_id", item["id"]), ("title", item["title"]), ("date", item["date"]),
            ("link", item["link"]), ("brief_kind", ref["kind"]), ("covers", ref["covers"]))
    for key, expected in same:
        if b[key] != expected:
            problems.append(Problem("identity_mismatch", "%s.%s" % (where, key), "differs from the index"))
    size = br.visible_chars(b)
    if size > br.VISIBLE_CHARS:
        problems.append(Problem("brief_too_long", where, "%d visible characters, the limit is %d" % (size, br.VISIBLE_CHARS)))
    if (b["brief_kind"] == "model") != (b["model"] is not None):
        problems.append(Problem("inconsistent", where + ".model", "brief_kind and model disagree"))
    if b["brief_kind"] == "model" and (len(b["claims"]) < br.CLAIMS_MIN or any(c["ref"] is None for c in b["claims"]) or b["new"] is None):
        problems.append(Problem("inconsistent", where + ".claims", "a model brief has at least %d claims, each with a ref, and says what is new" % br.CLAIMS_MIN))
    if (b["covers"] == "whole") != (b["covers_note"] is None):
        problems.append(Problem("inconsistent", where + ".covers_note", "a partial brief says what it covers, a whole one has no note"))
    if topics is not None and any(t not in {x["id"] for x in topics} for t in b["topics"]):
        problems.append(Problem("inconsistent", where + ".topics", "a topic is not in the vocabulary"))
    if transcript is not None:
        refs = {r for r, _, _, _ in br.lines_of(transcript)} | {br.ref_of_segment(s, n) for n, s in enumerate(transcript.segments)}
        body = br.norm(" ".join(s.text for s in transcript.segments))
        if any(c["ref"] is not None and c["ref"] not in refs for c in b["claims"]) or any(q["time"] not in refs for q in b["quotes"]):
            problems.append(Problem("inconsistent", where, "a ref names no line of the transcript"))
        if any(br.norm(q["text"]) not in body for q in b["quotes"]):
            problems.append(Problem("inconsistent", where + ".quotes", "a quote is not in the transcript word for word"))
    return (None if problems else b), problems


def check_briefs_index(data, store, items_by_source):
    """briefs-index.json (format 1.3, optional), against the store.json and the items files it was made from
    (`items_by_source`: {source id: parsed items file}). It must be exactly what those files give: every brief it names
    is listed, every count and title agrees, nothing is missing. An index that differs is not used."""
    where = bx.INDEX_FILE
    index, problems = read_json(data, "briefs-index", where, INDEX_BYTES)
    if index is None:
        return None, problems
    expected = bx.known_view(bx.build(store, items_by_source, store["generated_at"]))
    found = bx.known_view(index)
    if found["generated_at"] != expected["generated_at"]:
        problems.append(Problem("identity_mismatch", where + ".generated_at", "not the generated_at of the store.json beside it"))
    briefs = {(s, i["id"]) for s, items in items_by_source.items() for i in (items or {"items": []})["items"] if i.get("brief")}
    named = [(s["id"], e["item_id"]) for s in found["shows"] for e in s["latest"]] + [(e["show_id"], e["item_id"]) for e in found["latest_overall"]]
    missing = [n for n in named if n not in briefs]
    if missing:
        problems.append(Problem("missing", where, "names a brief that is not listed: %s/%s" % missing[0]))
    elif found["shows"] != expected["shows"] or found["latest_overall"] != expected["latest_overall"]:
        problems.append(Problem("inconsistent", where, "differs from the briefs listed in the items files"))
    return (None if problems else index), problems


class Report:
    def __init__(self):
        self.problems, self.files, self.bytes, self.sources, self.items = [], 0, 0, 0, 0
        self.bad_sources = set()

    @property
    def ok(self):
        return not self.problems


def _read(folder, relative):
    path = os.path.join(folder, *relative.split("/"))
    if not os.path.isfile(path) or os.path.islink(path):
        return None
    with open(path, "rb") as f:
        return f.read()


def check_source_folder(folder, listing, report=None, topics=None):
    """Every file of one source under `folder`. Returns the list of problems (also added to `report`). `topics` is the
    vocabulary of the store.json the listing is from (see check_items)."""
    report = report or Report()
    problems, listed = [], set()
    ref = listing["items_file"]
    if ref is not None:
        listed.add(ref["path"])
        data = _read(folder, ref["path"])
        if data is None:
            problems.append(Problem("missing", ref["path"], "the items file is not there"))
        else:
            items, found = check_items(data, listing, topics)
            problems += found
            report.files += 1
            report.bytes += len(data)
            for item in (items or {"items": []})["items"]:
                report.items += 1
                transcript = sha = None
                t = item["transcript"]["file"]
                if t is not None:
                    listed.add(t["path"])
                    data = _read(folder, t["path"])
                    if data is None:
                        problems.append(Problem("missing", t["path"], "the transcript is not there"))
                    else:
                        transcript, found = check_transcript(data, item)
                        problems += found
                        sha = t["sha256"]
                        report.files += 1
                        report.bytes += len(data)
                listed.add(item["digest"]["path"])
                data = _read(folder, item["digest"]["path"])
                if data is None:
                    problems.append(Problem("missing", item["digest"]["path"], "the digest is not there"))
                else:
                    _, found = check_digest(data, listing, item, transcript, sha)
                    problems += found
                    report.files += 1
                    report.bytes += len(data)
                if item.get("brief") is not None:
                    listed.add(item["brief"]["path"])
                    data = _read(folder, item["brief"]["path"])
                    if data is None:
                        problems.append(Problem("missing", item["brief"]["path"], "the brief is not there"))
                    else:
                        _, found = check_brief(data, listing, item, topics, transcript)
                        problems += found
                        report.files += 1
                        report.bytes += len(data)
    base = os.path.join(folder, "sources", listing["id"])
    if os.path.isdir(base):
        for name in sorted(os.listdir(base)):
            if "sources/%s/%s" % (listing["id"], name) not in listed:
                problems.append(Problem("unlisted_file", "sources/%s/%s" % (listing["id"], name), "no index names this file"))
    if problems:
        report.bad_sources.add(listing["id"])
    report.problems += problems
    return problems


def check_folder(folder):
    """A whole output folder: store.json, every source's items file, every digest, brief and transcript, the briefs
    index when there is one, health.json and state.json, and nothing else. Returns a Report."""
    report = Report()
    data = _read(folder, "store.json")
    if data is None:
        report.problems.append(Problem("missing", "store.json", "the folder has no store.json"))
        return report
    report.files, report.bytes = 1, len(data)
    store, problems = check_store(data)
    report.problems += problems
    if store is None:
        return report
    for listing in store["sources"]:
        report.sources += 1
        check_source_folder(folder, listing, report, store.get("topics", []))
    data = _read(folder, bx.INDEX_FILE)
    if data is not None:   # optional: an output of generator 0.6.0 has none, and a reader then makes the same list itself
        items_by_source = {}
        for listing in store["sources"]:
            ref = listing["items_file"]
            raw = _read(folder, ref["path"]) if ref else None
            if raw is not None:
                items_by_source[listing["id"]] = check_items(raw, listing, store.get("topics", []))[0]
        report.files += 1
        report.bytes += len(data)
        report.problems += check_briefs_index(data, store, items_by_source)[1]
    known = {s["id"] for s in store["sources"]}
    base = os.path.join(folder, "sources")
    for name in sorted(os.listdir(base)) if os.path.isdir(base) else []:
        if name not in known:
            report.problems.append(Problem("unlisted_file", "sources/" + name, "a folder for a source the store does not list"))
    for name, kind, needed in (("health.json", "health", True), ("state.json", "state", False)):
        data = _read(folder, name)
        if data is None:
            if needed:
                report.problems.append(Problem("missing", name, "the folder has no " + name))
            continue
        report.files += 1
        report.bytes += len(data)
        _, problems = read_json(data, kind, name, HEALTH_BYTES)
        report.problems += problems
    for name in sorted(os.listdir(folder)):
        if name not in ("store.json", bx.INDEX_FILE, "health.json", "state.json", "sources", ".nojekyll", "index.html"):
            report.problems.append(Problem("unlisted_file", name, "not part of the format"))
    return report
