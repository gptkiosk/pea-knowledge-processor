# Copyright 2026 The PEA knowledge processor authors
# SPDX-License-Identifier: Apache-2.0
"""Stage 2, first half: a publisher's index or feed read into one list of entries.

Three adapters: an agent index (`agent.json`: "editions" with date, title, markdown and an optional transcript),
RSS or Atom (with `podcast:transcript`), and JSON Feed. Each returns a `Listing` or raises `AdapterError` with a typed
reason. Nothing here fetches anything; every address an entry carries is checked before it is kept.
"""
import datetime
import email.utils
import hashlib
import re
import xml.etree.ElementTree as ET

from . import jsonschema_lite, textrules
from .fetch import validate_url

MAXIMUM_ENTRIES = 2_000     # entries read from one feed; the rest are not looked at
NOTES_CHARS = 6_000         # show notes kept per entry, as plain text
_DATE = re.compile(r"^(\d{4})-(\d{2})-(\d{2})")
_ID_UNSAFE = re.compile(r"[^a-z0-9]+")


class AdapterError(Exception):
    """`code` is "format_changed" (not the shape this adapter reads) or "empty" (the right shape with nothing in it)."""

    def __init__(self, code, detail):
        super().__init__("%s: %s" % (code, detail))
        self.code, self.detail = code, detail


class Entry:
    __slots__ = ("key", "title", "date", "link", "duration", "tags", "summary", "notes", "transcripts")

    def __init__(self):
        self.key = ""            # what identifies the entry at the publisher: a guid, else its link
        self.title = ""
        self.date = ""           # YYYY-MM-DD
        self.link = ""           # the page to send a reader back to; a checked https address, or ""
        self.duration = None     # whole seconds
        self.tags = []
        self.summary = ""        # the publisher's own short description, plain text
        self.notes = ""          # the publisher's show notes, plain text, at most NOTES_CHARS
        self.transcripts = []    # (address, declared type), in the publisher's order

    @property
    def id(self):
        """Stable, safe in a file name, and the same on every run: the date and ten characters of a hash of the key."""
        return "%s-%s" % (self.date, hashlib.sha256(self.key.encode("utf-8", "replace")).hexdigest()[:10])


class Listing:
    def __init__(self):
        self.title = ""
        self.language = ""
        self.entries = []
        self.fingerprint = ""    # which parts the feed has: a change here is a change of shape
        self.notes = []          # plain sentences for the health report


def _fingerprint(keys):
    return ",".join(sorted(set(keys)))


def _describe(data):
    head = data[:600].decode("utf-8", "replace").strip().lower()
    if head.startswith("<!doctype html") or "<html" in head:
        return "a web page"
    if head.startswith("{") or head.startswith("["):
        return "JSON of another shape"
    if head.startswith("<"):
        return "XML of another shape"
    return "unreadable data" if head else "an empty file"


def _text(value, limit):
    return textrules.clean(value, limit) if isinstance(value, str) else ""


def _whole_seconds(value):
    """A length in whole seconds, or None: finite, not negative, under 100 hours. Accepts a number, "1234", "MM:SS" and "H:MM:SS"."""
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        seconds = value
    elif isinstance(value, str):
        parts = value.strip().split(":")
        if not 1 <= len(parts) <= 3 or not all(re.fullmatch(r"\d{1,6}(\.\d{1,3})?", p, re.ASCII) for p in parts):
            return None
        seconds = 0.0
        for p in parts:
            seconds = seconds * 60 + float(p)
    else:
        return None
    if not (seconds == seconds and 0 <= seconds < 360_000):
        return None
    return int(seconds)


def _date(value):
    """A calendar date YYYY-MM-DD from an RFC 822 date, an ISO 8601 date or time, or ""; the date is the one the
    publisher wrote (its own time zone), and it must be a real day."""
    if not isinstance(value, str) or not value.strip() or len(value) > 80:
        return ""
    value = value.strip()
    m = _DATE.match(value)
    try:
        if m:
            return datetime.date(int(m.group(1)), int(m.group(2)), int(m.group(3))).isoformat()
        parsed = email.utils.parsedate_to_datetime(value)
        return parsed.date().isoformat() if 1990 <= parsed.year <= 2200 else ""
    except (TypeError, ValueError, IndexError, OverflowError):
        return ""


def _tags(values):
    out = []
    for v in values:
        t = _ID_UNSAFE.sub("-", textrules.plain(v).lower() if isinstance(v, str) else "").strip("-")[:24].strip("-")
        if t and t not in out:
            out.append(t)
        if len(out) == 6:
            break
    return out


def _finish(listing, counted, what):
    """Drops entries that share a key (the first one wins), newest first, and says what was skipped."""
    seen, kept, twice = set(), [], 0
    for e in listing.entries:
        if e.id in seen:
            twice += 1
            continue
        seen.add(e.id)
        kept.append(e)
    kept.sort(key=lambda e: (e.date, e.id), reverse=True)
    listing.entries = kept
    if twice:
        listing.notes.append("%d %s skipped: the same id as an earlier one" % (twice, what))
    for why, n in sorted(counted.items()):
        listing.notes.append("%d %s skipped: %s" % (n, what, why))
    return listing


