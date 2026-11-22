# Copyright 2026 The PEA knowledge processor authors
# SPDX-License-Identifier: Apache-2.0
"""Automated candidate-source intake testing (`python3 -m pea_knowledge test-source`).

Tests a requested podcast against the real ingestion pipeline without adding it to `config/sources.json`:
  1. Validates public HTTPS addresses (no loopback/private hosts) and optionally auto-discovers an RSS/Atom feed
     from a website's `<link rel="alternate">` tag or `/agent.json`.
  2. Parses the feed with `adapters.parse` (obeying `robots.txt` via `fetch.Fetcher`).
  3. Checks up to the newest 5 episodes for readable transcripts with `pipeline.normalize_transcript` against the
     catalog's discussability minimum (`min_full_transcript_share >= 0.6`, `min_discussable_items >= 2`).
  4. Runs the phone-style probe (`probe.probe`) on the newest discussable episode to confirm the iPhone app itself
     is not blocked by bot protection, wrong content-type, or size limits.
  5. Builds a sample extractive digest and brief and verifies `validate.check_brief_alone`.
  6. Emits a clear Markdown test report and a starter `config/sources.json` entry (`publish: "digest_only"`).
"""
import datetime
import json
import re
from html.parser import HTMLParser
from urllib.parse import urljoin, urlsplit

from . import adapters, brief as br, digest as dg, fetch, jsonschema_lite, pipeline, probe, textrules, validate
from .transcript import pea_transcript as pt

_FIELD_HEADING = re.compile(r"(?m)^###\s+(.+?)\s*$")
_SLUG_BAD = re.compile(r"[^a-z0-9]+")


def slugify(name):
    slug = _SLUG_BAD.sub("-", (name or "").strip().lower()).strip("-")
    slug = slug[:64].strip("-")
    return slug if slug and slug[0].isalnum() else "new-podcast"


def parse_issue_body(body):
    """Parses a GitHub Issue Form markdown body (`.github/ISSUE_TEMPLATE/request-podcast.yml`) into a clean dict."""
    fields = {"show_name": "", "feed_url": "", "website_url": "", "notes": ""}
    if not isinstance(body, str) or not body.strip():
        return fields
    matches = list(_FIELD_HEADING.finditer(body))
    if not matches:
        return fields
    key_map = {
        "podcast name": "show_name",
        "show name": "show_name",
        "rss feed or agent.json url": "feed_url",
        "feed url": "feed_url",
        "official website url": "website_url",
        "website url": "website_url",
        "notes": "notes",
        "notes (optional)": "notes",
    }
    for i, m in enumerate(matches):
        heading = m.group(1).strip().lower()
        target = None
        for k, field in key_map.items():
            if heading == k or heading.startswith(k):
                target = field
                break
        if target is None:
            continue
        start = m.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(body)
        val = body[start:end].strip()
        if val in ("_No response_", "No response", "None", "N/A"):
            val = ""
        fields[target] = val
    return fields


class _FeedLinkFinder(HTMLParser):
    def __init__(self):
        super().__init__()
        self.links = []

    def handle_starttag(self, tag, attrs):
        if tag.lower() != "link":
            return
        d = {k.lower(): (v or "") for k, v in attrs}
        rel = d.get("rel", "").lower().split()
        typ = d.get("type", "").lower()
        href = d.get("href", "").strip()
        if "alternate" in rel and href and any(x in typ for x in ("rss", "atom", "xml", "feed+json")):
            self.links.append((typ, href))


def _detect_adapter(body, content_type, url):
    ct = (content_type or "").lower()
    head = body[:2048].lstrip()
    if "json" in ct or head.startswith(b"{"):
        try:
            obj = json.loads(body.decode("utf-8"))
        except (UnicodeDecodeError, ValueError):
            return None
        if isinstance(obj, dict):
            if "editions" in obj or "agent.json" in url.lower():
                return "agent_index"
            if isinstance(obj.get("items"), list) and "jsonfeed.org" in str(obj.get("version", "")):
                return "json_feed"
            if isinstance(obj.get("items"), list):
                return "agent_index"
        return None
    if head.startswith(b"<") and (b"<rss" in head.lower() or b"<feed" in head.lower() or b"<?xml" in head.lower() or "xml" in ct):
        return "feed"
    return None


