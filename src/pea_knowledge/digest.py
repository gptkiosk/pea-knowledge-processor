# Copyright 2026 The PEA knowledge processor authors
# SPDX-License-Identifier: Apache-2.0
"""Stage 3: the digest of one item. This file holds the shape, its limits and the extractive digest.

The extractive digest uses no model: it picks sentences that are already in the transcript (or, without one, in the
publisher's notes), so the same input always gives the same digest and the pipeline works with no key at all.
`model_digest.py` adds the optional model path; whatever it returns is forced through `enforce` here.

Format 1.1 adds five members (docs/FORMAT.md, "What 1.1 adds"): `guests`, `mentioned_resources`, `chapters`,
`snippable_moments` and `recap_cards`. They follow the same rule as everything else: a name, a time or a quote is in
the digest only when it is in the publisher's notes, marks or transcript; nothing is made up to fill a member.
"""
import bisect
import hashlib
import re
from collections import Counter

from . import FORMAT_VERSION, jsonschema_lite, textrules
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
# Format 1.1. A reader of 1.0 ignores these members; the size limit of the file is the same.
GUESTS, GUEST_NAME_CHARS, GUEST_ROLE_CHARS = 6, 80, 140
RESOURCES, RESOURCE_NAME_CHARS, RESOURCE_CONTEXT_CHARS = 8, 80, 140
RESOURCE_KINDS = ("book", "paper", "tool", "product", "site", "media", "other")
CHAPTERS, CHAPTER_TITLE_CHARS, CHAPTER_OWN_TITLE_CHARS = 20, 100, 60
CHAPTER_ORIGINS = ("publisher", "transcript", "model")
MOMENTS, MOMENT_LABEL_CHARS = 5, 100
RECAP_CARDS, RECAP_QUESTION_CHARS, RECAP_ANSWER_CHARS = 3, 140, 200
LINK_KINDS = ("episode", "show")
DIGEST_REVISION = 2                    # raised when the digest code changes in a way that should rebuild kept digests
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
        "link_kind": item.get("link_kind", "episode"),
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
        "guests": [],
        "mentioned_resources": [],
        "chapters": [],
        "snippable_moments": [],
        "recap_cards": [],
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


def _stretch_starts(points, units):
    """For each picked point, where its part of the transcript starts: the first line for the first point, and for
    every other point the first line after the one the point before it is in. A point in the same line as the one
    before it has no part of its own (the same start again, which `transcript_chapters` leaves out)."""
    out = []
    for n, u in enumerate(points):
        if n == 0:
            out.append(units[0].at)
            continue
        first = next((c for c in units if c.segment > points[n - 1].segment), None)
        out.append(first.at if first is not None and first.segment <= u.segment else out[-1])
    return out


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


def _own_moments(d):
    """The snippable moments whose words are not already elsewhere in the digest: only these cost excerpt characters."""
    held = {q["text"] for q in d["quotes"]} | {k["point"] for k in d["talking_points"]} | {(d["strongest_claim"] or {}).get("text")}
    return [m for m in d.get("snippable_moments", []) if m["quote"] not in held]


def _taken_chars(d):
    return (sum(len(m["quote"]) for m in _own_moments(d)) + sum(len(k["point"]) + len(k["ask"] or "") for k in d["talking_points"]) + sum(len(q["text"]) for q in d["quotes"])
            + sum(len(n["context"]) for n in d["numbers"]) + sum(len(q) for q in d["follow_ups"]) + sum(len(c) for c in d["contested"])
            + sum(len(g["gloss"] or "") for g in d["glossary"] if g["gloss"] != "a speaker in this episode")
            + len((d["strongest_claim"] or {}).get("text", "")))


def within(d, budget):
    """Keeps the words taken from a transcript inside `budget` characters. What goes first: numbers, contested lines,
    follow-up questions, glosses, quotes, then talking points down to the five a digest should have."""
    while _taken_chars(d) > budget and _own_moments(d):
        d["snippable_moments"].remove(_own_moments(d)[-1])
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
    while _taken_chars(d) > budget and _own_moments(d):   # a moment whose quote was just dropped stands alone now
        d["snippable_moments"].remove(_own_moments(d)[-1])
    return d


