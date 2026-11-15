# Copyright 2026 The PEA knowledge processor authors
# SPDX-License-Identifier: Apache-2.0
"""Stage 1: polite, careful fetching of public files.

The rules are the ones the PEA iPhone app applies to any public address, plus what a scheduled robot owes a publisher:

- https only, port 443, a real public host name, no credentials in the address, no address typed as numbers;
- the name is resolved first, every address it resolves to must be public, and the connection is made to the address
  that was checked (so a name cannot be pointed somewhere else between the check and the request);
- at most four redirects, each checked the same way from the start;
- no cookies, no credentials, no proxy taken from the environment;
- a User-Agent that names this project and where to find it, robots.txt obeyed, a pause between requests to one host;
- conditional requests (ETag, Last-Modified), so an unchanged feed costs the publisher almost nothing;
- a size cap on what is read (also after decompression), a time cap per request and per file;
- one or two more tries with a growing pause for failures that look temporary; never for a 4xx.
"""
import http.client
import ipaddress
import re
import socket
import ssl
import time
import urllib.robotparser
import zlib
from urllib.parse import urljoin, urlsplit, urlunsplit

from . import REPOSITORY_URL, __version__

ROBOTS_TOKEN = "pea-knowledge-processor"
USER_AGENT = "%s/%s (+%s)" % (ROBOTS_TOKEN, __version__, REPOSITORY_URL)

MAXIMUM_REDIRECTS = 4
MAXIMUM_URL = 2_000
ROBOTS_BYTES = 500_000
FEED_BYTES = 8_000_000
TRANSCRIPT_BYTES = 1_500_000
REQUEST_SECONDS = 20
FILE_SECONDS = 60
PAUSE_SECONDS = 1.0
LONGEST_PAUSE_SECONDS = 30.0
RETRY_PAUSES = (1.0, 4.0)

_HOST = re.compile(r"^[a-z0-9]([a-z0-9\-]*[a-z0-9])?(\.[a-z0-9]([a-z0-9\-]*[a-z0-9])?)+$")
_BLOCKED_SUFFIXES = (".local", ".localdomain", ".internal", ".lan", ".home", ".corp", ".intranet", ".private", ".test",
                     ".invalid", ".example", ".onion", ".localhost")
_NUMBERS = re.compile(r"^[0-9.]+$")


class FetchError(Exception):
    """A fetch that did not give a file. `code` is one of CODES; `detail` is a short plain sentence."""
    CODES = ("not_public", "robots_disallowed", "not_found", "http_error", "rate_limited", "timeout", "network",
             "too_many_redirects", "not_text")

    def __init__(self, code, detail):
        super().__init__("%s: %s" % (code, detail))
        self.code, self.detail = code, detail


class Raw:
    """What one request gave: the opener's answer, before redirects and retries are dealt with."""

    def __init__(self, status, headers, body=b"", truncated=False):
        self.status, self.headers, self.body, self.truncated = status, {k.lower(): v for k, v in headers.items()}, body, truncated


class Response:
    def __init__(self, url, raw, not_modified=False):
        self.url, self.status, self.headers, self.body, self.truncated = url, raw.status, raw.headers, raw.body, raw.truncated
        self.not_modified = not_modified

    @property
    def content_type(self):
        return self.headers.get("content-type", "").split(";")[0].strip().lower()

    @property
    def etag(self):
        return self.headers.get("etag", "")[:200]

    @property
    def last_modified(self):
        return self.headers.get("last-modified", "")[:60]


# --- Addresses -------------------------------------------------------------------------------------------------------
def is_public_host(host):
    if len(host) > 253 or "." not in host or host.endswith(".") or ":" in host:
        return False
    if host == "localhost" or host.endswith(_BLOCKED_SUFFIXES):
        return False
    if _NUMBERS.match(host):  # any address typed as numbers, public or not
        return False
    return _HOST.match(host) is not None


