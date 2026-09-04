"""Shared HTTP plumbing for the literature layer.

Every network call made by :mod:`harness.lit` funnels through :func:`get_json`,
:func:`get_text` or :func:`download` so that on-disk caching, per-host rate
limiting, and retry/backoff behaviour is uniform across engines.

None of the functions here raise on network failure: they log a short message
to stderr and return ``None`` (or, for :func:`download`, ``None``). Higher
layers (the ``search``-style functions in ``arxiv.py``, ``openalex.py``, ...)
rely on this to guarantee they never raise on a flaky connection.
"""
from __future__ import annotations

import hashlib
import json
import sys
import time
from pathlib import Path
from urllib.parse import urlparse

import requests

from harness import CACHE

USER_AGENT = "Neugier/0.2 (research harness)"

#: Minimum seconds between consecutive requests to a given host (politeness).
MIN_INTERVAL: dict[str, float] = {
    "export.arxiv.org": 3.0,
    "arxiv.org": 1.0,
    "api.openalex.org": 0.2,
    "api.zbmath.org": 1.0,
    "oeis.org": 1.0,
    "api.stackexchange.com": 0.5,
}
DEFAULT_INTERVAL = 0.5
MAX_RETRIES = 3
TIMEOUT = 30

_last_call: dict[str, float] = {}


def _log(msg: str) -> None:
    print(f"[harness.lit.http] {msg}", file=sys.stderr)


def _rate_limit(host: str) -> None:
    interval = MIN_INTERVAL.get(host, DEFAULT_INTERVAL)
    now = time.monotonic()
    last = _last_call.get(host)
    if last is not None:
        wait = interval - (now - last)
        if wait > 0:
            time.sleep(wait)
    _last_call[host] = time.monotonic()


def _cache_dir(cache_ns: str) -> Path:
    d = CACHE / "lit" / cache_ns
    d.mkdir(parents=True, exist_ok=True)
    return d


