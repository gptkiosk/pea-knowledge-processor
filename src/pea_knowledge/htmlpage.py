# Copyright 2026 The PEA knowledge processor authors
# SPDX-License-Identifier: Apache-2.0
"""Stage 2, for publishers whose full transcript is a web page: finding the page of an episode, and reading it.

Some publishers offer the transcript of every episode openly on their own site, as an HTML page, and list no transcript
file in the feed. A source says so in config/sources.json with `transcript_page`: where the page of an episode is found
(`from`), the one host it may be on, and an optional `extract` rule that names the elements to read. The rule is data,
never code: lists of simple selectors ("tag", ".class", "#id", "tag.class", "tag#id").

Reading a page (docs/FORMAT.md, "Reading an HTML transcript page", states the same steps for any other reader):

- Nothing is executed and nothing else is fetched: no scripts, no styles, no frames, no images.
- One pass over the text, with a time bound. Tags that never close, tags nested thousands deep and broken markup cost
  no more than their length.
- What a browser would not show is dropped: scripts, styles, templates, comments, menus, headers, footers, forms,
  headings, and every element that is hidden (`hidden`, `aria-hidden`, an inline style or a style-sheet rule that hides
  it, or one of the usual class names for hidden text).
- Only the transcript block is read: the elements the source's rule names, or else the element whose id or class says
  "transcript". Speakers and times come from the elements the rule names (`<cite>`, `<time>`, `<dt>` by default) or
  from the text itself ("Lex Fridman: ...", "(00:01:23)"), which the transcript converter already reads.
- The text is data. It goes through the same clean-up, packing, sponsor rule and size cap as every other transcript.
- A page that gives too little text, no transcript block, or that looks like a sign-in, paywall, cookie or robot-check
  page is a typed failure (`none_published` or `unreadable`) with a detail. It is never read in part.
"""
import html
import re
import time
from urllib.parse import urljoin, urlsplit

from . import textrules
from .fetch import validate_url
from .transcript import convert, pea_transcript as pt

SECONDS = 10                 # the longest one page may take to read
MINIMUM_CHARS = 1_500        # a page with less transcript text than this is not a transcript
CHARS_PER_MINUTE = 150       # ...and neither is one with less than this per minute of the episode (speech runs near 800)
DEEPEST = 2_000              # elements inside one another; what is deeper is read as if it were not an element
TAG_CHARS = 4_000            # how far a tag's closing ">" is looked for
STYLE_CHARS = 300_000        # of style sheets in the page that are read for rules that hide
LINKS = 400

SELECTOR = r"^(?:[a-z][a-z0-9]{0,15})?(?:[.#][A-Za-z0-9_-]{1,60})?$"
_SELECTOR = re.compile(SELECTOR)

_VOID = frozenset("area base br col embed hr img input link meta param source track wbr".split())
# Their content is not text: skipped to the closing tag without being read.
_RAW = frozenset("script style textarea title xmp noscript iframe template svg math select object canvas audio video".split())
# Elements that are never part of what was said.
_NEVER = frozenset("head nav header footer aside form button figure figcaption h1 h2 h3 h4 h5 h6 label dialog menu summary del s map".split())
_BLOCK = frozenset("address article blockquote body dd details div dl dt fieldset hr li main ol p pre section table tbody td th thead "
                   "tr ul html center".split()) | _NEVER
_CLOSES_P = _BLOCK - frozenset(("body", "html", "td", "th", "tr", "tbody", "thead"))
_SIBLINGS = {"li": ("li",), "dt": ("dt", "dd"), "dd": ("dt", "dd"), "tr": ("tr", "td", "th"), "td": ("td", "th"), "th": ("td", "th"), "option": ("option",)}
_HIDDEN_CLASSES = frozenset("""hidden hide d-none sr-only visually-hidden visuallyhidden screen-reader-text screen-reader-only screenreader
invisible is-hidden u-hidden offscreen off-screen a11y-hidden display-none assistive-text element-invisible""".split())
_NOISE = frozenset("""ad ads advert advertisement adsbygoogle ad-container ad-slot promo newsletter share sharing social comments comment-respond
sidebar related cookie cookie-banner cookie-notice toc toc_container breadcrumbs pagination author-info""".split())
_WALL_CLASSES = ("paywall", "regwall", "subscriber-only", "members-only", "premium-content", "locked-content")
_WALL_WORDS = (
    ("a sign-in or paywall page", ("subscribe to continue", "subscribe to read", "sign in to read", "sign in to continue", "log in to read", "log in to continue",
                                    "members only", "member-only", "for members", "become a member to", "subscriber-only", "subscribers only", "already a subscriber",
                                    "premium members", "to read the full transcript", "unlock the full transcript", "create a free account")),
    ("a robot check", ("verify you are human", "checking your browser", "are you a robot", "captcha", "enable javascript", "unusual traffic")),
    ("a cookie wall", ("accept cookies", "accept all cookies", "we use cookies", "cookie settings", "consent to cookies")),
)
_HIDING_STYLE = re.compile(r"display:none|visibility:(?:hidden|collapse)|opacity:0(?![.\d])|font-size:0(?![.\d])|(?:left|top|text-indent|margin-left):-\d{3,}"
                           r"|clip:rect\(0|clip-path:inset\((?:50|100)%|color:transparent|content-visibility:hidden")
