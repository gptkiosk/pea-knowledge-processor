#!/usr/bin/env python3
# Copyright 2026 The PEA transcript authors
# SPDX-License-Identifier: Apache-2.0
"""Converts WebVTT, SubRip (SRT), Podcasting 2.0 JSON and plain text (with or without times) into PEA transcript v1.

    python3 convert.py episode.vtt --show "Harbor Voices" --title "The ledger" --date 2026-11-13 \
        --source https://example.org/ep6.vtt -o ep6.pea.txt

Standard library only. The steps follow SPEC.md, Appendix A, which describes the reference normalizer; the same input
gives the same file (the differences that remain are listed in SPEC.md, "Known gaps"). HTML transcript pages are not
converted by this tool. No input makes it fail or hang: what cannot be read is reported with a reason.
"""
import argparse
import json
import os
import re
import sys
import unicodedata
from urllib.parse import urlsplit

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import pea_transcript as pt  # noqa: E402
from pea_transcript import Segment, Transcript, seconds, trim, trim_lines, is_ad  # noqa: E402

MINIMUM_CHARS = 200
MAXIMUM_CHARS = pt.MAXIMUM_CHARS
LONGEST = pt.LONGEST_SEGMENT
TIME = r"(?:\d{1,2}:)?\d{1,2}:\d{2}(?:[.,]\d{1,3})?"

# The reference normalizer's patterns are written for the ICU engine. These pieces give Python's `re` the same meaning:
# white space is every character with the Unicode White_Space property; "." and the line anchors know seven line ends.
_Z = " \u00a0\u1680\u2000-\u200a\u2028\u2029\u202f\u205f\u3000"
_W = "\\t\\n\\x0b\\f\\r\\x85" + _Z
_S = "[" + _W + "]"                        # \s
_NS = "[^" + _W + "]"                      # \S
_HS = "[\\t\\x0b\\f\\r\\x85" + _Z + "]"     # [^\S\n]: white space inside a line
_NL = "\\n\\x0b\\x0c\\r\\x85\u2028\u2029"
_DOT = "[^" + _NL + "]"                    # .
_BOL = "(?:^|(?<=[" + _NL + "]))"          # ^ with (?m)
_EOL = "(?=[" + _NL + "]|\\Z)"             # $ with (?m)
_END = "(?=[" + _NL + "]?\\Z)"             # $ without it
_CONTROL = re.compile("[\\x00-\\x1f\\x7f-\\x9f\u2028\u2029]")
_SURROGATE = re.compile("[\ud800-\udfff]")


class Unreadable(Exception):
    """Nothing readable came of the input. `why` says so in a few words."""

    def __init__(self, why):
        super().__init__(why)
        self.why = why


class Cue:
    """One piece of a publisher's transcript. `paragraph`: in a text transcript, a blank line came before it, so it
    does not continue the line before."""
    __slots__ = ("start", "end", "speaker", "text", "paragraph")

    def __init__(self, start, end, speaker, text, paragraph=False):
        self.start, self.end, self.speaker, self.text, self.paragraph = start, end, speaker, text, paragraph


def _alnum(ch):
    return unicodedata.category(ch)[0] in "LMN"


def _has_alnum(s):
    return any(_alnum(ch) for ch in s)


def _white(ch):
    """A character with the Unicode White_Space property."""
    return ch in "\t\n\x0b\x0c\r\x85\u2028\u2029" or unicodedata.category(ch) == "Zs"


def _words(s):
    """Split on the plain space only, dropping empty pieces."""
    return [w for w in s.split(" ") if w]


_SPACES = re.compile("[ \t\u00a0]")


def _collapse(s):
    """Runs of space, tab and no-break space become one space; none at the ends."""
    return " ".join(w for w in _SPACES.split(s) if w)


# --- Markup and entities ------------------------------------------------------------------------------------------------
_NAMED = {
    "&amp;": "&", "&lt;": "<", "&gt;": ">", "&quot;": '"', "&apos;": "'", "&#39;": "'", "&nbsp;": " ", "&mdash;": "\u2014",
    "&ndash;": "\u2013", "&hellip;": "\u2026", "&rsquo;": "\u2019", "&lsquo;": "\u2018", "&ldquo;": "\u201c", "&rdquo;": "\u201d",
    "&middot;": "\u00b7", "&copy;": "\u00a9",
}
_ENTITY = re.compile(r"&(?:#(x?)([0-9a-f]{1,6})|[a-z]{2,6});", re.I)
_DECIMAL_DIGITS = re.compile(r"^[0-9]+$", re.ASCII)


