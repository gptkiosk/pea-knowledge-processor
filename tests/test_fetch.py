# Copyright 2026 The PEA knowledge processor authors
# SPDX-License-Identifier: Apache-2.0
import os
import unittest

from . import support  # noqa: F401
from pea_knowledge import fetch


class Addresses(unittest.TestCase):
    def test_only_public_https_addresses(self):
        self.assertEqual(fetch.validate_url("https://Example.org/a?b=1#frag"), "https://example.org/a?b=1")
        self.assertEqual(fetch.validate_url("https://example.org:443"), "https://example.org/")
        for bad in ("http://example.org/", "ftp://example.org/", "https://user:pw@example.org/", "https://user@example.org/", "https://example.org:8443/",
                    "https://127.0.0.1/", "https://2130706433/", "https://[::1]/", "https://localhost/", "https://router.local/", "https://x.internal/",
                    "https://service.test/", "https://x.onion/", "https://nodots/", "https://exa mple.org/", "https://exämple.org/", "https://example.org/a\nb",
                    "https://example.org\\@evil.example.net/", "//example.org/", "example.org", "", None, 7, "https://" + "a" * 3000 + ".org/",
                    "https://example.org./", "javascript:alert(1)", "file:///etc/passwd", "https://169.254.169.254/latest/meta-data/"):
            self.assertIsNone(fetch.validate_url(bad), bad)

    def test_addresses_that_are_never_a_public_site(self):
        for a in ("8.8.8.8", "93.184.216.34", "2606:4700::1111"):
            self.assertTrue(fetch.is_public_ip(a), a)
        for a in ("0.0.0.0", "10.1.2.3", "127.0.0.1", "169.254.169.254", "172.16.0.1", "172.31.255.255", "192.168.0.1", "100.64.0.1", "192.0.0.1", "192.0.2.1",
                  "198.18.0.1", "198.51.100.1", "203.0.113.1", "224.0.0.1", "240.0.0.1", "255.255.255.255", "::", "::1", "fe80::1", "fc00::1", "fd12::1", "ff02::1",
                  "::ffff:127.0.0.1", "::ffff:10.0.0.1", "64:ff9b::7f00:1", "2002:7f00:1::", "2001:db8::1", "not an address", ""):
            self.assertFalse(fetch.is_public_ip(a), a)

    def test_a_name_that_resolves_to_a_private_address_is_refused(self):
        with self.assertRaises(fetch.FetchError) as e:
            fetch.public_address("rebind.example.org", lambda host: ["93.184.216.34", "10.0.0.5"])
        self.assertEqual(e.exception.code, "not_public")
        with self.assertRaises(fetch.FetchError) as e:
            fetch.public_address("nowhere.example.org", lambda host: [])
        self.assertEqual(e.exception.code, "network")
        self.assertEqual(fetch.public_address("ok.example.org", lambda host: ["93.184.216.34"]), "93.184.216.34")


class Web:
    """A pretend web for the Fetcher: {address: Raw or list of Raw or exception}, with a record of every request."""

    def __init__(self, pages):
        self.pages, self.calls, self.slept = pages, [], []

    def opener(self, url, address, headers, maximum_bytes, seconds=None, total_seconds=None):
        self.calls.append((url, address, dict(headers)))
        page = self.pages.get(url, fetch.Raw(404, {}))
        if isinstance(page, list):
            page = page.pop(0) if len(page) > 1 else page[0]
        if isinstance(page, Exception):
            raise page
        return page

    def fetcher(self, resolver=None):
        return fetch.Fetcher(opener=self.opener, resolver=resolver or (lambda host: ["93.184.216.34"]), sleep=self.slept.append, clock=lambda: 0.0)

    def asked(self):
        return [c[0] for c in self.calls]


def page(body=b"hello", status=200, **headers):
    return fetch.Raw(status, headers, body)


