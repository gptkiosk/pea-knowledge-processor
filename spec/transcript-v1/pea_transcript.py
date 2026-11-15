# Copyright 2026 The PEA transcript authors
# SPDX-License-Identifier: Apache-2.0
"""PEA transcript v1: the data model, the writer, a lenient reader and the conformance rules.

Standard library only. See SPEC.md; rule ids in this file (F1, H4, S2 ...) are the ones the specification defines.
"""
import re
import unicodedata

MARKER = "PEA-TRANSCRIPT v1"
HEADER_END = "---"
UNTIMED = "[--:--:--]"
CUT_MARK = " (cut)"
MAXIMUM_CHARS = 150_000
# The longest segment the reference writer writes (SPEC.md section 5.1). A reader must not rely on it.
LONGEST_SEGMENT = 560
# The latest time a stamp can say, [99:59:59], in seconds.
LATEST_SECOND = 359_999
HEADER_KEYS = ["show", "title", "date", "source", "duration", "language", "format", "provenance", "quality", "speakers", "segments"]
# The value of `format`, with the short name convert.py uses for each.
FORMAT_LABELS = {
    "vtt": "WebVTT",
    "srt": "SubRip (SRT)",
    "json": "Podcasting 2.0 JSON",
    "html": "HTML page",
    "timedText": "text with times",
    "plain": "plain text",
}
DEFAULT_PROVENANCE = "publisher transcript"

# SPEC.md section 8: the v1 sponsor pattern. A segment whose text matches is a sponsor read or housekeeping.
AD_PATTERN = re.compile(
    r"(?i)\b(sponsor(?:ed|s)?|brought to you by|presented by|use (?:the )?(?:code|promo)|promo code|patreon|subscribe|newsletter"
    r"|ad-free|ad free|visit [a-z0-9.\-]+\.(?:com|ai|io|co)|is hiring|we are hiring|now hiring|link in the (?:show )?notes)\b"
)

_NEWLINES = "\n\r\x0b\x0c\x85  "


def is_ad(text):
    return AD_PATTERN.search(text) is not None


def is_space(ch):
    """A horizontal space as the reference implementation trims it: a tab, a Unicode space separator, or U+200B."""
    return ch == "\t" or ch == "\u200b" or unicodedata.category(ch) == "Zs"


def trim(s):
    a, b = 0, len(s)
    while a < b and is_space(s[a]):
        a += 1
    while b > a and is_space(s[b - 1]):
        b -= 1
    return s[a:b]


def trim_lines(s):
    a, b = 0, len(s)
    while a < b and (is_space(s[a]) or s[a] in _NEWLINES):
        a += 1
    while b > a and (is_space(s[b - 1]) or s[b - 1] in _NEWLINES):
        b -= 1
    return s[a:b]


_DECIMAL = re.compile(r"^[+-]?(?:\d+\.?\d*|\.\d+)(?:[eE][+-]?\d+)?$", re.ASCII)
_HEXADECIMAL = re.compile(r"^[+-]?0[xX](?:[0-9a-fA-F]+\.?[0-9a-fA-F]*|\.[0-9a-fA-F]+)(?:[pP][+-]?\d+)?$", re.ASCII)
_CLOCK_PART = re.compile(r"^(?:\d+\.?\d*|\.\d+)$", re.ASCII)


def to_number(s):
    """A number written in ASCII the way C's strtod reads one (decimal, or hexadecimal such as "0x1p3"), or None.
    No spaces. "inf", "nan" and a number too large to hold are None: they are never a time."""
    if len(s) > 400 or not (_DECIMAL.match(s) or _HEXADECIMAL.match(s)):
        return None
    try:
        value = float(s) if _DECIMAL.match(s) else float.fromhex(s)
    except (ValueError, OverflowError):
        return None
    return value if value == value and value not in (float("inf"), float("-inf")) else None


def sane(s):
    """A time that can be written: a whole number of seconds from 0 to 99:59:59. Anything else is "not known" (None)."""
    return s if isinstance(s, int) and not isinstance(s, bool) and 0 <= s <= LATEST_SECOND else None


