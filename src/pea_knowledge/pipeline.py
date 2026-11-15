# Copyright 2026 The PEA knowledge processor authors
# SPDX-License-Identifier: Apache-2.0
"""The pipeline: fetch and normalize (stages 1 and 2), digest (stage 3), build (stage 4).

The three parts talk through a work folder, so they can run as three jobs with different rights:

    work/work.json                         what was read from each source, and what each item needs
    work/transcripts/<source>/<item>.pea.txt   normalized transcripts (all of them, also those that may not be published)
    work/digests/<source>/<item>.json      digests, after stage 3

`build` then writes the output folder from the work folder and the previous output. It never edits the previous
output in place: the new folder is written beside it, checked as a whole, and only then put in its place.
"""
import datetime
import hashlib
import math
import os
import shutil
import statistics
import types
from urllib.parse import urlsplit

from . import FORMAT_VERSION, GENERATOR_NAME, __version__, adapters, digest as dg, fetch, htmlpage, jsonschema_lite, model_digest, probe, textrules, topics as tp, validate
from .transcript import convert, pea_transcript as pt

DEFAULTS = {"max_items": 6, "retention_days": 45, "auto_pause_after_failed_runs": 3, "tombstone_days": 90,
            "excerpt_budget_chars": 1_500, "suggested_keep": 5, "max_total_bytes": 40_000_000,
            # The rule of the catalog: an item is offered only when the assistant has a full path to its whole text, and a source only when
            # enough of its newest items are (docs/FORMAT.md, "Discussable items"). Of the newest `transcript_check_items`, at least
            # `min_discussable_items` and at least `min_full_transcript_share` of them must be discussable; 0 and 0 switch the rule off.
            "min_full_transcript_share": 0.6, "min_discussable_items": 2, "transcript_check_items": 5, "withdraw_without_transcripts_days": 30,
            # The phone-style probe of the newest discussable item (probe.py); an ok result is reused for this many hours.
            "phone_probe": True, "phone_probe_reuse_hours": 24,
            # The item rule itself. Only the tests of what a digest says about a thin item switch it off; the curated list never does.
            "only_discussable_items": True}
NO_TRANSCRIPTS = "full transcripts for"   # how the detail of the minimum rule starts; the reason code is empty or format_changed
REFUSED = probe.SENTENCE                  # how the detail of a failed probe starts; the reason code is fetch_failed
RULE_DETAILS = (NO_TRANSCRIPTS, REFUSED)
# Why an item is not in items.json (health.json, `dropped`): no transcript published, it could not be fetched, it could not be read,
# it was read but gives no address to fetch the whole text from, or the phone-style probe failed for it.
DROPPED = ("none_published", "fetch_failed", "unreadable", "no_source", "phone_probe")
RECENT_DAYS = 7          # a dropped item this young is asked for again every run: transcripts often appear a few days after the episode
TRANSCRIPT_TRIES = 3
SOURCE_REVISION = 1     # of what an item says about where its transcript is (`transcript_source`); a change makes every item anew
CHAPTERS_BYTES = 300_000
NEWS_SUMMARY_CHARS = 280


class ConfigError(Exception):
    pass


# --- Small helpers ---------------------------------------------------------------------------------------------------
def timestamp(now):
    return now.strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_timestamp(text):
    return datetime.datetime.strptime(text, "%Y-%m-%dT%H:%M:%SZ")


def sha256(data):
    return hashlib.sha256(data).hexdigest()


