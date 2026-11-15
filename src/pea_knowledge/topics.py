# Copyright 2026 The PEA knowledge processor authors
# SPDX-License-Identifier: Apache-2.0
"""Topics: one controlled vocabulary for every source, and a tagger that needs no model (docs/FORMAT.md, "Topics").

    config/topics.json          the vocabulary: about thirty topics, each with an id, a label, the words a person
                                might say for it, and one line of description. Published in store.json as `topics`.
    config/topic_lexicon.json   what the tagger looks for: per topic, words and phrases with a weight of 1, 2 or 3,
                                phrases that are never counted, and the numbers of the scoring.

The tagger is deterministic and uses the standard library only. It reads four texts of an item: the title, the
publisher's description and notes, the digest's talking points, quotes and glossary, and the first part of the
transcript. Each text is cut into words, each word loses a plural or possessive ending, and the longest phrase of
the lexicon that starts at a word is taken, so "machine learning model" is counted once for AI and the bare word
"model" is never counted at all. A topic is given only with enough evidence (two different words or phrases, or one
strong phrase), with a score over the minimum, and never because of the source alone. At most four topics.

A wrong tag is worse than a missing one: an item with no confident topic gets an empty list, and a reader falls back
to the topics of the source.

Nothing in an item's text can add an id: the ids come from the vocabulary, the text only decides which of them fit.
"""
import hashlib
import json
import math
import os
import re

from . import textrules

ITEM_TOPICS = 4               # topics on one item; the other limits are in schema/store.schema.json and items.schema.json
FIELDS = ("title", "notes", "digest", "transcript")
PHRASE_WORDS = 4              # the longest phrase the lexicon may hold
MODEL_SCORE_FLOOR = 0.3       # a model's topic below this is not taken
TRANSCRIPT_READ = 60_000      # characters of speech handed to the tagger, which cuts at the lexicon's own number

_WORD = re.compile(r"[a-z0-9]+(?:'[a-z]+)?")
_FILES = {}


class TopicsError(ValueError):
    """The vocabulary or the lexicon is not usable. Stops a run before anything is fetched."""


def stem(word):
    """A word without a possessive or plural ending: "podcasts" and "podcast's" are "podcast", "allergies" is
    "allergy". Nothing else is cut, so "supplementing" is not "supplement"."""
    if "'" in word:
        word = word.split("'", 1)[0]
    if len(word) > 4 and word.endswith("ies"):
        return word[:-3] + "y"
    if len(word) > 4 and word.endswith(("sses", "shes", "ches", "xes", "zes")):
        return word[:-2]
    if len(word) > 3 and word.endswith("s") and not word.endswith(("ss", "us", "is")):
        return word[:-1]
    return word


def words(text):
    """The stemmed words of a text, in order."""
    return [stem(w) for w in _WORD.findall(text.lower().replace("’", "'"))]


def _file(name):
    here = os.path.dirname(os.path.abspath(__file__))
    for folder in (os.path.join(here, "config"), os.path.join(here, "..", "..", "config")):
        path = os.path.join(folder, name)
        if os.path.exists(path):
            return path
    raise TopicsError("config/%s is not beside the code" % name)


def _read(path):
    if path not in _FILES:
        with open(path, "rb") as f:
            _FILES[path] = f.read()
    return _FILES[path]


def _json(data, name):
    def no_duplicates(pairs):
        out = {}
        for key, value in pairs:
            if key in out:
                raise TopicsError("%s: the key %s is written twice" % (name, key))
            out[key] = value
        return out
    try:
        return json.loads(data.decode("utf-8"), object_pairs_hook=no_duplicates)
    except (UnicodeDecodeError, ValueError) as e:
        if isinstance(e, TopicsError):
            raise
        raise TopicsError("%s is not JSON" % name) from None


def duplicate_id(topics):
    """The first id a vocabulary lists twice, or None."""
    seen = set()
    for t in topics:
        if t["id"] in seen:
            return t["id"]
        seen.add(t["id"])
    return None