def validate_url(text):
    """The address normalized (lower-case host, no fragment), or None when it is not one this project will request."""
    if not isinstance(text, str) or len(text) > MAXIMUM_URL:
        return None
    text = text.strip()
    if any(ord(c) < 0x21 or ord(c) == 0x7f or ord(c) > 0x7e for c in text):  # spaces, controls, anything not ASCII
        return None
    try:
        parts = urlsplit(text)
        port = parts.port
        host = (parts.hostname or "").lower()
    except ValueError:
        return None
    if parts.scheme.lower() != "https" or parts.username is not None or parts.password is not None or "@" in parts.netloc:
        return None
    if port not in (None, 443) or not is_public_host(host) or "\\" in text:
        return None
    return urlunsplit(("https", host, parts.path or "/", parts.query, ""))


def is_public_ip(text):
    """False for the addresses that are never a public website: this machine, home and office networks, link-local,
    shared carrier space, documentation and benchmark ranges, multicast, reserved, and IPv6 forms that wrap one of them."""
    try:
        ip = ipaddress.ip_address(text.split("%")[0])
    except ValueError:
        return False
    if isinstance(ip, ipaddress.IPv6Address):
        for inner in (ip.ipv4_mapped, ip.sixtofour, ip.teredo[1] if ip.teredo else None):
            if inner is not None:
                return is_public_ip(str(inner))
        if ip in ipaddress.ip_network("64:ff9b::/96"):  # an IPv4 address reached through NAT64
            return is_public_ip(str(ipaddress.IPv4Address(int(ip) & 0xFFFFFFFF)))
        if ip.is_unspecified or ip.is_loopback or ip.is_link_local or ip.is_multicast or ip.is_site_local:
            return False
        if ip in ipaddress.ip_network("fc00::/7"):
            return False
        return ip.is_global
    b = ip.packed
    if b[0] in (0, 10, 127) or (b[0], b[1]) in ((169, 254), (192, 168)) or b[0] >= 224:
        return False
    if (b[0] == 172 and 16 <= b[1] <= 31) or (b[0] == 100 and 64 <= b[1] <= 127):
        return False
    if (b[0], b[1]) == (192, 0) and b[2] in (0, 2):
        return False
    return ip.is_global


def system_resolver(host):
    try:
        found = socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM)
    except (socket.gaierror, UnicodeError, OSError):
        return []
    return [entry[4][0] for entry in found]


def public_address(host, resolver=system_resolver):
    """The first address `host` resolves to, after checking that every one of them is public. Raises FetchError."""
    addresses = resolver(host)
    if not addresses:
        raise FetchError("network", "the name %s does not resolve" % host)
    for a in addresses:
        if not is_public_ip(a):
            raise FetchError("not_public", "%s resolves to an address that is not public" % host)
    return addresses[0]


# --- One request -----------------------------------------------------------------------------------------------------
class _PinnedConnection(http.client.HTTPSConnection):
    """An HTTPS connection to one address that was already checked. The certificate is still verified against the name."""

    def __init__(self, host, address, timeout, context):
        super().__init__(host, 443, timeout=timeout, context=context)
        self._address, self._tls = address, context

    def connect(self):
        sock = socket.create_connection((self._address, 443), self.timeout)
        try:
            self.sock = self._tls.wrap_socket(sock, server_hostname=self.host)
        except BaseException:
            sock.close()
            raise