def _entity(m):
    whole = m.group(0)
    if whole in _NAMED:
        return _NAMED[whole]
    digits = m.group(2)
    if digits is None or (not m.group(1) and not _DECIMAL_DIGITS.match(digits)):
        return whole
    code = int(digits, 16 if m.group(1) else 10)
    if code > 0x10FFFF or 0xD800 <= code <= 0xDFFF:
        return whole
    return chr(code)


def decode(s):
    """Entities decoded once, in one pass from left to right: each &name; or &#number; is replaced where it stands and
    the result is never read again, so "&amp;lt;" is the text "&lt;"."""
    return _ENTITY.sub(_entity, s) if "&" in s else s


def without(s, open_, close, within=None):
    """`s` without every run that starts with `open_` and ends at the next `close`: {\\an8}, <i>, <00:00:01.280>.
    With `within`, the end must be at most that many characters on, so "a < b" stays text. A run with no end stays.
    One pass over the text, so a line made of a million "<" costs no more than any other line of that length."""
    i = s.find(open_)
    if i < 0:
        return s
    out, pos, nxt = [], 0, -1
    while i >= 0:
        start = i + len(open_)
        if nxt < start:
            nxt = s.find(close, start)
            if nxt < 0:
                break  # nothing closes from here on
        if within is None or nxt - start <= within:
            out.append(s[pos:i])
            pos = nxt + 1
            i = s.find(open_, pos)
        else:
            i = s.find(open_, i + 1)
    out.append(s[pos:])
    return "".join(out)


def plain(s):
    """Markup out, once: tags, karaoke times and SubRip position codes are removed, and only then are entities decoded.
    So "&lt;once&gt;" becomes the text "<once>" and stays. Every reader below calls this exactly once on each piece of
    publisher text; `tidied` never does."""
    return decode(without(without(s, "{\\", "}"), "<", ">", 200))


_LEADING_MARKS = re.compile("^" + _S + "*>{2,}" + _S + "*")


def squeeze(s):
    """Text made safe for one line of the file: three backticks broken, control characters and line separators turned
    into spaces, a leading ">>" dropped, spaces collapsed. It changes nothing in text that is already clean."""
    t = _CONTROL.sub(" ", s.replace("```", "'''"))
    if ">" in t:
        t = _LEADING_MARKS.sub("", t)
    return _collapse(t)


def strip(s):
    """`plain`, then `squeeze`: one line of publisher text as it is kept."""
    return squeeze(plain(s))


def language_tag(s):
    """A language tag as the header holds it: ASCII letters, digits, "-" and "_", at most 12. Anything else in a
    publisher's value is dropped, so it cannot break the header."""
    if s is None:
        return None
    tag = "".join(ch for ch in s if ch.isascii() and (ch.isalnum() or ch in "-_"))[:12]
    return tag or None


# --- Detection --------------------------------------------------------------------------------------------------------
_JSON_START = re.compile(r"^\[" + _S + r"*[\{\[]")
_ARROW_MILLIS = re.compile(r"\d{1,2}:\d{2}(?::\d{2})?[.,]\d{1,3}" + _S + "*-->")
_ARROW_SECONDS = re.compile(r"\d{1,2}:\d{2}:\d{2}" + _S + "*-->")
_ARROW_COMMA = re.compile(r"\d{2}:\d{2},\d{1,3}" + _S + "*-->")
_MARKS = re.compile(r"[\[\(]" + TIME + r"[\]\)]")
_LEADING_LINES = re.compile(_BOL + _HS + "*" + TIME + ":?(?:" + _S + "|" + _EOL + ")")
_STAMPED_LINES = re.compile(_BOL + _DOT + "{1,40}?" + _S + r"[\(\[]?" + TIME + r"[\)\]]?:?" + _S + "*" + _EOL)


def detect_format(raw, type="", mime="", url=""):
    """What the text really is: a key of pea_transcript.FORMAT_LABELS. The declared type and the address only break ties."""
    head = trim_lines(raw[:4000]).replace("\ufeff", "")
    lower, declared = head.lower(), (type + " " + mime).lower()
    try:
        path = urlsplit(url).path.lower()
    except ValueError:
        path = ""
    if lower.startswith("webvtt"):
        return "vtt"
    if lower.startswith("{") or _JSON_START.search(lower):
        return "json"
    if _ARROW_MILLIS.search(head) or _ARROW_SECONDS.search(head):
        return "srt" if _ARROW_COMMA.search(head) else "vtt"
    if (lower.startswith("<!doctype html") or "<html" in lower or "<body" in lower or "<cite" in lower
            or ("<p" in lower and "</p>" in lower) or "<div" in lower):
        return "html"
    if "json" in declared or path.endswith(".json"):
        return "json"
    marks = sum(1 for _ in _MARKS.finditer(raw))
    leading = sum(1 for _ in _LEADING_LINES.finditer(raw))
    stamped = sum(1 for _ in _STAMPED_LINES.finditer(raw))
    return "timedText" if marks >= 2 or leading >= 3 or stamped >= 3 else "plain"