def vocabulary(path=None):
    """The vocabulary as a list of {"id", "label", "synonyms", "description"}, in its own order: config/topics.json,
    held to the shape store.json publishes it in and to the text rules. Raises TopicsError."""
    from . import jsonschema_lite, validate   # here, because validate reads this module too
    raw = _json(_read(path or _file("topics.json")), "topics.json")
    found = raw.get("topics") if isinstance(raw, dict) else None
    errors = jsonschema_lite.validate(found, validate.schema("store")["properties"]["topics"])
    if errors:
        raise TopicsError("topics.json: %s %s" % errors[0])
    for t in found:
        for text in [t["label"], t["description"]] + t["synonyms"]:
            if textrules.check(text) is not None:
                raise TopicsError("topics.json: %s breaks the text rules (%r)" % (t["id"], text))
    if duplicate_id(found):
        raise TopicsError("topics.json: the topic id %s is listed twice" % duplicate_id(found))
    return found


SPOKEN_WORDS = 8              # the longest synonym, in words (the schema's limit)


def resolve(spoken, topics):
    """The ids a spoken word or phrase stands for, in the vocabulary's order. Every topic can be named by its id
    (hyphens as spaces), its label or one of its synonyms. What was said is cut into words like any other text, and
    at each word the longest name that starts there is taken, with every topic that carries it: "tech" gives
    technology, "mental health" gives mental-health and not health as well, "investing" gives more than one topic on
    purpose, and nothing known gives an empty list. This is the reference for a reader; it uses no model."""
    names = {}
    for t in topics:
        for name in [t["id"].replace("-", " "), t["label"]] + list(t["synonyms"]):
            key = " ".join(words(name))
            if key and t["id"] not in names.setdefault(key, []):
                names[key].append(t["id"])
    tokens, found, i = words(spoken), set(), 0
    while i < len(tokens):
        for n in range(min(SPOKEN_WORDS, len(tokens) - i), 0, -1):
            ids = names.get(" ".join(tokens[i:i + n]))
            if ids:
                found.update(ids)
                i += n - 1
                break
        i += 1
    return [t["id"] for t in topics if t["id"] in found]


