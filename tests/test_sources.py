import json
import os
import time
import urllib.error

import pytest

from claude_usage import api, cli

ENDPOINT = {"five_hour": {"utilization": 23.0, "resets_at": "2026-10-24T20:10:00.886739+00:00"},
            "seven_day": {"utilization": 59.0, "resets_at": "2026-10-25T07:00:00.886762+00:00"}}
STATUS = {"model": {"display_name": "Fable 5.1"}, "rate_limits": {
    "five_hour": {"used_percentage": 25, "resets_at": 1792000000},
    "seven_day": {"used_percentage": 59, "resets_at": 1792100000}}}


@pytest.fixture(autouse=True)
def local_only(monkeypatch, tmp_path):
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path))
    monkeypatch.setenv("CLAUDE_CODE_OAUTH_TOKEN", "PRIVATE-TOKEN")
    get_json = api._get_json
    monkeypatch.setattr(api, "_get_json", lambda *a, **k: pytest.fail("unmocked HTTP call"))
    return get_json


def save(tmp_path, name, data, age=0):
    path = tmp_path / name
    path.write_text(json.dumps(data))
    then = time.time() - age
    os.utime(path, (then, then))
    return path


def rate_limited(*args, **kwargs):
    raise urllib.error.HTTPError(api.URL, 429, "too many", {}, None)


def test_fresh_skips_endpoint_and_credentials(monkeypatch, tmp_path, capsys):
    save(tmp_path, 'last-usage.json', ENDPOINT, 180)
    monkeypatch.setattr(api, "resolve_token", lambda *a, **k: pytest.fail("credentials called"))
    out = api.usage(verbose=True)
    assert out['raw'] == ENDPOINT
    assert out['source'] == 'endpoint, 3 min ago'
    assert capsys.readouterr().err == 'usage: endpoint, 3 min ago\n'


def test_under_one_minute_source(tmp_path):
    save(tmp_path, 'last-usage.json', ENDPOINT, 20)
    assert api.usage()['source'] == 'endpoint'


def test_endpoint_success_saves_atomically(monkeypatch, tmp_path, capsys):
    def get(url, headers, timeout):
        assert url == 'https://api.anthropic.com/api/oauth/usage'
        assert headers == {"Authorization": "Bearer PRIVATE-TOKEN", "anthropic-beta": "oauth-2025-04-20", "Accept": "application/json"}
        assert timeout == 15
        return ENDPOINT
    monkeypatch.setattr(api, '_get_json', get)
    out = api.usage(verbose=True)
    assert out['source'] == 'endpoint'
    assert json.loads((tmp_path / 'last-usage.json').read_text()) == ENDPOINT
    assert not (tmp_path / 'last-usage.json.tmp').exists()
    assert capsys.readouterr().err == 'credentials: CLAUDE_CODE_OAUTH_TOKEN\nusage: endpoint\n'


def test_429_uses_stale_endpoint_before_status(monkeypatch, tmp_path):
    save(tmp_path, 'last-usage.json', ENDPOINT, 600)
    save(tmp_path, 'last-statusline.json', STATUS, 120)
    monkeypatch.setattr(api, '_get_json', rate_limited)
    assert api.usage()['source'] == 'endpoint, 10 min ago'


def test_429_uses_statusline(monkeypatch, tmp_path):
    save(tmp_path, 'last-usage.json', ENDPOINT, 3700)
    save(tmp_path, 'last-statusline.json', STATUS, 720)
    monkeypatch.setattr(api, '_get_json', rate_limited)
    out = api.usage()
    assert out['source'] == 'status line, 12 min ago'
    assert out['five_hour']['utilization'] == 25
    assert out['raw'] == STATUS


def test_all_fail_distinct_reasons_once(monkeypatch):
    monkeypatch.setattr(api, '_get_json', rate_limited)
    with pytest.raises(RuntimeError) as exc:
        api.usage()
    assert str(exc.value) == ('no saved endpoint answer yet; HTTP 429 from ' + api.URL +
                             '; no status-line cache yet (is the status line set to `claude-usage --statusline`?)')


def test_old_statusline_rejected(monkeypatch, tmp_path):
    save(tmp_path, 'last-statusline.json', STATUS, 3660)
    monkeypatch.setattr(api, '_get_json', rate_limited)
    with pytest.raises(RuntimeError, match='status-line cache is 61 min old'):
        api.usage()


def test_no_rate_limits_pro_max_message(monkeypatch, tmp_path):
    save(tmp_path, 'last-statusline.json', {"model": {"display_name": "Fable"}})
    monkeypatch.setattr(api, '_get_json', rate_limited)
    with pytest.raises(RuntimeError, match=r'no rate_limits \(Pro/Max only, after the first reply\)'):
        api.usage()


def test_urlerror_reason(monkeypatch):
    def get(*args):
        raise urllib.error.URLError('offline')
    monkeypatch.setattr(api, '_get_json', get)
    with pytest.raises(RuntimeError, match='; offline;'):
        api.usage()


def test_invalid_endpoint_cache_falls_through(monkeypatch, tmp_path):
    (tmp_path / 'last-usage.json').write_text('broken JSON')
    monkeypatch.setattr(api, '_get_json', lambda *args: ENDPOINT)
    assert api.usage()['raw'] == ENDPOINT


def test_new_config_directory_is_created(monkeypatch, tmp_path):
    config = tmp_path / 'new-config'
    monkeypatch.setattr(api, '_get_json', lambda *args: ENDPOINT)
    assert api.usage(config=config)['raw'] == ENDPOINT
    assert (config / 'last-usage.json').exists()


def test_cli_status_source_details_and_raw(monkeypatch, tmp_path, capsys):
    save(tmp_path, 'last-statusline.json', STATUS)
    monkeypatch.setattr(api, '_get_json', rate_limited)
    assert cli.main(['--all']) == 0
    out = capsys.readouterr().out
    assert '(from the status line, 0 min ago)' in out
    assert '(details not available from the status-line source)' in out
    assert cli.main(['--json']) == 0
    assert json.loads(capsys.readouterr().out) == STATUS


def test_get_json_uses_urllib(monkeypatch, local_only):
    # Exercise the real HTTP seam with an in-memory response, never a socket.
    import io
    def urlopen(request, timeout):
        assert request.full_url == api.URL
        assert request.get_method() == 'GET'
        assert request.get_header('Authorization') == 'Bearer test'
        assert timeout == 15
        return io.StringIO(json.dumps(ENDPOINT))
    monkeypatch.setattr(api.urllib.request, 'urlopen', urlopen)
    assert local_only(api.URL, {'Authorization': 'Bearer test'}, 15) == ENDPOINT


def test_request_errors_never_print_credentials(monkeypatch, capsys):
    def invalid_header(*args):
        raise ValueError("Invalid header value b'Bearer PRIVATE-TOKEN'")
    monkeypatch.setattr(api, '_get_json', invalid_header)
    assert cli.main(['-v']) == 1
    captured = capsys.readouterr()
    assert 'PRIVATE-TOKEN' not in captured.out + captured.err
    assert 'Bearer' not in captured.err
    assert 'invalid request or JSON response' in captured.err
