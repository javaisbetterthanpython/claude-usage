import io
import json
from datetime import datetime, timedelta, timezone

import pytest

from claude_usage import cli, report

# Representative weekly payload based on the live response; values are illustrative.
ENDPOINT = {
    "seven_day": {"utilization": 59.0, "resets_at": "2026-10-25T07:00:00.886762+00:00",
                  "limit_dollars": None, "used_dollars": None, "remaining_dollars": None, "locked_reason": None},
    "seven_day_oauth_apps": None, "seven_day_opus": None, "seven_day_sonnet": None,
    "seven_day_cowork": None, "seven_day_omelette": None, "pace": None,
    "extra_usage": {"is_enabled": False, "monthly_limit": None, "used_credits": None,
                    "utilization": None, "currency": None, "decimal_places": None,
                    "disabled_reason": None, "user_disabled": True, "spend_limit_reached": False,
                    "credits_ever_enabled": True, "daily": None, "weekly": None},
    "limits": [
        {"kind": "weekly_all", "group": "weekly", "percent": 59, "severity": "normal",
         "resets_at": "2026-10-25T07:00:00.886762+00:00", "scope": None, "is_active": True},
        {"kind": "weekly_scoped", "group": "weekly", "percent": 6, "severity": "normal",
         "resets_at": "2026-10-25T07:00:00.886962+00:00",
         "scope": {"model": {"id": None, "display_name": "Fable"}, "surface": None}, "is_active": False},
    ],
    "spend": {"used": {"amount_minor": 0, "currency": "USD", "exponent": 2},
              "limit": None, "percent": 0, "severity": "normal", "enabled": False},
    "member_dashboard_available": False,
    "seven_day_breakdown": {"as_of": "...", "window_started_at": "...", "rows": [
        {"key": "claude_code", "display_name": "Claude Code", "percent": 96},
        {"key": "chat", "display_name": "Chats", "percent": 0},
        {"key": "cowork", "display_name": "Cowork", "percent": 4},
        {"key": "other", "display_name": "Other", "percent": 0},
    ]},
    "weekly_scoped_shares": [{"limit_index": 1, "used_percent_of_weekly": 3, "allowance_percent_of_weekly": 50}],
}
STATUS = {"model": {"display_name": "Fable 5.1"}, "rate_limits": {
    "seven_day": {"used_percentage": 59, "resets_at": 1792100000},
}}


@pytest.fixture(autouse=True)
def local_only(monkeypatch, tmp_path):
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path))
    monkeypatch.setattr(cli, "usage", lambda **kwargs: report.shape(ENDPOINT, "endpoint"))


def test_shape_endpoint():
    out = report.shape(ENDPOINT, "endpoint")
    assert out == {"seven_day": {"utilization": 59.0, "resets_at": ENDPOINT['seven_day']['resets_at']},
                   "source": "endpoint", "raw": ENDPOINT}
    assert report.shape({}, "endpoint")['seven_day'] == {"utilization": None, "resets_at": None}


def test_shape_status_line():
    out = report.shape(STATUS, "status line, 12 min ago")
    assert out['seven_day'] == {"utilization": 59.0, "resets_at": datetime.fromtimestamp(1792100000, timezone.utc).isoformat()}
    assert out['seven_day']['utilization'] == 59.0
    assert out['raw'] == STATUS
    assert report.shape({"rate_limits": {}}, "status line, 0 min ago")['seven_day']['resets_at'] is None


def test_when(monkeypatch):
    local_tz = datetime(2026, 10, 24).astimezone().tzinfo
    now = datetime(2026, 10, 24, 14, 31, tzinfo=local_tz)
    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return now.astimezone(tz)
    monkeypatch.setattr(report, "datetime", Clock)
    assert report.when((now + timedelta(minutes=99)).isoformat()) == "resets 16:10 (in 1h39m)"
    assert report.when((now + timedelta(minutes=7)).isoformat()) == "resets 14:38 (in 7m)"
    assert report.when((now + timedelta(days=1)).isoformat()) == "resets Sun 14:31 (in 24h00m)"
    assert report.when((now - timedelta(minutes=2)).isoformat()) == "resets 14:29 (in 0m)"
    assert report.when(None) == "reset time unknown"


@pytest.mark.parametrize("value,expected", [(23, "23%"), (23.6, "24%"), (0, "0%"), (None, "?")])
def test_pct(value, expected):
    assert report.pct({"utilization": value}) == expected
    assert report.pct({}) == "?"


def test_plain_exact_layout(monkeypatch):
    monkeypatch.setattr(report, "when", lambda iso: "reset time unknown")
    out = report.render_plain(report.shape(ENDPOINT, "endpoint, 3 min ago"))
    assert out == ("7-day: 59% used, reset time unknown\n"
                   "(from the endpoint, 3 min ago)")