def _cache_key(method: str, url: str, params: dict | None, headers: dict | None) -> str:
    payload = json.dumps(
        {"method": method, "url": url, "params": params or {}, "headers": headers or {}},
        sort_keys=True,
        default=str,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _cache_path(cache_ns: str, key: str, suffix: str) -> Path:
    return _cache_dir(cache_ns) / f"{key}{suffix}"


def _cache_fresh(path: Path, ttl_hours: float) -> bool:
    if ttl_hours <= 0 or not path.exists():
        return False
    age_hours = (time.time() - path.stat().st_mtime) / 3600.0
    return age_hours < ttl_hours


def _request_with_retries(
    method: str,
    url: str,
    *,
    params: dict | None = None,
    headers: dict | None = None,
    stream: bool = False,
) -> requests.Response:
    """Issue a rate-limited HTTP request, retrying on 429/5xx and connection errors.

    Raises ``requests.RequestException`` if all attempts are exhausted.
    """
    host = urlparse(url).netloc
    hdrs = {"User-Agent": USER_AGENT}
    if headers:
        hdrs.update(headers)

    last_exc: Exception | None = None
    for attempt in range(MAX_RETRIES + 1):
        _rate_limit(host)
        try:
            resp = requests.request(
                method, url, params=params, headers=hdrs, timeout=TIMEOUT, stream=stream
            )
        except requests.RequestException as exc:
            last_exc = exc
            if attempt < MAX_RETRIES:
                backoff = float(2**attempt)
                _log(
                    f"{method} {url} failed ({exc}); retrying in {backoff:.0f}s "
                    f"(attempt {attempt + 1}/{MAX_RETRIES})"
                )
                time.sleep(backoff)
                continue
            raise
        else:
            if resp.status_code == 429 or 500 <= resp.status_code < 600:
                if attempt < MAX_RETRIES:
                    backoff = float(2**attempt)
                    retry_after = resp.headers.get("Retry-After")
                    if retry_after:
                        try:
                            backoff = max(backoff, float(retry_after))
                        except ValueError:
                            pass
                    _log(
                        f"{method} {url} -> HTTP {resp.status_code}; retrying in "
                        f"{backoff:.0f}s (attempt {attempt + 1}/{MAX_RETRIES})"
                    )
                    time.sleep(backoff)
                    continue
            return resp

    if last_exc is not None:
        raise last_exc
    raise requests.RequestException(f"exhausted retries for {url}")


def get_json(
    url: str,
    params: dict | None = None,
    headers: dict | None = None,
    cache_ns: str = "misc",
    ttl_hours: float = 72,
):
    """GET ``url`` and parse the body as JSON, with caching and polite retries.

    Returns ``None`` on any failure (network error, non-2xx status, or a body
    that fails to parse as JSON) rather than raising. A literal JSON ``null``
    response also comes back as ``None`` — callers that need to distinguish
    "no data" from "request failed" should check the source's own semantics.
    """
    key = _cache_key("GET", url, params, headers)
    cpath = _cache_path(cache_ns, key, ".json")
    if _cache_fresh(cpath, ttl_hours):
        try:
            with open(cpath, encoding="utf-8") as f:
                return json.load(f)
        except (OSError, json.JSONDecodeError) as exc:
            _log(f"cache read failed for {cpath}: {exc}")

    try:
        resp = _request_with_retries("GET", url, params=params, headers=headers)
    except requests.RequestException as exc:
        _log(f"GET {url} failed: {exc}")
        return None

    if not resp.ok:
        _log(f"GET {url} -> HTTP {resp.status_code}")
        return None

    try:
        data = resp.json()
    except ValueError as exc:
        _log(f"GET {url} returned non-JSON body: {exc}")
        return None

    try:
        with open(cpath, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False)
    except OSError as exc:
        _log(f"cache write failed for {cpath}: {exc}")

    return data


def get_text(
    url: str,
    params: dict | None = None,
    headers: dict | None = None,
    cache_ns: str = "misc",
    ttl_hours: float = 72,
) -> str | None:
    """GET ``url`` and return the response body as text, with caching/retries.

    Returns ``None`` on failure rather than raising.
    """
    key = _cache_key("GET", url, params, headers)
    cpath = _cache_path(cache_ns, key, ".txt")
    if _cache_fresh(cpath, ttl_hours):
        try:
            with open(cpath, encoding="utf-8") as f:
                return f.read()
        except OSError as exc:
            _log(f"cache read failed for {cpath}: {exc}")

    try:
        resp = _request_with_retries("GET", url, params=params, headers=headers)
    except requests.RequestException as exc:
        _log(f"GET {url} failed: {exc}")
        return None

    if not resp.ok:
        _log(f"GET {url} -> HTTP {resp.status_code}")
        return None

    resp.encoding = resp.encoding or "utf-8"
    text = resp.text

    try:
        with open(cpath, "w", encoding="utf-8") as f:
            f.write(text)
    except OSError as exc:
        _log(f"cache write failed for {cpath}: {exc}")

    return text


def download(url: str, dest_path: Path | str) -> Path | None:
    """Download ``url`` as binary to ``dest_path``, with retries and rate limiting.

    ``dest_path`` doubles as the cache: if it already exists and is non-empty
    it is returned immediately without re-downloading. Returns ``None`` on
    failure rather than raising.
    """
    dest = Path(dest_path)
    if dest.exists() and dest.stat().st_size > 0:
        return dest
    dest.parent.mkdir(parents=True, exist_ok=True)

    try:
        resp = _request_with_retries("GET", url, stream=True)
    except requests.RequestException as exc:
        _log(f"GET {url} failed: {exc}")
        return None

    if not resp.ok:
        _log(f"GET {url} -> HTTP {resp.status_code}")
        return None

    tmp = dest.with_name(dest.name + ".part")
    try:
        with open(tmp, "wb") as f:
            for chunk in resp.iter_content(chunk_size=65536):
                if chunk:
                    f.write(chunk)
        tmp.replace(dest)
    except OSError as exc:
        _log(f"write failed for {dest}: {exc}")
        try:
            tmp.unlink(missing_ok=True)
        except OSError:
            pass
        return None

    return dest
