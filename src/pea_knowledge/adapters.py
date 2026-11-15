# Copyright 2026 The PEA knowledge processor authors
# SPDX-License-Identifier: Apache-2.0
"""Stage 2, first half: a publisher's index or feed read into one list of entries.

Three adapters: an agent index (`agent.json`: "editions" with date, title, markdown and an optional transcript),
RSS or Atom (with `podcast:transcript`), and JSON Feed. Each returns a `Listing` or raises `AdapterError` with a typed
reason. Nothing here fetches anything; every address an entry carries is checked before it is kept.

An entry's `link` is the publisher's page for that one item. It is looked for in this order: the entry's own link, a
guid that is a permanent link, an Atom alternate link, a page that follows from the enclosure by a known host's rule,
an HTML transcript page. When none exists `link` is "" and the pipeline falls back to the show's site and says so
(`link_kind: "show"`). The id never depends on that fallback.

What the publisher itself marks up is read here too, as plain data for the digest: people (`podcast:person`), chapter
marks (`psc:chapter`, a `podcast:chapters` address, or lines in the notes that start with a time), soundbites
(`podcast:soundbite`) and the names the notes link to. The addresses of those links are dropped; only the names stay.
"""
import datetime
import email.utils
import hashlib
import re
import xml.etree.ElementTree as ET

from . import htmlpage, jsonschema_lite, textrules
from .fetch import validate_url

MAXIMUM_ENTRIES = 2_000     # entries read from one feed; the rest are not looked at
NOTES_CHARS = 6_000         # show notes kept per entry, as plain text
NOTE_LINKS = 80             # links of an entry's notes that are looked at for a transcript page
_DATE = re.compile(r"^(\d{4})-(\d{2})-(\d{2})")
_ID_UNSAFE = re.compile(r"[^a-z0-9]+")


class AdapterError(Exception):
    """`code` is "format_changed" (not the shape this adapter reads) or "empty" (the right shape with nothing in it)."""

    def __init__(self, code, detail):
        super().__init__("%s: %s" % (code, detail))
        self.code, self.detail = code, detail


class Entry:
    __slots__ = ("key", "title", "date", "link", "duration", "tags", "summary", "notes", "transcripts", "people", "chapters",
                 "chapters_url", "soundbites", "resources", "links")

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
        self.people = []         # (name, role) as the publisher marks them: "host", "guest", ...
        self.chapters = []       # (start in whole seconds, title): the publisher's own chapter marks, in order
        self.chapters_url = ""   # a podcast:chapters JSON file, when the feed has no inline marks; a checked address, or ""
        self.soundbites = []     # (start, length, title or ""): the passages the publisher itself points out
        self.resources = []      # names the notes link to (books, tools, sites); the addresses are not kept
        self.links = []          # (address, label, words before it) of the notes' links: only read to find a transcript page, never published

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


# --- What the publisher marks up in an entry: chapters, people, linked names ---------------------------------------------
PEOPLE, CHAPTER_MARKS, SOUNDBITES, RESOURCES = 12, 60, 8, 30
NAME_CHARS, CHAPTER_TITLE_CHARS = 80, 100
_MARKUP_CHARS = 200_000       # of an entry's notes, as written, that are looked at for chapter lines and linked names
_LINE_BREAK = re.compile(r"(?i)<br\s*/?>|</?(?:p|li|div|h[1-6]|tr|ul|ol|blockquote)\b[^<>]{0,300}>|[\r\n]+")
_CHAPTER_LINE = re.compile(r"^[(\[]?(\d{1,3}:\d{2}(?::\d{2})?)[)\]]?\s*[-–—:|]*\s*(\S.*)$")
_ANCHOR = re.compile(r"(?is)<a\b[^<>]{0,1500}>(.{1,300}?)</a\s*>")
_DOMAIN_LIKE = re.compile(r"(?i)[a-z0-9]\.[a-z]{2,}(?:[/?#]|\b)")
_GENERIC_LINK = frozenset("""here link links this website site web homepage home page subscribe follow twitter x youtube instagram linkedin
facebook tiktok threads bluesky mastodon spotify apple podcasts apple-podcasts overcast pocket-casts rss feed patreon discord slack
email e-mail newsletter transcript transcripts sponsor sponsors privacy policy terms learn more read watch listen click support
donate merch shop store episode video audio download contact about login signup sign up now today free trial full show notes
chapters credits music by and the a an of on to for our us me my your""".split())
# A page for one episode that follows from its enclosure, for hosts whose feeds carry no <link>. host rule -> page.
_ENCLOSURE_PAGES = (
    (re.compile(r"(?:^|/)www\.buzzsprout\.com/(\d{1,12})/episodes/(\d{1,12}(?:-[a-z0-9-]{1,200})?)\.mp3(?:\?|$)"), "https://www.buzzsprout.com/%s/episodes/%s"),
)


