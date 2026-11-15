# Copyright 2026 The PEA knowledge processor authors
# SPDX-License-Identifier: Apache-2.0
"""Stage 3: the digest of one item. This file holds the shape, its limits and the extractive digest.

The extractive digest uses no model: it picks sentences that are already in the transcript (or, without one, in the
publisher's notes), so the same input always gives the same digest and the pipeline works with no key at all.
`model_digest.py` adds the optional model path; whatever it returns is forced through `enforce` here.
"""
import hashlib
import re
from collections import Counter

from . import FORMAT_VERSION, textrules
from .transcript import pea_transcript as pt

# The limits of docs/FORMAT.md, "The digest". The schema states the same numbers; a test keeps the two in step.
ABOUT_CHARS = 400
POINTS, POINTS_WANTED, POINT_CHARS, WHY_CHARS, ASK_CHARS = 8, 5, 280, 200, 160
QUOTES, QUOTE_CHARS, SPEAKER_CHARS = 5, 240, 40
GLOSSARY, TERM_CHARS, GLOSS_CHARS = 14, 80, 140
NUMBERS, NUMBER_VALUE_CHARS, NUMBER_CONTEXT_CHARS = 6, 40, 200
BACKGROUND_CHARS = 400
CLAIM_CHARS = 280
CONTESTED, CONTESTED_CHARS = 3, 200
CONNECTIONS, CONNECTION_CHARS = 3, 120
STARTERS, FOLLOW_UPS, OFFER_CHARS = 3, 3, 160
QUALITY_NOTES, QUALITY_NOTE_CHARS = 6, 160
BRIEF_CHARS = 900                      # all the text of the brief form together
BRIEF_ABOUT_CHARS, BRIEF_POINTS, BRIEF_POINT_CHARS, BRIEF_QUOTE_CHARS, BRIEF_HOOK_CHARS = 240, 3, 170, 170, 140
DIGEST_BYTES = 24_000
KINDS = ("person", "organisation", "product", "other")
TONES = ("news", "analysis", "technical", "interview", "conversational", "light", "unknown")
BASES = ("transcript", "notes", "headline")

_WORD = re.compile(r"[a-z0-9][a-z0-9']{2,}")
_STOP = frozenset("""the and that this with for are was were have has had not but you your they them their there then than
what when where which who whom will would could should can about into from over under just like really very also been being
its it's i'm i've we're we've you're they're don't doesn't didn't that's there's here's let's going gonna kind sort lot
thing things something anything know think mean right yeah okay well actually basically some any all one two out get got
because how why more most much many other these those our his her she him so too now see say said says people way want
make made time even still back only little good great bit lots stuff yes no""".split())
_FILLER = re.compile(r"(?i)^(?:yeah|yep|yes|no|okay|ok|right|well|um|uh|oh|so yeah|i mean|you know|all right|alright|hey|hi|hello|thanks|thank you|welcome)\b")
_NUMBER = re.compile(
    r"(?:[$€£]\s?\d[\d,]*(?:\.\d+)?(?:\s?(?:trillion|billion|million|thousand|[kKmMbB]n?\b))?"
    r"|\b\d[\d,]*(?:\.\d+)?\s?(?:%|percent\b|x\b|times\b|trillion\b|billion\b|million\b|thousand\b|dollars\b|users\b|people\b"
    r"|employees\b|customers\b|subscribers\b|downloads\b|episodes\b|years\b|months\b|weeks\b|days\b|hours\b|minutes\b|tokens\b))")
_CAPITALISED = re.compile(r"\b(?:[A-Z][A-Za-z0-9&'’\-]*\.?)(?:\s+(?:(?:of|the|and|for|de|van|von)\s+)?[A-Z][A-Za-z0-9&'’\-]*)*")
_NOT_NAMES = frozenset("""The A An And But So Or If In On At It Its This That These Those There Then They We You He She I Im Ive
What When Where Which Who Why How Yes No Not Now Well Okay OK Oh Yeah Right Also Because For From With Without To Of As By
Is Are Was Were Be Been Do Does Did Have Has Had Can Could Will Would Should May Might Must Let Lets My Our Your His Her
Their Some Any All One Two Three Four Five Six Seven Eight Nine Ten First Second Third Today Tomorrow Yesterday Monday
Tuesday Wednesday Thursday Friday Saturday Sunday January February March April June July August September October
November December Thanks Thank Welcome Hello Hi Hey Just Like Maybe Actually Basically Here Every Each Most Many Much
More Less Other Another Plus After Before During While Since Until Although Though However Still Even Only Again Chapter
Episode Part Mr Mrs Ms Dr""".split())
_ORGANISATION = re.compile(r"(?:\b(?:Inc|Corp|Corporation|Company|Labs?|AI|University|Institute|Foundation|Group|Bank|Capital|Ventures|"
                           r"Department|Agency|Committee|Commission|Association|Technologies|Systems|Networks|Media|News|Times|Post|Journal|"
                           r"Court|Senate|Congress|Council|Board|Trust|Cooperative|Sons|Ministry|Party|Union|Society|Studio|Studios|Index)\b)")
