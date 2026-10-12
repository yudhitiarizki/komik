"""HTTP client with rate limiting and retry, shared by all sources."""
import time

import requests


class Client:
    def __init__(self, base_url="", headers=None, delay=1.0, retries=3, timeout=30):
        self.base_url = base_url.rstrip("/")
        self.delay = delay
        self.retries = retries
        self.timeout = timeout
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": "Mozilla/5.0", **(headers or {})})
        self._last = 0.0

    def _wait(self):
        gap = self.delay - (time.monotonic() - self._last)
        if gap > 0:
            time.sleep(gap)
        self._last = time.monotonic()

    def get(self, url, **kwargs):
        if not url.startswith("http"):
            url = f"{self.base_url}/{url.lstrip('/')}"
        for attempt in range(self.retries + 1):
            self._wait()
            try:
                resp = self.session.get(url, timeout=self.timeout, **kwargs)
                if resp.status_code in (429, 500, 502, 503, 504) and attempt < self.retries:
                    time.sleep(2 ** (attempt + 1))
                    continue
                resp.raise_for_status()
                return resp
            except (requests.ConnectionError, requests.Timeout):
                if attempt == self.retries:
                    raise
                time.sleep(2 ** (attempt + 1))

    def get_json(self, url, **kwargs):
        return self.get(url, **kwargs).json()