# --- Format 1.1: guests, mentioned resources, chapters, snippable moments, recap cards ---------------------------------
_NAME = r"[A-Z][a-zA-Z'’\-]+(?:\s+(?:[A-Z]\.\s+|(?:de|van|von|del|bin|al|la|le)\s+)?[A-Z][a-zA-Z'’\-]+){1,3}"
_TITLE_WORD = r"(?:(?:Dr|Prof|Professor|Sen|Senator|Rep|Gov|Sir|Dame|Mr|Mrs|Ms)\.?\s+)?"
_GUEST_CUE = re.compile(r"\b(?:[Jj]oined by|[Gg]uests?(?: today| this week)?(?: is| are|:)?|[Ii]nterview(?:s|ed|ing)?(?: with)?|[Cc]onversation with|[Tt]alks? (?:to|with)"
                        r"|[Ss]peaks? (?:to|with)|[Ss]its? down with|[Ss]at down with|[Ff]eaturing|[Ww]elcomes?|[Cc]hat(?:s|ted)? with)\s+" + _TITLE_WORD + "(" + _NAME + ")"
                        r"(?:\s+and\s+" + _TITLE_WORD + "(" + _NAME + "))?")
_TITLE_GUEST = (re.compile(r"\((?:with|feat\.?|featuring)\s+" + _TITLE_WORD + "(" + _NAME + r")\)"),
                re.compile(r"\s[|—–]\s+" + _TITLE_WORD + "(" + _NAME + r")(?=$|,|\s\()"),
                re.compile("^" + _TITLE_WORD + "(" + _NAME + r")\s+on\s"),
                re.compile("^" + _TITLE_WORD + "(" + _NAME + r"):\s"))
_ROLE_AFTER = r"(?:\s*,\s+|\s+\(|\s+is\s+(?=the\s|an?\s))((?:the\s+|an?\s+)?(?:[a-z][a-z\-]+|CEO|CTO|CFO|COO|VP)\b[^,.;:!?()]{3,%d})(?=[,.;:!?()]|$)" % (GUEST_ROLE_CHARS - 10)
_RESOURCE_CUE = re.compile(r"\b(book|paper|essay|novel|memoir|article|report|study|documentary|film|movie|podcast|newsletter|blog|app|tool|library"
                           r"|framework|plugin|product|game|website|site)s?,?\s+(?:is\s+)?(?:called|titled|named|entitled)\s+[\"“'‘]?(?=[A-Z0-9])")
_RESOURCE_KIND = {"book": "book", "novel": "book", "memoir": "book", "paper": "paper", "essay": "paper", "article": "paper", "report": "paper", "study": "paper",
                  "documentary": "media", "film": "media", "movie": "media", "podcast": "media", "newsletter": "media", "blog": "media", "app": "tool",
                  "tool": "tool", "library": "tool", "framework": "tool", "plugin": "tool", "product": "product", "game": "product", "website": "site", "site": "site"}
_DOMAIN_LIKE = re.compile(r"(?i)[a-z0-9]\.[a-z]{2,}(?:[/?#]|\b)")


def _mentions(name, text):
    return re.search(r"(?<![A-Za-z0-9])%s(?![A-Za-z0-9])" % re.escape(name), text, re.I) is not None


def _person_like(name):
    tokens = name.split()
    return 2 <= len(tokens) <= 4 and not any(t.rstrip(".") in _NOT_NAMES for t in tokens) and usable(name) and len(name) <= GUEST_NAME_CHARS


def role_in(name, text):
    """What `text` itself says the person is, right after the name ("Ada Reed, founder of Quay Labs, ..."), or None.
    The role is always a piece of `text`: nothing is written for it."""
    m = re.search(re.escape(name) + _ROLE_AFTER, text)
    role = " ".join(m.group(1).split()).rstrip(" ,") if m else ""
    return role if 4 <= len(role) <= GUEST_ROLE_CHARS and usable(role) else None