def https_opener(url, address, headers, maximum_bytes, seconds=REQUEST_SECONDS, total_seconds=FILE_SECONDS):
    """One GET over TLS to `address`. Reads at most `maximum_bytes` of the body (counted after decompression)."""
    parts = urlsplit(url)
    target = parts.path + ("?" + parts.query if parts.query else "")
    deadline = time.monotonic() + total_seconds
    connection = _PinnedConnection(parts.hostname, address, seconds, ssl.create_default_context())
    try:
        connection.request("GET", target, headers=headers)
        answer = connection.getresponse()
        found = {k: v for k, v in answer.getheaders()}
        encoding = (answer.getheader("Content-Encoding") or "").strip().lower()
        if encoding not in ("", "identity", "gzip", "x-gzip", "deflate"):
            raise FetchError("not_text", "the answer is encoded as %s" % encoding[:20])
        unpack = zlib.decompressobj(47 if encoding in ("gzip", "x-gzip") else 15) if encoding not in ("", "identity") else None
        chunks, size, truncated = [], 0, False
        while True:
            if time.monotonic() > deadline:
                raise FetchError("timeout", "the file took longer than %d seconds" % total_seconds)
            piece = answer.read(65_536)
            if not piece:
                break
            if unpack is not None:
                piece = unpack.decompress(piece, maximum_bytes + 1 - size)
            chunks.append(piece)
            size += len(piece)
            if size > maximum_bytes or (unpack is not None and unpack.unconsumed_tail):
                truncated = True
                break
        body = b"".join(chunks)[:maximum_bytes]
        return Raw(answer.status, found, body, truncated)
    except FetchError:
        raise
    except socket.timeout:
        raise FetchError("timeout", "no answer within %d seconds" % seconds) from None
    except ssl.SSLError as e:
        raise FetchError("network", "the secure connection failed (%s)" % (getattr(e, "reason", None) or "TLS")) from None
    except (OSError, http.client.HTTPException, zlib.error) as e:
        raise FetchError("network", "the request failed (%s)" % type(e).__name__) from None
    finally:
        connection.close()


# --- The fetcher -----------------------------------------------------------------------------------------------------
class Fetcher:
    """Fetches files by the rules at the top of this file. `opener`, `resolver`, `sleep` and `clock` can be replaced,
    which is how the tests and the saved fixtures run it without a network."""

    def __init__(self, opener=https_opener, resolver=system_resolver, sleep=time.sleep, clock=time.monotonic,
                 pause=PAUSE_SECONDS, retry_pauses=RETRY_PAUSES, log=None):
        self.opener, self.resolver, self.sleep, self.clock = opener, resolver, sleep, clock
        self.pause, self.retry_pauses = pause, retry_pauses
        self.log = log or (lambda message: None)
        self._robots = {}      # host -> (parser or None when everything is allowed, False when nothing is)
        self._last = {}        # host -> when the last request to it ended
        self.requests = 0

    # robots.txt -------------------------------------------------------------------------------------------------
    def _rules(self, host):
        if host not in self._robots:
            address = "https://%s/robots.txt" % host
            try:
                answer = self._follow(address, ROBOTS_BYTES, {}, robots=False)
            except FetchError as e:
                if e.code == "not_public":
                    raise
                # RFC 9309: a robots.txt that says "not here" (4xx) restricts nothing; one that cannot be reached
                # (5xx, no answer) must be read as "stay away".
                self._robots[host] = None if e.code == "not_found" or (e.code == "http_error" and e.detail.startswith("4")) else False
                self.log("robots.txt of %s: %s (%s)" % (host, "nothing is restricted" if self._robots[host] is None else "not reachable, so the host is left alone", e.detail))
            else:
                parser = urllib.robotparser.RobotFileParser()
                parser.parse(answer.body.decode("utf-8", "replace").splitlines())
                self._robots[host] = parser
        return self._robots[host]

    def allowed(self, url):
        rules = self._rules(urlsplit(url).hostname)
        if rules is None:
            return True
        if rules is False:
            return False
        return rules.can_fetch(ROBOTS_TOKEN, url)

    def _wait(self, host):
        rules = self._robots.get(host)
        wanted = self.pause
        if rules:
            try:
                asked = rules.crawl_delay(ROBOTS_TOKEN)
            except Exception:
                asked = None
            if asked:
                wanted = max(wanted, min(float(asked), LONGEST_PAUSE_SECONDS))
        last = self._last.get(host)
        if last is not None:
            remaining = wanted - (self.clock() - last)
            if remaining > 0:
                self.sleep(remaining)

    # requests ---------------------------------------------------------------------------------------------------
    def _once(self, url, maximum_bytes, extra):
        host = urlsplit(url).hostname
        address = public_address(host, self.resolver)
        headers = {"User-Agent": USER_AGENT, "Accept": "*/*", "Accept-Encoding": "gzip", "Connection": "close"}
        headers.update(extra)
        tries = 0
        while True:
            self._wait(host)
            self.requests += 1
            try:
                raw = self.opener(url, address, headers, maximum_bytes)
                failure = None
            except FetchError as e:
                raw, failure = None, e
            finally:
                self._last[host] = self.clock()
            temporary = (failure is not None and failure.code in ("timeout", "network")) or (raw is not None and raw.status >= 500)
            if not temporary or tries >= len(self.retry_pauses):
                if failure is not None:
                    raise failure
                return raw
            self.sleep(self.retry_pauses[tries])
            tries += 1

    def _follow(self, url, maximum_bytes, extra, robots=True):
        for _ in range(MAXIMUM_REDIRECTS + 1):
            checked = validate_url(url)
            if checked is None:
                raise FetchError("not_public", "not a public https address")
            url = checked
            if robots and not self.allowed(url):
                raise FetchError("robots_disallowed", "robots.txt of %s does not allow it" % urlsplit(url).hostname)
            raw = self._once(url, maximum_bytes, extra)
            if raw.status in (301, 302, 303, 307, 308):
                target = raw.headers.get("location", "")
                if not target:
                    raise FetchError("http_error", "%d without a target" % raw.status)
                url = urljoin(url, target)
                continue
            if raw.status == 304:
                return Response(url, raw, not_modified=True)
            if raw.status == 200:
                return Response(url, raw)
            if raw.status in (404, 410):
                raise FetchError("not_found", "not found (%d)" % raw.status)
            if raw.status == 429:
                raise FetchError("rate_limited", "the host asked for fewer requests (429)")
            raise FetchError("http_error", "%d" % raw.status)
        raise FetchError("too_many_redirects", "more than %d redirects" % MAXIMUM_REDIRECTS)

    def get(self, url, maximum_bytes, etag="", last_modified=""):
        """The file at `url`. With `etag` or `last_modified` from an earlier answer the request is conditional and
        the response may say `not_modified`. Raises FetchError."""
        extra = {}
        if etag:
            extra["If-None-Match"] = etag
        if last_modified:
            extra["If-Modified-Since"] = last_modified
        return self._follow(url, maximum_bytes, extra)