_PERSON_CUE = r"(?:%s(?:'s|’s)?\s+(?:said|says|told|argues|argued|wrote|writes|thinks|believes|joined|explains|explained|asked|added|noted)\b|\b(?:CEO|founder|co-founder|president|professor|senator|director|host|author|Mr\.?|Ms\.?|Mrs\.?|Dr\.?)\s+%s)"


_HEDGE = re.compile(r"(?i)\b(?:reportedly|allegedly|alleged|unclear|unconfirmed|unverified|rumou?rs?|disputed|contested|critics|"
                    r"skeptic\w*|sceptic\w*|no evidence|not clear|we don't know|nobody knows|remains to be seen|open question|"
                    r"may or may not|hard to say|too early to)\b")


_QUESTION = re.compile(r"(?i)^(?:(?:and|so|but|now|okay),?\s+)?(?:[A-Z][a-z]+,\s+)?(?:how|what|why|where|when|who|which|can|could|do|does|did|is|are|should|would|will|have|has)\b")


class Unit:
    """One sentence that may be picked: where it was said, by whom, and how much it says."""
    __slots__ = ("index", "segment", "time", "speaker", "text", "score")

    def __init__(self, index, segment, time, speaker, text):
        self.index, self.segment, self.time, self.speaker, self.text, self.score = index, segment, time, speaker, text, 0.0

    @property
    def at(self):
        return {"time_seconds": self.time, "segment": self.segment}


NOWHERE = {"time_seconds": None, "segment": None}