# --- WebVTT and SubRip -------------------------------------------------------------------------------------------------
_ARROW = re.compile("^" + _S + "*(" + TIME + ")" + _S + "*-->" + _S + "*(" + TIME + ")")
_VOICE = re.compile(r"<v(?:\.[^>" + _W + r"]+)*" + _S + r"+([^>]+)>")
_LANGUAGE_LINE = re.compile(r"^Language:" + _S + r"*([A-Za-z\-]{2,12})" + _S + "*" + _END, re.I)


def caption_cues(text):
    """Cues of a WebVTT or SubRip file. Header, NOTE, STYLE and REGION blocks, cue numbers and cue settings are dropped; <v Name> gives the speaker."""
    cues, language = [], None
    lines = text.split("\n")
    trimmed = [trim(line) for line in lines]
    # For each line, whether the next non-empty line is a timing line (so this one is a cue number or cue name).
    before_timing, next_is_timing = [False] * len(lines), False
    for i in range(len(lines) - 1, -1, -1):
        before_timing[i] = next_is_timing
        if trimmed[i]:
            next_is_timing = _ARROW.search(trimmed[i]) is not None
    open_, skipping, header_done = False, False, False
    for i, raw in enumerate(lines):
        line = trimmed[i]
        g = _ARROW.search(line)
        if g:
            cues.append(Cue(seconds(g.group(1)), seconds(g.group(2)), None, ""))
            open_, skipping, header_done = True, False, True
            continue
        # An empty line ends a cue. A line of spaces inside a cue (rolling captions pad with one) is skipped without ending it.
        if line == "":
            if raw == "" or not open_:
                open_, skipping = False, False
                if cues or i > 0:
                    header_done = True
            continue
        if not header_done:
            g = _LANGUAGE_LINE.search(line)
            if g:
                language = g.group(1)
            continue
        if line.startswith("NOTE") or line in ("STYLE", "REGION") or line.startswith("STYLE ") or line.startswith("REGION "):
            skipping, open_ = True, False
            continue
        if skipping:
            continue
        if before_timing[i] and (not open_ or all(unicodedata.category(ch)[0] == "N" for ch in line)):
            continue
        if not open_ or not cues:
            continue
        g = _VOICE.search(line)
        speaker = trim(g.group(1)) if g else None
        piece = strip(line)
        if piece == "":
            continue
        last = cues[-1]
        if last.text == "":
            last.speaker, last.text = speaker, piece
        elif speaker is not None and speaker != last.speaker:
            cues.append(Cue(last.start, last.end, speaker, piece))
        else:
            last.text += "\n" + piece
    return [c for c in cues if c.text], language


# --- JSON --------------------------------------------------------------------------------------------------------------
def _refuse_constant(name):
    raise ValueError(name)


def _first_string(row, keys):
    for key in keys:
        if isinstance(row.get(key), str):
            return row[key]
    return None


def _first_present(row, keys):
    for key in keys:
        if key in row:
            return row[key]
    return None


def _time(value):
    """A JSON time as whole seconds: a number, a string holding one, or a clock string. None for anything else, and
    for a time that is not a number, infinite, negative or 100 hours and more: the row keeps its text."""
    number = None
    if isinstance(value, (int, float)):
        number = value
    elif isinstance(value, str):
        number = pt.to_number(value)
        if number is None:
            number = seconds(value)
    return None if number is None else pt.whole(number)


def ends_sentence(s):
    t = trim(s)
    return bool(t) and t[-1] in ".!?\u2026\"\u201d"


def _first_wins(pairs):
    """An object with a key written twice keeps the first, as the reference reader's JSON parser does."""
    out = {}
    for key, value in pairs:
        out.setdefault(key, value)
    return out


def _float(text):
    """A number too large to hold makes the file unreadable (the reference parser refuses it)."""
    value = float(text)
    if value == float("inf"):
        raise ValueError("a number out of range")
    return value


_DEEPEST = 511  # lists and objects inside one another; the reference parser refuses more


