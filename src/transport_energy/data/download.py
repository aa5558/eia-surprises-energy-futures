"""Polite, cached downloads with a provenance manifest.

Every file fetched from the internet is recorded in ``data/raw/MANIFEST.json`` with
its source URL, UTC download time, size and SHA-256 hash, so any number in the
project can be traced back to an exact file. A file already on disk is not fetched
again unless ``refresh=True``; its manifest entry is left untouched.
"""

from __future__ import annotations

import hashlib
import json
import time
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path

import requests

from transport_energy.config import REPO_ROOT

USER_AGENT = "transport-energy-quant research"
MANIFEST_NAME = "MANIFEST.json"
DEFAULT_RAW = REPO_ROOT / "data" / "raw"


class DownloadError(RuntimeError):
    """Raised when a source returns an error status or an unusable body."""


@dataclass(frozen=True)
class ManifestEntry:
    path: str            # relative to the raw-data root
    url: str             # URL actually requested
    original_url: str    # the page being documented (differs from url for archived copies)
    downloaded_at: str   # ISO-8601 UTC
    sha256: str
    bytes: int


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 16), b""):
            h.update(chunk)
    return h.hexdigest()


def load_manifest(raw_root: Path = DEFAULT_RAW) -> dict[str, dict]:
    path = raw_root / MANIFEST_NAME
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def _save_manifest(manifest: dict[str, dict], raw_root: Path) -> None:
    path = raw_root / MANIFEST_NAME
    path.write_text(json.dumps(manifest, indent=1, sort_keys=True), encoding="utf-8")


class Fetcher:
    """Downloads into ``raw_root`` with a minimum delay between network requests."""

    def __init__(
        self,
        raw_root: Path = DEFAULT_RAW,
        min_interval: float = 0.5,
        timeout: float = 90.0,
        retries: int = 3,
        session: requests.Session | None = None,
    ) -> None:
        self.raw_root = Path(raw_root)
        self.min_interval = min_interval
        self.timeout = timeout
        self.retries = retries
        self.session = session or requests.Session()
        self.session.headers["User-Agent"] = USER_AGENT
        self._last = 0.0
        self.manifest = load_manifest(self.raw_root)

    def _get(self, url: str) -> requests.Response:
        last_exc: Exception | None = None
        for attempt in range(self.retries):
            wait = self.min_interval - (time.monotonic() - self._last)
            if wait > 0:
                time.sleep(wait)
            self._last = time.monotonic()
            try:
                resp = self.session.get(url, timeout=self.timeout)
            except requests.RequestException as exc:
                last_exc = exc
            else:
                if resp.status_code == 200:
                    return resp
                if resp.status_code in (404, 403, 410):
                    raise DownloadError(f"HTTP {resp.status_code} for {url}")
                last_exc = DownloadError(f"HTTP {resp.status_code} for {url}")
            time.sleep(5 * (attempt + 1))   # 429 / 5xx / network: back off and retry
        raise DownloadError(f"giving up on {url}: {last_exc}")

    def fetch(
        self, url: str, rel_path: str, *, original_url: str | None = None, refresh: bool = False
    ) -> Path:
        """Return the local path of ``url``, downloading it if needed."""
        dest = self.raw_root / rel_path
        if dest.exists() and not refresh:
            return dest
        body = self._get(url).content
        dest.parent.mkdir(parents=True, exist_ok=True)
        tmp = dest.with_suffix(dest.suffix + ".part")
        tmp.write_bytes(body)
        tmp.replace(dest)
        entry = ManifestEntry(
            path=rel_path,
            url=url,
            original_url=original_url or url,
            downloaded_at=datetime.now(UTC).isoformat(timespec="seconds"),
            sha256=sha256_file(dest),
            bytes=len(body),
        )
        # re-read before writing so several fetchers can share one manifest
        self.manifest = load_manifest(self.raw_root)
        self.manifest[rel_path] = asdict(entry)
        _save_manifest(self.manifest, self.raw_root)
        return dest

    def get_text(self, url: str) -> str:
        """Uncached GET for small index queries (e.g. archive listings); not stored."""
        return self._get(url).text