def transcript_sha256(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def empty(source, item):
    """The fixed frame of a digest: what identifies the item. None of it ever comes from a transcript or a model."""
    return {
        "format": "pea-knowledge-digest",
        "format_version": FORMAT_VERSION,
        "source_id": source["id"],
        "source_name": source["name"],
        "item_id": item["id"],
        "title": item["title"],
        "date": item["date"],
        "link": item["link"],
        "language": source["language"],
        "duration_seconds": item.get("duration_seconds"),
        "basis": "headline",
        "about": "",
        "brief": {"about": "", "points": [], "quote": None, "hook": None},
        "talking_points": [],
        "quotes": [],
        "glossary": [],
        "numbers": [],
        "background": None,
        "strongest_claim": None,
        "contested": [],
        "connections": [],
        "starters": [],
        "follow_ups": [],
        "tone": "unknown",
        "provenance": {"method": "extractive", "model": None, "transcript_sha256": None},
        "quality": {"grade": "headline", "notes": []},
    }


def usable(text):
    return isinstance(text, str) and textrules.check(text) is None and not textrules.looks_like_instruction(text)


def units_of(transcript):
    """Every sentence of the transcript outside sponsor reads, in order, with the segment, time and speaker it has."""
    out = []
    for number, segment in enumerate(transcript.segments):
        if pt.is_ad(segment.text):
            continue
        for sentence in textrules.sentences(segment.text):
            out.append(Unit(len(out), number, segment.start, segment.speaker, sentence))
    return out


def _score(units, title):
    counts = Counter()
    words = []
    for u in units:
        found = {w for w in _WORD.findall(u.text.lower()) if w not in _STOP}
        words.append(found)
        counts.update(found)
    title_words = {w for w in _WORD.findall(title.lower()) if w not in _STOP}
    for u, found in zip(units, words):
        if not found:
            continue
        score = sum(counts[w] for w in found) / (len(found) ** 0.6)
        score *= 1.0 + 0.25 * len(found & title_words)
        if _NUMBER.search(u.text):
            score *= 1.15
        if _FILLER.match(u.text):
            score *= 0.5
        u.score = score


def _candidates(units, shortest=40, longest=600, words=8):
    return [u for u in units if shortest <= len(u.text) <= longest and len(u.text.split()) >= words
            and not u.text.endswith("?") and usable(u.text)]


def _spread(candidates, wanted):
    """`wanted` candidates spread over the whole length, in order: the best of each stretch."""
    if len(candidates) <= wanted:
        return list(candidates)
    picked = []
    for b in range(wanted):
        stretch = candidates[b * len(candidates) // wanted:(b + 1) * len(candidates) // wanted]
        if stretch:
            picked.append(max(stretch, key=lambda u: (u.score, -u.index)))
    return sorted(picked, key=lambda u: u.index)


def _glossary(units, speakers):
    """Names that come up at least twice, most frequent first, each with the sentence that first mentions it as its gloss."""
    text_all = " ".join(u.text for u in units)
    counts, first = Counter(), {}
    for u in units:
        for m in _CAPITALISED.finditer(u.text):
            tokens = m.group(0).split()
            while tokens and (tokens[0].rstrip(".").replace("'", "").replace("’", "") in _NOT_NAMES):
                tokens = tokens[1:]
            while tokens and tokens[-1] in ("of", "the", "and", "for"):
                tokens = tokens[:-1]
            name = " ".join(tokens).rstrip(".").strip("'’-")
            if name.endswith(("'s", "’s")):
                name = name[:-2]
            if len(name) < 3 or len(name) > TERM_CHARS or len(tokens) > 5 or name in _NOT_NAMES or name.isdigit() or "'" in name or "’" in name:
                continue
            if len(tokens) == 1 and (m.start() == 0 or name.rstrip("s") in ("CEO", "CTO", "CFO", "API", "FAQ")):
                continue  # a single capitalised word that starts a sentence is usually just a word
            counts[name] += 1
            first.setdefault(name, u)
    out = [{"term": s, "kind": "person", "gloss": "a speaker in this episode"} for s in speakers if usable(s)][:GLOSSARY]
    seen = {n["term"].lower() for n in out}
    ranked = sorted((n for n in counts if counts[n] >= 2), key=lambda n: (-counts[n], first[n].index, n))
    for name in ranked:
        if len(out) >= GLOSSARY:
            break
        if name.lower() in seen or any(name.lower() in s for s in seen) or not usable(name):
            continue
        short = next((g for g in out if len(g["term"].split()) == 1 and g["term"] in name.split() and g["gloss"] != "a speaker in this episode"), None)
        if short is not None:  # "Tobias Renn" after "Tobias": one entry, under the fuller name
            seen.add(name.lower())
            short["term"] = name
            continue
        tokens = name.split()
        if len(tokens) == 1 and _ORGANISATION.fullmatch(name):
            continue  # "Studio", "Board": a word that only hints at an organisation is not a name
        if len(tokens) >= 2 and _ORGANISATION.search(name):
            kind = "organisation"
        elif 2 <= len(tokens) <= 3 and all(t[:1].isupper() and t.replace("-", "").isalpha() for t in tokens) \
                and re.search(_PERSON_CUE % (re.escape(name), re.escape(name)), text_all):
            kind = "person"
        else:
            kind = "other"
        mention = first[name].text
        out.append({"term": name, "kind": kind, "gloss": textrules.shorten(mention, GLOSS_CHARS) if usable(mention) else None})
        seen.add(name.lower())
    return out


def _numbers(units, taken):
    found, values = [], set()
    for u in sorted((u for u in units if 30 <= len(u.text) <= 600 and usable(u.text)), key=lambda u: (-u.score, u.index)):
        m = _NUMBER.search(u.text)
        if not m:
            continue
        value = " ".join(m.group(0).split()).rstrip(",.")
        if value.lower() in values or u.index in taken or len(value) > NUMBER_VALUE_CHARS:
            continue
        values.add(value.lower())
        found.append((u, value))
        if len(found) == NUMBERS:
            break
    return [{"value": v, "context": textrules.shorten(u.text, NUMBER_CONTEXT_CHARS), "at": u.at}
            for u, v in sorted(found, key=lambda pair: pair[0].index)]


def _questions(units):
    return [u for u in units if u.text.endswith("?") and 30 <= len(u.text) <= ASK_CHARS and len(u.text.split()) >= 6
            and usable(u.text) and _QUESTION.match(u.text)]


def _about(item, units):
    for text, least in ((item.get("summary", ""), 60), (item.get("notes", ""), 120)):
        if len(text) >= least and text.strip().lower() != item["title"].strip().lower():
            picked = textrules.first_sentences(text, ABOUT_CHARS, most=3)
            if usable(picked):
                return picked, True
    opening = _candidates(units[:max(12, len(units) // 5)], longest=200)
    best = sorted(sorted(opening, key=lambda u: (-u.score, u.index))[:2], key=lambda u: u.index)
    text = ""
    for u in best:
        if len(text) + len(u.text) + 1 <= ABOUT_CHARS:
            text = (text + " " + u.text).strip()
    return text or item["title"], False


def connections(digest, earlier):
    """Earlier items of the same source whose title names something in this item's glossary. `earlier` is a list of
    (item id, title), newest first."""
    terms = [g["term"] for g in digest["glossary"] if len(g["term"]) >= 4 and g["term"].lower() not in digest["source_name"].lower()]
    out = []
    for item_id, title in earlier:
        if item_id == digest["item_id"]:
            continue
        for term in terms:
            if re.search(r"(?<![A-Za-z0-9])%s(?![A-Za-z0-9])" % re.escape(term), title):
                out.append({"item_id": item_id, "why": textrules.shorten("also about %s" % term, CONNECTION_CHARS)})
                break
        if len(out) == CONNECTIONS:
            break
    return out


def _offers(d, questions):
    """Three things the assistant can offer to open with, built from what the digest holds."""
    out = []
    for g in d["glossary"]:
        if g["gloss"] != "a speaker in this episode":
            out.append("What was said about %s" % g["term"])
            break
    if d["numbers"]:
        out.append("The figure %s and where it comes from" % d["numbers"][0]["value"])
    if questions:
        out.append(questions[0].text)
    out.append("The main points of this one, in order")
    if d["quotes"]:
        out.append("The most quotable line" + (" from %s" % d["quotes"][0]["speaker"] if d["quotes"][0]["speaker"] else ""))
    return [textrules.shorten(o, OFFER_CHARS) for o in out if usable(o)][:STARTERS]


def _taken_chars(d):
    return (sum(len(k["point"]) + len(k["ask"] or "") for k in d["talking_points"]) + sum(len(q["text"]) for q in d["quotes"])
            + sum(len(n["context"]) for n in d["numbers"]) + sum(len(q) for q in d["follow_ups"]) + sum(len(c) for c in d["contested"])
            + sum(len(g["gloss"] or "") for g in d["glossary"] if g["gloss"] != "a speaker in this episode")
            + len((d["strongest_claim"] or {}).get("text", "")))


def within(d, budget):
    """Keeps the words taken from a transcript inside `budget` characters. What goes first: numbers, contested lines,
    follow-up questions, glosses, quotes, then talking points down to the five a digest should have."""
    for field, least in (("numbers", 2), ("contested", 1), ("follow_ups", 1), ("quotes", 2), ("numbers", 0), ("contested", 0), ("follow_ups", 0)):
        while _taken_chars(d) > budget and len(d[field]) > least:
            d[field].pop()
    for g in reversed(d["glossary"]):
        if _taken_chars(d) <= budget:
            break
        if g["gloss"] != "a speaker in this episode":
            g["gloss"] = None
    for field, least in (("quotes", 0), ("talking_points", POINTS_WANTED)):
        while _taken_chars(d) > budget and len(d[field]) > least:
            d[field].pop()
    return d


def extractive(source, item, transcript=None, budget=None, earlier=()):
    """The digest of `item` with no model. `transcript` is a pea_transcript.Transcript or None; `budget` caps the
    characters taken from a transcript that may not be republished in full; `earlier` is (id, title) of older items."""
    d = empty(source, item)
    notes = d["quality"]["notes"]
    news = source.get("kind") == "news"
    if transcript is not None and transcript.segments:
        units = units_of(transcript)
        _score(units, item["title"])
        d["basis"] = "transcript"
        d["provenance"]["transcript_sha256"] = transcript_sha256(transcript.render())
        d["about"], from_publisher = _about(item, units)
        candidates = _candidates(units)
        points = _spread(candidates, 7)
        questions = _questions(units)
        asked = set()
        for i, u in enumerate(points):
            until = points[i + 1].index if i + 1 < len(points) else len(units)
            hook = next((q for q in questions if u.index < q.index < until and q.index not in asked), None)
            if hook is not None:
                asked.add(hook.index)
            d["talking_points"].append({"point": textrules.shorten(u.text, POINT_CHARS), "why": None, "at": u.at, "ask": hook.text if hook else None})
        taken = {u.index for u in points}
        quotable = [u for u in candidates if 50 <= len(u.text) <= QUOTE_CHARS and u.index not in taken and not _FILLER.match(u.text)]
        quotes = sorted(sorted(quotable, key=lambda u: (u.speaker is None, -u.score, u.index))[:4], key=lambda u: u.index)
        d["quotes"] = [{"text": u.text, "speaker": u.speaker if u.speaker and usable(u.speaker) else None, "at": u.at, "exact": True} for u in quotes]
        taken |= {u.index for u in quotes}
        d["glossary"] = _glossary(units, transcript.speakers)
        d["numbers"] = _numbers(units, taken)
        claims = sorted((u for u in candidates if len(u.text) <= CLAIM_CHARS and u.index not in taken), key=lambda u: (-u.score, u.index))
        if claims:
            d["strongest_claim"] = {"text": claims[0].text, "at": claims[0].at}
            taken.add(claims[0].index)
        hedged = sorted((u for u in candidates if _HEDGE.search(u.text) and u.index not in taken), key=lambda u: (-u.score, u.index))[:2]
        d["contested"] = [textrules.shorten(u.text, CONTESTED_CHARS) for u in sorted(hedged, key=lambda u: u.index)]
        left = [q for q in questions if q.index not in asked]
        d["follow_ups"] = [q.text for q in sorted(sorted(left, key=lambda u: (-u.score, u.index))[:FOLLOW_UPS], key=lambda u: u.index)]
        if from_publisher and len(item.get("notes", "")) >= 200 and not item["notes"].startswith(d["about"][:60]):
            background = textrules.first_sentences(item["notes"], BACKGROUND_CHARS, most=3)
            d["background"] = background if usable(background) else None
        if budget is not None:
            within(d, budget)
        d["starters"] = _offers(d, left)
        d["tone"] = "news" if news else "interview" if len(transcript.speakers) >= 2 and len(questions) >= 8 else "conversational" if len(transcript.speakers) >= 2 else "unknown"
        partial = transcript.partial is not None
        enough = len(d["talking_points"]) >= POINTS_WANTED
        d["quality"]["grade"] = "full" if enough and not partial else "partial"
        notes.append("made without a model: points and glosses are sentences from the transcript; 'why' is not written")
        if partial:
            notes.append("the transcript is cut: the digest covers its first part only")
        if not enough:
            notes.append("fewer than %d talking points: the transcript is short or has few whole sentences" % POINTS_WANTED)
        if not transcript.timed:
            notes.append("the transcript has no times")
        notes.append("names and their kinds are found by pattern and may be wrong")
    elif len(item.get("notes", "")) >= 400 and not news:
        units = [Unit(i, None, None, None, s) for i, s in enumerate(textrules.sentences(item["notes"]))]
        _score(units, item["title"])
        d["basis"] = "notes"
        d["about"], _ = _about(item, units)
        points = _spread([u for u in _candidates(units, longest=400) if u.text not in d["about"]], 6)
        d["talking_points"] = [{"point": textrules.shorten(u.text, POINT_CHARS), "why": None, "at": dict(NOWHERE), "ask": None} for u in points]
        d["glossary"] = _glossary(units, [])
        d["numbers"] = _numbers(units, set())
        d["starters"] = _offers(d, [])
        d["quality"]["grade"] = "partial"
        notes.append("made from the publisher's show notes: no transcript, so no quotes and no times")
    else:
        about = textrules.first_sentences(item.get("summary") or "", 280, most=2) or item["title"]
        d["about"] = about if usable(about) else item["title"]
        d["tone"] = "news" if news else "unknown"
        d["starters"] = ["What this one is about, going by its headline"]
        notes.append("the headline and the publisher's short description only: follow the link for the piece itself")
    d["connections"] = connections(d, earlier)
    return enforce(d)


def _brief(d):
    """The compact form, made from the full one so that it can never say anything the full form does not: the framing,
    up to three points (first, middle, last, so it still reads as a story), one short quote, one hook."""
    points = d["talking_points"]
    chosen = [points[i] for i in sorted({0, len(points) // 2, len(points) - 1})] if points else []
    quote = next((q for q in d["quotes"] if len(q["text"]) <= BRIEF_QUOTE_CHARS), None)
    brief = {
        "about": textrules.shorten(d["about"], BRIEF_ABOUT_CHARS),
        "points": [textrules.shorten(p["point"], BRIEF_POINT_CHARS) for p in chosen][:BRIEF_POINTS],
        "quote": {"text": quote["text"], "speaker": quote["speaker"], "time_seconds": quote["at"]["time_seconds"]} if quote else None,
        "hook": textrules.shorten(d["starters"][0], BRIEF_HOOK_CHARS) if d["starters"] else None,
    }
    while brief_chars(brief) > BRIEF_CHARS:
        if brief["points"]:
            brief["points"].pop()
        elif brief["quote"]:
            brief["quote"] = None
        else:
            brief["hook"] = None
    return brief


def brief_chars(brief):
    """How long the brief form is: the characters of all its text together. The limit is BRIEF_CHARS."""
    quote = brief.get("quote") or {}
    return (len(brief.get("about") or "") + sum(len(p) for p in brief.get("points") or []) + len(quote.get("text") or "")
            + len(quote.get("speaker") or "") + len(brief.get("hook") or ""))


def enforce(d):
    """The last gate before a digest is written, whoever made it: every list cut to its limit, every text checked
    against the text rules and its length, anything that fails dropped, the brief form rebuilt. Returns the digest;
    raises ValueError when what is left is not a digest (no framing)."""
    def text_ok(value, limit):
        return isinstance(value, str) and 0 < len(value) <= limit and textrules.check(value) is None

    def optional(value, limit):
        return value if text_ok(value, limit) else None

    def at_ok(at):
        def whole(v, most):
            return v is None or (isinstance(v, int) and not isinstance(v, bool) and 0 <= v <= most)
        return isinstance(at, dict) and set(at) == {"time_seconds", "segment"} and whole(at["time_seconds"], pt.LATEST_SECOND) and whole(at["segment"], 100_000)

    if not text_ok(d.get("about"), ABOUT_CHARS):
        raise ValueError("no usable framing")
    d["talking_points"] = [{"point": p["point"], "why": optional(p.get("why"), WHY_CHARS), "at": p["at"], "ask": optional(p.get("ask"), ASK_CHARS)}
                           for p in d["talking_points"] if isinstance(p, dict) and text_ok(p.get("point"), POINT_CHARS) and at_ok(p.get("at"))][:POINTS]
    d["quotes"] = [{"text": q["text"], "speaker": optional(q.get("speaker"), SPEAKER_CHARS), "at": q["at"], "exact": q["exact"]}
                   for q in d["quotes"] if isinstance(q, dict) and text_ok(q.get("text"), QUOTE_CHARS) and at_ok(q.get("at")) and isinstance(q.get("exact"), bool)][:QUOTES]
    seen, glossary = set(), []
    for g in d["glossary"]:
        if isinstance(g, dict) and text_ok(g.get("term"), TERM_CHARS) and g.get("kind") in KINDS and g["term"].lower() not in seen:
            seen.add(g["term"].lower())
            glossary.append({"term": g["term"], "kind": g["kind"], "gloss": optional(g.get("gloss"), GLOSS_CHARS)})
    d["glossary"] = glossary[:GLOSSARY]
    d["numbers"] = [{"value": n["value"], "context": n["context"], "at": n["at"]} for n in d["numbers"]
                    if isinstance(n, dict) and text_ok(n.get("value"), NUMBER_VALUE_CHARS) and text_ok(n.get("context"), NUMBER_CONTEXT_CHARS) and at_ok(n.get("at"))][:NUMBERS]
    d["background"] = optional(d.get("background"), BACKGROUND_CHARS)
    claim = d.get("strongest_claim")
    d["strongest_claim"] = {"text": claim["text"], "at": claim["at"]} if isinstance(claim, dict) and text_ok(claim.get("text"), CLAIM_CHARS) and at_ok(claim.get("at")) else None
    d["contested"] = [c for c in d["contested"] if text_ok(c, CONTESTED_CHARS)][:CONTESTED]
    d["connections"] = [c for c in d["connections"] if isinstance(c, dict) and re.fullmatch(r"[a-z0-9][a-z0-9-]{0,63}", str(c.get("item_id", "")))
                        and text_ok(c.get("why"), CONNECTION_CHARS)][:CONNECTIONS]
    d["starters"] = [s for s in d["starters"] if text_ok(s, OFFER_CHARS)][:STARTERS]
    d["follow_ups"] = [s for s in d["follow_ups"] if text_ok(s, OFFER_CHARS)][:FOLLOW_UPS]
    d["tone"] = d.get("tone") if d.get("tone") in TONES else "unknown"
    d["quality"]["notes"] = [textrules.shorten(n, QUALITY_NOTE_CHARS) for n in d["quality"]["notes"] if isinstance(n, str) and textrules.check(n) is None][:QUALITY_NOTES]
    d["brief"] = _brief(d)
    return d