def test_all_details(monkeypatch):
    monkeypatch.setattr(report, "when", lambda iso: "resets 16:10 (in 1h39m)")
    out = report.render_limits(report.shape(ENDPOINT, "endpoint"))
    assert "kind" in out and "severity" in out and "model" in out
    assert "weekly_all" in out and "59%" in out
    assert "weekly_scoped" in out and "6%" in out and "Fable" in out
    active = next(line for line in out.splitlines() if "weekly_all" in line)
    assert "active" in active
    assert out.count("resets 16:10 (in 1h39m)") == 2
    assert out.endswith("Claude Code 96%, Cowork 4%, Chats 0%, Other 0%")
    assert report.render_limits(report.shape(STATUS, "status line, 0 min ago")) == "(details not available from the status-line source)"
    assert report.render_limits(report.shape({}, "endpoint")) == ""


@pytest.mark.parametrize("raw,source,expected", [
    (ENDPOINT, "endpoint", "7d 59%"),
    (STATUS, "status line, 0 min ago", "Fable 5.1 · 7d 59%"),
    ({"model": {"display_name": "Fable"}}, "status line, 0 min ago", "Fable"),
    ({"rate_limits": {"seven_day": {"used_percentage": 0}}}, "status line, 0 min ago", "7d 0%"),
    ({}, "endpoint", ""),
])
def test_short(raw, source, expected):
    assert report.render_short(report.shape(raw, source)) == expected


@pytest.mark.parametrize("value,code", [(69, 0), (70, 1), (71, 1), (None, 0)])
@pytest.mark.parametrize("flag,key", [("--warn", "seven_day"), ("--warn-7d", "seven_day")])
def test_warn_default(monkeypatch, capsys, value, code, flag, key):
    raw = {key: {"utilization": value}}
    monkeypatch.setattr(cli, "usage", lambda **kwargs: report.shape(raw, "endpoint"))
    assert cli.main([flag]) == code
    assert "7-day:" in capsys.readouterr().out


def test_thresholds_combine_and_json(monkeypatch, capsys):
    assert cli.main(["--warn", "60", "--warn-7d", "59", "--json"]) == 1
    assert json.loads(capsys.readouterr().out) == ENDPOINT
    assert cli.main(["--warn", "59", "--warn-7d", "60", "--format", "short"]) == 1
    assert capsys.readouterr().out == "7d 59%\n"
    assert cli.main(["--warn", "60", "--warn-7d", "60"]) == 0


@pytest.mark.parametrize("args", [["--json"], ["--format", "json"], ["--all", "--json"]])
def test_json_raw_roundtrip(args, capsys):
    assert cli.main(args) == 0
    assert capsys.readouterr().out == json.dumps(ENDPOINT, indent=1) + '\n'


def test_cli_all(capsys):
    assert cli.main(["--all"]) == 0
    out = capsys.readouterr().out
    assert out.startswith("7-day: 59% used,")
    assert "weekly_scoped" in out and "Claude Code 96%" in out


@pytest.mark.parametrize("raw", ["garbage", "", "null", "[]", '"text"', "42"])
def test_statusline_bad_input_is_silent(monkeypatch, capsys, tmp_path, raw):
    monkeypatch.setattr(cli.sys, "stdin", io.StringIO(raw))
    monkeypatch.setattr(cli, "usage", lambda **k: pytest.fail("looked up usage"))
    assert cli.main(["--statusline"]) == 0
    assert capsys.readouterr() == ("", "")
    assert not (tmp_path / 'last-statusline.json').exists()


def test_statusline_cache_and_line(monkeypatch, capsys, tmp_path):
    monkeypatch.setattr(cli.sys, "stdin", io.StringIO(json.dumps(STATUS)))
    monkeypatch.setattr(cli, "usage", lambda **k: pytest.fail("looked up usage"))
    assert cli.main(["--statusline"]) == 0
    assert capsys.readouterr().out == "Fable 5.1 · 7d 59%\n"
    assert json.loads((tmp_path / 'last-statusline.json').read_text()) == STATUS
    assert not (tmp_path / 'last-statusline.json.tmp').exists()


def test_statusline_write_failure_is_silent(monkeypatch, capsys, tmp_path):
    config = tmp_path / 'a-file'
    config.write_text('blocked')
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(config))
    monkeypatch.setattr(cli.sys, "stdin", io.StringIO(json.dumps(STATUS)))
    assert cli.main(["--statusline"]) == 0
    assert capsys.readouterr() == ("", "")