def guests(item, speakers=(), hosts=()):
    """The guests of an item: the people the publisher marks as guests, then names the title or the notes introduce as
    one ("joined by ...", "(with ...)"). A name is never made up: each comes from the publisher's own words."""
    words = " ".join(t for t in (item.get("summary", ""), item.get("notes", "")) if t)
    hosts = {n.lower() for n, role in item.get("people", []) if role != "guest"} | {h.lower() for h in hosts}
    out, seen = [], set()

    def add(name):
        name = " ".join(name.split())
        if name.lower() in seen or name.lower() in hosts or not _person_like(name):
            return
        seen.add(name.lower())
        out.append({"name": name, "role": role_in(name, words)})

    for name, role in item.get("people", []):
        if role == "guest" and usable(name) and len(name) <= GUEST_NAME_CHARS and name.lower() not in seen and name.lower() not in hosts:
            seen.add(name.lower())
            out.append({"name": name, "role": role_in(name, words)})
    for m in _GUEST_CUE.finditer(item["title"] + ". " + words):
        for name in m.groups():
            if name:
                add(name)
    known = words + " " + " ".join(speakers)
    for n, pattern in enumerate(_TITLE_GUEST):
        m = pattern.search(item["title"])
        if m and (n in (0, 3) or _mentions(m.group(1), known)):
            add(m.group(1))
    return out[:GUESTS]


def _resource_name(text):
    """The capitalised name that `text` starts with ("Thinking, Fast and Slow by ..." gives the title), or ""."""
    small = r"of|the|and|for|in|to|a|an|on|with|at|from|or|as|is"
    m = re.match(r"[\"“'‘]?((?:[A-Z0-9][\w'’&\-]*)(?:,?\s+[A-Z0-9][\w'’&\-]*|\s+(?:%s)(?![\w'’\-])){0,9})" % small, text)
    if not m:
        return ""
    tokens = m.group(1).split()
    for n, t in enumerate(tokens):   # "Django MCPX and I've ..." ends before the speaker goes on
        if n and t.strip(",").split("'")[0].split("’")[0] in ("I", "We", "It", "He", "She", "They", "You", "But", "So", "That", "This"):
            tokens = tokens[:n]
            break
    while tokens and tokens[-1].strip(",") in small.split("|") + ["by"]:
        tokens = tokens[:-1]
    return " ".join(tokens).strip(" ,.'’\"”")


_SMALL_WORDS = frozenset("of the and for in to a an on with at from or as is by vs".split())
_NOT_A_RESOURCE = re.compile(r"(?i)\b(?:membership|members|courses?|sponsors?|subscribe|newsletter|patreon|merch|donate|fan mail|discount|coupon|promo)\b")
_SPONSOR = re.compile(r"(?i)\b(?:sponsor(?:s|ed)?|brought to you by|promo code|discount|% off|free trial|use code|support the show|thanks to our)\b")


def _titled(name):
    """True for a name written as names and titles are: every word starts with a capital or a digit, small words
    ("of", "the") only in between. "The Power Law" is; "says Bloomberg in a paid article" is not."""
    tokens = name.split()
    if not tokens or tokens[0].lower() in _SMALL_WORDS and len(tokens) == 1 or tokens[-1].lower() in _SMALL_WORDS:
        return False
    return all(t[:1].isupper() or t[:1].isdigit() or (t.lower() in _SMALL_WORDS and 0 < n) or (n == 0 and t.lower() == "the") for n, t in enumerate(tokens)) \
        and any(t[:1].isupper() for t in tokens)