def _too_deep(data):
    level = [data]
    for _ in range(_DEEPEST):
        level = [v for x in level for v in (x.values() if isinstance(x, dict) else x) if isinstance(v, (dict, list))]
        if not level:
            return False
    return True


def _has_surrogate(value):
    if isinstance(value, str):
        return _SURROGATE.search(value) is not None
    if isinstance(value, dict):
        return any(_has_surrogate(k) or _has_surrogate(v) for k, v in value.items())
    if isinstance(value, list):
        return any(_has_surrogate(v) for v in value)
    return False


def json_cues(text, truncated):
    """{"version","segments":[{"speaker","startTime","endTime","body"}]}, a bare list of such rows, rows with start/text, or one text string."""
    try:
        data = json.loads(text, parse_constant=_refuse_constant, parse_float=_float, object_pairs_hook=_first_wins)
        if not isinstance(data, (dict, list)):
            raise ValueError("not an object or a list")
        if _too_deep(data):
            raise ValueError("nested too deep")
        # Half a surrogate pair ("\ud800" with no partner) is not text: the file is refused.
        if "\\u" in text and _has_surrogate(data):
            raise ValueError("half a surrogate pair")
    except (ValueError, RecursionError):
        raise Unreadable("a JSON file over 1.5 MB, cut off before its end" if truncated else "JSON that does not parse")
    root = data if isinstance(data, dict) else None
    language = None
    if root is not None:
        language = root["language"] if isinstance(root.get("language"), str) else root["lang"] if isinstance(root.get("lang"), str) else None
    rows = data if isinstance(data, list) and all(isinstance(r, dict) for r in data) else []
    if not rows and root is not None:
        for key in ("segments", "cues", "results", "transcript", "utterances", "paragraphs", "monologues"):
            r = root.get(key)
            if isinstance(r, list) and r and all(isinstance(x, dict) for x in r):
                rows = r
                break
    if not rows:
        whole = _first_string(root, ("text", "transcript", "body")) if root is not None else None
        if whole is not None and len(whole) >= MINIMUM_CHARS:
            return text_cues(whole), language
        keys = ", ".join(sorted(root.keys())[:5]) if root is not None else "a list"
        raise Unreadable("JSON without transcript segments (" + (keys or "empty") + ")")
    cues = []
    for r in rows:
        body = _first_string(r, ("body", "text", "content", "transcript")) or ""
        if body == "":
            continue
        speaker = _first_string(r, ("speaker", "speakerName", "name"))
        speaker = trim(speaker) if speaker is not None else None
        start = _time(_first_present(r, ("startTime", "start", "start_time", "begin")))
        end = _time(_first_present(r, ("endTime", "end", "end_time")))
        # A row that is only punctuation ("-.") is caption noise between words: it becomes a space.
        decoded = plain(body).replace("\n", " ")
        clean = decoded if _has_alnum(decoded) else " "
        # Word-by-word rows ("Welcome", " ", "back"): glued onto the cue being built, with a space only where the pieces carry none.
        last = cues[-1] if cues else None
        if (last is not None and last.speaker == (speaker if speaker else last.speaker) and len(last.text) < 220
                and (not ends_sentence(last.text) or len(last.text) < 40)):
            glue = "" if (last.text and _white(last.text[-1])) or _white(clean[0]) or clean[0] in ".,!?;:%)\u2019'" else " "
            last.text += glue + clean
            last.end = end if end is not None else last.end
        elif trim(clean) != "":
            cues.append(Cue(start, end, speaker if speaker else None, clean))
    return cues, language


# --- Text and markdown --------------------------------------------------------------------------------------------------
_LINK_MARKS = re.compile(r"[\[\]\n]")
_ADDRESS_END = re.compile(r"[)\n]")


def without_links(s):
    """Markdown links keep their words: "[the notes](https://example.org/notes)" becomes "the notes". The same matches as
    the pattern \\[([^\\]\\n]+)\\]\\((?:https?:)[^)\\n]+\\), found in one pass (the pattern itself searches to the end of
    the line from every "[" that has no "]" after it)."""
    if "]" not in s:
        return s
    out, copied = [], 0     # `out` holds s[:copied], with the links found so far replaced by their words
    open_ = -1              # the first "[" since the last "]", line break or link: where a link's words could start
    stop = -1               # the next ")" or line break at or after an address
    for m in _LINK_MARKS.finditer(s):
        i, c = m.start(), m.group(0)
        if i < copied:
            continue        # inside the address of a link already replaced
        if c == "\n":
            open_ = -1
        elif c == "[":
            if open_ < 0:
                out.append(s[copied:i])
                copied = open_ = i
        else:
            address = -1
            if open_ >= 0 and i - open_ >= 2:
                if s.startswith("(https:", i + 1):
                    address = i + 8
                elif s.startswith("(http:", i + 1):
                    address = i + 7
            if address >= 0:
                if stop < address:
                    found = _ADDRESS_END.search(s, address)
                    stop = found.start() if found else len(s)
                if stop < len(s) and s[stop] == ")" and stop > address:
                    out.append(s[open_ + 1:i])
                    copied = stop + 1
            open_ = -1
    out.append(s[copied:])
    return "".join(out)