def test_cli_failure(monkeypatch, capsys):
    def fail(**kwargs):
        raise RuntimeError("no sources answered")
    monkeypatch.setattr(cli, "usage", fail)
    assert cli.main([]) == 1
    assert capsys.readouterr() == ("", "claude-usage: no sources answered\n")


def test_version(capsys):
    with pytest.raises(SystemExit) as exc:
        cli.main(["--version"])
    assert exc.value.code == 0
    assert capsys.readouterr().out == "claude-usage 0.2.0\n"


def test_help_hides_statusline(capsys):
    with pytest.raises(SystemExit) as exc:
        cli.main(["--help"])
    assert exc.value.code == 0
    out = capsys.readouterr().out
    for flag in ("--json", "--warn", "--warn-7d", "--all", "--format", "--verbose", "--version"):
        assert flag in out
    assert '--statusline' not in out


def test_argparse_error(capsys):
    with pytest.raises(SystemExit) as exc:
        cli.main(["--format", "bad"])
    assert exc.value.code == 2


@pytest.mark.parametrize('legacy', [None, {'utilization': 99, 'resets_at': 'bad date'}])
@pytest.mark.parametrize('source', ['endpoint', 'status line, 0 min ago'])
def test_retired_window_ignored_and_removed_from_json(monkeypatch, capsys, legacy, source):
    windows = {'five_hour': legacy, 'seven_day': None}
    raw = {'rate_limits': windows} if source.startswith('status line') else windows
    shaped = report.shape(raw, source)
    assert 'five_hour' not in shaped
    assert 'five_hour' not in json.dumps(shaped['raw'])
    assert raw.get('rate_limits', raw)['five_hour'] == legacy  # Never mutate the cache/feed.
    assert report.render_short(shaped) == ''
    assert report.render_plain(shaped).startswith('7-day: ? used, reset time unknown')
    monkeypatch.setattr(cli, 'usage', lambda **kwargs: shaped)
    assert cli.main(['--json', '--warn']) == 0
    assert 'five_hour' not in capsys.readouterr().out


def test_legacy_session_details_and_share_indices(monkeypatch, capsys):
    raw = dict(ENDPOINT, five_hour={'utilization': 99})
    raw['limits'] = [{'kind': 'session', 'group': 'session', 'percent': 99}] + ENDPOINT['limits']
    raw['weekly_scoped_shares'] = [dict(ENDPOINT['weekly_scoped_shares'][0], limit_index=2)]
    shaped = report.shape(raw, 'endpoint')
    assert shaped['raw'] == ENDPOINT
    assert raw['weekly_scoped_shares'][0]['limit_index'] == 2
    monkeypatch.setattr(cli, 'usage', lambda **kwargs: shaped)
    assert cli.main(['--all', '--warn']) == 0
    assert 'session' not in capsys.readouterr().out


@pytest.mark.parametrize('source', ['endpoint', 'status line, 0 min ago'])
def test_populated_weekly_variants(monkeypatch, capsys, source):
    status = source.startswith('status line')
    field = 'used_percentage' if status else 'utilization'
    windows = {'seven_day': {field: 10}, 'seven_day_opus': {field: 70},
               'seven_day_omelette': {field: 20}, 'seven_day_sonnet': None,
               'seven_day_breakdown': {'rows': []}}
    raw = {'rate_limits': windows} if status else windows
    shaped = report.shape(raw, source)
    assert report.render_short(shaped) == '7d 10% · 7d omelette 20% · 7d opus 70%'
    assert '7-day opus: 70% used' in report.render_plain(shaped)
    monkeypatch.setattr(cli, 'usage', lambda **kwargs: shaped)
    assert cli.main(['--warn']) == 1
    assert cli.main(['--warn-7d']) == 0
    assert cli.main(['--warn', '71']) == 0


@pytest.mark.parametrize('percent,code', [(69, 0), (70, 1), (71, 1), (None, 0)])
def test_weekly_scoped_limit_warning(monkeypatch, percent, code):
    raw = {'seven_day': {'utilization': 10},
           'limits': [{'kind': 'weekly_scoped', 'group': 'weekly', 'percent': percent}]}
    monkeypatch.setattr(cli, 'usage', lambda **kwargs: report.shape(raw, 'endpoint'))
    assert cli.main(['--warn']) == code
    assert cli.main(['--warn-7d']) == 0


def test_missing_weekly_window_does_not_warn_at_zero(monkeypatch):
    monkeypatch.setattr(cli, 'usage', lambda **kwargs: report.shape({}, 'endpoint'))
    assert cli.main(['--warn', '0', '--warn-7d', '0']) == 0