_ATTRIBUTE = re.compile(r"""([^\s"'<>/=]{1,60})(?:\s*=\s*(?:"([^"]*)"|'([^']*)'|([^\s"'>]+)))?""")
_TAG_END = re.compile(r"""(?:[^>"']|"[^"]*"|'[^']*')*>""")
_NAME = re.compile(r"/?[A-Za-z][A-Za-z0-9:-]{0,30}")
_STYLE_BLOCK = re.compile(r"(?is)<style\b[^>]{0,300}>(.*?)</style")
_STYLE_RULE = re.compile(r"([^{}]{1,400})\{([^{}]{0,2000})\}")
_SIMPLE_NAME = re.compile(r"^[.#][A-Za-z0-9_-]{1,60}$")
_SPACE = re.compile(r"\s+")
_CLOCK = re.compile(r"(?<![\d:])(" + convert.TIME + r")(?![\d:])")
_NAME_THEN_TIME = re.compile(r"^([A-Z][^\d\[\(:]{0,38}?)\s*:?\s*[\(\[](" + convert.TIME + r")[\)\]]\s*:?\s*(\S.*)?$", re.S)
_HREF = re.compile(r"""(?is)<a\b[^<>]{0,2000}?\bhref\s*=\s*(?:"([^"<>]{1,2000})"|'([^'<>]{1,2000})')[^<>]{0,2000}>(.{0,400}?)</a\s*>""")


class PageProblem(Exception):
    """The page gave no transcript. `code` is "none_published" (there is none on it) or "unreadable" (there may be one,
    but it cannot be read); `detail` is one plain sentence."""

    def __init__(self, code, detail):
        super().__init__("%s: %s" % (code, detail))
        self.code, self.detail = code, detail


# --- The rule of a source ---------------------------------------------------------------------------------------------
def _selectors(values):
    out = []
    for text in values or []:
        if not isinstance(text, str) or not text or not _SELECTOR.match(text):
            raise ValueError("not a simple selector: %r" % (text,))
        mark = max(text.find("."), text.find("#"))
        out.append((text if mark < 0 else text[:mark], "" if mark < 0 else text[mark], "" if mark < 0 else text[mark + 1:]))
    return out


class Rules:
    """A source's `extract` rule: which elements hold the transcript (`within`), which are left out (`drop`), and which
    mark one turn (`row`), its speaker (`speaker`) and its time (`time`). Every member is a list of simple selectors."""
    KEYS = ("within", "drop", "row", "speaker", "time")

    def __init__(self, rule=None):
        rule = rule or {}
        self.within, self.drop, self.row, self.speaker, self.time = (_selectors(rule.get(k)) for k in self.KEYS)
        if not self.speaker and not self.row:
            self.speaker = _selectors(["cite", "dt"])       # what a page uses when it marks speakers with HTML itself
        if not self.time and not self.row:
            self.time = _selectors(["time"])

    def published(self):
        """The rule as an item carries it for a reader on a phone: the same lists, empty ones left out."""
        return {k: [tag + mark + name for tag, mark, name in getattr(self, k)] for k in self.KEYS if getattr(self, k)}


def _matches(selectors, tag, ident, classes):
    for wanted, mark, name in selectors:
        if wanted and wanted != tag:
            continue
        if not mark or (mark == "#" and name == ident) or (mark == "." and name in classes):
            return True
    return False