_EMPHASIS = re.compile(r"[*_`]+")
_QUOTE_MARKS = re.compile(_BOL + _HS + "*>+" + _HS + "?")
_RULES = re.compile(_BOL + _HS + "*[-=]{3,}" + _HS + "*" + _EOL)
_ADDRESS_LINE = re.compile("^https?://" + _NS + "+(" + _S + "+\u00b7" + _S + "+" + _DOT + "*)?\\Z")
_HASHES = re.compile("^#+" + _S + "*")
_LEADING_LINE = re.compile("^" + TIME + ":?(?:" + _S + "|" + _END + ")")
_INLINE = re.compile(r"[\[\(](" + TIME + r")[\]\)]")
_LEADING = re.compile("^(" + TIME + "):?(?:" + _S + "+[-\u2013\u2014:]?" + _S + "*|" + _END + ")(" + _DOT + "*)" + _END)
# The name may end in a number ("Speaker 1", "Guest 12"); no other digit, so the name stops where the time starts.
_STAMPED = re.compile(r"^([A-Z][^\d\[\(:]{0,38}?(?:\d{1,3}(?![\d:]))?)" + _S + r"*[\(\[]?(" + TIME + r")[\)\]]?:?" + _S + "*" + _END)


def text_cues(raw, clean=False):
    """Plain text or markdown. Times in brackets or parentheses anywhere in a line ("[00:01:00]"), a line that starts with
    a time ("0:31 text", "0:31: text", "0:31 - text"), and "Name 0:12" or "Speaker 1 (00:12):" lines set the time of what
    follows. `clean`: the text was already through `strip`."""
    # Markdown marks go; the page's own title line and bare address lines are not speech.
    text = _RULES.sub("", _QUOTE_MARKS.sub("", _EMPHASIS.sub("", without_links(raw))))
    lines = [_collapse(line) for line in text.split("\n")]
    lines = [line for line in lines if not (line.startswith("http") and _ADDRESS_LINE.search(line))]
    first = next((i for i, line in enumerate(lines) if line), None)
    if first is not None and lines[first].startswith("#"):
        del lines[first]
    leading_count = sum(1 for line in lines if line and unicodedata.category(line[0])[0] == "N" and _LEADING_LINE.search(line))
    is_stamped = [bool(line) and _STAMPED.search(line) is not None for line in lines]
    stamped_count = sum(is_stamped)
    # A line with a time mark in its middle speaks for times written inside the text; "Speaker 1 (00:12):" is a
    # name-and-time line, not one of those.
    mid_count = 0
    if stamped_count >= 3:
        for line, name_line in zip(lines, is_stamped):
            if not name_line:
                m = _INLINE.search(line)
                if m and m.end() < len(line):
                    mid_count += 1
    stamped_lines = stamped_count >= 3 and stamped_count > mid_count
    # `gap`: a blank line came before this line, so it starts a new paragraph. Under "Name 0:12" lines a block runs to
    # the next such line, whatever the blank lines.
    cues, now, speaker, gap = [], None, None, True

    def add(piece):
        nonlocal speaker, gap
        said = piece if clean else strip(piece)
        if said == "":
            return
        cues.append(Cue(now, None, speaker, said, gap and not stamped_lines))
        speaker, gap = None, False

    for line in lines:
        if line.startswith("#"):
            line = _HASHES.sub("", line)
        if line == "":
            gap = True
            continue
        # "Speaker 1 (00:12):" or "Justin 0:12" on a line of its own (only in a transcript written that way throughout).
        if stamped_lines:
            g = _STAMPED.search(line)
            if g:
                name, at = g.group(1).strip(" -\u2013\u2014"), seconds(g.group(2))
                if len(_words(name)) <= 4 and at is not None:
                    speaker, now = name, at
                    continue
        if leading_count >= 3:
            g = _LEADING.search(line)
            if g:
                at = seconds(g.group(1))
                if at is not None:
                    now, line = at, g.group(2) or ""
                    if line == "":
                        continue
        # Times inside the line split it: what comes before a mark belongs to the earlier time.
        start = 0
        for m in _INLINE.finditer(line):
            add(trim(line[start:m.start()]))
            at = seconds(m.group(1))
            now = at if at is not None else now
            start = m.end()
        add(trim(line[start:]))
    return cues