def _clock(text):
    """"12:34" or "1:02:03" as whole seconds, or None."""
    if not isinstance(text, str) or not re.fullmatch(r"\d{1,3}(?::\d{2}){1,2}(?:\.\d{1,3})?", text.strip(), re.ASCII):
        return None
    parts = text.strip().split(".")[0].split(":")
    if int(parts[-1]) > 59 or (len(parts) == 3 and int(parts[1]) > 59):
        return None
    return _whole_seconds(text.strip())


def _lines(markup):
    """An entry's notes as written, split where the publisher broke the line, each line as plain text."""
    out = []
    for piece in _LINE_BREAK.split(markup[:_MARKUP_CHARS])[:1_500]:
        line = textrules.plain(piece, 2_000)
        if line:
            out.append(line)
    return out


def _notes(lines, has_chapters):
    """Show notes as one line of plain text, at most NOTES_CHARS. Each line the publisher wrote ends as a sentence, so
    a list does not run together; the lines of a chapter list are left out (they are read as chapters instead)."""
    kept = []
    for line in lines:
        if has_chapters and _CHAPTER_LINE.match(line):
            continue
        kept.append(line if line[-1] in ".!?…:;,\"”’')]" else line + ".")
    return textrules.shorten(" ".join(kept), NOTES_CHARS)


def _marks(pairs):
    """Chapter marks as (seconds, title), in order: the times must not go back, a title is checked text, at most CHAPTER_MARKS."""
    out, last = [], -1
    for start, title in pairs:
        title = textrules.clean(title, CHAPTER_TITLE_CHARS) if isinstance(title, str) else ""
        if start is None or start < last or not title or (out and start == last) or textrules.looks_like_instruction(title):
            continue
        out.append((start, title))
        last = start
        if len(out) == CHAPTER_MARKS:
            break
    return out


def chapter_lines(lines):
    """The chapter marks written into show notes: lines that start with a time ("(02:13) - Title", "1:02:03 Title").
    Fewer than three such lines are not a chapter list."""
    found = []
    for line in lines:
        m = _CHAPTER_LINE.match(line)
        if m and _clock(m.group(1)) is not None:
            found.append((_clock(m.group(1)), m.group(2).strip(" -–—:|")))
    marks = _marks(found)
    return marks if len(marks) >= 3 else []


def linked_names(markup):
    """The names an entry's notes link to, in order, without the addresses. A name that is itself an address, a bare
    domain, a handle, a time or a word like "here" is left out."""
    out, seen = [], set()
    for m in _ANCHOR.finditer(markup[:_MARKUP_CHARS]):
        name = textrules.clean(m.group(1), 200).strip(" .,:;-–—|\"'“”")
        low = name.lower()
        if not 3 <= len(name) <= NAME_CHARS or low in seen or len(name.split()) > 8:
            continue
        if _DOMAIN_LIKE.search(name) or "@" in name or _CHAPTER_LINE.match(name) or not any(c.isupper() or c.isdigit() for c in name) or not any(c.isalpha() for c in name):
            continue
        if all(w.strip(".,:;!?()") in _GENERIC_LINK for w in low.split()) or textrules.looks_like_instruction(name):
            continue
        seen.add(low)
        out.append(name)
        if len(out) == RESOURCES:
            break
    return out


def chapters_file(data):
    """A podcast:chapters JSON file ({"chapters": [{"startTime": seconds, "title": "..."}]}) as chapter marks; [] when
    it is anything else. Images and addresses in it are not read."""
    try:
        root = jsonschema_lite.loads(data)
    except jsonschema_lite.NotJSON:
        return []
    rows = root.get("chapters") if isinstance(root, dict) else None
    if not isinstance(rows, list):
        return []
    pairs = []
    for r in rows[:500]:
        if isinstance(r, dict) and r.get("toc") is not False:
            start = r.get("startTime")
            pairs.append((_whole_seconds(start) if not isinstance(start, str) else _clock(start), r.get("title")))
    return _marks(sorted((p for p in pairs if p[0] is not None), key=lambda p: p[0]))