def discover_feed(fetcher, feed_url="", website_url=""):
    """Resolves and fetches the candidate feed, auto-discovering RSS/Atom from an HTML site if needed.
    Returns `(adapter, resolved_url, answer, discovery_notes)` or raises `ValueError` / `fetch.FetchError`."""
    notes = []
    primary = (feed_url or website_url or "").strip()
    if not primary:
        raise ValueError("Provide at least a feed URL or an official website URL to run ingestion tests.")
    valid = fetch.validate_url(primary)
    if valid is None:
        raise ValueError("URL must be a public https:// address (not http or private/local).")
    answer = fetcher.get(valid, fetch.FEED_BYTES)
    adapter = _detect_adapter(answer.body, answer.content_type, answer.url)
    if adapter is not None:
        return adapter, answer.url, answer, notes

    # HTML page: look for <link rel="alternate" type="application/rss+xml|atom+xml|feed+json">
    parser = _FeedLinkFinder()
    try:
        parser.feed(answer.body.decode("utf-8", "replace"))
    except Exception:
        pass
    for _, href in parser.links:
        cand = fetch.validate_url(urljoin(answer.url, href))
        if not cand:
            continue
        try:
            feed_ans = fetcher.get(cand, fetch.FEED_BYTES)
        except fetch.FetchError as e:
            notes.append("Discovered feed link %s failed (%s)." % (cand, e.detail))
            continue
        found = _detect_adapter(feed_ans.body, feed_ans.content_type, feed_ans.url)
        if found is not None:
            notes.append("Auto-discovered %s feed at %s from website HTML." % (found, feed_ans.url))
            return found, feed_ans.url, feed_ans, notes

    raise ValueError("The URL did not return an RSS/Atom feed, JSON Feed, or agent.json, and no feed link was found on the page.")


def _starter_config(name, adapter, feed_url, website_url, sample_format, robots_note, today):
    site = fetch.validate_url(website_url) if website_url else None
    if not site:
        parts = urlsplit(feed_url)
        site = "%s://%s/" % (parts.scheme, parts.netloc)
    robots_url = "%s://%s/robots.txt" % (urlsplit(site).scheme, urlsplit(site).netloc)
    return {
        "id": slugify(name),
        "name": textrules.clean(name, 80) or "New Podcast",
        "kind": "podcast",
        "adapter": adapter,
        "url": feed_url,
        "site": site,
        "publisher": textrules.clean(name, 80) or "Publisher",
        "language": "en",
        "description": "TODO: one-sentence description of the show.",
        "overview": "TODO: 2 to 4 plain sentences describing the show's beat, format, and style.",
        "categories": ["podcast"],
        "topics": ["technology"],
        "icon": {"symbol": "mic", "colour": "blue"},
        "publish": "digest_only",
        "attribution": "%s, %s" % (textrules.clean(name, 60) or "Publisher", urlsplit(site).netloc),
        "suggested_keep": 3,
        "terms": {
            "checked": today,
            "robots": {"url": robots_url, "finding": robots_note},
            "licence": {"url": None, "finding": "TODO: check the publisher's licence / terms page before merging."},
            "terms_of_use": {"url": None, "finding": "TODO: review publisher terms of use (docs/SOURCES-TERMS.md)."},
            "summary": "Public feed checked via automated intake; publish stays digest_only until terms explicitly allow full transcripts.",
            "uncertain": ["Curator review needed on publisher terms before adding to config/sources.json."],
        },
        "transcript_route": "Feed provides %s transcripts." % sample_format if sample_format else "TODO: configure transcript_page if transcripts live on episode web pages.",
    }