def resources(item, units=None, exclude=()):
    """Books, papers, tools and sites that are named: the names the publisher's notes link to (the addresses are never
    kept), and what a speaker introduces as "a book called ...". With a transcript, a linked name is kept only when it
    is also said, and points to where; a context line comes from the notes only."""
    note_sentences = textrules.sentences(item.get("notes", ""))
    skip = {e.lower() for e in exclude} | {item["title"].lower()}
    out, seen = [], set()

    def add(name, kind, at):
        low = name.lower()
        if low in seen or low in skip or not 3 <= len(name) <= RESOURCE_NAME_CHARS or _DOMAIN_LIKE.search(name) or not usable(name):
            return
        seen.add(low)
        said = next((s for s in note_sentences if _mentions(name, s) and usable(s) and s.strip() != name), None)
        if kind is None:   # a linked name: what it is only when the notes say so right before it ("the book The Power Law")
            if not _titled(name) or _NOT_A_RESOURCE.search(name) or (said and _SPONSOR.search(said)):
                seen.discard(low)
                return
            cue = re.search(r"(?i)\b(book|novel|memoir|paper|essay|article|report|study|documentary|film|newsletter|app|tool|library|framework|website)s?\W{1,4}(?:[a-z]+\W{1,3}){0,2}$",
                            said[:said.lower().find(low)] if said and low in said.lower() else "")
            kind = _RESOURCE_KIND[cue.group(1).lower()] if cue else "other"
        out.append({"name": name, "kind": kind, "context": textrules.shorten(said, RESOURCE_CONTEXT_CHARS) if said else None, "at": at})

    for u in units or []:
        for m in _RESOURCE_CUE.finditer(u.text):
            name = _resource_name(u.text[m.end():])
            if name and usable(u.text):
                add(name, _RESOURCE_KIND[m.group(1).lower()], u.at)
    for name in item.get("resources", []):
        if units is None:
            add(name, None, dict(NOWHERE))
        else:
            first = next((u for u in units if _mentions(name, u.text)), None)
            if first is not None:
                add(name, None, first.at)
    return out[:RESOURCES]


def _segment_at(transcript, second):
    """The number of the segment that is running at `second`, or None when the transcript has no times."""
    starts = [s.start for s in transcript.segments]
    if not starts or any(t is None for t in starts) or starts != sorted(starts):
        return None
    return max(0, bisect.bisect_right(starts, second) - 1)