# --- Reading the page -------------------------------------------------------------------------------------------------
class _Node:
    __slots__ = ("tag", "dropped", "scope", "role", "block")

    def __init__(self, tag, dropped, scope, role, block):
        self.tag, self.dropped, self.scope, self.role, self.block = tag, dropped, scope, role, block


class _Block:
    __slots__ = ("speaker", "start", "text", "scopes", "walled")

    def __init__(self, speaker, start, text, scopes, walled):
        self.speaker, self.start, self.text, self.scopes, self.walled = speaker, start, text, scopes, walled


def _hiding_rules(markup):
    """The class names and ids that a style sheet in the page hides (".note{display:none}"). Only rules whose selector
    is one bare class or id are read: enough for text that was hidden on purpose, and never more than was written."""
    found, read = set(), 0
    for block in _STYLE_BLOCK.finditer(markup):
        sheet = block.group(1)[:STYLE_CHARS - read]
        read += len(sheet)
        for rule in _STYLE_RULE.finditer(sheet):
            if _HIDING_STYLE.search(_SPACE.sub("", rule.group(2).lower())):
                for selector in rule.group(1).split(","):
                    selector = selector.strip()
                    if _SIMPLE_NAME.match(selector):
                        found.add(selector)
        if read >= STYLE_CHARS:
            break
    return found


def _name_and_time(text):
    """A speaker element's text as (name or None, seconds or None): "Mara (00:01:23)" names both."""
    start = None
    m = _CLOCK.search(text)
    if m:
        start = pt.seconds(m.group(1))
        text = text[:m.start()] + " " + text[m.end():]
    name = _SPACE.sub(" ", text).strip(" \t()[]:;,.-–—|>")
    return (name if 0 < len(name) <= 60 and convert._has_alnum(name) else None), start