# --- Saved fixtures --------------------------------------------------------------------------------------------------
FIXTURE_ADDRESS = "93.184.216.34"


def fixture_fetcher(folder, log=None):
    """A Fetcher that answers from a folder instead of the network: manifest.json there maps each address to
    {"file", "status", "content_type", "etag", "location"}. Everything else (address checks, robots.txt, redirects,
    conditional requests) runs as it does live. An address the manifest does not list is a 404."""
    import json
    import os

    with open(os.path.join(folder, "manifest.json"), encoding="utf-8") as f:
        manifest = json.load(f)["responses"]

    def opener(url, address, headers, maximum_bytes, seconds=None, total_seconds=None):
        entry = manifest.get(url)
        if entry is None:
            return Raw(404, {})
        if "error" in entry:
            raise FetchError(entry["error"], "saved failure")
        status = entry.get("status", 200)
        found = {"Content-Type": entry.get("content_type", "")}
        if entry.get("etag"):
            found["ETag"] = entry["etag"]
        if entry.get("location"):
            found["Location"] = entry["location"]
        if status == 200 and entry.get("etag") and headers.get("If-None-Match") == entry["etag"]:
            return Raw(304, found)
        body = b""
        if "file" in entry:
            with open(os.path.join(folder, entry["file"]), "rb") as f:
                body = f.read()
        return Raw(status, found, body[:maximum_bytes], len(body) > maximum_bytes)

    return Fetcher(opener=opener, resolver=lambda host: [FIXTURE_ADDRESS], sleep=lambda s: None, clock=lambda: 0.0, pause=0, log=log)
