"""Polite HTTP client for GMAT Club.

GMAT Club fronts the forum with anti-bot protection (Cloudflare-class).
A vanilla `requests.get` will receive HTTP 403 from most networks. To run
the crawler successfully you will typically need:

- A real browser User-Agent and Accept-* headers (set below by default).
- A session cookie obtained by visiting the site once in a real browser
  (export to a Netscape cookies.txt and pass --cookies to the CLI).
- Slow request cadence (--delay >= 3.0 is a reasonable starting point).
- Possibly a residential proxy or an authenticated session.

This module deliberately does NOT bundle headless-browser bypass — that is
a separate engineering problem and out of scope for the scraper core.
"""
from __future__ import annotations

import logging
import random
import time
from dataclasses import dataclass, field
from http.cookiejar import MozillaCookieJar
from typing import Optional

import requests

log = logging.getLogger(__name__)

DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Accept-Encoding": "gzip, deflate, br",
    "Connection": "keep-alive",
    "Upgrade-Insecure-Requests": "1",
}


class FetchError(Exception):
    """Raised when a URL cannot be fetched after retries."""


@dataclass
class PoliteClient:
    delay: float = 3.0           # seconds between requests (jittered)
    jitter: float = 1.0          # +/- random component on delay
    max_retries: int = 4
    timeout: int = 20
    cookies_path: Optional[str] = None
    extra_headers: dict = field(default_factory=dict)
    _session: requests.Session = field(init=False)
    _last_request_at: float = field(init=False, default=0.0)

    def __post_init__(self) -> None:
        self._session = requests.Session()
        self._session.headers.update(DEFAULT_HEADERS)
        if self.extra_headers:
            self._session.headers.update(self.extra_headers)
        if self.cookies_path:
            jar = MozillaCookieJar(self.cookies_path)
            jar.load(ignore_discard=True, ignore_expires=True)
            self._session.cookies = jar

    def _sleep_between_requests(self) -> None:
        elapsed = time.monotonic() - self._last_request_at
        wait = self.delay + random.uniform(-self.jitter, self.jitter)
        wait = max(0.0, wait - elapsed)
        if wait > 0:
            time.sleep(wait)

    def get_html(self, url: str) -> str:
        """Fetch a URL, returning decoded HTML. Raises FetchError on failure."""
        for attempt in range(1, self.max_retries + 1):
            self._sleep_between_requests()
            try:
                resp = self._session.get(url, timeout=self.timeout)
                self._last_request_at = time.monotonic()
            except requests.RequestException as exc:
                log.warning("network error %s on %s (attempt %d/%d)",
                            exc, url, attempt, self.max_retries)
                time.sleep(2 ** attempt)
                continue

            if resp.status_code == 200:
                return resp.text
            if resp.status_code in (403, 429, 503):
                backoff = (2 ** attempt) + random.uniform(0, 2)
                log.warning("HTTP %d on %s (attempt %d/%d) — backing off %.1fs",
                            resp.status_code, url, attempt, self.max_retries, backoff)
                time.sleep(backoff)
                continue
            if 400 <= resp.status_code < 500:
                # Treat other 4xx as permanent — no retry.
                raise FetchError(f"HTTP {resp.status_code} for {url}")
            log.warning("HTTP %d on %s (attempt %d/%d)",
                        resp.status_code, url, attempt, self.max_retries)
            time.sleep(2 ** attempt)

        raise FetchError(f"giving up on {url} after {self.max_retries} attempts")