def test_candidate(fetcher, name, feed_url="", website_url="", notes="", check_items=5, min_share=0.6, min_discussable=2, today=None):
    """Runs the full ingestion test suite against one candidate podcast source. Returns a structured report dict."""
    today = today or datetime.date.today().isoformat()
    show_name = textrules.clean(name or "", 120) or "Requested podcast"
    checks = []
    report = {
        "show_name": show_name,
        "feed_url": (feed_url or "").strip(),
        "website_url": (website_url or "").strip(),
        "notes": textrules.clean(notes or "", 500),
        "verdict": "FAIL",
        "checks": checks,
        "episodes_found": 0,
        "checked_episodes": 0,
        "discussable_episodes": 0,
        "transcript_share": 0.0,
        "transcript_formats": [],
        "phone_probe": None,
        "brief_contract": None,
        "starter_config": None,
        "discovery_notes": [],
    }

    # 1. URL validation & feed discovery
    try:
        adapter, resolved_url, answer, d_notes = discover_feed(fetcher, feed_url=feed_url, website_url=website_url)
        report["feed_url"] = resolved_url
        report["adapter"] = adapter
        report["discovery_notes"] = d_notes
        checks.append(("PASS", "Feed reachable & adapter detected", "`%s` at `%s` (%d bytes)" % (adapter, resolved_url, len(answer.body))))
    except (ValueError, fetch.FetchError) as e:
        detail = getattr(e, "detail", str(e))
        checks.append(("FAIL", "Feed reachable & valid HTTPS", detail))
        return report

    # 2. Parse feed items (support oversized feeds via adapters.head_of_feed, matching pipeline.py)
    try:
        body = answer.body
        if answer.truncated and adapter == "feed":
            trimmed = adapters.head_of_feed(body)
            if trimmed is None:
                checks.append(("FAIL", "Feed parses cleanly", "Feed exceeds %d bytes and head_of_feed could not extract complete items." % fetch.FEED_BYTES))
                return report
            body = trimmed
        listing = adapters.ADAPTERS[adapter](body)
        entries = listing.entries
    except Exception as e:
        checks.append(("FAIL", "Feed parses cleanly", str(e)))
        return report
    report["episodes_found"] = len(entries)
    if not entries:
        checks.append(("FAIL", "Feed lists episodes", "0 episodes parsed from the feed."))
        return report
    checks.append(("PASS", "Feed parses cleanly", "%d episode(s) found; newest: \u201C%s\u201D (%s)" % (len(entries), textrules.shorten(entries[0].title, 80), entries[0].date)))

    # 3. Transcript check across newest `check_items` episodes
    site_url = fetch.validate_url(website_url) if website_url else None
    if not site_url:
        p = urlsplit(resolved_url)
        site_url = "%s://%s/" % (p.scheme, p.netloc)
    dummy_source = {
        "id": slugify(show_name),
        "name": show_name[:80],
        "kind": "podcast",
        "adapter": adapter,
        "url": resolved_url,
        "site": site_url,
        "publisher": show_name[:80],
        "language": "en",
        "publish": "digest_only",
    }
    sample_entries = entries[:max(1, check_items)]
    report["checked_episodes"] = len(sample_entries)
    discussable_items = []
    formats = set()
    first_transcript_text = None
    first_item_dict = None
    first_origin = None
    for idx, entry in enumerate(sample_entries):
        item = {
            "id": "%s-%02d" % (entry.date or today, idx + 1),
            "title": textrules.clean(entry.title, 200) or "Episode %d" % (idx + 1),
            "date": entry.date or today,
            "link": fetch.validate_url(entry.link) or site_url,
            "summary": textrules.clean(entry.summary or "", 2000),
            "notes": entry.notes or "",
            "duration_seconds": entry.duration,
            "tags": list(entry.tags or []),
            "people": list(entry.people or []),
            "chapters": [list(c) for c in (entry.chapters or [])],
            "soundbites": [list(s) for s in (entry.soundbites or [])],
            "resources": list(entry.resources or []),
        }
        status, reason, detail, text, origin = pipeline.normalize_transcript(
            fetcher, dummy_source, item, entry.transcripts, link=item["link"], links=entry.links
        )
        if text is not None and origin is not None:
            discussable_items.append((item, text, origin, status))
            formats.add(origin.get("format", "text"))
            if first_transcript_text is None:
                first_transcript_text, first_item_dict, first_origin = text, item, origin

    report["discussable_episodes"] = len(discussable_items)
    report["transcript_share"] = round(len(discussable_items) / len(sample_entries), 2)
    report["transcript_formats"] = sorted(formats)
    meets_min = len(discussable_items) >= min(min_discussable, len(sample_entries)) and report["transcript_share"] >= min_share
    if meets_min:
        checks.append((
            "PASS",
            "Transcript availability & discussability rule",
            "%d of %d newest episodes have readable transcripts (%.0f%%; formats: %s)."
            % (len(discussable_items), len(sample_entries), report["transcript_share"] * 100, ", ".join(sorted(formats))),
        ))
    else:
        checks.append((
            "WARN" if len(entries) > 0 else "FAIL",
            "Transcript availability & discussability rule",
            "Only %d of %d newest episodes had inline feed transcripts (%.0f%%; minimum is %.0f%% and %d episodes). If transcripts live on episode web pages, add a `transcript_page` rule in `config/sources.json`."
            % (len(discussable_items), len(sample_entries), report["transcript_share"] * 100, min_share * 100, min_discussable),
        ))

    # 4. Phone-style probe on newest discussable episode
    probe_ok = False
    if first_origin is not None and first_item_dict is not None:
        def _read(body, content_type, truncated):
            fake = fetch.Response(first_origin["link"], fetch.Raw(200, {"content-type": content_type}, body, truncated))
            _, _, detail, txt, _ = pipeline.read_answer(dummy_source, first_item_dict, first_origin["link"], "", fake)
            return None if txt is not None else (detail or "could not convert transcript")

        res = probe.probe(fetcher, first_origin, _read)
        report["phone_probe"] = res
        probe_ok = res["result"] == "ok"
        if probe_ok:
            checks.append(("PASS", "Phone-style probe (iPhone headers)", "Fetched and converted cleanly like the iPhone app."))
        else:
            checks.append(("FAIL", "Phone-style probe (iPhone headers)", "%s: %s" % (res["reason"]["code"], res["reason"]["detail"])))
    else:
        checks.append(("SKIP", "Phone-style probe (iPhone headers)", "Skipped until a readable transcript route is available."))

    # 5. Sample extractive digest + brief contract verification
    brief_ok = False
    if first_transcript_text is not None and first_item_dict is not None:
        parsed_t = pt.parse(first_transcript_text)
        dig = dg.extractive(dummy_source, first_item_dict, parsed_t, 1_500, [])
        brief_bytes = br.extractive_file(dummy_source, first_item_dict, dig, [])
        b, problems = validate.check_brief_alone(brief_bytes, "sample.brief.json")
        brief_ok = b is not None and not problems
        report["brief_contract"] = {"ok": brief_ok, "bytes": len(brief_bytes), "problems": [repr(p) for p in problems]}
        if brief_ok:
            checks.append(("PASS", "Brief contract check", "Sample brief passed (`%d` bytes, `%d` claims)." % (len(brief_bytes), len(b["claims"]))))
        else:
            checks.append(("FAIL", "Brief contract check", "; ".join(repr(p) for p in problems[:3])))
    else:
        checks.append(("SKIP", "Brief contract check", "Skipped until a readable transcript is available."))

    robots_note = "Checked via automated Fetcher (robots.txt obeyed during intake test on %s)." % today
    report["starter_config"] = _starter_config(
        show_name, adapter, resolved_url, site_url, (sorted(formats)[0] if formats else None), robots_note, today
    )

    if meets_min and probe_ok and brief_ok:
        report["verdict"] = "PASS"
    elif not meets_min:
        report["verdict"] = "NEEDS_TRANSCRIPT_RULE"
    else:
        report["verdict"] = "FAIL"
    return report