def blocks(markup, rules=None, clock=time.monotonic, seconds=SECONDS):
    """The page as the blocks of text a reader would see, in order, each with the speaker and time its markup states
    and the containers it stands in. Returns (blocks, containers, sample of everything visible, signs of a wall)."""
    rules = rules or Rules()
    deadline = clock() + seconds
    hidden_by_sheet = _hiding_rules(markup) if "<style" in markup.lower() else set()
    stack, open_tags, dropped, active = [], {}, 0, []
    containers = [["rule", 0]]            # [kind, characters]: "rule" (one for all the rule names), "named", "article", "main", "body"
    out, sample, sample_size, signs = [], [], 0, set()
    state = {"buffer": [], "capture": None, "speaker": None, "start": None, "walls": 0}

    def flush():
        text = convert.squeeze(html.unescape("".join(state["buffer"])).replace("<", "‹").replace(">", "›"))
        state["buffer"] = []
        if text and convert._has_alnum(text):
            out.append(_Block(state["speaker"], state["start"], text, tuple(active), state["walls"] > 0))
            state["start"] = None
            for index in set(active):
                containers[index][1] += len(text)

    def leave(node):
        nonlocal dropped
        open_tags[node.tag] -= 1
        if node.block:
            flush()
        if node.role in ("speaker", "time") and state["capture"] is not None and state["capture"][0] is node:
            said = _SPACE.sub(" ", html.unescape("".join(state["capture"][1]))).strip()
            state["capture"] = None
            if node.role == "speaker":
                name, at = _name_and_time(said)
                if name is not None:
                    flush()
                    state["speaker"] = name
                    state["start"] = at if at is not None else state["start"]
                elif said:
                    state["buffer"].append(" " + said + " ")       # too long to be a name: it is text
            else:
                m = _CLOCK.search(said)
                at = pt.seconds(m.group(1)) if m else None
                if at is not None:
                    flush()
                    state["start"] = at
        if node.role == "wall":
            state["walls"] -= 1
        if node.dropped:
            dropped -= 1
        if node.scope is not None:
            active.pop()

    def text_piece(piece):
        nonlocal sample_size
        if dropped or not piece:
            return
        if state["capture"] is not None:
            state["capture"][1].append(piece)
            return
        state["buffer"].append(piece)
        if sample_size < 20_000:
            sample.append(piece[:2_000])
            sample_size += len(piece)

    position, size, tags = 0, len(markup), 0
    while position < size:
        less = markup.find("<", position)
        if less < 0:
            text_piece(markup[position:])
            break
        text_piece(markup[position:less])
        tags += 1
        if tags % 256 == 0 and clock() > deadline:
            raise PageProblem("unreadable", "the page took more than %d seconds to read" % seconds)
        if markup.startswith("<!--", less):
            end = markup.find("-->", less + 4)
            position = size if end < 0 else end + 3
            continue
        named = _NAME.match(markup, less + 1)
        if named is None:
            if markup.startswith(("<!", "<?"), less):            # a declaration or an instruction: not text
                end = markup.find(">", less + 2)
                position = size if end < 0 else end + 1
            else:
                text_piece("<")                                   # "a < b": a character, not a tag
                position = less + 1
            continue
        end = _TAG_END.match(markup, named.end(), min(size, named.end() + TAG_CHARS))
        if end is None:
            plain_end = markup.find(">", named.end(), min(size, named.end() + TAG_CHARS))
            if plain_end < 0:
                position = size                                   # a tag that never ends takes the rest of the page with it
                continue
            stop = plain_end + 1
        else:
            stop = end.end()
        tag = named.group(0).lower()
        position = stop
        if tag.startswith("/"):
            tag = tag[1:]
            if open_tags.get(tag):
                while stack:
                    node = stack.pop()
                    leave(node)
                    if node.tag == tag:
                        break
            elif tag in ("p", "br"):
                flush()
            continue
        if tag in _RAW:
            close = re.compile("</" + tag + r"\b", re.I).search(markup, stop)
            if close is None:
                position = size
            else:
                after = markup.find(">", close.end())
                position = size if after < 0 else after + 1
            continue
        attributes = {}
        for a in _ATTRIBUTE.finditer(markup, named.end(), stop - 1):
            key = a.group(1).lower()
            if key not in attributes and len(attributes) < 60:
                attributes[key] = a.group(2) if a.group(2) is not None else a.group(3) if a.group(3) is not None else a.group(4) or ""
        if tag == "input" and attributes.get("type", "").lower() == "password":
            signs.add("a sign-in or paywall page")
        if tag == "br":
            flush()
        if tag in _VOID:
            continue
        if tag == "body":                                         # whatever the head left open ends here
            while stack:
                leave(stack.pop())
        if tag in _CLOSES_P and stack and stack[-1].tag == "p":
            leave(stack.pop())
        if tag in _SIBLINGS and stack and stack[-1].tag in _SIBLINGS[tag]:
            leave(stack.pop())
        if markup[stop - 2:stop] == "/>" or len(stack) >= DEEPEST:
            continue
        ident = attributes.get("id", "")[:200]
        classes = attributes.get("class", "")[:2_000].split()
        style = _SPACE.sub("", attributes.get("style", "")[:2_000].lower())
        lowered = [c.lower() for c in classes]
        chosen = _matches(rules.within, tag, ident, classes) or _matches(rules.row, tag, ident, classes)
        hide = (tag in _NEVER or "hidden" in attributes or attributes.get("aria-hidden", "").strip().lower() == "true"
                or bool(style and _HIDING_STYLE.search(style)) or any(c in _HIDDEN_CLASSES for c in lowered)
                or _matches(rules.drop, tag, ident, classes)
                or (not chosen and (any(c in _NOISE for c in lowered) or ident.lower() in _NOISE
                                    or any("." + c in hidden_by_sheet for c in classes) or (ident and "#" + ident in hidden_by_sheet))))
        block = tag in _BLOCK or _matches(rules.row, tag, ident, classes)
        if block:
            flush()
        role = None
        if any(mark in c for c in lowered for mark in _WALL_CLASSES) or any(mark in ident.lower() for mark in _WALL_CLASSES):
            role = "wall"
            state["walls"] += 1
            signs.add("a sign-in or paywall page")
        elif not hide and not dropped and state["capture"] is None:
            if _matches(rules.row, tag, ident, classes):
                state["speaker"], state["start"] = None, None
            elif _matches(rules.speaker, tag, ident, classes):
                role = "speaker"
            elif _matches(rules.time, tag, ident, classes):
                role = "time"
        scope = None
        if not hide and not dropped and chosen and _matches(rules.within if rules.within else rules.row, tag, ident, classes):
            scope = 0
            active.append(scope)
        elif not hide and not dropped and len(containers) < 200:
            kind = None
            if tag not in ("a", "li", "span", "i", "b", "em", "strong", "p") and ("transcript" in ident.lower() or any("transcript" in c for c in lowered)):
                kind = "named"
            elif tag in ("article", "main", "body"):
                kind = tag
            if kind is not None:
                scope = len(containers)
                containers.append([kind, 0])
                active.append(scope)
        node = _Node(tag, hide, scope, role, block)
        stack.append(node)
        open_tags[tag] = open_tags.get(tag, 0) + 1
        if hide:
            dropped += 1
        if role in ("speaker", "time"):
            state["capture"] = (node, [])
    while stack:
        leave(stack.pop())
    flush()
    return out, containers, _SPACE.sub(" ", html.unescape("".join(sample))).lower(), signs