# --- agent.json ------------------------------------------------------------------------------------------------------
def parse_agent_index(data):
    try:
        root = jsonschema_lite.loads(data)
    except jsonschema_lite.NotJSON:
        raise AdapterError("format_changed", "expected an episode index (JSON), found %s" % _describe(data)) from None
    rows = root.get("editions") if isinstance(root, dict) else None
    if not isinstance(rows, list):
        raise AdapterError("format_changed", "expected an editions list, found %s" % _describe(data))
    if not rows:
        raise AdapterError("empty", "the episode index lists no episodes")
    listing, skipped, keys = Listing(), {}, ["editions"]
    show = root.get("show") if isinstance(root.get("show"), dict) else {}
    listing.title = _text(show.get("title"), 120)
    if listing.title:
        keys.append("show.title")
    for r in rows[:MAXIMUM_ENTRIES]:
        if not isinstance(r, dict):
            skipped["not an object"] = skipped.get("not an object", 0) + 1
            continue
        e = Entry()
        e.date = _date(r.get("date")) if isinstance(r.get("date"), str) and re.fullmatch(r"\d{4}-\d{2}-\d{2}", r["date"]) else ""
        e.title = _text(r.get("title"), 200)
        page = validate_url(r.get("html")) or validate_url(r.get("markdown"))
        missing = "date" if not e.date else "title" if not e.title else "html or markdown" if not page else None
        if missing:
            why = "'%s' missing" % missing
            skipped[why] = skipped.get(why, 0) + 1
            continue
        e.link, e.key = page, page
        e.summary = _text(r.get("teaser"), 400)
        minutes = r.get("durationMin")
        e.duration = _whole_seconds(minutes * 60) if isinstance(minutes, (int, float)) and not isinstance(minutes, bool) and minutes == minutes and abs(minutes) < 1e6 else None
        e.tags = _tags(r.get("tags") if isinstance(r.get("tags"), list) else [])
        transcript = validate_url(r.get("transcript"))
        if transcript:
            e.transcripts.append((transcript, "text/markdown"))
        listing.entries.append(e)
    if not listing.entries:
        worst = max(skipped.items(), key=lambda kv: kv[1])
        raise AdapterError("format_changed", "expected episodes with date, title and a page; %s in %d of %d" % (worst[0], worst[1], len(rows)))
    keys += ["date", "title", "page"]
    if any(e.transcripts for e in listing.entries):
        keys.append("transcript")
    listing.fingerprint = _fingerprint(keys)
    return _finish(listing, skipped, "episodes")


# --- RSS and Atom ----------------------------------------------------------------------------------------------------
def _local(tag):
    return tag.rsplit("}", 1)[-1].lower() if isinstance(tag, str) else ""


def _namespace(tag):
    return tag[1:].split("}", 1)[0].lower() if isinstance(tag, str) and tag.startswith("{") else ""


def _child_text(node, *names, namespace=None):
    for child in node:
        if _local(child.tag) in names and (namespace is None or namespace in _namespace(child.tag)):
            text = "".join(child.itertext())
            if text.strip():
                return text
    return ""


