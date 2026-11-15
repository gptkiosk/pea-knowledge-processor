# Copyright 2026 The PEA knowledge processor authors
# SPDX-License-Identifier: Apache-2.0
"""The text rules of docs/FORMAT.md ("Hostile input"): what a text field may hold, and how publisher text is made to fit.

`check` is the rule a reader applies. `clean` is what the writer does to publisher text so that it passes.
Every step is one pass over the text, so no input makes it slow.
"""
import html
import re
import unicodedata

# Rule T1: no control characters, no line breaks, no characters that reorder or hide text.
_FORBIDDEN = re.compile("[\x00-\x1f\x7f-\x9f  ‪-‮⁦-⁩﻿￹-￻\ud800-\udfff]")
# Rule T2: nothing that reads as an HTML or XML tag, a comment or a declaration.
_TAG = re.compile(r"<[A-Za-z/!?][^<>]{0,400}>")
# Rule T3: no address. A scheme followed by "://", "www." at the start of a word, or a "mailto:"/"javascript:"/"data:" link.
_URL = re.compile(r"(?i)[a-z][a-z0-9+.\-]{1,20}://|(?<![a-z0-9])www\.[a-z0-9]|(?<![a-z0-9])(?:mailto|javascript|data|tel|sms):\S")
# Rule T4: one line, trimmed, single spaces.
_SPACES = re.compile(r"\s+")
_ADDRESS = re.compile(r"(?i)(?:[a-z][a-z0-9+.\-]{1,20}://|(?<![a-z0-9])www\.)[^\s<>\"')\]]*|(?<![a-z0-9])(?:mailto|javascript|data|tel|sms):\S+")

# Text addressed to the program that reads the file instead of to a listener. The extractive digest never picks a
# sentence that matches, and the model digest drops a field that does. This is one extra layer, not the defence: the
# defence is that the structure is fixed and every reader treats every field as quoted data (docs/FORMAT.md).
_INSTRUCTION = re.compile(
    r"(?i)\b(?:ignore|disregard|forget|override)\b[^.!?]{0,40}\b(?:previous|prior|above|earlier|all|your|the)\b[^.!?]{0,30}"
    r"\b(?:instruction|prompt|rule|direction|message|context)s?\b"
    r"|\b(?:new|updated|real)\s+(?:system\s+)?instructions?\s*:"
    r"|\byou\s+are\s+now\s+(?:a|an|in|the)\b"
    r"|\b(?:system|developer|assistant)\s*(?:prompt|message)\s*:"
    r"|\b(?:reveal|print|repeat|show)\b[^.!?]{0,30}\b(?:system\s+prompt|your\s+instructions|api\s+key|secret)s?\b"
    r"|<\s*/?\s*(?:system|assistant|user|instructions?)\s*>"
    r"|\[\s*/?\s*(?:INST|SYSTEM)\s*\]"
)

REASONS = ("control_character", "html", "url", "spacing")


def check(text):
    """None when `text` may stand in a text field, otherwise the reason: one of REASONS."""
    if _FORBIDDEN.search(text):
        return "control_character"
    if _TAG.search(text):
        return "html"
    if _URL.search(text):
        return "url"
    if text != text.strip() or "  " in text or _SPACES.sub(" ", text) != text:
        return "spacing"
    return None


def has_url(text):
    return _URL.search(text) is not None


def has_tag(text):
    return _TAG.search(text) is not None


def looks_like_instruction(text):
    return _INSTRUCTION.search(text) is not None


def _without_blocks(s, name):
    """`s` without <name ...> ... </name> blocks. A block that never closes takes the rest of the text. One pass."""
    lower = s.lower()
    out, pos = [], 0
    while True:
        i = lower.find("<" + name, pos)
        if i < 0:
            out.append(s[pos:])
            break
        out.append(s[pos:i])
        j = lower.find("</" + name, i)
        if j < 0:
            break
        k = lower.find(">", j)
        if k < 0:
            break
        pos = k + 1
    return " ".join(out)


def _without_tags(s):
    """`s` with every "<...>" run of up to 400 characters replaced by a space. One pass; a "<" that nothing closes stays."""
    out, pos = [], 0
    while True:
        i = s.find("<", pos)
        if i < 0:
            out.append(s[pos:])
            break
        j = s.find(">", i + 1)
        if j < 0:
            out.append(s[pos:])
            break
        if j - i <= 401 and "<" not in s[i + 1:j]:
            out.append(s[pos:i])
            out.append(" ")
            pos = j + 1
        else:
            out.append(s[pos:i + 1])
            pos = i + 1
    return "".join(out)


def plain(s, limit=200_000):
    """Publisher text (HTML or not) as plain text on one line: scripts and styles out, tags out, entities decoded,
    then tags out again (text that was written as &lt;b&gt; must not come back as a tag), addresses out, forbidden
    characters out, spaces collapsed. At most `limit` characters of input are read."""
    s = s[:limit]
    for name in ("script", "style", "template", "iframe", "noscript"):
        if "<" + name in s.lower():
            s = _without_blocks(s, name)
    s = _without_tags(s)
    s = html.unescape(s)
    s = _without_tags(s)
    s = unicodedata.normalize("NFC", s)
    s = _ADDRESS.sub(" ", s)
    s = _FORBIDDEN.sub(" ", s)
    s = _SPACES.sub(" ", s).strip()
    if _TAG.search(s):  # what is left that still reads as a tag loses its brackets
        s = _SPACES.sub(" ", s.replace("<", " ").replace(">", " ")).strip()
    return s


def shorten(s, limit):
    """`s` in at most `limit` characters: cut at the last space before the limit and ended with an ellipsis."""
    if len(s) <= limit:
        return s
    cut = s[:limit - 1]
    space = cut.rfind(" ")
    if space >= limit // 2:
        cut = cut[:space]
    return cut.rstrip(" ,;:-–—") + "…"


def clean(s, limit):
    """Publisher text made to fit a text field of `limit` characters. The result always passes `check`."""
    out = shorten(plain(s), limit)
    return out if check(out) is None else ""


_SENTENCE_END = re.compile(r"([.!?\u2026][\"'\u201d\u2019)\]]*)\s+(?=[\"'\u201c\u2018(\[]?[A-Z0-9])")
_ABBREVIATION = re.compile(r"(?:\b(?:Mr|Mrs|Ms|Dr|Prof|Sr|Jr|St|vs|etc|Inc|Ltd|Co|No|U\.S|U\.K|e\.g|i\.e|a\.m|p\.m)\.|\b[A-Z]\.)$")


def sentences(text):
    """`text` split into sentences. A full stop after a known abbreviation or a single capital does not end one."""
    out, start = [], 0
    for m in _SENTENCE_END.finditer(text):
        piece = text[start:m.end(1)]
        if _ABBREVIATION.search(piece.rstrip("\"'\u201d\u2019)]")):
            continue
        if piece.strip():
            out.append(piece.strip())
        start = m.end()
    tail = text[start:].strip()
    if tail:
        out.append(tail)
    return out


def first_sentences(text, limit, most=4):
    """The first whole sentences of `text` that fit in `limit` characters, at most `most`; the shortened first one when
    even that does not fit."""
    kept = []
    for s in sentences(text)[:most]:
        if len(" ".join(kept + [s])) > limit:
            break
        kept.append(s)
    if kept:
        return " ".join(kept)
    return shorten(text, limit)