def _wall(sample, signs):
    """What kind of wall the page looks like, or None."""
    for what, words in _WALL_WORDS:
        if what in signs or any(w in sample for w in words):
            return what
    return None


def cues(markup, rules=None, minimum=MINIMUM_CHARS, clock=time.monotonic, seconds=SECONDS):
    """The transcript on the page as the converter's cues. Raises PageProblem."""
    rules = rules or Rules()
    found, containers, sample, signs = blocks(markup, rules, clock, seconds)
    ruled = bool(rules.within or rules.row)
    if ruled:
        wanted = {0}
        what = "the block the source's rule names"
    else:
        named = [(n, size) for n, (kind, size) in enumerate(containers) if kind == "named"]
        most = max((size for _, size in named), default=0)
        # Of the blocks that say "transcript", the innermost one that still holds nearly all of the text.
        wanted = {max(n for n, size in named if size >= 0.8 * most)} if most else set()
        what = "a block marked as the transcript"
        if not wanted:
            for kind in ("article", "main", "body"):
                sizes = [(size, -n) for n, (k, size) in enumerate(containers) if k == kind and size]
                if sizes:
                    wanted = {-max(sizes)[1]}
                    break
    chosen = [b for b in found if wanted.intersection(b.scopes)] if wanted else ([] if ruled or len(containers) > 1 else found)
    size = sum(len(b.text) for b in chosen)
    wall = _wall(sample, signs)
    if any(b.walled for b in chosen):
        raise PageProblem("unreadable", "the transcript on the page is inside a paywall block")
    if size < minimum:
        if wall:
            raise PageProblem("unreadable", "the page looks like %s, not a transcript" % wall)
        if not chosen or not (ruled or (wanted and containers[min(wanted)][0] == "named")):
            raise PageProblem("none_published", "the page has no transcript: %s was not found" % what)
        raise PageProblem("unreadable", "only %d characters of text in %s" % (size, what))
    marked = any(b.speaker is not None or b.start is not None for b in chosen)
    lines = [] if marked else [_NAME_THEN_TIME.match(b.text) for b in chosen]
    if marked:
        made = [convert.Cue(b.start, None, b.speaker, b.text, True) for b in chosen]
    elif sum(1 for m in lines if m and len(m.group(1).split()) <= 4 and pt.seconds(m.group(2)) is not None) >= 3:
        # "Lex Fridman: (00:01:23) ..." or "Lex Fridman (00:01:23) ..." at the head of a paragraph, throughout the page:
        # the name and the time of that paragraph. A paragraph without them continues the speaker before it.
        made, speaker = [], None
        for b, m in zip(chosen, lines):
            if m and len(m.group(1).split()) <= 4 and pt.seconds(m.group(2)) is not None:
                speaker = m.group(1).strip()
                if m.group(3):
                    made.append(convert.Cue(pt.seconds(m.group(2)), None, speaker, m.group(3), True))
            else:
                made.append(convert.Cue(None, None, speaker, b.text, True))
    else:
        made = convert.text_cues("\n\n".join(b.text for b in chosen), clean=True)
    if not any(c.speaker is not None for c in made):
        made = convert.labelled_speakers(made)
    if not ruled and not (wanted and containers[min(wanted)][0] == "named"):
        # Nothing on the page says "transcript": it counts only when it reads like one (speakers or times throughout).
        shaped = sum(1 for c in made if c.speaker is not None or c.start is not None)
        if shaped < 3 or shaped * 5 < len(made):
            raise PageProblem("none_published", "the page has no recognizable transcript (no transcript block, no speakers, no times)")
    return made