def parse_feed(data):
    """RSS 2.0, RSS 1.0 or Atom; a file that starts with "{" is read as a JSON Feed."""
    head = data[:600].decode("utf-8", "replace").strip().lower()
    if head.startswith("{"):
        return parse_json_feed(data)
    if not any(mark in head for mark in ("<rss", "<feed", "<rdf:rdf", "<channel", "<?xml")):
        raise AdapterError("format_changed", "expected an RSS or Atom feed, found %s" % _describe(data))
    # A feed needs no entity declarations; a file that brings its own is refused unread (entity expansion, outside files).
    if b"<!ENTITY" in data or b"<!entity" in data:
        raise AdapterError("format_changed", "expected an RSS or Atom feed, found XML that declares entities")
    try:
        root = ET.fromstring(data)
    except (ET.ParseError, ValueError, LookupError, RecursionError, MemoryError):
        raise AdapterError("format_changed", "expected readable feed entries, found broken XML") from None
    kind = _local(root.tag)
    if kind == "feed":
        channel, nodes = root, [n for n in root if _local(n.tag) == "entry"]
    elif kind in ("rss", "rdf"):
        channel = next((n for n in root if _local(n.tag) == "channel"), None)
        if channel is None:
            raise AdapterError("format_changed", "expected a channel in the feed, found none")
        nodes = [n for n in channel if _local(n.tag) == "item"] + [n for n in root if _local(n.tag) == "item"]
    else:
        raise AdapterError("format_changed", "expected an RSS or Atom feed, found XML of another shape")
    if not nodes:
        raise AdapterError("empty", "the feed has no entries")
    listing, skipped, keys = Listing(), {}, ["title", "link"]
    listing.title = _text(_child_text(channel, "title"), 120)
    listing.language = _child_text(channel, "language").strip()[:12]
    for node in nodes[:MAXIMUM_ENTRIES]:
        e = Entry()
        e.title = _text(_child_text(node, "title"), 200)
        link = ""
        for child in node:
            if _local(child.tag) == "link":
                if kind == "feed":
                    if child.get("rel", "alternate") == "alternate" and child.get("href"):
                        link = link or child.get("href")
                elif "itunes" not in _namespace(child.tag) and "atom" not in _namespace(child.tag):
                    link = link or (child.text or "")
        e.link = validate_url(link) or ""
        guid = _child_text(node, "guid", "id").strip()
        e.key = (guid or e.link)[:500]
        e.date = _date(_child_text(node, "pubdate", "published", "date") or _child_text(node, "updated"))
        missing = "title" if not e.title else "date" if not e.date else "guid and link" if not e.key else None
        if missing:
            why = "no %s" % missing
            skipped[why] = skipped.get(why, 0) + 1
            continue
        e.duration = _whole_seconds(_child_text(node, "duration", namespace="itunes").strip())
        e.tags = _tags([c.get("term") or c.get("text") or (c.text or "") for c in node if _local(c.tag) == "category"])
        short = _child_text(node, "summary", "subtitle") or _child_text(node, "description")
        long = _child_text(node, "encoded") or _child_text(node, "content") or _child_text(node, "description") or short
        e.notes = textrules.shorten(textrules.plain(long), NOTES_CHARS)
        e.summary = textrules.first_sentences(textrules.plain(short, 20_000), 400, most=3)
        for child in node:
            if _local(child.tag) == "transcript" and "podcast" in _namespace(child.tag):
                address = validate_url(child.get("url"))
                if address and len(e.transcripts) < 8:
                    e.transcripts.append((address, (child.get("type") or "").strip().lower()[:60]))
        listing.entries.append(e)
    if not listing.entries:
        worst = max(skipped.items(), key=lambda kv: kv[1])
        raise AdapterError("format_changed", "expected entries with a title, a date and a link; %s in %d of %d" % (worst[0], worst[1], len(nodes)))
    if any(e.transcripts for e in listing.entries):
        keys.append("podcast:transcript")
    if any(len(e.notes) >= 1_500 for e in listing.entries):
        keys.append("content")
    listing.fingerprint = _fingerprint(keys)
    return _finish(listing, skipped, "entries")


# --- JSON Feed -------------------------------------------------------------------------------------------------------
def parse_json_feed(data):
    try:
        root = jsonschema_lite.loads(data)
    except jsonschema_lite.NotJSON:
        raise AdapterError("format_changed", "expected a JSON Feed, found %s" % _describe(data)) from None
    if not isinstance(root, dict) or "jsonfeed.org" not in str(root.get("version", "")) or not isinstance(root.get("items"), list):
        raise AdapterError("format_changed", "expected a JSON Feed (version and items), found %s" % _describe(data))
    if not root["items"]:
        raise AdapterError("empty", "the feed has no entries")
    listing, skipped = Listing(), {}
    listing.title = _text(root.get("title"), 120)
    listing.language = root["language"].strip()[:12] if isinstance(root.get("language"), str) else ""
    for r in root["items"][:MAXIMUM_ENTRIES]:
        if not isinstance(r, dict):
            skipped["not an object"] = skipped.get("not an object", 0) + 1
            continue
        e = Entry()
        body = r.get("content_text") if isinstance(r.get("content_text"), str) else r.get("content_html") if isinstance(r.get("content_html"), str) else ""
        e.title = _text(r.get("title"), 200) or textrules.clean(body, 80)
        e.link = validate_url(r.get("url")) or validate_url(r.get("external_url")) or ""
        e.key = (str(r.get("id")) if isinstance(r.get("id"), (str, int)) and not isinstance(r.get("id"), bool) else e.link)[:500]
        e.date = _date(r.get("date_published")) or _date(r.get("date_modified"))
        missing = "title" if not e.title else "date" if not e.date else "id and url" if not e.key else None
        if missing:
            why = "no %s" % missing
            skipped[why] = skipped.get(why, 0) + 1
            continue
        e.notes = textrules.shorten(textrules.plain(body), NOTES_CHARS)
        e.summary = _text(r.get("summary"), 400) or textrules.first_sentences(e.notes, 400, most=3)
        e.tags = _tags(r.get("tags") if isinstance(r.get("tags"), list) else [])
        for a in r.get("attachments") if isinstance(r.get("attachments"), list) else []:
            if isinstance(a, dict):
                e.duration = e.duration if e.duration is not None else _whole_seconds(a.get("duration_in_seconds"))
        listing.entries.append(e)
    if not listing.entries:
        worst = max(skipped.items(), key=lambda kv: kv[1])
        raise AdapterError("format_changed", "expected items with a title, a date and a url; %s in %d of %d" % (worst[0], worst[1], len(root["items"])))
    listing.fingerprint = _fingerprint(["version", "items", "title", "url"])
    return _finish(listing, skipped, "items")


ADAPTERS = {"agent_index": parse_agent_index, "feed": parse_feed, "json_feed": parse_json_feed}