class Fetching(unittest.TestCase):
    def get(self, pages, url="https://a.example.org/feed", resolver=None, **more):
        web = Web(pages)
        try:
            return web, web.fetcher(resolver).get(url, 1000, **more), None
        except fetch.FetchError as e:
            return web, None, e

    def test_a_plain_fetch_is_polite(self):
        web, answer, _ = self.get({"https://a.example.org/feed": page(b"ok", **{"ETag": '"v1"', "Content-Type": "text/xml; charset=utf-8"})})
        self.assertEqual((answer.body, answer.etag, answer.content_type), (b"ok", '"v1"', "text/xml"))
        self.assertEqual(web.asked(), ["https://a.example.org/robots.txt", "https://a.example.org/feed"])
        url, address, headers = web.calls[1]
        self.assertEqual(address, "93.184.216.34", "the request goes to the address that was checked")
        self.assertIn("pea-knowledge-processor/", headers["User-Agent"])
        self.assertIn("+https://github.com/gptkiosk/pea-knowledge-processor", headers["User-Agent"])
        self.assertFalse({"cookie", "authorization", "referer"} & {k.lower() for k in headers})
        self.assertTrue(web.slept and web.slept[0] >= 1.0, "a pause between two requests to one host")

    def test_conditional_requests(self):
        web, answer, _ = self.get({"https://a.example.org/feed": page(b"", 304)}, etag='"v1"', last_modified="Sat, 14 Nov 2026 00:00:00 GMT")
        self.assertTrue(answer.not_modified)
        self.assertEqual(web.calls[1][2]["If-None-Match"], '"v1"')
        self.assertEqual(web.calls[1][2]["If-Modified-Since"], "Sat, 14 Nov 2026 00:00:00 GMT")

    def test_robots_txt_is_obeyed(self):
        robots = page(b"User-agent: *\nDisallow: /private/\nCrawl-delay: 7\n\nUser-agent: pea-knowledge-processor\nDisallow: /feed\nCrawl-delay: 500\n")
        web, _, error = self.get({"https://a.example.org/robots.txt": robots, "https://a.example.org/feed": page()})
        self.assertEqual(error.code, "robots_disallowed")
        self.assertEqual(web.asked(), ["https://a.example.org/robots.txt"])
        web, answer, _ = self.get({"https://a.example.org/robots.txt": robots, "https://a.example.org/other": page()}, url="https://a.example.org/other")
        self.assertEqual(answer.body, b"hello")
        self.assertEqual(web.slept[-1], fetch.LONGEST_PAUSE_SECONDS, "a crawl delay is honoured up to the longest pause")

    def test_robots_txt_that_cannot_be_reached_means_stay_away(self):
        _, _, error = self.get({"https://a.example.org/robots.txt": page(b"", 503), "https://a.example.org/feed": page()})
        self.assertEqual(error.code, "robots_disallowed")
        _, _, error = self.get({"https://a.example.org/robots.txt": fetch.FetchError("timeout", "slow"), "https://a.example.org/feed": page()})
        self.assertEqual(error.code, "robots_disallowed")
        for status in (400, 401, 403, 404, 410):
            _, answer, _ = self.get({"https://a.example.org/robots.txt": page(b"", status), "https://a.example.org/feed": page()})
            self.assertEqual(answer.body, b"hello", status)

    def test_redirects_are_checked_again(self):
        def to(target, status=302):
            return page(b"", status, Location=target)
        web, answer, _ = self.get({"https://a.example.org/feed": to("https://b.example.org/new"), "https://b.example.org/new": page(b"moved")})
        self.assertEqual((answer.body, answer.url), (b"moved", "https://b.example.org/new"))
        self.assertIn("https://b.example.org/robots.txt", web.asked(), "the new host's robots.txt is read too")
        _, answer, _ = self.get({"https://a.example.org/feed": to("/relative"), "https://a.example.org/relative": page(b"rel")})
        self.assertEqual(answer.body, b"rel")
        for target in ("http://a.example.org/plain", "https://127.0.0.1/", "https://router.local/x", "https://user:pw@b.example.org/", "file:///etc/passwd",
                       "https://b.example.org:8080/"):
            web, _, error = self.get({"https://a.example.org/feed": to(target)})
            self.assertEqual(error.code, "not_public", target)
            self.assertEqual(len(web.calls), 2, "nothing is requested at the refused target")
        _, _, error = self.get({"https://a.example.org/feed": to("https://inside.example.org/x")},
                               resolver=lambda host: ["10.0.0.9"] if host.startswith("inside") else ["93.184.216.34"])
        self.assertEqual(error.code, "not_public")
        loop = {"https://a.example.org/%d" % n: to("https://a.example.org/%d" % (n + 1)) for n in range(10)}
        _, _, error = self.get(loop, url="https://a.example.org/0")
        self.assertEqual(error.code, "too_many_redirects")
        _, _, error = self.get({"https://a.example.org/feed": page(b"", 302)})
        self.assertEqual(error.code, "http_error")

    def test_temporary_failures_are_tried_again_and_others_are_not(self):
        web, answer, _ = self.get({"https://a.example.org/feed": [page(b"", 503), fetch.FetchError("timeout", "slow"), page(b"third time")]})
        self.assertEqual(answer.body, b"third time")
        self.assertEqual([s for s in web.slept if s > 1.0], [4.0], "a growing pause between tries: one second, then four")
        web, _, error = self.get({"https://a.example.org/feed": page(b"", 503)})
        self.assertEqual((error.code, len(web.calls)), ("http_error", 4))
        for status, code in ((404, "not_found"), (410, "not_found"), (429, "rate_limited"), (403, "http_error"), (401, "http_error")):
            web, _, error = self.get({"https://a.example.org/feed": page(b"", status)})
            self.assertEqual((error.code, len(web.calls)), (code, 2), status)

    def test_an_address_that_is_not_public_is_never_requested(self):
        for url in ("http://a.example.org/feed", "https://10.0.0.1/feed", "https://localhost/feed"):
            web, _, error = self.get({}, url=url)
            self.assertEqual((error.code, web.calls), ("not_public", []))
        web, _, error = self.get({}, resolver=lambda host: ["192.168.1.1"])
        self.assertEqual((error.code, web.calls), ("not_public", []))