# --- Speakers, clean-up and segments --------------------------------------------------------------------------------------
NOT_NAMES = {
    "note", "notes", "warning", "update", "today", "source", "sources", "link", "links", "listen", "http", "https", "transcript",
    "chapter", "summary", "title", "date", "disclaimer", "remember", "example", "step", "tip", "ps", "fact", "quote", "question",
    "answer", "topic", "first", "second", "third", "finally", "also", "so", "and", "but", "the", "this", "that",
}
_LABEL = re.compile(
    r"^((?:[A-Z][A-Za-z0-9.'\u2019\-]*|Dr\.|Mr\.|Ms\.|Mrs\.)(?: [A-Z0-9][A-Za-z0-9.'\u2019\-]*){0,3}|[A-Z][A-Z0-9 .'\-]{1,30}"
    r"|Speaker \d{1,2}|SPEAKER[_ ]\d{1,2}|Host|Guest|Interviewer)" + _S + "?:" + _S + "+(" + _NS + ".*)" + _END,
    re.S,
)


def labelled_speakers(cues):
    """"Kevin: Welcome back" at the start of a cue. A name counts when it labels at least two cues and is not an ordinary word."""
    counts, found = {}, []
    for c in cues:
        g = _LABEL.search(c.text)
        if g and len(g.group(1)) <= 40 and g.group(1).lower() not in NOT_NAMES:
            counts[g.group(1)] = counts.get(g.group(1), 0) + 1
            found.append((g.group(1), g.group(2)))
        else:
            found.append(None)
    if not any(n >= 2 for n in counts.values()):
        return cues
    for c, hit in zip(cues, found):
        if hit and counts[hit[0]] >= 2:
            c.speaker, c.text = hit
    return cues


_NOT_FOLDED = re.compile("[^a-z0-9 ]")


def fold(s):
    """Lower case, letters and digits only, one space between words: how two caption lines are compared."""
    s = s.lower()
    if s.isascii():
        return " ".join(_words(_NOT_FOLDED.sub("", s)))
    return " ".join(_words("".join(ch for ch in s if ch == " " or (_alnum(ch) if ord(ch) > 127 else ch.isalnum()))))


_SOUND_NOTE = re.compile(r"^[\[\(][^\]\)]{1,40}[\]\)]\Z")


def tidied(cues):
    """Cues with caption noise removed: empty cues, bare sound notes, a caption line repeated from the cue before, and a line that only grows the one before it."""
    out, recent = [], []
    for c in cues:
        kept = []
        for raw in c.text.split("\n"):
            line = squeeze(raw)
            if not _has_alnum(line):
                continue
            if _SOUND_NOTE.search(line) or line.startswith("\u266a"):
                continue
            folded = fold(line)
            if folded == "":
                continue
            # Only a line with some length can be called a repeat: "Yeah." twice in a row is two people agreeing.
            if len(folded) >= 12 and folded in recent:
                continue
            if recent and len(recent[-1]) >= 12 and folded.startswith(recent[-1] + " "):
                # The line before, grown by a few words: keep only what is new.
                words, skip = _words(line), len(_words(recent[-1]))
                if len(words) > skip:
                    kept.append(" ".join(words[skip:]))
            else:
                kept.append(line)
            recent.append(folded)
            if len(recent) > 3:
                recent.pop(0)
        if kept:
            out.append(Cue(c.start, c.end, c.speaker, " ".join(kept), c.paragraph))
    return out


def without_overlap(a, b):
    """`b` without the words it repeats from the end of `a` (three to twelve words)."""
    bw = _words(b)
    if len(bw) < 3:
        return b
    aw, bf = [fold(w) for w in _words(a)[-12:]], [fold(w) for w in bw[:12]]
    if len(aw) < 3 or len(bf) < 3:
        return b
    for k in range(min(len(aw), len(bf)), 2, -1):
        if aw[-k:] == bf[:k] and "" not in aw[-k:]:
            return " ".join(bw[k:])
    return b