def publisher_chapters(item, transcript=None):
    """The publisher's own chapter marks as chapters. A mark must lie inside the item: before its end when the length
    is known, and not after the last line of a timed transcript."""
    marks = [(start, title) for start, title in item.get("chapters", []) if usable(title)]
    length = item.get("duration_seconds")
    last = None
    if transcript is not None and transcript.timed and transcript.partial is None and transcript.segments:
        last = max((s.start for s in transcript.segments if s.start is not None), default=None)
    marks = [(s, t) for s, t in marks if (length is None or s < max(length, 1)) and (last is None or s <= last + 60) and s <= pt.LATEST_SECOND]
    if len(marks) > CHAPTERS:   # a long list is thinned evenly, so the chapters still cover the whole item
        marks = [marks[i * len(marks) // CHAPTERS] for i in range(CHAPTERS)]
    out = []
    for n, (start, title) in enumerate(marks):
        end = marks[n + 1][0] if n + 1 < len(marks) else (length if length is not None and length > start else None)
        segment = _segment_at(transcript, start) if transcript is not None and transcript.timed else None
        out.append({"title": textrules.shorten(title, CHAPTER_TITLE_CHARS), "start_seconds": start, "end_seconds": end, "segment": segment, "origin": "publisher"})
    return out if len(out) >= 2 else []


def transcript_chapters(d, starts, length=None):
    """Chapters cut from a timed transcript when the publisher marks none: one per talking point, starting where that
    point's stretch of the transcript starts, titled with the opening words of the point (text the digest already holds)."""
    rows = []
    for at, p in zip(starts, d["talking_points"]):
        if at["time_seconds"] is not None and (not rows or at["time_seconds"] > rows[-1][0]["time_seconds"]):
            rows.append((at, p))
    if len(rows) < 3:
        return []
    out = []
    for n, (at, p) in enumerate(rows):
        end = rows[n + 1][0]["time_seconds"] if n + 1 < len(rows) else (length if length is not None and length > at["time_seconds"] else None)
        out.append({"title": textrules.shorten(p["point"], CHAPTER_OWN_TITLE_CHARS), "start_seconds": at["time_seconds"], "end_seconds": end,
                    "segment": at["segment"], "origin": "transcript"})
    return out


def moments(d, transcript, soundbites=(), speakers=None, extra=()):
    """Up to five passages worth keeping, best first, each an exact piece of one transcript segment with its time.
    First what the publisher itself points out (a soundbite), then the digest's quotes, its strongest claim and the
    talking points that are whole sentences. `extra` are passages already checked against the transcript."""
    segments = transcript.segments
    pool = list(extra) + [{"quote": q["text"], "speaker": q["speaker"], "at": q["at"]} for q in d["quotes"] if q["exact"]]
    if d["provenance"]["method"] == "extractive":
        claim = d["strongest_claim"]
        rest = ([claim] if claim else []) + [{"text": p["point"], "at": p["at"]} for p in d["talking_points"]]
        pool += [{"quote": r["text"], "speaker": (speakers or {}).get(r["text"]), "at": r["at"]} for r in rest if len(r["text"]) <= QUOTE_CHARS]
    kept, seen, labelled = [], set(), set()
    for m in pool:
        number = m["at"]["segment"]
        if number is None or number >= len(segments) or m["quote"] in seen or m["quote"] not in segments[number].text or pt.is_ad(segments[number].text):
            continue
        seen.add(m["quote"])
        time = m["at"]["time_seconds"]
        bite = next((b for b in soundbites if time is not None and b[0] - 5 <= time <= b[0] + b[1]), None)
        pointed = bite is not None
        label = bite[2] if bite and bite[2] and bite[2] not in labelled else None   # a soundbite's title names one moment
        labelled.add(label)
        later = next((s.start for s in segments[number + 1:] if s.start is not None and time is not None and s.start > time), None)
        kept.append((0 if pointed else 1, len(kept), {"quote": m["quote"], "speaker": m["speaker"], "at": m["at"], "end_seconds": later,
                                                         "label": label if label and usable(label) else None}))
    return [m for _, _, m in sorted(kept, key=lambda k: k[:2])][:MOMENTS]


def recap_cards(d):
    """Three short question and answer pairs for a daily recap, made only from text the digest already holds."""
    cards = [("What is this one about?", d["about"])]
    if d["guests"]:
        cards.append(("Who is the guest?", d["guests"][0]["name"] + (", " + d["guests"][0]["role"] if d["guests"][0]["role"] else "")))
    if d["numbers"]:
        cards.append(("What does the figure %s refer to?" % d["numbers"][0]["value"], d["numbers"][0]["context"]))
    said = next((q for q in d["quotes"] if q["exact"] and q["speaker"] and len(q["text"]) <= RECAP_QUESTION_CHARS - 12), None)
    if said:
        cards.append(("Who said: “%s”" % said["text"], said["speaker"]))
    gloss = next((g for g in d["glossary"] if g["gloss"] and g["gloss"] != "a speaker in this episode"), None)
    if gloss:
        cards.append(("Who or what is %s?" % gloss["term"], gloss["gloss"]))
    if d["strongest_claim"]:
        cards.append(("What is the strongest claim made?", d["strongest_claim"]["text"]))
    if d["contested"]:
        cards.append(("What is still disputed or unclear?", d["contested"][0]))
    out = []
    for question, answer in cards:
        question, answer = textrules.shorten(question, RECAP_QUESTION_CHARS), textrules.shorten(answer, RECAP_ANSWER_CHARS)
        if textrules.check(question) is None and textrules.check(answer) is None and answer not in (a for _, a in out):
            out.append((question, answer))
    return [{"question": q, "answer": a} for q, a in out[:RECAP_CARDS]]


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
        stretch_starts = _stretch_starts(points, units)
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
        d["guests"] = guests(item, transcript.speakers, source.get("hosts", ()))
        d["mentioned_resources"] = resources(item, [u for u in units if usable(u.text)],
                                             [g["name"] for g in d["guests"]] + list(transcript.speakers) + [source["name"]] + list(source.get("hosts", ())))
        if budget is not None:
            within(d, budget)
        d["chapters"] = publisher_chapters(item, transcript) or (transcript_chapters(d, stretch_starts, item.get("duration_seconds")) if transcript.timed else [])
        d["snippable_moments"] = moments(d, transcript, item.get("soundbites", ()), {u.text: u.speaker if u.speaker and usable(u.speaker) else None for u in points + claims[:1]})
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
        d["guests"] = guests(item, (), source.get("hosts", ()))
        d["mentioned_resources"] = resources(item, None, [g["name"] for g in d["guests"]] + [source["name"]] + list(source.get("hosts", ())))
        d["chapters"] = publisher_chapters(item)
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
    d["link_kind"] = d.get("link_kind") if d.get("link_kind") in LINK_KINDS else "episode"
    seen, people = set(), []
    for g in d.get("guests") or []:
        if isinstance(g, dict) and text_ok(g.get("name"), GUEST_NAME_CHARS) and g["name"].lower() not in seen:
            seen.add(g["name"].lower())
            people.append({"name": g["name"], "role": optional(g.get("role"), GUEST_ROLE_CHARS)})
    d["guests"] = people[:GUESTS]
    seen, named = set(), []
    for r in d.get("mentioned_resources") or []:
        if isinstance(r, dict) and text_ok(r.get("name"), RESOURCE_NAME_CHARS) and r.get("kind") in RESOURCE_KINDS and at_ok(r.get("at")) \
                and r["name"].lower() not in seen and not _DOMAIN_LIKE.search(r["name"]):
            seen.add(r["name"].lower())
            named.append({"name": r["name"], "kind": r["kind"], "context": optional(r.get("context"), RESOURCE_CONTEXT_CHARS), "at": r["at"]})
    d["mentioned_resources"] = named[:RESOURCES]

    def second(v, nullable=False):
        return (nullable and v is None) or (isinstance(v, int) and not isinstance(v, bool) and 0 <= v <= pt.LATEST_SECOND)

    chapters, last = [], -1
    for c in d.get("chapters") or []:
        if isinstance(c, dict) and text_ok(c.get("title"), CHAPTER_TITLE_CHARS) and second(c.get("start_seconds")) and c["start_seconds"] > last \
                and second(c.get("end_seconds"), True) and (c["end_seconds"] is None or c["end_seconds"] > c["start_seconds"]) \
                and at_ok({"time_seconds": None, "segment": c.get("segment")}) and c.get("origin") in CHAPTER_ORIGINS:
            if chapters and chapters[-1]["end_seconds"] is not None and chapters[-1]["end_seconds"] > c["start_seconds"]:
                chapters[-1]["end_seconds"] = c["start_seconds"]
            chapters.append({"title": c["title"], "start_seconds": c["start_seconds"], "end_seconds": c["end_seconds"], "segment": c["segment"], "origin": c["origin"]})
            last = c["start_seconds"]
    d["chapters"] = chapters[:CHAPTERS]
    seen, kept = set(), []
    for m in d.get("snippable_moments") or []:
        if isinstance(m, dict) and text_ok(m.get("quote"), QUOTE_CHARS) and at_ok(m.get("at")) and m["at"]["segment"] is not None and m["quote"] not in seen \
                and second(m.get("end_seconds"), True) and d.get("basis") == "transcript":
            seen.add(m["quote"])
            kept.append({"quote": m["quote"], "speaker": optional(m.get("speaker"), SPEAKER_CHARS), "at": m["at"], "end_seconds": m["end_seconds"],
                         "label": optional(m.get("label"), MOMENT_LABEL_CHARS)})
    d["snippable_moments"] = kept[:MOMENTS]
    d["tone"] = d.get("tone") if d.get("tone") in TONES else "unknown"
    d["quality"]["notes"] = [textrules.shorten(n, QUALITY_NOTE_CHARS) for n in d["quality"]["notes"] if isinstance(n, str) and textrules.check(n) is None][:QUALITY_NOTES]
    d["brief"] = _brief(d)
    d["recap_cards"] = recap_cards(d)
    # The file has one size limit. What 1.1 added gives way first, longest list first; then the lists of 1.0.
    for field in ("chapters", "mentioned_resources", "guests", "snippable_moments", "glossary", "numbers", "quotes", "talking_points"):
        while d[field] and len(jsonschema_lite.dumps(d).encode("utf-8")) > DIGEST_BYTES:
            d[field].pop()
    return d