def write(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as f:
        f.write(data if isinstance(data, bytes) else data.encode("utf-8"))


def read(path):
    with open(path, "rb") as f:
        return f.read()


def note(text):
    """A sentence made fit for a report: plain text, no addresses, at most 240 characters."""
    return textrules.clean(text, 240) or "something was noticed that cannot be written here"


def reason(code, detail=""):
    return {"code": code, "detail": textrules.clean(detail, 200)}


def load_config(path):
    """config/sources.json, checked against its schema and the text rules. Raises ConfigError: a bad curated list
    stops the run before anything is fetched."""
    try:
        config = jsonschema_lite.loads(read(path))
    except (OSError, jsonschema_lite.NotJSON) as e:
        raise ConfigError("%s: %s" % (path, e)) from None
    errors = jsonschema_lite.validate(config, validate.schema("sources"))
    if errors:
        raise ConfigError("%s: %s %s" % (path, errors[0][0], errors[0][1]))
    seen = set()
    for s in config["sources"]:
        if s["id"] in seen:
            raise ConfigError("the source id %s is used twice" % s["id"])
        seen.add(s["id"])
        for key in ("url", "site"):
            if fetch.validate_url(s[key]) != s[key]:
                raise ConfigError("%s: %s is not a normalized public https address" % (s["id"], key))
        for key in ("name", "description", "overview", "publisher", "attribution", "message"):
            if key in s and textrules.check(s[key]) is not None:
                raise ConfigError("%s: %s breaks the text rules (%s)" % (s["id"], key, textrules.check(s[key])))
        if textrules.check(s["terms"]["summary"]) is not None:
            raise ConfigError("%s: terms.summary breaks the text rules" % s["id"])
        if s.get("state") in ("paused", "withdrawn") and not s.get("message"):
            raise ConfigError("%s: a manual %s state needs a message for the owner" % (s["id"], s["state"]))
        if s.get("purge") and s.get("state") != "withdrawn":
            raise ConfigError("%s: purge is only allowed with state withdrawn" % s["id"])
        if s["kind"] == "news" and s["publish"] != "digest_only":
            raise ConfigError("%s: a news source is always digest_only" % s["id"])
        page = s.get("transcript_page")
        if page is not None:
            if not fetch.is_public_host(page["host"]):
                raise ConfigError("%s: transcript_page.host is not a public host name" % s["id"])
            if (page["from"] == "template") != ("template" in page):
                raise ConfigError("%s: transcript_page.template goes with from: template, and only with it" % s["id"])
            if "template" in page and (page["template"].count("{slug}") != 1 or fetch.validate_url(page["template"].replace("{slug}", "x")) is None
                                       or not page["template"].startswith("https://%s/" % page["host"])):
                raise ConfigError("%s: transcript_page.template must be an https address on the host with {slug} once" % s["id"])
            try:
                htmlpage.Rules(page.get("extract"))
            except ValueError as e:
                raise ConfigError("%s: transcript_page.extract: %s" % (s["id"], e)) from None
    config["defaults"] = dict(DEFAULTS, **config.get("defaults", {}))
    try:
        known = set(tagger(config).ids) if tagger(config) else set()
    except tp.TopicsError as e:
        raise ConfigError(str(e)) from None
    for s in config["sources"]:
        for tid in s.get("topics", []):
            if tagger(config) and tid not in known:
                raise ConfigError("%s: the topic %s is not in config/topics.json" % (s["id"], tid))
    return config


_TAGGER = []


def tagger(config):
    """The topic tagger (the vocabulary and the lexicon beside the code), or None when the config switches topics off."""
    if not config.get("topics", {}).get("enabled", True):
        return None
    if not _TAGGER:
        _TAGGER.append(tp.Tagger())
    return _TAGGER[0]


def topics_key(config):
    """What an item's topics depend on besides its own text: the vocabulary, the lexicon, and who may tag. A change
    makes every item anew, so no item keeps a tag from an older vocabulary."""
    t = tagger(config)
    return "topics off" if t is None else "topics %s %s" % (t.fingerprint, "model" if config.get("model", {}).get("topics") else "keywords")


def setting(config, source, name):
    return source.get(name, config["defaults"][name])


class Previous:
    """The last published output, as far as it can be trusted: sources whose files do not all check out are treated
    as if they had never been published."""

    def __init__(self, folder):
        self.folder, self.store, self.listings, self.items, self.state = folder, None, {}, {}, {}
        if not folder or not os.path.isfile(os.path.join(folder, "store.json")):
            return
        store, problems = validate.check_store(read(os.path.join(folder, "store.json")))
        if store is None:
            return
        self.store = store
        for listing in store["sources"]:
            self.listings[listing["id"]] = listing
            if listing["items_file"] is not None and not validate.check_source_folder(folder, listing, topics=store.get("topics", [])):
                loaded = jsonschema_lite.loads(read(os.path.join(folder, *listing["items_file"]["path"].split("/"))))
                self.items[listing["id"]] = {i["id"]: i for i in loaded["items"]}
        path = os.path.join(folder, "state.json")
        if os.path.isfile(path):
            state, problems = validate.read_json(read(path), "state", "state.json", validate.HEALTH_BYTES)
            self.state = state["sources"] if state else {}


# --- Stages 1 and 2: fetch and normalize ---------------------------------------------------------------------------------
_RANK = (("vtt", 0), ("srt", 1), ("subrip", 1), ("json", 2), ("markdown", 3), ("plain", 3), ("text/", 3))


def transcript_order(listed):
    """The transcripts an entry lists, best first: WebVTT, SubRip, JSON, text, a type that is not known, and last an
    HTML page (read by htmlpage, which has more to leave out)."""
    ranked = []
    for n, (address, kind) in enumerate(listed):
        path = address.split("?")[0].lower()
        if "html" in kind or path.endswith((".html", ".htm")):
            rank = 5
        else:
            rank = next((r for mark, r in _RANK if mark in kind or path.endswith("." + mark)), 4)
        ranked.append((rank, n, address, kind))
    return [(address, kind) for _, _, address, kind in sorted(ranked)][:TRANSCRIPT_TRIES]


def decode(body):
    """A transcript's bytes as text, or None when they are not text: UTF-8 (with or without a mark), or UTF-16 with one."""
    if body[:2] in (b"\xff\xfe", b"\xfe\xff"):
        try:
            return body.decode("utf-16")
        except UnicodeDecodeError:
            return None
    try:
        return body.decode("utf-8-sig")
    except UnicodeDecodeError:
        return None


def source_format(written, kind, mime, address):
    """How a publisher's transcript is named in `transcript_source.format`: vtt, srt, json, html, markdown or text."""
    if written in ("vtt", "srt", "json", "html"):
        return written
    return "markdown" if "markdown" in kind + " " + mime or address.split("?")[0].lower().endswith((".md", ".markdown")) else "text"


def _checked(t):
    """The v1 file of a transcript, or None when it does not pass its own checks."""
    text = t.render()
    return text if pt.conforms(pt.validate(text.encode("utf-8"))) and len(text.encode("utf-8")) <= validate.TRANSCRIPT_BYTES else None


def _page(markup, rules, minimum, answer, source, item, address):
    """One HTML transcript page read into (status, reason, detail, text of the v1 file or None)."""
    try:
        t = htmlpage.read(markup, rules, minimum, truncated=answer.truncated, show=source["name"], title=item["title"], date=item["date"], source=address,
                          duration=item["duration_seconds"], language=source["language"])
    except htmlpage.PageProblem as e:
        return "no", e.code, e.detail, None
    except (RecursionError, MemoryError, ValueError, OverflowError):
        return "no", "unreadable", "the page could not be read", None
    text = _checked(t)
    if text is None:
        return "no", "unreadable", "the normalized transcript did not pass its own checks", None
    return ("partial", "cut", t.partial, text) if t.partial is not None else ("yes", None, "", text)


def page_transcript(fetcher, source, item, link, links):
    """The transcript of an item from the publisher's HTML transcript page, found by the source's `transcript_page`
    rule. Returns (status, reason, detail, text or None, where it was read or None)."""
    rule = source["transcript_page"]
    how = rule["from"]
    if how == "page_link":
        if not link or urlsplit(link).hostname != rule["host"]:
            return "no", "none_published", "the feed gives no page for this episode, so its transcript page cannot be found", None, None
        try:
            page = fetcher.get(link, fetch.TRANSCRIPT_BYTES)
        except fetch.FetchError as e:
            return "no", "fetch_failed", e.detail, None, None
        address = htmlpage.page_from_page(rule, page.url, page.body.decode("utf-8", "replace"))
        if address is None:
            return "no", "none_published", "the episode page links to no transcript page", None, None
    else:
        address = htmlpage.page_from_feed(rule, link, links)
        if address is None:
            return "no", "none_published", {"notes_link": "the notes link to no transcript page", "link": "the feed gives no page for this episode"}.get(
                how, "no transcript page follows from the episode's address"), None, None
    try:
        answer = fetcher.get(address, fetch.TRANSCRIPT_BYTES)
    except fetch.FetchError as e:   # also a page that is not there yet: counted as a failed fetch, so the next run asks again
        return "no", "fetch_failed", e.detail, None, None
    final = answer.url if fetch.validate_url(answer.url) == answer.url else address
    if urlsplit(final).hostname != rule["host"]:
        return "no", "unreadable", "the transcript page leads to another host", None, None
    rules = htmlpage.Rules(rule.get("extract"))
    status, why, detail, text = _page(answer.body.decode("utf-8", "replace"), rules, rule.get("min_chars", htmlpage.MINIMUM_CHARS), answer, source, item, final)
    origin = None if text is None else {"link": final, "format": "html", "route": "notes_link" if how == "notes_link" else "page", "bytes": len(answer.body),
                                        "extract": rules.published()}
    return status, why, detail, text, origin


def read_answer(source, item, address, kind, answer, minimum=None):
    """One fetched transcript file, read: (status, reason, detail, text of the v1 file or None, where it was read or None). Shared by the
    pipeline and by the phone-style probe, so both read a file the same way."""
    body = answer.body
    if answer.truncated:  # the cut may fall inside a character: the last few bytes are dropped until it decodes
        for trim in range(4):
            if decode(body[:len(body) - trim]) is not None:
                body = body[:len(body) - trim]
                break
    raw = decode(body)
    if raw is None or "\x00" in raw[:4000]:
        return "no", "unreadable", "not UTF-8 text", None, None
    if convert.detect_format(raw.replace("\ufeff", ""), type=kind, mime=answer.content_type, url=address) == "html":
        rules = htmlpage.Rules((source.get("transcript_page") or {}).get("extract"))
        status, why, detail, text = _page(raw, rules, minimum or htmlpage.MINIMUM_CHARS, answer, source, item, address)
        if text is None:
            return status, why, detail, None, None
        return status, why, detail, text, {"link": address, "format": "html", "route": "feed_tag", "bytes": len(answer.body), "extract": rules.published()}
    try:
        t = convert.normalize(raw, type=kind, mime=answer.content_type, truncated=answer.truncated, show=source["name"], title=item["title"],
                              date=item["date"], source=address, duration=item["duration_seconds"], language=source["language"])
    except convert.Unreadable as e:
        return "no", "unreadable", str(e), None, None
    except (RecursionError, MemoryError, ValueError, OverflowError):
        return "no", "unreadable", "the converter could not read it", None, None
    text = _checked(t)
    if text is None:
        return "no", "unreadable", "the normalized transcript did not pass its own checks", None, None
    origin = {"link": address, "format": source_format(t.format, kind, answer.content_type, address), "route": "feed_tag", "bytes": len(answer.body)}
    return ("partial", "cut", t.partial, text, origin) if t.partial is not None else ("yes", None, "", text, origin)


def normalize_transcript(fetcher, source, item, listed, link="", links=()):
    """Tries the listed transcripts in order, then the source's transcript page when it has a rule for one. Returns
    (status, reason, detail, text of the v1 file or None, where it was read or None). The last is what the item
    publishes as `transcript_source`: the publisher's own address, the format, how it was found and its size."""
    paged = source.get("transcript_page") is not None
    if not listed and not paged:
        return "no", "none_published", "", None, None
    outcome = ("no", "fetch_failed", "nothing was tried", None, None)
    for address, kind in transcript_order(listed):
        try:
            answer = fetcher.get(address, fetch.TRANSCRIPT_BYTES)
        except fetch.FetchError as e:
            outcome = ("no", "fetch_failed", e.detail, None, None)
            continue
        outcome = read_answer(source, item, address, kind, answer)
        if outcome[3] is not None:
            return outcome
    if paged:
        return page_transcript(fetcher, source, item, link, links)
    return outcome


def item_key(entry, source, config=None):
    """What an item's digest and topics depend on at the publisher. The same key next run means there is nothing to redo."""
    parts = [entry.title, entry.date, entry.link, entry.summary[:200], source["publish"], source["kind"]] + [a for a, _ in entry.transcripts]
    if config is not None:
        parts += [topics_key(config), ",".join(source.get("topics", []))]
    rule = source.get("transcript_page")
    if rule and rule["from"] != "page_link":   # a transcript page that appears in the notes later makes the item anew
        parts.append(htmlpage.page_from_feed(rule, entry.link, entry.links) or "")
    marks = jsonschema_lite.dumps([dg.DIGEST_REVISION, entry.people, entry.chapters, entry.chapters_url, entry.soundbites, entry.resources, "source %d" % SOURCE_REVISION])
    return sha256("\x1f".join(parts + [marks]).encode("utf-8", "replace"))


def source_key(config, source):
    """What a source's item list depends on in the config. When it changes, an unchanged feed is still read again."""
    parts = [source["url"], source["adapter"], source["publish"], source["kind"], "digest revision %d" % dg.DIGEST_REVISION, "generator %s" % __version__, ",".join(source.get("hosts", [])),
             topics_key(config), ",".join(source.get("topics", []))] \
        + [str(setting(config, source, n)) for n in ("max_items", "retention_days", "excerpt_budget_chars")] \
        + ([jsonschema_lite.dumps(source["transcript_page"])] if "transcript_page" in source else [])
    return sha256("\x1f".join(parts).encode("utf-8"))


def discussable(entry):
    """True for an index entry the assistant can discuss in depth: the pipeline read its transcript in full or in part, and the entry says where
    the whole text can be fetched from (`transcript_source`). Only such entries are published."""
    return transcript_read(entry) != "none" and "transcript_source" in entry


def no_text_reason(t):
    """Why a transcript of the work folder gives no discussable item: one of DROPPED."""
    if t["status"] in ("yes", "partial"):
        return "no_source"
    return t["reason"] if t["reason"] in ("none_published", "fetch_failed", "unreadable") else "none_published"


def drop_reason(entry):
    """Why an index entry of an earlier output is not discussable: one of DROPPED."""
    if transcript_read(entry) != "none":
        return "no_source"
    return entry["transcript"]["reason"] if entry["transcript"]["reason"] in ("none_published", "fetch_failed", "unreadable") else "none_published"


def judge(config, source, record, before_items):
    """None when the source keeps the rule of the catalog, otherwise {"code", "detail"}: of its newest items too few are discussable. Of the newest
    `transcript_check_items`, at least `min_discussable_items` and at least `min_full_transcript_share` of them must be (one count, one rule: the
    share is not counted again anywhere). Code `format_changed` when the source had discussable items before (it used to work and no longer does)
    or still has some; code `empty` when it has none now and never had. The detail is one plain sentence."""
    share, floor = setting(config, source, "min_full_transcript_share"), setting(config, source, "min_discussable_items")
    if not share and not floor:
        return None
    newest = record["items"][:setting(config, source, "transcript_check_items")]
    found = sum(1 for i in newest if i["discussable"])
    needed = max(floor, math.ceil(share * len(newest) - 1e-9))
    if found >= needed:
        return None
    return {"code": "empty" if found == 0 and not any(discussable(e) for e in before_items.values()) else "format_changed",
            "detail": textrules.clean("%s %d of the newest %d items; the catalog carries a source only when at least %d of them (and %d percent) can be read in full" % (
                NO_TRANSCRIPTS, found, len(newest), floor, round(share * 100)), 200)}


def phone_read(source, item, origin):
    """The probe's converter for one item: None when the body converts with this repository's own readers, else one sentence on why not."""
    rule = source.get("transcript_page") or {}
    minimum = rule.get("min_chars") if origin.get("route") in ("page", "notes_link") else None

    def read(body, content_type, truncated):
        answer = types.SimpleNamespace(body=body, content_type=content_type, truncated=truncated)
        _, why, detail, text, _ = read_answer(source, item, origin["link"], probe.DECLARED_TYPES.get(origin["format"], "text/plain"), answer, minimum)
        return None if text is not None else textrules.clean(detail or why or "it could not be read", 200)
    return read


def run_probe(config, source, record, fetcher, now, before):
    """The phone-style probe (probe.py) of the newest discussable item: one request, or the last ok result when it is still fresh and nothing
    changed. Returns {"item", "result", "reason", "checked_at", "reused", "link", "key"} or None when there is nothing to probe or it is off.
    A failed item is marked dropped."""
    if not setting(config, source, "phone_probe"):
        return None
    item = next((i for i in record["items"] if i["discussable"] and i["origin"]), None)
    if item is None:
        return None
    origin, memo = item["origin"], before.get("probe")
    hours = setting(config, source, "phone_probe_reuse_hours")
    if memo and memo["result"] == "ok" and (memo["item"], memo["link"], memo["key"]) == (item["id"], origin["link"], item["key"]) \
            and now - parse_timestamp(memo["at"]) < datetime.timedelta(hours=hours):
        result = {"result": "ok", "reason": None, "checked_at": memo["at"], "reused": True}
    else:
        result = dict(probe.probe(fetcher, origin, phone_read(source, item, origin)), checked_at=timestamp(now), reused=False)
    if result["result"] == "failed":
        item["discussable"], item["dropped"] = False, "phone_probe"
    return dict(result, item=item["id"], link=origin["link"], key=item["key"])


def fetch_stage(config, work, fetcher, previous, now, mode="live", log=print):
    """Reads every source that is not manually switched off and writes the work folder."""
    wanted = "model" if model_digest.Settings(config.get("model")).enabled else "extractive"
    out = {"now": timestamp(now), "mode": mode, "sources": {}}
    for source in config["sources"]:
        sid = source["id"]
        record = {"outcome": "ok", "reason": None, "notes": [], "items": [], "etag": "", "last_modified": "", "fingerprint": "", "rule": None, "phone_probe": None}
        out["sources"][sid] = record
        if source.get("state") in ("paused", "withdrawn"):
            record["outcome"] = "skipped"
            continue
        before, before_items = previous.state.get(sid, {}), previous.items.get(sid, {})
        settled = bool(before_items) and before.get("config") == source_key(config, source) and not any(i["stale"] or i["transcript"]["reason"] == "fetch_failed" for i in before_items.values()) \
            and all(m["method"] == wanted or before_items.get(i, {}).get("digest", {}).get("basis") != "transcript" for i, m in before.get("items", {}).items())
        try:
            answer = fetcher.get(source["url"], fetch.FEED_BYTES, before.get("etag", "") if settled else "", before.get("last_modified", "") if settled else "")
            if answer.not_modified:
                record.update(outcome="unchanged", etag=before.get("etag", ""), last_modified=before.get("last_modified", ""), fingerprint=before.get("fingerprint", ""))
                log("%s: not modified" % sid)
                continue
            body, cut = answer.body, False
            if answer.truncated:   # a very long feed: the whole entries at its head are read, the rest is not needed
                body, cut = (adapters.head_of_feed(body) if source["adapter"] == "feed" else None), True
                if body is None:
                    raise fetch.FetchError("http_error", "the feed is larger than %d bytes" % fetch.FEED_BYTES)
            listing = adapters.ADAPTERS[source["adapter"]](body)
            if cut:
                listing.notes.append("the feed is larger than %d bytes: its newest %d entries were read" % (fetch.FEED_BYTES, len(listing.entries)))
        except fetch.FetchError as e:
            record.update(outcome="failed", reason=reason("robots_disallowed" if e.code == "robots_disallowed" else "fetch_failed", e.detail))
            log("%s: %s" % (sid, e))
            continue
        except adapters.AdapterError as e:
            record.update(outcome="failed", reason=reason(e.code, e.detail))
            log("%s: %s" % (sid, e))
            continue
        record.update(etag=answer.etag, last_modified=answer.last_modified, fingerprint=listing.fingerprint)
        record["notes"] += [note(n) for n in listing.notes]
        if before.get("fingerprint") and before["fingerprint"] != listing.fingerprint:
            gone = sorted(set(before["fingerprint"].split(",")) - set(listing.fingerprint.split(",")))
            record["notes"].append(note("the feed changed shape" + (": no longer has " + ", ".join(gone) if gone else ": it has new parts")))
        oldest = (now - datetime.timedelta(days=setting(config, source, "retention_days"))).date().isoformat()
        future = (now + datetime.timedelta(days=2)).date().isoformat()
        entries = [e for e in listing.entries if oldest <= e.date <= future][:setting(config, source, "max_items")]
        if not entries:
            record["notes"].append(note("no entry is newer than %s" % oldest))
        recent = (now - datetime.timedelta(days=RECENT_DAYS)).date().isoformat()
        newer = False   # a newer item of this source is already discussable
        for e in entries:
            news = source["kind"] == "news"
            item = {"id": e.id, "title": e.title, "date": e.date, "link": e.link or source["site"], "link_kind": "episode" if e.link else "show",
                    "duration_seconds": e.duration, "tags": e.tags,
                    "people": [] if news else [list(p) for p in e.people], "chapters": [] if news else [list(c) for c in e.chapters],
                    "soundbites": [] if news else [list(b) for b in e.soundbites], "resources": [] if news else list(e.resources),
                    "summary": textrules.first_sentences(e.summary, NEWS_SUMMARY_CHARS, most=2) if news else e.summary,
                    "notes": "" if news else e.notes, "key": item_key(e, source, config), "reuse": False,
                    "transcript": {"status": "no", "reason": "none_published", "detail": "", "file": None},
                    "dropped": None, "origin": None, "discussable": False}
            known = before.get("items", {}).get(e.id)
            old = before_items.get(e.id)
            why_out = known["dropped"] if known and known["key"] == item["key"] and known.get("dropped") else None
            if why_out and (why_out == "fetch_failed" or (why_out == "phone_probe" and not newer) or (why_out != "phone_probe" and e.date >= recent)):
                why_out = None    # asked for again: it may have been mended
            if why_out:   # judged before and nothing changed: not fetched again
                item["reuse"], item["dropped"] = True, why_out
            elif known and old and known["key"] == item["key"] and not old["stale"] and old["transcript"]["reason"] != "fetch_failed" \
                    and (known["method"] == wanted or old["digest"]["basis"] != "transcript") and (discussable(old) or e.date < recent or not setting(config, source, "only_discussable_items")):
                item["reuse"] = True
                if discussable(old):
                    item["origin"] = old["transcript_source"]
                elif setting(config, source, "only_discussable_items"):
                    item["dropped"] = drop_reason(old)
            elif not news:
                status, why, detail, text, origin = normalize_transcript(fetcher, source, item, e.transcripts, e.link, e.links)
                item["transcript"] = {"status": status, "reason": why, "detail": textrules.clean(detail, 200), "file": None, "source": origin}
                if text is not None:
                    item["transcript"]["file"] = "transcripts/%s/%s.pea.txt" % (sid, e.id)
                    write(os.path.join(work, *item["transcript"]["file"].split("/")), text)
                if not item["chapters"] and e.chapters_url:   # the publisher's chapter file, when the feed has no inline marks
                    try:
                        item["chapters"] = [list(c) for c in adapters.chapters_file(fetcher.get(e.chapters_url, CHAPTERS_BYTES).body)]
                    except fetch.FetchError as error:
                        record["notes"].append(note("%s: the chapter file could not be read (%s)" % (e.id, error.detail)))
            if not item["reuse"]:
                t = item["transcript"]
                if t["status"] in ("yes", "partial") and t.get("source"):
                    item["origin"] = t["source"]
                elif old and discussable(old) and old["digest"]["basis"] == "transcript" and t["reason"] in ("fetch_failed", "unreadable"):
                    item["origin"] = old["transcript_source"]   # the earlier copy is kept, marked stale (build_stage)
                elif setting(config, source, "only_discussable_items"):
                    item["dropped"] = no_text_reason(t)
            item["discussable"] = item["dropped"] is None
            newer = newer or item["discussable"]
            record["items"].append(item)
        log("%s: %d items (%d reused)" % (sid, len(record["items"]), sum(1 for i in record["items"] if i["reuse"])))
        record["rule"] = judge(config, source, record, before_items)
        record["phone_probe"] = None
        if record["rule"] is None:
            record["phone_probe"] = run_probe(config, source, record, fetcher, now, before)
            if record["phone_probe"] and record["phone_probe"]["result"] == "failed":
                record["rule"] = {"code": "fetch_failed", "detail": textrules.clean("%s: %s" % (REFUSED, record["phone_probe"]["reason"]["detail"]), 200)}
                log("%s: the phone-style probe failed (%s)" % (sid, record["phone_probe"]["reason"]["detail"]))
    out["requests"] = fetcher.requests
    write(os.path.join(work, "work.json"), jsonschema_lite.dumps(out))
    return out


# --- Stage 3: digest -----------------------------------------------------------------------------------------------------
def digest_stage(config, work, environment=None, log=print):
    """Writes a digest for every item of the work folder that needs one. Always works without a key."""
    state = jsonschema_lite.loads(read(os.path.join(work, "work.json")))
    settings = model_digest.Settings(config.get("model"), environment)
    budget = model_digest.Budget(settings)
    use_model = settings.enabled and bool(settings.key)
    by_id = {s["id"]: s for s in config["sources"]}
    tags = tagger(config)
    for sid, record in state["sources"].items():
        source = by_id[sid]
        excerpt = None if source["publish"] == "full" else setting(config, source, "excerpt_budget_chars")
        for item in record["items"]:
            if item["reuse"] or item.get("dropped"):
                continue
            earlier = [(i["id"], i["title"]) for i in record["items"] if (i["date"], i["id"]) < (item["date"], item["id"])]
            transcript = None
            if item["transcript"]["file"]:
                transcript = pt.parse(read(os.path.join(work, *item["transcript"]["file"].split("/"))).decode("utf-8"))
            made, proposed = None, []
            if use_model and transcript is not None:
                made = model_digest.digest(settings, budget, source, item, transcript, excerpt, earlier, log,
                                           vocabulary=tags.topics if tags and settings.topics else None, proposed=proposed)
            if made is None:
                made, proposed = dg.extractive(source, item, transcript, excerpt, earlier), []
            write(os.path.join(work, "digests", sid, item["id"] + ".json"), jsonschema_lite.dumps(made))
            if tags is not None:
                # Topics. The keyword tagger always can; a model's topics are taken only when they hold up against the digest.
                fields = tp.fields_of(item, made, transcript)
                checked = tags.from_model(proposed[0], fields) if proposed else []
                item["topics"] = checked or tags.tag(fields, source.get("topics", ()))
                item["topics_by"] = "model" if checked else "keywords"
    report = dict(budget.report(), requested=settings.enabled, used=use_model and budget.accepted > 0, model=settings.model[:80] if use_model else None,
                  note=None if use_model or not settings.enabled else "a model digest is switched on but no key was given, so every digest is extractive")
    state["model"] = report
    write(os.path.join(work, "work.json"), jsonschema_lite.dumps(state))
    if settings.enabled:
        log("model: %(calls)d calls, %(accepted)d accepted, %(fell_back)d fell back, %(skipped_for_budget)d skipped, cost USD %(cost_usd).4f" % report)
    return report


# --- Stage 4: build ------------------------------------------------------------------------------------------------------
def _cadence(dates):
    days = sorted({datetime.date.fromisoformat(d) for d in dates}, reverse=True)[:10]
    if len(days) < 3:
        return "unknown"
    gap = statistics.median((a - b).days for a, b in zip(days, days[1:]))
    for limit, name in ((1.5, "daily"), (4, "several_per_week"), (10, "weekly"), (20, "fortnightly"), (45, "monthly")):
        if gap <= limit:
            return name
    return "irregular"


def _whats_new(items):
    if not items:
        return None
    line = "Newest: %s (%s)." % (items[0]["title"], items[0]["date"])
    if len(items) > 1:
        line += " Before that: %s (%s)." % (items[1]["title"], items[1]["date"])
    return textrules.shorten(line, 240)


def _listing(config, source, items, items_ref, state, state_reason, message, purge, state_since, freshness):
    durations = [i["duration_seconds"] for i in items if i["duration_seconds"] is not None]
    known = set(tagger(config).ids) if tagger(config) else None
    beat = {} if known is None else {"topics": [t for t in source.get("topics", []) if t in known]}
    return {
        **beat,
        "id": source["id"], "name": source["name"], "description": source["description"], "overview": source["overview"],
        "categories": source["categories"], "language": source["language"], "kind": source["kind"], "publisher": source["publisher"],
        "site": source["site"], "icon": source["icon"], "cadence": _cadence([i["date"] for i in items]),
        "typical_duration_seconds": int(statistics.median(durations)) if durations else None,
        "publish": source["publish"], "terms_summary": source["terms"]["summary"] if "terms" in source else source["terms_summary"],
        "attribution": source["attribution"], "state": state, "state_reason": state_reason, "message": message, "purge": purge,
        "state_since": state_since, "freshness": freshness, "item_count": len(items), "latest_titles": [i["title"] for i in items[:3]],
        "latest_date": items[0]["date"] if items else None,
        "available": {"digest": len(items), "transcript": sum(1 for i in items if i["transcript"]["file"]), "link_back": True},
        "avg_bytes": sum(i["bytes"] for i in items) // len(items) if items else 0,
        "suggested_keep": source.get("suggested_keep", config["defaults"]["suggested_keep"]),
        "whats_new": _whats_new(items), "items_file": items_ref,
    }


def _new_item(config, source, work, item):
    """The index entry and the files of an item made in this run. Returns (entry, {path: bytes})."""
    sid, iid = source["id"], item["id"]
    files = {}
    digest_bytes = read(os.path.join(work, "digests", sid, iid + ".json"))
    d = jsonschema_lite.loads(digest_bytes)
    path = "sources/%s/%s.digest.json" % (sid, iid)
    files[path] = digest_bytes
    t = item["transcript"]
    read_at_publisher = {"yes": "full", "partial": "partial"}.get(t["status"], "none")
    transcript = {"available": "no", "reason": t["reason"], "file": None, "read": read_at_publisher}
    if t["file"]:
        if source["publish"] == "full":
            data = read(os.path.join(work, *t["file"].split("/")))
            tpath = "sources/%s/%s.transcript.pea.txt" % (sid, iid)
            files[tpath] = data
            transcript = {"available": t["status"], "reason": t["reason"], "file": {"path": tpath, "sha256": sha256(data), "bytes": len(data)}, "read": read_at_publisher}
        else:
            transcript["reason"] = "withheld_terms"
    entry = {"id": iid, "title": item["title"], "date": item["date"], "link": item["link"], "link_kind": item.get("link_kind", "episode"),
             "duration_seconds": item["duration_seconds"],
             "tags": item["tags"], "teaser": textrules.shorten(d["about"], 240), "stale": False, "stale_reason": None,
             "bytes": sum(len(b) for b in files.values()),
             "digest": {"path": path, "sha256": sha256(digest_bytes), "bytes": len(digest_bytes), "basis": d["basis"], "grade": d["quality"]["grade"],
                        "method": d["provenance"]["method"]},
             "transcript": transcript}
    if t.get("source") and t["file"]:   # where the publisher itself offers the transcript, for a reader that fetches it there
        entry["transcript_source"] = t["source"]
    if tagger(config) is not None and "topics" in item:
        entry["topics"], entry["topics_by"] = item["topics"], item["topics_by"]
    return entry, files


def _fit_topics(config, entry):
    """An index entry kept from an earlier run, with its topics made to fit this run's vocabulary: none when topics
    are switched off, and no id the vocabulary no longer has."""
    if "topics" not in entry:
        return entry
    t = tagger(config)
    if t is None:
        return {k: v for k, v in entry.items() if k not in ("topics", "topics_by")}
    if all(x["id"] in t.order for x in entry["topics"]):
        return entry
    return dict(entry, topics=[x for x in entry["topics"] if x["id"] in t.order])


def transcript_read(entry):
    """What was read at the publisher for an index entry: "full", "partial" or "none". An entry written before 1.1
    does not say; then a transcript in the output, or a digest made from one, counts as it stands."""
    t = entry["transcript"]
    if "read" in t:
        return t["read"]
    if t["available"] != "no":
        return "full" if t["available"] == "yes" else "partial"
    return "full" if t["reason"] == "withheld_terms" and entry["digest"]["basis"] == "transcript" and entry["digest"]["grade"] != "partial" else "none"


def _old_files(previous, entry):
    files = {entry["digest"]["path"]: read(os.path.join(previous.folder, *entry["digest"]["path"].split("/")))}
    if entry["transcript"]["file"]:
        p = entry["transcript"]["file"]["path"]
        files[p] = read(os.path.join(previous.folder, *p.split("/")))
    return files


def blank_report(sid, outcome, state, reason_, notes=()):
    """One source's entry in health.json before anything is counted."""
    return {"id": sid, "outcome": outcome, "state": state, "reason": reason_, "items": 0, "new": 0, "reused": 0, "kept": 0, "stale": 0, "pruned": 0,
            "transcripts": dict.fromkeys(("yes", "partial", "none_published", "fetch_failed", "unreadable", "withheld_terms"), 0),
            "dropped": dict.fromkeys(DROPPED, 0), "phone_probe": None, "digests": {"extractive": 0, "model": 0}, "notes": list(notes)}


def build_stage(config, work, previous, out, now, log=print):
    """Writes the output folder. Returns the health report. Raises RuntimeError when the result does not validate:
    then nothing is put in place and the previous output stays as it was."""
    state = jsonschema_lite.loads(read(os.path.join(work, "work.json")))
    stamp = timestamp(now)
    staging = out.rstrip("/\\") + ".building"
    shutil.rmtree(staging, ignore_errors=True)
    os.makedirs(staging)
    listings, health_sources, memory, total_items = [], [], {}, 0
    pause_after = config["defaults"]["auto_pause_after_failed_runs"]
    last_run = previous.store["generated_at"] if previous.store else None
    vocabulary = {"topics": tagger(config).topics} if tagger(config) else {}

    def tombstone(source, old, why, message, purge):
        since = old["state_since"] if old and old["state"] == "withdrawn" else stamp
        if (now - parse_timestamp(since)).days > config["defaults"]["tombstone_days"]:
            return None
        return _listing(config, source, [], None, "withdrawn", why, message, purge, since,
                        {"status": "stale", "last_ok": (old or {}).get("freshness", {}).get("last_ok") or (last_run if old and old["freshness"]["status"] == "fresh" else None), "failed_runs": 0})

    for source in config["sources"]:
        sid = source["id"]
        record = state["sources"].get(sid, {"outcome": "skipped", "reason": None, "notes": [], "items": []})
        old = previous.listings.get(sid)
        # Only discussable entries are published, so an entry of an older output that is not one is left out here, whatever else happens.
        old_items = {iid: _fit_topics(config, entry) for iid, entry in previous.items.get(sid, {}).items() if discussable(entry) or not setting(config, source, "only_discussable_items")}
        report = blank_report(sid, record["outcome"], "active", record["reason"], record["notes"])
        if record.get("phone_probe"):
            report["phone_probe"] = {k: record["phone_probe"][k] for k in ("item", "result", "reason", "checked_at", "reused")}
        health_sources.append(report)
        if source.get("state") == "withdrawn":
            entry = tombstone(source, old, reason(source.get("state_reason", "manual")), source["message"], bool(source.get("purge")))
            report["state"] = "withdrawn"
            if entry is None:
                report["notes"].append("withdrawn long enough ago: no longer listed; it can be removed from the config")
            else:
                listings.append(entry)
            continue
        read_feed = record["outcome"] == "ok"
        earlier = previous.state.get(sid, {})
        if record["outcome"] == "unchanged":   # nothing was read this run: what the last run found is still true
            report["dropped"].update(earlier.get("skipped", {}))
            if earlier.get("probe"):
                report["phone_probe"] = {"item": earlier["probe"]["item"], "result": "ok", "reason": None, "checked_at": earlier["probe"]["at"], "reused": True}
        rule = record.get("rule") if record["outcome"] == "ok" else None
        short = rule["detail"] if rule else None
        if rule:   # read without trouble, but not what the catalog carries: counted like a failed read
            record = dict(record, outcome="failed", reason=reason(rule["code"], short))
            report.update(outcome="failed", reason=record["reason"])
            report["notes"].append(note("the publisher refuses requests like the app's, so the newest transcript cannot be fetched by the phone" if short.startswith(REFUSED)
                                        else "too few of the newest items can be discussed in full"))
        for item in (record["items"] if record["outcome"] in ("ok", "failed") else []):
            if item.get("dropped"):   # not discussable: counted here, never listed; the first few are named so the owner sees which
                report["dropped"][item["dropped"]] += 1
                if sum(report["dropped"].values()) <= 4:
                    report["notes"].append(note("%s: not listed, no full path to its text (%s)" % (item["id"], item["transcript"]["detail"] or item["dropped"].replace("_", " "))))
        dropped_ids = {i["id"] for i in record["items"] if i.get("dropped")}
        entries, files = {}, {}
        if record["outcome"] == "ok":
            for item in record["items"]:
                if item.get("dropped"):
                    continue
                before = old_items.get(item["id"])
                if item["reuse"] and before:
                    entries[item["id"]] = before
                    files.update(_old_files(previous, before))
                    report["reused"] += 1
                    continue
                worse = before and before["digest"]["basis"] == "transcript" and item["transcript"]["reason"] in ("fetch_failed", "unreadable")
                if worse:
                    entries[item["id"]] = dict(before, stale=True, stale_reason=item["transcript"]["reason"])
                    files.update(_old_files(previous, before))
                    report["notes"].append(note("%s: the transcript could not be refreshed (%s), the earlier copy is kept" % (item["id"], item["transcript"]["detail"] or item["transcript"]["reason"])))
                    continue
                entry, made = _new_item(config, source, work, item)
                entries[item["id"]] = entry
                files.update(made)
                report["reused" if entry == before else "new"] += 1   # asked again (a transcript that failed last time) and nothing came of it: not new
                if item["transcript"]["reason"] in ("fetch_failed", "unreadable"):
                    report["notes"].append(note("%s: no transcript (%s)" % (item["id"], item["transcript"]["detail"] or item["transcript"]["reason"])))
        for iid, before in old_items.items():   # what the feed no longer lists, or what this run did not read
            if iid not in entries and (iid not in dropped_ids or record["outcome"] != "ok"):
                entries[iid] = before
                files.update(_old_files(previous, before))
                report["kept"] += 1
        oldest = (now - datetime.timedelta(days=setting(config, source, "retention_days"))).date().isoformat()
        ordered = sorted(entries.values(), key=lambda i: (i["date"], i["id"]), reverse=True)
        frozen = record["outcome"] in ("failed", "skipped")    # a source that could not be read keeps exactly what it had
        kept = ordered if frozen else [i for i in ordered if i["date"] >= oldest][:setting(config, source, "max_items")]
        report["pruned"] = len(ordered) - len(kept)
        wanted = {i["digest"]["path"] for i in kept} | {i["transcript"]["file"]["path"] for i in kept if i["transcript"]["file"]}
        files = {p: b for p, b in files.items() if p in wanted}

        # The lifecycle state: a manual one always wins; otherwise a run of failures pauses the source.
        failed_before = old["freshness"]["failed_runs"] if old else 0
        last_ok = None
        if record["outcome"] in ("ok", "unchanged"):
            failed, status = 0, "fresh"
        else:
            failed = failed_before + (1 if record["outcome"] == "failed" else 0)
            status = "stale"
            last_ok = (old["freshness"]["last_ok"] if old["freshness"]["status"] == "stale" else last_run) if old else None
        manual = source.get("state")
        if manual == "paused":
            lifecycle, why, message = "paused", reason(source.get("state_reason", "manual")), source["message"]
        elif record["outcome"] == "failed" and failed >= pause_after and manual != "active":
            lifecycle, why = "paused", record["reason"]
            message = "This source could not be read %d times in a row. What is shown is the last good copy." % failed
            if short:
                message = ("This source's publisher refuses requests like the app's, so it is paused. What is shown is the last good copy." if short.startswith(REFUSED) else
                           "This source no longer publishes full transcripts for most new episodes, so it is paused. What is shown is the last good copy.")
        else:
            lifecycle, why, message = "active", record["reason"] if record["outcome"] == "failed" else None, None
        since = None if lifecycle == "active" else (old["state_since"] if old and old["state"] == lifecycle else stamp)
        if lifecycle == "paused":
            status = "stale"
            if record["outcome"] != "failed" and old:
                last_ok = old["freshness"]["last_ok"] if old["freshness"]["status"] == "stale" else last_run
        freshness = {"status": status, "last_ok": last_ok, "failed_runs": failed}
        gone = old is not None and old["state"] == "withdrawn" and (old["state_reason"] or {}).get("detail", "").startswith(RULE_DETAILS)
        if short and manual is None and (gone or (lifecycle == "paused" and (now - parse_timestamp(since)).days >= config["defaults"]["withdraw_without_transcripts_days"])):
            # Paused long enough for want of transcripts: withdrawn. It is still read every run and comes back by itself.
            entry = tombstone(source, old, reason("quality", short), "This source's publisher refuses requests like the app's, so it was removed from the catalog." if short.startswith(REFUSED)
                              else "This source stopped publishing full transcripts and was removed from the catalog.", False)
            report.update(state="withdrawn", kept=0, pruned=len(old_items))
            report["notes"].append("withdrawn: the source has failed the catalog's rule for %d days" % config["defaults"]["withdraw_without_transcripts_days"] if entry
                                   else "withdrawn long enough ago: no longer listed; it can be removed from the config")
            if entry is not None:
                entry["freshness"]["failed_runs"] = failed
                listings.append(entry)
            continue

        items_ref = None
        if kept:
            data = jsonschema_lite.dumps({"format": "pea-knowledge-items", "format_version": FORMAT_VERSION, "source_id": sid, "items": kept}).encode("utf-8")
            items_ref = {"path": "sources/%s/items.json" % sid, "sha256": sha256(data), "bytes": len(data)}
            files[items_ref["path"]] = data
        listing = _listing(config, source, kept, items_ref, lifecycle, why, message, False, since, freshness)
        for path, data in files.items():
            write(os.path.join(staging, *path.split("/")), data)
        problems = validate.check_source_folder(staging, listing, topics=vocabulary.get("topics", []))
        _, listing_problems = validate.check_store(jsonschema_lite.dumps({"format": "pea-knowledge-store", "format_version": FORMAT_VERSION, "generated_at": stamp,
                                                                           "generator": {"name": GENERATOR_NAME, "version": __version__}, "min_app_version": None,
                                                                           "sources": [listing], **vocabulary}).encode("utf-8"))
        problems += listing_problems
        if problems:
            # Never publish a source that does not check out: put back its last good copy, count the run as failed.
            log("%s: the new output does not validate (%s); the last good copy is kept" % (sid, problems[0]))
            shutil.rmtree(os.path.join(staging, "sources", sid), ignore_errors=True)
            why = reason("invalid_output", "%s: %s" % (problems[0].code, problems[0].detail))
            failed = failed_before + 1
            kept = sorted(old_items.values(), key=lambda i: (i["date"], i["id"]), reverse=True)
            items_ref = old["items_file"] if old and kept else None
            if kept:
                shutil.copytree(os.path.join(previous.folder, "sources", sid), os.path.join(staging, "sources", sid))
                if old_items != previous.items.get(sid):   # the last good copy named topics this run's vocabulary does not have
                    data = jsonschema_lite.dumps({"format": "pea-knowledge-items", "format_version": FORMAT_VERSION, "source_id": sid, "items": kept}).encode("utf-8")
                    items_ref = {"path": "sources/%s/items.json" % sid, "sha256": sha256(data), "bytes": len(data)}
                    write(os.path.join(staging, *items_ref["path"].split("/")), data)
            paused = failed >= pause_after and manual != "active" or manual == "paused"
            listing = _listing(config, source, kept, items_ref, "paused" if paused else "active", why,
                               ("This source could not be read %d times in a row. What is shown is the last good copy." % failed) if paused else None, False,
                               (old["state_since"] if old and old["state"] == "paused" else stamp) if paused else None,
                               {"status": "stale", "last_ok": (old["freshness"]["last_ok"] if old["freshness"]["status"] == "stale" else last_run) if old else None, "failed_runs": failed})
            report.update(outcome="failed", reason=why, new=0, reused=0, kept=len(kept), pruned=0)
            lifecycle = listing["state"]
            memory[sid] = previous.state.get(sid, {"etag": "", "last_modified": "", "fingerprint": "", "items": {}})
        else:
            fresh = {i["id"]: i for i in record["items"]} if record["outcome"] == "ok" else {}
            before = previous.state.get(sid, {})
            memory[sid] = {"config": source_key(config, source), "etag": record.get("etag", "") if record["outcome"] in ("ok", "unchanged") else "" if short else before.get("etag", ""),
                           "last_modified": record.get("last_modified", "") if record["outcome"] in ("ok", "unchanged") else "" if short else before.get("last_modified", ""),
                           "fingerprint": record.get("fingerprint", "") or before.get("fingerprint", ""),
                           "items": {i["id"]: {"key": fresh[i["id"]]["key"] if i["id"] in fresh else before.get("items", {}).get(i["id"], {}).get("key", "0" * 64),
                                               "method": i["digest"]["method"]} for i in kept}}
            for i in (record["items"] if sid in state["sources"] else []):   # what was judged not discussable is remembered, so it is not fetched again
                if i.get("dropped") and i["id"] not in memory[sid]["items"] and record["outcome"] in ("ok", "failed"):
                    memory[sid]["items"][i["id"]] = {"key": i["key"], "method": "extractive", "dropped": i["dropped"]}
            memory[sid]["skipped"] = dict(report["dropped"]) if read_feed else earlier.get("skipped", dict.fromkeys(DROPPED, 0))
            asked = record.get("phone_probe")
            if asked and asked["result"] == "ok":   # a good result is reused while it is fresh (run_probe)
                memory[sid]["probe"] = {"item": asked["item"], "link": asked["link"], "key": asked["key"], "at": asked["checked_at"], "result": "ok"}
            elif record["outcome"] in ("unchanged", "skipped") and before.get("probe"):
                memory[sid]["probe"] = before["probe"]
        report["state"], report["items"] = lifecycle, len(kept)
        report["stale"] = sum(1 for i in kept if i["stale"])
        for i in kept:
            report["transcripts"][i["transcript"]["reason"] if i["transcript"]["available"] == "no" else i["transcript"]["available"]] += 1
            report["digests"][i["digest"]["method"]] += 1
        total_items += len(kept)
        listings.append(listing)

    configured = {s["id"] for s in config["sources"]}
    for sid, old in previous.listings.items():   # a source taken out of the config is withdrawn, and says so for a while
        if sid in configured:
            continue
        was = old["state"] == "withdrawn"
        entry = tombstone(old, old, old["state_reason"] if was else reason("removed"), old["message"] if was else "The curator removed this source.", old["purge"] if was else False)
        gone_report = blank_report(sid, "removed", "withdrawn", reason("removed"), ["not in the config any more" + ("" if entry else ": the notice has run its time and is dropped")])
        health_sources.append(dict(gone_report, pruned=old["item_count"]))
        if entry is not None:
            listings.append(entry)

    generator = {"name": GENERATOR_NAME, "version": __version__}
    store = {"format": "pea-knowledge-store", "format_version": FORMAT_VERSION, "generated_at": stamp, "generator": generator,
             "min_app_version": config.get("min_app_version"), "sources": listings, **vocabulary}
    write(os.path.join(staging, "store.json"), jsonschema_lite.dumps(store))
    write(os.path.join(staging, "state.json"), jsonschema_lite.dumps({"format": "pea-knowledge-state", "format_version": FORMAT_VERSION, "sources": memory}))
    total = sum(os.path.getsize(os.path.join(d, f)) for d, _, names in os.walk(staging) for f in names)
    model = state.get("model") or dict(model_digest.Budget(model_digest.Settings({})).report(), requested=False, used=False, model=None, note=None)
    health = {"format": "pea-knowledge-health", "format_version": FORMAT_VERSION, "generated_at": stamp, "generator": generator, "mode": state["mode"],
              "model": model, "sources": health_sources,
              "totals": {"sources": len(listings), "items": total_items, "bytes": total, "requests": state.get("requests", 0)}}
    write(os.path.join(staging, "health.json"), jsonschema_lite.dumps(health))
    write(os.path.join(staging, ".nojekyll"), b"")
    result = validate.check_folder(staging)
    if total > config["defaults"]["max_total_bytes"]:
        result.problems.append(validate.Problem("too_large", "the output", "%d bytes, the limit is %d" % (total, config["defaults"]["max_total_bytes"])))
    if not result.ok:
        shutil.rmtree(staging, ignore_errors=True)
        raise RuntimeError("the new output does not validate, nothing was replaced: %s" % "; ".join(repr(p) for p in result.problems[:5]))
    aside = out.rstrip("/\\") + ".replaced"
    shutil.rmtree(aside, ignore_errors=True)
    if os.path.exists(out):
        os.rename(out, aside)
    os.rename(staging, out)
    shutil.rmtree(aside, ignore_errors=True)
    return health


def health_summary(health):
    """The health report as a few lines of Markdown, for a job summary."""
    lines = ["## PEA knowledge run, %s" % health["generated_at"], "",
             "%(sources)d sources, %(items)d items, %(bytes)d bytes, %(requests)d requests." % health["totals"], "",
             "| Source | Run | State | Items | New | Reused | Kept | Stale | Transcripts | Model digests | Notes |", "| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |"]
    for s in health["sources"]:
        t = s["transcripts"]
        why = (" (%s)" % s["reason"]["code"]) if s["reason"] else ""
        lines.append("| %s | %s%s | %s | %d | %d | %d | %d | %d | %d full, %d cut, %d withheld, %d failed | %d | %s |" % (
            s["id"], s["outcome"], why, s["state"], s["items"], s["new"], s["reused"], s["kept"], s["stale"], t["yes"], t["partial"], t["withheld_terms"],
            t["fetch_failed"] + t["unreadable"], s["digests"]["model"], "; ".join(s["notes"])[:300].replace("|", "/")))
    m = health["model"]
    lines += ["", "Model: %s. %d calls, %d accepted, %d fell back, %d skipped for budget, %d + %d tokens, USD %.4f." % (
        m["model"] or ("requested, no key" if m["requested"] else "off"), m["calls"], m["accepted"], m["fell_back"], m["skipped_for_budget"],
        m["prompt_tokens"], m["completion_tokens"], m["cost_usd"])]
    return "\n".join(lines) + "\n"