def read(markup, rules=None, minimum=MINIMUM_CHARS, truncated=False, show="", title="", date="", source="", duration=None, language=None,
         clock=time.monotonic, seconds=SECONDS):
    """An HTML transcript page as a pea_transcript.Transcript (format "HTML page"). Raises PageProblem."""
    text = convert._SURROGATE.sub("�", markup).replace("\r\n", "\n").replace("\r", "\n").replace("﻿", "").replace("\x00", " ")
    made = cues(text, rules, minimum, clock, seconds)
    t = pt.Transcript()
    t.show, t.title, t.date, t.source, t.format = show, title, date, source, "html"
    t.segments = convert.pack_segments(convert.tidied(made))
    total = t.chars
    stated = pt.sane(duration)
    if total < minimum:
        raise PageProblem("unreadable", "only %d characters of speech text on the page" % total)
    if stated and total < CHARS_PER_MINUTE * stated // 60:
        raise PageProblem("unreadable", "only %d characters for an episode of %d minutes: not a full transcript" % (total, stated // 60))
    times = [c.start for c in made if c.start is not None]
    t.duration = stated if stated is not None else (max(times) if times else None)
    t.language = convert.language_tag(language)
    kept = count = 0
    for s in t.segments:      # the size cap of every transcript: whole segments only, and the cut is said
        if kept + len(s.text) > convert.MAXIMUM_CHARS and count > 0:
            break
        kept += len(s.text)
        count += 1
    if count < len(t.segments):
        everything = len(t.segments)
        t.segments = t.segments[:count]
        starts = [s.start for s in t.segments if s.start is not None]
        t.partial = "cut at {:,} chars; {} of {} segments kept".format(convert.MAXIMUM_CHARS, count, everything)
        if starts:
            t.partial += ", up to " + pt.clock(max(starts)) + (" of " + pt.clock(t.duration) if t.duration is not None else "")
    elif truncated:
        starts = [s.start for s in t.segments if s.start is not None]
        t.partial = "the page was over 1.5 MB; end missing" + (", kept up to " + pt.clock(max(starts)) if starts else "")
    return t


# --- Finding the page -------------------------------------------------------------------------------------------------
def links(markup, base=""):
    """The links of a piece of HTML as (address, label, the words just before it), in order. Only addresses this
    project would request are kept; nothing is fetched."""
    out = []
    for m in _HREF.finditer(markup[:2_000_000]):
        target = html.unescape(m.group(1) or m.group(2) or "").strip()
        try:
            address = validate_url(urljoin(base, target) if base else target)
        except ValueError:
            address = None
        if address:
            before = textrules.plain(markup[max(0, m.start() - 160):m.start()], 400)[-60:]
            out.append((address, textrules.plain(m.group(3), 400)[:120], before))
            if len(out) == LINKS:
                break
    return out


def _fits(rule, address, label="", before=""):
    parts = urlsplit(address)
    if parts.hostname != rule["host"]:
        return False
    if rule.get("path_ends"):
        return parts.path.rstrip("/").endswith(rule["path_ends"])
    return "transcript" in label.lower() or "transcript" in before.lower()


def page_from_feed(rule, link, feed_links):
    """The transcript page of an entry, as far as the feed alone says it, or None: the entry's own page ("link"), the
    first fitting link of its notes ("notes_link"), or the source's template filled with the last part of the entry's
    page address ("template")."""
    how = rule["from"]
    if how == "link":
        return link if link and urlsplit(link).hostname == rule["host"] else None
    if how == "notes_link":
        return next((a for a, label, before in feed_links if _fits(rule, a, label, before)), None)
    if how == "template" and link and urlsplit(link).hostname == rule["host"]:
        slug = urlsplit(link).path.rstrip("/").rsplit("/", 1)[-1]
        if re.fullmatch(r"[A-Za-z0-9._~-]{1,200}", slug):
            return validate_url(rule["template"].replace("{slug}", slug))
    return None


def page_from_page(rule, page_address, markup):
    """For "page_link": the transcript page an episode page links to. The link must fit the rule and lie under the
    episode page's own path, so a link to another episode's transcript elsewhere on the page is never taken."""
    own = urlsplit(page_address).path.rstrip("/") + "/"
    for address, label, before in links(markup, page_address):
        if _fits(rule, address, label, before) and (own == "/" or urlsplit(address).path.startswith(own)) and address != page_address:
            return address
    return None
