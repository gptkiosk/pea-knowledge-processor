# Copyright 2026 The PEA knowledge processor authors
# SPDX-License-Identifier: Apache-2.0
"""The phone-style probe: can the app itself fetch and read an item's transcript from the publisher?

The pipeline fetches with its own bot User-Agent and obeys robots.txt. The phone does neither: it sends the app's
headers, never reads robots.txt, and some hosts (Cloudflare-style bot protection) refuse non-browser clients, or answer
a page that is not the transcript. So for the newest discussable item of each source the pipeline makes one request
exactly the way the app makes it, and checks that the answer is a 200, of the type the item's format should have, no
larger than the app reads, and that it converts with this repository's own converter (an HTML page with the page
reader). A source whose newest item fails is paused: the app must not offer what its own phone cannot fetch.

The request style is copied from the iPhone app (a private repository, read 2026-11-15, app version 0.10.1):
    Sources/PEACore/Research.swift, `PublicFetcher.get(_:headers:json:transcript:)` and `PublicFetcher.userAgent(for:version:)`
    (header set, limits, content types), `PublisherTranscript.load` (the transcript is fetched with `transcript: true`).
When the app's request changes, change the constants below with it. The URLSession of the phone adds its own
Accept-Encoding and Accept-Language, which a probe cannot reproduce exactly; only the headers the app sets itself are copied.
"""
from . import fetch

# --- Copied from the app -------------------------------------------------------------------------------------------------
APP_VERSION = "0.10.1"   # CFBundleShortVersionString of the app's project when this was copied (the app's own fallback is "1.0")
PHONE_USER_AGENT = "PEA/%s (a personal assistant app; reads public pages its owner asks for)" % APP_VERSION   # PublicFetcher.userAgent(for:), a host that is not Wikimedia
PHONE_ACCEPT = "text/html,application/xhtml+xml,application/xml,application/rss+xml,text/plain,application/json;q=0.9,*/*;q=0.1"   # PublicFetcher.get
PHONE_HEADERS = {"User-Agent": PHONE_USER_AGENT, "Accept": PHONE_ACCEPT}
PHONE_MAXIMUM_BYTES = 1_500_000   # PublicFetcher.maximumBytes
PHONE_REQUEST_SECONDS = 10        # URLSessionConfiguration.timeoutIntervalForRequest
PHONE_FILE_SECONDS = 25           # URLSessionConfiguration.timeoutIntervalForResource
# PublicURL.allowedContent: what the app reads as a page. An empty type is accepted too.
APP_TYPES = {"text/html", "application/xhtml+xml", "text/plain", "text/xml", "application/xml", "application/rss+xml", "application/atom+xml", "application/json",
             "text/vtt", "application/x-subrip", "text/srt", "application/srt", "text/markdown", "text/javascript", ""}
# PublicFetcher.transcriptContent: types a transcript is often served as; accepted for a transcript address when what arrives is text.
APP_TRANSCRIPT_TYPES = {"application/octet-stream", "binary/octet-stream", "text/x-vtt", "text/x-srt", "application/x-vtt", "application/vtt", "application/x-srt",
                        "text/x-subrip", "application/json+pod2", "text/x-markdown", "text/x-web-markdown"}

# What each `transcript_source.format` is expected to be served as. Always a subset of what the app accepts, plus a plain
# text type or a generic download, which publishers use for every kind of file.
_GENERIC = {"text/plain", "application/octet-stream", "binary/octet-stream", ""}
EXPECTED_TYPES = {
    "html": {"text/html", "application/xhtml+xml"},
    "vtt": {"text/vtt", "text/x-vtt", "application/x-vtt", "application/vtt"} | _GENERIC,
    "srt": {"application/x-subrip", "text/srt", "application/srt", "text/x-srt", "application/x-srt", "text/x-subrip"} | _GENERIC,
    "json": {"application/json", "application/json+pod2", "text/javascript"} | _GENERIC,
    "markdown": {"text/markdown", "text/x-markdown", "text/x-web-markdown"} | _GENERIC,
    "text": _GENERIC | {"text/markdown", "text/x-markdown", "text/x-web-markdown"},
}
# The type the app tells its normalizer for each format (PublisherTranscript.type(_:)).
DECLARED_TYPES = {"vtt": "text/vtt", "srt": "application/x-subrip", "json": "application/json", "html": "text/html", "markdown": "text/markdown", "text": "text/plain"}

CODES = ("refused", "not_found", "rate_limited", "http_status", "timeout", "network", "content_type", "too_large", "unreadable")
SENTENCE = "the publisher refuses requests like the app's"   # the detail of a paused source, whatever the code


def type_is_expected(fmt, content_type):
    """True when `content_type` is one the app accepts for a transcript of this format."""
    wanted = EXPECTED_TYPES.get(fmt, _GENERIC)
    return content_type in wanted or (fmt == "json" and content_type.endswith("+json"))


def failure(code, detail):
    return {"result": "failed", "reason": {"code": code, "detail": detail[:200]}}


def explain(error):
    """A fetch error as a probe failure."""
    if error.code == "timeout":
        return failure("timeout", "no answer in the app's time limit (%s)" % error.detail)
    if error.code == "rate_limited":
        return failure("rate_limited", "the host asked for fewer requests (429)")
    if error.code == "not_found":
        return failure("not_found", "the address is not found (404 or 410)")
    if error.code == "http_error" and error.detail[:3].isdigit():
        status = int(error.detail[:3])
        if status in (401, 402, 403):
            return failure("refused", "the host answers %d to the app's request" % status)
        return failure("http_status", "the host answers %d, not 200" % status)
    if error.code == "not_text":
        return failure("unreadable", error.detail)
    return failure("network", error.detail)


def probe(fetcher, origin, read):
    """One phone-style request for `origin` (an item's `transcript_source`). `read(body, content_type, truncated)` is the
    caller's converter: it returns None when the body converts, otherwise one plain sentence on why not.
    Returns {"result": "ok", "reason": None} or {"result": "failed", "reason": {"code", "detail"}}."""
    try:
        answer = fetcher.get_like_the_app(origin["link"], PHONE_MAXIMUM_BYTES, PHONE_HEADERS, PHONE_REQUEST_SECONDS, PHONE_FILE_SECONDS)
    except fetch.FetchError as e:
        return explain(e)
    if answer.truncated:
        return failure("too_large", "the file is larger than the app reads (%d bytes)" % PHONE_MAXIMUM_BYTES)
    if not type_is_expected(origin["format"], answer.content_type):
        return failure("content_type", "served as %s, not a %s transcript" % (answer.content_type[:60] or "an unnamed type", origin["format"]))
    problem = read(answer.body, answer.content_type, answer.truncated)
    if problem is not None:
        return failure("unreadable", problem)
    return {"result": "ok", "reason": None}