class SavedWeb(unittest.TestCase):
    def test_the_fixture_fetcher_answers_from_the_folder(self):
        f = fetch.fixture_fetcher(support.WEB)
        answer = f.get("https://tide.example.org/feed.xml", 10_000_000)
        self.assertIn(b"<rss", answer.body)
        self.assertTrue(f.get("https://tide.example.org/feed.xml", 10_000_000, etag=answer.etag).not_modified)
        self.assertTrue(f.get("https://tide.example.org/feed.xml", 100).truncated)
        with self.assertRaises(fetch.FetchError) as e:
            f.get("https://tide.example.org/private/x", 100)
        self.assertEqual(e.exception.code, "robots_disallowed")
        with self.assertRaises(fetch.FetchError) as e:
            f.get("https://tide.example.org/nothing", 100)
        self.assertEqual(e.exception.code, "not_found")


@unittest.skipUnless(os.environ.get("PEA_NETWORK_TESTS") == "1", "real network tests run only with PEA_NETWORK_TESTS=1")
class RealNetwork(unittest.TestCase):
    def test_one_real_public_file(self):
        answer = fetch.Fetcher().get("https://www.rfc-editor.org/rfc/rfc9309.txt", 2_000_000)
        self.assertIn(b"Robots Exclusion Protocol", answer.body)

    def test_a_real_name_for_this_machine_is_refused(self):
        with self.assertRaises(fetch.FetchError) as e:
            fetch.Fetcher().get("https://localtest.me/", 1000)
        self.assertEqual(e.exception.code, "not_public")


if __name__ == "__main__":
    unittest.main()
