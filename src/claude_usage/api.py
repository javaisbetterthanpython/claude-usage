"""Minimal OAuth usage client with endpoint and documented status-line caches.

The undocumented endpoint is rate limited: reuse answers for five minutes,
make at most one live request, then accept either cache for up to an hour.
No retries, polling, or token refresh. All HTTP goes through ``_get_json``.
"""

import json
import os
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

from .auth import config_dir, resolve_token
from .report import shape

URL = "https://api.anthropic.com/api/oauth/usage"
FRESH = 300
MAX_AGE = 3600


def write_cache(path, data):
    """Replace a cache atomically, never exposing a partially written JSON file."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + '.tmp')
    with tmp.open('w', encoding='utf-8') as stream:
        json.dump(data, stream)
    os.replace(tmp, path)


def _get_json(url, headers, timeout):
    request = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.load(response)


def from_endpoint(config, verbose=False):
    headers = {
        'Authorization': 'Bearer ' + resolve_token(config, verbose=verbose),
        'anthropic-beta': 'oauth-2025-04-20',
        'Accept': 'application/json',
    }
    try:
        data = _get_json(URL, headers, 15)
    except urllib.error.HTTPError as exc:
        raise RuntimeError(f'HTTP {exc.code} from {URL}') from None
    except urllib.error.URLError as exc:
        raise RuntimeError(str(exc.reason)) from None
    except (ValueError, TypeError):
        # A rejected HTTP header can appear verbatim in the library exception.
        raise RuntimeError(f'invalid request or JSON response from {URL}') from None
    out = shape(data, 'endpoint')
    write_cache(Path(config) / 'last-usage.json', data)
    return out


def from_last(config, max_age):
    path = Path(config) / 'last-usage.json'
    if not path.exists():
        raise RuntimeError('no saved endpoint answer yet')
    age = time.time() - path.stat().st_mtime
    if age >= max_age:
        raise RuntimeError(f'last endpoint answer is {int(age // 60)} min old')
    with path.open(encoding='utf-8') as stream:
        data = json.load(stream)
    source = f'endpoint, {int(age // 60)} min ago' if age >= 60 else 'endpoint'
    return shape(data, source)


def from_cache(config):
    path = Path(config) / 'last-statusline.json'
    if not path.exists():
        raise RuntimeError('no status-line cache yet (is the status line set to `claude-usage --statusline`?)')
    age = time.time() - path.stat().st_mtime
    if age >= MAX_AGE:
        raise RuntimeError(f'status-line cache is {int(age // 60)} min old')
    with path.open(encoding='utf-8') as stream:
        data = json.load(stream)
    if not isinstance(data, dict) or not data.get('rate_limits'):
        raise RuntimeError('status-line cache has no rate_limits (Pro/Max only, after the first reply)')
    return shape(data, f'status line, {int(age // 60)} min ago')


def usage(config=None, verbose=False):
    """Return the first available source or raise its distinct failure reasons."""
    config = Path(config) if config is not None else config_dir()
    errors = []
    sources = (lambda: from_last(config, FRESH),
               lambda: from_endpoint(config, verbose=verbose),
               lambda: from_last(config, MAX_AGE),
               lambda: from_cache(config))
    for source in sources:
        try:
            out = source()
        except (RuntimeError, OSError, ValueError, KeyError, TypeError, AttributeError, OverflowError) as exc:
            if str(exc) not in errors:
                errors.append(str(exc))
        else:
            if verbose:
                print('usage: ' + out['source'], file=sys.stderr)
            return out
    raise RuntimeError('; '.join(errors))