def format_markdown(report):
    """Formats a `test_candidate` report as a clean GitHub Issue comment / CLI Markdown summary."""
    icon = {"PASS": "PASS", "WARN": "NEEDS REVIEW", "FAIL": "FAIL", "SKIP": "SKIP"}
    lines = [
        "## Automated Source Ingestion Test: %s" % report["verdict"],
        "",
        "- **Show:** %s" % report["show_name"],
        "- **Feed URL:** %s" % (report["feed_url"] or "_not resolved_"),
    ]
    if report.get("website_url"):
        lines.append("- **Website:** %s" % report["website_url"])
    if report.get("discovery_notes"):
        for n in report["discovery_notes"]:
            lines.append("- **Discovery:** %s" % n)
    lines += ["", "| Result | Check | Details |", "| --- | --- | --- |"]
    for status, label, detail in report["checks"]:
        lines.append("| **%s** | %s | %s |" % (icon.get(status, status), label, detail.replace("\n", " ")))
    lines.append("")
    if report["verdict"] == "PASS":
        lines.append("This podcast passed automated feed, transcript, phone-probe, and brief-contract checks. After reviewing publisher terms (`docs/SOURCES-TERMS.md`), a curator can add the starter entry below to `config/sources.json` and open a PR.")
    elif report["verdict"] == "NEEDS_TRANSCRIPT_RULE":
        lines.append("The feed parsed cleanly, but did not include enough inline `<podcast:transcript>` tags. If the publisher hosts transcripts on episode web pages, add a `transcript_page` extraction rule (see `docs/ADDING-SOURCES.md`) and re-run `python3 -m pea_knowledge test-source`.")
    else:
        lines.append("One or more required checks failed above. See details before adding this source to `config/sources.json`.")
    if report.get("starter_config"):
        lines += [
            "",
            "<details>",
            "<summary>Starter <code>config/sources.json</code> entry (review terms before merging)</summary>",
            "",
            "```json",
            json.dumps(report["starter_config"], indent=2),
            "```",
            "</details>",
        ]
    return "\n".join(lines) + "\n"