def collapse_repeats(text):
    """A run of three or more words said twice in a row is kept once."""
    words = _words(text)
    if len(words) < 6:
        return text
    folded = [fold(w) for w in words]
    out, i = [], 0
    while i < len(words):
        skipped, most = False, min(20, (len(words) - i) // 2)
        for n in range(most, 2, -1):
            if folded[i] == folded[i + n] and folded[i:i + n] == folded[i + n:i + 2 * n] and "" not in folded[i:i + n]:
                i += n
                skipped = True
                break
        if not skipped:
            out.append(words[i])
            i += 1
    return " ".join(out)


_SENTENCE_END = re.compile("([.!?][\"\u201d')\\]]?)" + _S + "+")


def sentences(text, size):
    """Sentences packed up to `size`, split only where a stop is followed by a space, so "5.2" and "$1.5B" stay whole.
    A sentence longer than `size` is cut at a word (anywhere, when it has no space in reach)."""
    out, current = [], ""
    for part in _SENTENCE_END.sub("\\1\x1f", text).split("\x1f"):
        part = trim(part)
        pos, n = 0, len(part)
        while n - pos > size:
            end = pos + size
            cut = part.rfind(" ", pos, end)
            if cut <= pos:
                cut = end
            if current:
                out.append(current)
                current = ""
            out.append(part[pos:cut])
            pos = cut
            while pos < n and pt.is_space(part[pos]):
                pos += 1
        sentence = part[pos:]
        if sentence == "":
            continue
        if current and len(current) + len(sentence) + 1 > size:
            out.append(current)
            current = ""
        current += (" " if current else "") + sentence
    if current:
        out.append(current)
    return out


_SPONSOR_WORDS = ("sponsor", "brought to you by", "presented by", "use ", "promo", "patreon", "subscribe", "newsletter", "ad-free",
                  "ad free", "visit ", "hiring", "link in the")


def _is_ad(text):
    """pea_transcript.is_ad, asked only of text that holds one of the words its pattern needs: the answer is the same."""
    lower = text.lower()
    return any(word in lower for word in _SPONSOR_WORDS) and is_ad(text)


def speaker_name(raw):
    """A speaker's name as the header and the segment lines hold it: one line, at most 40 characters, no ", " or ": "
    inside (they would read as two names, or as a label). "none" is how the header says there are no speakers, so a
    publisher's speaker called that is no speaker."""
    name = trim(squeeze(raw)[:40].replace(", ", " ").replace(": ", " "))
    return None if name in ("", "none") else name


def pack_segments(cues):
    """Cues packed into segments: one speaker each, about 300 to 560 characters and never more than 560, closed at a
    sentence end where there is one, and never holding a cue that starts ninety seconds or more after the segment did.
    A segment without a time never takes in a cue that has one. The speaker is carried from one cue to the next only
    where the format continues it: captions, rows and "Name 0:12" blocks. In a text transcript a line after a blank line
    that has no label of its own has no stated speaker."""
    out, current, speaker, sponsor = [], None, None, False

    def close():
        if current is not None:
            current.text = collapse_repeats(current.text)
            if current.text:
                out.append(current)

    for cue in cues:
        if cue.speaker is not None:
            speaker = speaker_name(cue.speaker)
        elif cue.paragraph:
            speaker = None
        pieces = sentences(cue.text, LONGEST) if len(cue.text) > LONGEST else [cue.text]
        for n, text in enumerate(pieces):
            # A sponsor read is never packed into the same segment as the talk around it.
            ad = _is_ad(text)
            if current is not None:
                have = len(current.text)
                changed = n == 0 and (cue.speaker is not None or cue.paragraph) and speaker != current.speaker
                long = (have >= 280 and ends_sentence(current.text)) or have + len(text) > LONGEST
                late = cue.start is not None and current.start is not None and cue.start - current.start >= 90
                first_time = current.start is None and cue.start is not None
                if changed or long or late or first_time or ad != sponsor:
                    close()
                else:
                    piece = without_overlap(current.text, text)
                    if piece:
                        current.text += " " + piece
                    continue
            current, sponsor = Segment(cue.start, speaker, text), ad
    close()
    return out


# --- The one entry point -------------------------------------------------------------------------------------------------
def normalize(raw, type="", mime="", truncated=False, show="", title="", date="", source="", duration=None, language=None):
    """Reads `raw` in whatever format it is and returns a pea_transcript.Transcript. Raises Unreadable with the reason.

    truncated: the input was cut off at a size limit, so its end is missing.
    """
    # Half a surrogate pair cannot be written as UTF-8: it is read as the replacement character, as bytes that are not UTF-8 are.
    text = _SURROGATE.sub("\ufffd", raw).replace("\r\n", "\n").replace("\r", "\n").replace("\ufeff", "")
    if trim_lines(text) == "":
        raise Unreadable("an empty file")
    if "\x00" in text[:4000]:
        raise Unreadable("not a text file")
    fmt = detect_format(text, type=type, mime=mime, url=source)
    if fmt in ("vtt", "srt"):
        cues, found = caption_cues(text)
        language = language if language is not None else found
    elif fmt == "json":
        cues, found = json_cues(text, truncated)
        language = language if language is not None else found
    elif fmt == "html":
        raise Unreadable("an HTML page (this converter does not read HTML transcript pages)")
    else:
        cues = text_cues(text)
    # Speaker labels written into the text ("Kevin: Welcome back") count only when a name labels at least two lines.
    if not any(c.speaker is not None for c in cues):
        cues = labelled_speakers(cues)
    t = Transcript()
    t.show, t.title, t.date, t.source, t.format = show, title, date, source, fmt
    t.segments = pack_segments(tidied(cues))
    total = t.chars
    if total < MINIMUM_CHARS:
        label = pt.FORMAT_LABELS[fmt]
        raise Unreadable("no speech text in the %s file" % label if total == 0 else "only %d characters of speech text" % total)
    # The latest time the file names, start or end (a cue that ends before it starts must not make the episode shorter
    # than its last segment). A stated length that cannot be written is dropped.
    times = [x for c in cues for x in (c.start, c.end) if x is not None]
    stated = pt.sane(duration)
    t.duration = stated if stated is not None else (max(times) if times else None)
    t.language = language_tag(language)
    # Size cap: whole segments only, so nothing stops mid-sentence, and the cut is said. No segment is longer than
    # LONGEST, so the first one always fits.
    kept = count = 0
    for s in t.segments:
        if kept + len(s.text) > MAXIMUM_CHARS and count > 0:
            break
        kept += len(s.text)
        count += 1
    if count < len(t.segments):
        everything = len(t.segments)
        t.segments = t.segments[:count]
        starts = [s.start for s in t.segments if s.start is not None]
        t.partial = "cut at {:,} chars; {} of {} segments kept".format(MAXIMUM_CHARS, count, everything)
        if starts:
            t.partial += ", up to " + pt.clock(max(starts)) + (" of " + pt.clock(t.duration) if t.duration is not None else "")
    elif truncated:
        starts = [s.start for s in t.segments if s.start is not None]
        t.partial = "the file was over 1.5 MB; end missing" + (", kept up to " + pt.clock(max(starts)) if starts else "")
    return t


def _clock_argument(value):
    s = seconds(value) if ":" in value else (int(value) if value.isdigit() else None)
    if s is None:
        raise argparse.ArgumentTypeError("write the duration as seconds, MM:SS or H:MM:SS")
    return s


def main(argv=None):
    p = argparse.ArgumentParser(description="Convert WebVTT, SubRip, Podcasting 2.0 JSON or plain text into PEA transcript v1.")
    p.add_argument("input", help="the transcript to read, or - for standard input")
    p.add_argument("-o", "--output", help="where to write the v1 file (default: standard output)")
    p.add_argument("--show", default="", help="the show's name")
    p.add_argument("--title", default="", help="the episode's title")
    p.add_argument("--date", default="", help="the episode's date, YYYY-MM-DD")
    p.add_argument("--source", default="", help="the public address the transcript came from")
    p.add_argument("--duration", type=_clock_argument, help="the episode's length when known (seconds, MM:SS or H:MM:SS)")
    p.add_argument("--language", help="a BCP 47 language tag; overrides what the file says")
    p.add_argument("--type", default="", help="the type the publisher declared (for example application/json); only breaks ties")
    p.add_argument("--truncated", action="store_true", help="the input was cut off at a size limit")
    a = p.parse_args(argv)
    data = sys.stdin.buffer.read() if a.input == "-" else open(a.input, "rb").read()
    # Bytes that are not UTF-8 are read as the replacement character, the way the reference implementation reads a download.
    raw = data.decode("utf-8", errors="replace")
    try:
        t = normalize(raw, type=a.type, truncated=a.truncated, show=a.show, title=a.title, date=a.date, source=a.source,
                      duration=a.duration, language=a.language)
    except Unreadable as e:
        print("unreadable: " + e.why, file=sys.stderr)
        return 1
    out = t.render().encode("utf-8")
    if a.output:
        with open(a.output, "wb") as f:
            f.write(out)
    else:
        sys.stdout.buffer.write(out)  # no final line break: the file ends with its last segment (SPEC.md, rule F3)
    return 0


if __name__ == "__main__":
    sys.exit(main())