def whole(d):
    """A number read from someone else's file as whole seconds. One that is not a number, infinite, negative or
    100 hours and more is "not known" (None). This is the one checked conversion every time goes through; it never
    fails, whatever the value (SPEC.md section 7.1)."""
    try:
        d = float(d)
    except (TypeError, ValueError, OverflowError):
        return None
    if d != d or d < 0 or not d < LATEST_SECOND + 1:
        return None
    return int(d)


def seconds(stamp):
    """"00:18:20", "18:20", "1:02:10.500", "00:00:01,360" as whole seconds, or None.

    Two or three parts, each 1 to 12 characters of ASCII digits with at most one point: so "nan", "inf", "-5" and "1e308"
    are not times. The sum is checked before it becomes a whole number, and a time of 100 hours or more is None."""
    parts = [p for p in trim(stamp).replace(",", ".").split(":") if p]
    if len(parts) not in (2, 3):
        return None
    total = 0.0
    for p in parts:
        if not 1 <= len(p) <= 12 or not _CLOCK_PART.match(p):
            return None
        total = total * 60 + float(p)
    return whole(total)


def stamp(start):
    """"[00:18:20]" for a segment line; "[--:--:--]" for a time that is not known or cannot be written."""
    start = sane(start)
    if start is None:
        return UNTIMED
    return "[%02d:%02d:%02d]" % (start // 3600, start % 3600 // 60, start % 60)


def clock(s):
    """"18:20", or "1:02:10" from the first hour on: the form of the `duration` value."""
    s = max(0, s)
    if s >= 3600:
        return "%d:%02d:%02d" % (s // 3600, s % 3600 // 60, s % 60)
    return "%02d:%02d" % (s // 60, s % 60)


def one_line(s, limit=200):
    """A header value: code fences replaced, line breaks and runs of spaces turned into one space, cut to `limit` characters."""
    s = s.replace("```", "'''")
    for ch in _NEWLINES:
        s = s.replace(ch, " ")
    return " ".join(p for p in s.split(" ") if p)[:limit]


class Segment:
    __slots__ = ("start", "speaker", "text")

    def __init__(self, start, speaker, text):
        self.start, self.speaker, self.text = start, speaker, text

    def __eq__(self, other):
        return (self.start, self.speaker, self.text) == (other.start, other.speaker, other.text)

    def __repr__(self):
        return "Segment(%r, %r, %r)" % (self.start, self.speaker, self.text)


class Transcript:
    def __init__(self):
        self.show = self.title = self.date = self.source = ""
        self.duration = None  # seconds
        self.language = None
        self.format = "plain"  # a key of FORMAT_LABELS
        self.provenance = DEFAULT_PROVENANCE
        self.partial = None  # the reason, when the transcript is not whole
        self.segments = []

    @property
    def chars(self):
        return sum(len(s.text) for s in self.segments)

    @property
    def timed(self):
        return any(s.start is not None for s in self.segments)

    @property
    def speakers(self):
        seen, out = set(), []
        for s in self.segments:
            if s.speaker is not None and s.speaker not in seen:
                seen.add(s.speaker)
                out.append(s.speaker)
        return out

    def render(self):
        """The file text: the fixed header, one line per segment, the cut mark when partial, and no final line break.
        A whole transcript whose last words are " (cut)" gets a full stop after them, so it is not read as cut."""
        lines = [MARKER]
        lines.append("show: " + one_line(self.show))
        lines.append("title: " + one_line(self.title))
        lines.append("date: " + (one_line(self.date, 40) if self.date else "unknown"))
        lines.append("source: " + (one_line(self.source, 400) if self.source else "unknown"))
        lines.append("duration: " + (clock(sane(self.duration)) if sane(self.duration) is not None else "unknown"))
        lines.append("language: " + ((one_line(self.language, 12) if self.language is not None else "") or "unknown"))
        lines.append("format: " + FORMAT_LABELS[self.format])
        lines.append("provenance: " + one_line(self.provenance, 80))
        lines.append("quality: " + ("partial (" + one_line(self.partial, 120) + ")" if self.partial is not None else "full"))
        speakers = self.speakers
        lines.append("speakers: " + (", ".join(speakers) if speakers else "none"))
        lines.append("segments: %d" % len(self.segments))
        lines.append(HEADER_END)
        for s in self.segments:
            lines.append(stamp(s.start) + " " + (s.speaker + ": " if s.speaker is not None else "") + s.text)
        if self.partial is None and self.segments and lines[-1].endswith(CUT_MARK):
            lines[-1] += "."
        return "\n".join(lines) + (CUT_MARK if self.partial is not None else "")


def is_v1(text):
    """The first line is the marker and nothing else: "PEA-TRANSCRIPT v10", "v1.1" and "v2" are other formats."""
    return text == MARKER or text.startswith(MARKER + "\n")


_ODD_STAMP = re.compile(r"^[0-9:\-]+$", re.ASCII)


def segment_line(line):
    """(start, rest) for a segment line, or None for a line that is not one (SPEC.md section 13.1, point 6).

    The usual line has "]" as its tenth character and its text from the twelfth. A stamp of another length made only of
    digits, ":" and "-" and followed by a space (an early writer could produce "[00:00:-5]" and "[111:06:40]") is read
    too: the segment keeps its text and has no time."""
    if not line.startswith("["):
        return None
    close = line.find("]", 0, 32)
    if close < 0:
        return None
    inner = line[1:close]
    if len(inner) == 8:
        rest = line[close + 2:]
        return (None if inner == "--:--:--" else seconds(inner), rest) if rest else None
    if not _ODD_STAMP.match(inner) or line[close + 1:close + 2] != " " or close + 1 >= 32:
        return None
    rest = line[close + 2:]
    return (seconds(inner), rest) if rest else None


def parse(text):
    """The lenient reader (SPEC.md section 13.1). Returns a Transcript, or None when the text is not PEA transcript v1.

    It follows the reference reader line for line: keys in any order (the first of each counts), defaults for missing
    ones, unknown keys and lines that are not segments skipped, a time that cannot be read taken as no time, line breaks
    at the very end accepted. It never fails on any text."""
    if not is_v1(text):
        return None
    t = Transcript()
    in_header, names, seen, cut = True, [], set(), False
    body = text.rstrip("\n")
    if body.endswith(CUT_MARK):
        body, cut = body[: -len(CUT_MARK)], True
    labels = {label: key for key, label in FORMAT_LABELS.items()}
    for n, line in enumerate(body.split("\n")):
        if n == 0:
            continue
        if in_header:
            if line == HEADER_END:
                in_header = False
                continue
            at = line.find(": ")
            if at < 0:
                continue
            key, value = line[:at], line[at + 2:]
            if key in seen:
                continue
            seen.add(key)
            if key == "show":
                t.show = value
            elif key == "title":
                t.title = value
            elif key == "date":
                t.date = "" if value == "unknown" else value
            elif key == "source":
                t.source = "" if value == "unknown" else value
            elif key == "duration":
                t.duration = None if value == "unknown" else seconds(value)
            elif key == "language":
                t.language = None if value == "unknown" else value
            elif key == "format":
                t.format = labels.get(value, "plain")
            elif key == "provenance":
                t.provenance = value
            elif key == "quality":
                if value.startswith("partial"):
                    t.partial = value[9:-1] if value.startswith("partial (") and value.endswith(")") else "end missing"
            elif key == "speakers":
                names = [] if value == "none" else [name for name in value.split(", ") if name]
            continue
        found = segment_line(line)
        if found is None:
            continue
        start, rest = found
        speaker = None
        for name in names:
            if rest.startswith(name + ": "):
                speaker, rest = name, rest[len(name) + 2:]
                break
        t.segments.append(Segment(start, speaker, rest))
    if cut and t.partial is None:
        t.partial = "end missing"
    return None if in_header else t


# ---------------------------------------------------------------------------------------------------------------------
# Conformance rules (SPEC.md section 13.2). Each rule has an id, a level ("error" for MUST, "warning" for SHOULD) and a
# one-line statement. validate() returns one Result per rule, in this order, so a report always lists every rule.

RULES = [
    ("F1", "error", "The file is valid UTF-8 with no byte order mark and no NUL character."),
    ("F2", "error", "Lines end with LF only: no CR anywhere."),
    ("F3", "error", "The file does not end with a line break."),
    ("F4", "error", "Three backticks in a row appear nowhere in the file."),
    ("H1", "error", "Line 1 is exactly \"PEA-TRANSCRIPT v1\"."),
    ("H2", "error", "Lines 2 to 12 are the eleven header keys in the fixed order, each written \"key: value\"."),
    ("H3", "error", "Line 13 is exactly \"---\"."),
    ("H4", "error", "show and title are at most 200 characters."),
    ("H5", "error", "date is \"unknown\" or 1 to 40 characters."),
    ("H6", "error", "source is \"unknown\" or 1 to 400 characters."),
    ("H7", "error", "duration is \"unknown\", MM:SS (under an hour) or H:MM:SS."),
    ("H8", "error", "language is \"unknown\" or 1 to 12 characters, each an ASCII letter, a digit, \"-\" or \"_\"."),
    ("H9", "error", "format is one of the six registered values."),
    ("H10", "error", "provenance is 1 to 80 characters."),
    ("H11", "error", "quality is \"full\" or \"partial (reason)\" with a reason of 1 to 120 characters."),
    ("H12", "error", "speakers is \"none\" or names joined by \", \": each 1 to 40 characters, unique, without \": \", none called \"none\"."),
    ("H13", "error", "segments is a whole number equal to the number of segment lines."),
    ("H14", "error", "show, title, date, source, provenance and quality have no space at either end and no doubled space."),
    ("S1", "error", "Every line after the header is a segment line: a stamp, one space, then text that starts with a non-space character."),
    ("S2", "error", "Every stamp is [HH:MM:SS] with minutes and seconds under 60, or [--:--:--]."),
    ("S3", "error", "Every name in speakers labels at least one segment, and the names are listed in the order of first use."),
    ("S4", "error", "quality is partial exactly when the file ends with the cut mark \" (cut)\"."),
    ("S5", "error", "The segment text is at most 150,000 characters in all (stamps and speaker labels not counted)."),
    ("S6", "error", "There is at least one segment."),
    ("W1", "warning", "date is \"unknown\" or a calendar date written YYYY-MM-DD."),
    ("W2", "warning", "language is \"unknown\" or looks like a BCP 47 tag."),
    ("W3", "warning", "Times do not go backwards."),
    ("W4", "warning", "No control characters other than LF."),
    ("W5", "warning", "No segment has two speaker labels in a row."),
    ("W6", "warning", "duration is not earlier than the last segment time."),
    ("W7", "warning", "No segment's text is longer than 560 characters."),
]
RULE_TEXT = {rule: text for rule, _, text in RULES}
RULE_LEVEL = {rule: level for rule, level, _ in RULES}


class Result:
    """The outcome of one rule: status is "pass", "fail" or "skip" (not checked, because an earlier rule failed)."""
    __slots__ = ("rule", "level", "status", "detail")

    def __init__(self, rule, status, detail=""):
        self.rule, self.level, self.status, self.detail = rule, RULE_LEVEL[rule], status, detail

    @property
    def ok(self):
        return self.status == "pass"


_BRACKET = re.compile(r"^\[([^\]]{0,16})\](.*)$", re.S)
_STAMP = re.compile(r"^(?:(\d{2}):([0-5]\d):([0-5]\d)|--:--:--)$", re.ASCII)
_DURATION = re.compile(r"^(?:\d{2}:[0-5]\d|[1-9]\d*:[0-5]\d:[0-5]\d)$", re.ASCII)
_DATE = re.compile(r"^\d{4}-(?:0[1-9]|1[0-2])-(?:0[1-9]|[12]\d|3[01])$", re.ASCII)
_LANGUAGE = re.compile(r"^[A-Za-z]{2,3}(?:-[A-Za-z0-9]{1,8})*$")
_COUNT = re.compile(r"^(?:0|[1-9]\d*)$", re.ASCII)
# Header values the reference writer passes through its one-line clean-up.
_ONE_LINE_KEYS = ("show", "title", "date", "source", "provenance", "quality")
_HEADER_RULES = ["H4", "H5", "H6", "H7", "H8", "H9", "H10", "H11", "H12", "H14", "W1", "W2"]
_BODY_RULES = ["H13", "S1", "S2", "S3", "S4", "S5", "S6", "W3", "W5", "W6", "W7"]
_LANGUAGE_CHARACTERS = re.compile(r"^[A-Za-z0-9_-]{1,12}$", re.ASCII)


def _line_of(text, needle):
    return text[: text.index(needle)].count("\n") + 1


def validate(data):
    """Checks the bytes of one file against every rule of the writer level (SPEC.md section 13.2).

    Returns a list of Result, one per rule, in the order of RULES. A rule that could not be checked because an earlier
    one failed (the header keys are missing, say) is reported as "skip", so the report never claims more than was looked at.
    """
    failed, skipped = {}, {}

    def fail(rule, detail):
        failed.setdefault(rule, detail)

    def skip(rules, why):
        for rule in rules:
            skipped.setdefault(rule, why)

    def results():
        out = []
        for rule, _, _ in RULES:
            if rule in failed:
                out.append(Result(rule, "fail", failed[rule]))
            elif rule in skipped:
                out.append(Result(rule, "skip", skipped[rule]))
            else:
                out.append(Result(rule, "pass"))
        return out

    # File level
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError as e:
        fail("F1", "not UTF-8 at byte %d" % e.start)
        skip([rule for rule, _, _ in RULES], "not checked: the file is not UTF-8 (F1)")
        return results()
    if text.startswith("﻿"):
        fail("F1", "starts with a byte order mark")
        text = text[1:]
    elif "\x00" in text:
        fail("F1", "NUL at line %d" % _line_of(text, "\x00"))
    if "\r" in text:
        fail("F2", "CR at line %d" % _line_of(text, "\r"))
        text = text.replace("\r\n", "\n").replace("\r", "\n")
    if text.endswith("\n"):
        fail("F3", "the last character is a line break")
        text = text[:-1]
    if "```" in text:
        fail("F4", "at line %d" % _line_of(text, "```"))
    control = next((ch for ch in text if ch not in "\n\x00" and unicodedata.category(ch) == "Cc"), None)
    if control is not None:
        fail("W4", "U+%04X at line %d" % (ord(control), _line_of(text, control)))

    cut = text.endswith(CUT_MARK)
    lines = (text[: -len(CUT_MARK)] if cut else text).split("\n")

    # Header
    if lines[0] != MARKER:
        fail("H1", "line 1 is %r" % lines[0][:60])
    header = {}
    for i, key in enumerate(HEADER_KEYS):
        line = lines[i + 1] if i + 1 < len(lines) else None
        prefix = key + ": "
        # An empty value is still written with the space after the colon: "show: ".
        if line is None or not line.startswith(prefix):
            fail("H2", "line %d should start with %r%s" % (i + 2, prefix, "; the file ends before it" if line is None else "; found %r" % line[:60]))
            skip(_HEADER_RULES + _BODY_RULES, "not checked: the header keys are not in place (H2)")
            break
        header[key] = line[len(prefix):]
    if "H2" in failed:
        skip(["H3"], "not checked: the header keys are not in place (H2)")
        return results()
    if len(lines) < 13 or lines[12] != HEADER_END:
        fail("H3", "line 13 is %s" % ("missing" if len(lines) < 13 else repr(lines[12][:60])))
        skip(_BODY_RULES, "not checked: the header does not end at line 13 (H3)")

    for key in ("show", "title"):
        if len(header[key]) > 200:
            fail("H4", "%s has %d characters" % (key, len(header[key])))
    for key in _ONE_LINE_KEYS:
        value = header[key]
        if value != value.strip(" ") or "  " in value:
            fail("H14", "%s: %r" % (key, value[:60]))
    if not 1 <= len(header["date"]) <= 40:
        fail("H5", "%d characters" % len(header["date"]))
    elif header["date"] != "unknown" and not _DATE.match(header["date"]):
        fail("W1", repr(header["date"]))
    if not 1 <= len(header["source"]) <= 400:
        fail("H6", "%d characters" % len(header["source"]))
    duration = None
    if header["duration"] != "unknown":
        if _DURATION.match(header["duration"]):
            duration = seconds(header["duration"])
        else:
            fail("H7", repr(header["duration"][:40]))
    language = header["language"]
    if not _LANGUAGE_CHARACTERS.match(language) or language.endswith("\n"):
        fail("H8", repr(language[:40]))
    elif language != "unknown" and not _LANGUAGE.match(language):
        fail("W2", repr(language))
    if header["format"] not in FORMAT_LABELS.values():
        fail("H9", repr(header["format"][:40]))
    if not 1 <= len(header["provenance"]) <= 80:
        fail("H10", "%d characters" % len(header["provenance"]))
    quality = header["quality"]
    if quality != "full" and not (quality.startswith("partial (") and quality.endswith(")") and 1 <= len(quality) - 10 <= 120):
        fail("H11", repr(quality[:60]))
    names = []
    if header["speakers"] == "":
        fail("H12", "empty; write \"none\"")
    elif header["speakers"] != "none":
        names = header["speakers"].split(", ")
        for name in names:
            if not 1 <= len(name) <= 40 or ": " in name or name == "none" or name != name.strip(" "):
                fail("H12", "name %r" % name[:60])
        if len(set(names)) != len(names):
            fail("H12", "a name is listed twice")
    if "H3" in failed:
        return results()

    # Segment lines
    if quality.startswith("partial") != cut:
        fail("S4", "quality is %r and the file %s with the cut mark" % (quality[:40], "ends" if cut else "does not end"))
    used, total, last_time, count = [], 0, None, 0
    for offset, line in enumerate(lines[13:]):
        number = offset + 14
        m = _BRACKET.match(line)
        if m is None:
            fail("S1", "line %d is not a segment line: %r" % (number, line[:40]))
            continue
        count += 1
        at = None
        time = _STAMP.match(m.group(1))
        if time is None:
            fail("S2", "line %d: [%s]" % (number, m.group(1)))
        elif time.group(1) is not None:
            at = int(time.group(1)) * 3600 + int(time.group(2)) * 60 + int(time.group(3))
        rest = m.group(2)
        if len(rest) < 2 or rest[0] != " " or rest[1].isspace():
            fail("S1", "line %d: one space and then text must follow the stamp" % number)
            continue
        rest = rest[1:]
        speaker = next((name for name in names if rest.startswith(name + ": ")), None)
        if speaker is not None:
            rest = rest[len(speaker) + 2:]
            if speaker not in used:
                used.append(speaker)
            if rest == "" or rest[0].isspace():
                fail("S1", "line %d: text must follow the speaker" % number)
            # A reader takes "Name: " at the start of a segment for its speaker, so a second label right after the first
            # is the one sign a file can give that a label was part of the speech.
            if any(rest.startswith(name + ": ") for name in names):
                fail("W5", "line %d has two speaker labels in a row" % number)
        total += len(rest)
        if len(rest) > LONGEST_SEGMENT:
            fail("W7", "line %d has %d characters of text" % (number, len(rest)))
        if at is not None:
            if last_time is not None and at < last_time:
                fail("W3", "line %d: %s comes after %s" % (number, stamp(at), stamp(last_time)))
            last_time = at if last_time is None else max(last_time, at)
    if count == 0:
        fail("S6", "no segment lines")
    if not _COUNT.match(header["segments"]):
        fail("H13", "segments is %r" % header["segments"][:40])
    elif int(header["segments"]) != count:
        fail("H13", "the header says %s, the file has %d" % (header["segments"], count))
    if "H12" not in failed and used != names:
        unused = [n for n in names if n not in used]
        fail("S3", ("never used: " + ", ".join(unused)) if unused else "first used in the order " + ", ".join(used))
    if total > MAXIMUM_CHARS:
        fail("S5", "{:,} characters".format(total))
    if duration is not None and last_time is not None and duration < last_time:
        fail("W6", "duration %s, last segment at %s" % (header["duration"], stamp(last_time)))
    return results()


def conforms(results):
    """True when every rule of level "error" passed (the writer level of SPEC.md)."""
    return all(r.ok for r in results if r.level == "error")