class Tagger:
    """The vocabulary with the lexicon, ready to tag. `Tagger()` reads the two files beside the code."""

    def __init__(self, topics=None, lexicon=None):
        self.topics = vocabulary() if topics is None else topics
        self.ids = [t["id"] for t in self.topics]
        self.order = {i: n for n, i in enumerate(self.ids)}
        if lexicon is None:
            data = _read(_file("topic_lexicon.json"))
            lexicon = _json(data, "topic_lexicon.json")
            self.fingerprint = hashlib.sha256(_read(_file("topics.json")) + b"\x1f" + data).hexdigest()
        else:
            self.fingerprint = hashlib.sha256(json.dumps([self.topics, lexicon], sort_keys=True).encode("utf-8")).hexdigest()
        try:
            self._load(lexicon)
        except (KeyError, TypeError, AttributeError) as e:
            raise TopicsError("topic_lexicon.json does not have the expected shape (%s)" % type(e).__name__) from None

    def _load(self, lexicon):
        s = lexicon["scoring"]
        self.weights = {f: float(s["fields"][f]) for f in FIELDS}
        self.transcript_chars, self.notes_chars = int(s["transcript_chars"]), int(s["notes_chars"])
        self.count_cap, self.half = int(s["count_cap"]), float(s["half_score_at"])
        self.min_score, self.floor = float(s["min_score"]), float(s["relative_floor"])
        self.most = min(int(s["max_topics"]), ITEM_TOPICS)
        self.prior = float(s["prior_bonus"])
        self.repeats = int(s["strong_repeats_in_transcript"])
        self.weak_in = tuple(s["weak_words_count_in"])
        self.said_twice = int(s["clear_repeats_in_transcript"])
        self.anchors = tuple(s["anchor_fields"])
        if not (0 < self.min_score < 1 and self.half > 0 and self.count_cap >= 1 and self.most >= 1 and 0 <= self.floor <= 1):
            raise TopicsError("topic_lexicon.json: the scoring numbers are out of range")
        self.table = {}
        for phrase in lexicon.get("blocked", []):
            self.table[self._key(phrase, "blocked")] = ()
        for tid, by_weight in lexicon["topics"].items():
            if tid not in self.order:
                raise TopicsError("topic_lexicon.json names the topic %s, which the vocabulary does not have" % tid)
            for weight, phrases in by_weight.items():
                if weight not in ("1", "2", "3"):
                    raise TopicsError("topic_lexicon.json: %s has a weight other than 1, 2 or 3" % tid)
                for phrase in phrases:
                    key = self._key(phrase, tid)
                    if self.table.get(key) == ():
                        raise TopicsError("topic_lexicon.json: %r is both blocked and counted for %s" % (phrase, tid))
                    entry = self.table.setdefault(key, [])
                    if any(t == tid for t, _ in entry):
                        raise TopicsError("topic_lexicon.json: %r is listed twice for %s" % (phrase, tid))
                    entry.append((tid, int(weight)))
        missing = [i for i in self.ids if i not in lexicon["topics"]]
        if missing:
            raise TopicsError("topic_lexicon.json has no words for the topic %s" % missing[0])
        self.firsts = {key.split(" ", 1)[0] for key in self.table}

    @staticmethod
    def _key(phrase, where):
        parts = words(phrase) if isinstance(phrase, str) else []
        if not parts or len(parts) > PHRASE_WORDS:
            raise TopicsError("topic_lexicon.json: %r (%s) is not a phrase of one to %d words" % (phrase, where, PHRASE_WORDS))
        return " ".join(parts)

    def hits(self, text):
        """{phrase: times} for the lexicon phrases in a text, the longest phrase at each word first. A blocked phrase
        takes its words with it and counts for nothing."""
        tokens, found, i = words(text), {}, 0
        while i < len(tokens):
            if tokens[i] in self.firsts:
                for n in range(min(PHRASE_WORDS, len(tokens) - i), 0, -1):
                    key = " ".join(tokens[i:i + n])
                    entry = self.table.get(key)
                    if entry is not None:
                        if entry:
                            found[key] = found.get(key, 0) + 1
                        i += n - 1
                        break
            i += 1
        return found

    def evidence(self, fields):
        """Per topic id: {"raw": the weighted sum, "phrases": the different phrases found, "strong": whether one strong
        phrase is enough}. `fields` is {"title", "notes", "digest", "transcript"} as text."""
        out = {}
        for field in FIELDS:
            text = fields.get(field) or ""
            if field == "transcript":
                text = text[:self.transcript_chars]
            elif field == "notes":
                text = text[:self.notes_chars]
            for key, count in self.hits(text).items():
                for tid, weight in self.table[key]:
                    if weight == 1 and field not in self.weak_in:
                        continue   # a weak word says something in a title or in the publisher's notes, nothing in an hour of talk
                    if weight == 2 and field == "transcript" and count < self.said_twice:
                        continue   # a clear word said once in passing is not what the item is about
                    e = out.setdefault(tid, {"raw": 0.0, "phrases": set(), "strong": False, "anchored": False, "titled": False})
                    e["raw"] += self.weights[field] * weight * math.sqrt(min(count, self.count_cap))
                    e["phrases"].add(key)
                    if weight == 3 and (field != "transcript" or count >= self.repeats):
                        e["strong"] = True
                    if weight >= 2 and field in self.anchors:
                        e["anchored"] = True   # what the item is about shows in its title, notes or digest, not only in passing talk
                    if weight >= 2 and field == "title":
                        e["titled"] = True
        return out

    def score(self, raw):
        return raw / (raw + self.half)

    def tag(self, fields, prior=()):
        """The topics of one item: at most four {"id", "score"}, best first, ties in the vocabulary's order. `prior` is
        the source's own topics: a small push for a topic the text already points to, never a reason by itself."""
        found = self.evidence(fields)
        kept = []
        for tid, e in found.items():
            if (len(e["phrases"]) < 2 and not e["strong"]) or not e["anchored"]:
                continue
            raw = e["raw"] + (self.prior if tid in prior else 0.0)
            kept.append((raw, tid, e["titled"]))
        if not kept:
            return []
        top = max(raw for raw, _, _ in kept)
        scored = [(round(self.score(raw), 2), tid) for raw, tid, titled in kept if titled or raw >= self.floor * top]
        scored = [(s, tid) for s, tid in scored if s >= self.min_score]
        scored.sort(key=lambda p: (-p[0], self.order[p[1]]))
        return [{"id": tid, "score": s} for s, tid in scored[:self.most]]

    def from_model(self, proposed, fields):
        """A model's topics, checked: only ids of the vocabulary, each once, a score that is a number from 0.3 to 1,
        and only a topic for which the title, the notes and the digest hold the evidence a keyword tag needs (two
        different phrases of the lexicon, or one strong one). So text that talks a model into an answer can neither
        add an id nor tag an item with a topic its own digest does not bear out. The model decides which of the
        borne-out topics the item is about and how much. Returns a list like `tag`, possibly empty."""
        if not isinstance(proposed, list):
            return []
        found = self.evidence({f: fields.get(f) for f in ("title", "notes", "digest")})
        out, seen = [], set()
        for row in proposed[:ITEM_TOPICS * 2]:
            tid = row.get("id") if isinstance(row, dict) else None
            value = row.get("score") if isinstance(row, dict) else None
            if not isinstance(tid, str) or tid not in self.order or tid in seen:
                continue
            e = found.get(tid)
            if e is None or (len(e["phrases"]) < 2 and not e["strong"]) or not e["anchored"]:
                continue   # the same evidence a keyword tag needs, from the title, the notes and the digest alone
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or not MODEL_SCORE_FLOOR <= value <= 1:
                continue
            seen.add(tid)
            out.append((round(float(value), 2), tid))
        out.sort(key=lambda p: (-p[0], self.order[p[1]]))
        return [{"id": tid, "score": s} for s, tid in out[:self.most]]