def _enclosure_page(address):
    for rule, page in _ENCLOSURE_PAGES:
        m = rule.search(address or "")
        if m:
            return validate_url(page % m.groups()) or ""
    return ""


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
        guid_node = next((c for c in node if _local(c.tag) in ("guid", "id")), None)
        guid = _child_text(node, "guid", "id").strip()
        html_transcript = enclosure = alternate = ""
        for child in node:
            name = _local(child.tag)
            if name == "enclosure":
                enclosure = enclosure or (child.get("url") or "")
            elif name == "link" and kind != "feed" and "atom" in _namespace(child.tag) and child.get("rel") == "alternate" and "html" in (child.get("type") or "html"):
                alternate = alternate or (child.get("href") or "")
            elif name == "transcript" and "podcast" in _namespace(child.tag) and "html" in (child.get("type") or "").lower():
                html_transcript = html_transcript or (child.get("url") or "")
        if not e.link and kind != "feed" and guid_node is not None and (guid_node.get("isPermaLink") or "true").strip().lower() != "false":
            e.link = validate_url(guid) or ""     # in RSS a guid is a permanent link unless it says otherwise
        e.link = e.link or validate_url(alternate) or _enclosure_page(enclosure) or validate_url(html_transcript) or ""
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
        e.summary = textrules.first_sentences(textrules.plain(short, 20_000), 400, most=3)
        inline = []
        for child in node:
            name, space = _local(child.tag), _namespace(child.tag)
            if name == "transcript" and "podcast" in space:
                address = validate_url(child.get("url"))
                if address and len(e.transcripts) < 8:
                    e.transcripts.append((address, (child.get("type") or "").strip().lower()[:60]))
            elif name == "person" and "podcast" in space and len(e.people) < PEOPLE:
                person = textrules.clean("".join(child.itertext()), NAME_CHARS)
                role = _ID_UNSAFE.sub("-", (child.get("role") or "host").strip().lower()).strip("-")[:24] or "host"
                if person and not textrules.looks_like_instruction(person) and person.lower() not in {p.lower() for p, _ in e.people}:
                    e.people.append((person, role))
            elif name == "chapters" and "podcast" in space:
                if "json" in (child.get("type") or "json").lower():
                    e.chapters_url = e.chapters_url or validate_url(child.get("url")) or ""
            elif name == "chapters" and "podlove" in space:
                inline += [(_clock(c.get("start") or ""), c.get("title")) for c in list(child)[:500] if _local(c.tag) == "chapter"]
            elif name == "soundbite" and "podcast" in space and len(e.soundbites) < SOUNDBITES:
                start, length = _whole_seconds(child.get("startTime") or ""), _whole_seconds(child.get("duration") or "")
                if start is not None and length is not None and 0 < length <= 600:
                    e.soundbites.append((start, length, textrules.clean("".join(child.itertext()), CHAPTER_TITLE_CHARS)))
        lines = _lines(long)
        e.chapters = _marks(inline) or chapter_lines(lines)
        e.notes = _notes(lines, bool(chapter_lines(lines)))
        e.resources = linked_names(long)
        e.links = htmlpage.links(long[:_MARKUP_CHARS])[:NOTE_LINKS]
        listing.entries.append(e)
    if not listing.entries:
        worst = max(skipped.items(), key=lambda kv: kv[1])
        raise AdapterError("format_changed", "expected entries with a title, a date and a link; %s in %d of %d" % (worst[0], worst[1], len(nodes)))
    if any(e.transcripts for e in listing.entries):
        keys.append("podcast:transcript")
    if any(len(e.notes) >= 1_500 for e in listing.entries):
        keys.append("content")
    listing.fingerprint = _fingerprint(keys)
    with_page = sum(1 for e in listing.entries if e.link)
    if with_page < len(listing.entries):
        listing.notes.append("%d of %d entries have no page of their own in the feed: they link to the show" % (len(listing.entries) - with_page, len(listing.entries)))
    return _finish(listing, skipped, "entries")


def head_of_feed(data):
    """The whole entries at the head of an RSS feed that was cut off at the size cap, closed so that it parses; None
    when there is no whole entry to keep. A long-running show's feed can be many megabytes; the newest entries come
    first, and those are the ones a run needs."""
    end = data.rfind(b"</item>")
    if end < 0 or b"<channel" not in data[:200_000] or b"<rss" not in data[:20_000]:
        return None
    return data[:end + len(b"</item>")] + b"</channel></rss>"


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
        lines = _lines(body)
        e.chapters = chapter_lines(lines)
        e.notes = _notes(lines, bool(e.chapters))
        e.summary = _text(r.get("summary"), 400) or textrules.first_sentences(e.notes, 400, most=3)
        e.resources = linked_names(body)
        e.links = htmlpage.links(body[:_MARKUP_CHARS])[:NOTE_LINKS]
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