_SPONSOR = re.compile(r"(?i)\bsponsors?\b|\bsponsored\b|brought to you by|promo code|use code|% off|free trial|support (?:for )?(?:the|this) show")
SPONSOR_SENTENCES = 3


def without_sponsors(notes):
    """Publisher notes without their sponsor lines: a sentence that names a sponsor goes, and the two after it, which
    are usually what the sponsor sells. Otherwise every show that reads an advertisement for a security company would
    be about security."""
    kept, skip = [], 0
    for sentence in textrules.sentences(notes):
        if _SPONSOR.search(sentence):
            skip = SPONSOR_SENTENCES
        if skip:
            skip -= 1
            continue
        kept.append(sentence)
    return " ".join(kept)


def fields_of(item, digest, transcript=None):
    """The four texts the tagger reads for an item of the work folder, its digest and its transcript (or None)."""
    points = [p["point"] for p in digest.get("talking_points", [])] + [q["text"] for q in digest.get("quotes", [])]
    points += ["%s %s" % (g["term"], g["gloss"] or "") for g in digest.get("glossary", [])]
    spoken, size = [], 0
    if transcript is not None:
        from .transcript import pea_transcript as pt
        for s in transcript.segments:
            if pt.is_ad(s.text):
                continue
            spoken.append(s.text)
            size += len(s.text) + 1
            if size >= TRANSCRIPT_READ:
                break
    return {"title": item["title"], "notes": " ".join(without_sponsors(t) for t in (item.get("summary", ""), item.get("notes", "")) if t),
            "digest": " ".join(points), "transcript": " ".join(spoken)}


def check_item(topics, method, known):
    """What is wrong with the `topics` and `topics_by` of an item, as a list of sentences. `known` is the set of ids of
    the vocabulary, or None when the reader was not given one."""
    problems = []
    if (topics is None) != (method is None):
        return ["topics and topics_by go together"]
    if topics is None:
        return problems
    ids = [t["id"] for t in topics]
    if len(set(ids)) != len(ids):
        problems.append("a topic is listed twice")
    if known is not None and any(i not in known for i in ids):
        problems.append("the topic %s is not in the vocabulary" % next(i for i in ids if i not in known))
    if any(round(t["score"], 2) != t["score"] for t in topics):
        problems.append("a score has more than two decimals")
    if [t["score"] for t in topics] != sorted((t["score"] for t in topics), reverse=True):
        problems.append("the topics are not sorted by score")
    return problems
