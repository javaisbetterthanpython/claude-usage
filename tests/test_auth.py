import json
import subprocess
import time
from types import SimpleNamespace

import pytest

from claude_usage import auth


@pytest.fixture(autouse=True)
def local_only(monkeypatch, tmp_path):
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path))
    monkeypatch.delenv("CLAUDE_CODE_OAUTH_TOKEN", raising=False)
    monkeypatch.setattr(auth.sys, "platform", "linux")


def credentials(tmp_path, **overrides):
    oauth = {"accessToken": "PRIVATE-TOKEN", "refreshToken": "PRIVATE-REFRESH",
             "expiresAt": (time.time() + 3600) * 1000}
    oauth.update(overrides)
    (tmp_path / '.credentials.json').write_text(json.dumps({"claudeAiOauth": oauth}))


def test_env_wins_as_is(monkeypatch, tmp_path, capsys):
    credentials(tmp_path, expiresAt=1)
    monkeypatch.setenv("CLAUDE_CODE_OAUTH_TOKEN", " token as-is ")
    monkeypatch.setattr(auth.sys, "platform", "darwin")
    monkeypatch.setattr(auth.subprocess, "run", lambda *a, **k: pytest.fail("keychain called"))
    assert auth.resolve_token(verbose=True) == " token as-is "
    assert capsys.readouterr().err == "credentials: CLAUDE_CODE_OAUTH_TOKEN\n"


def test_file_and_verbose(tmp_path, capsys):
    credentials(tmp_path)
    assert auth.resolve_token(verbose=True) == "PRIVATE-TOKEN"
    assert capsys.readouterr().err == "credentials: credentials file\n"


def test_expired_milliseconds_rejected(tmp_path):
    credentials(tmp_path, expiresAt=(time.time() - 10) * 1000)
    with pytest.raises(auth.CredentialsNotFound, match="open `claude` so it refreshes") as exc:
        auth.resolve_token()
    assert "PRIVATE" not in str(exc.value)


def test_missing_file_is_helpful():
    with pytest.raises(auth.CredentialsNotFound, match="run `claude` once to log in"):
        auth.resolve_token()


@pytest.mark.parametrize("raw", ['PRIVATE-TOKEN', '{"claudeAiOauth": "PRIVATE-TOKEN"}',
                                 '{"claudeAiOauth": {"accessToken": "PRIVATE-TOKEN", "expiresAt": "PRIVATE-REFRESH"}}',
                                 '{"claudeAiOauth": {"refreshToken": "PRIVATE-REFRESH"}}'])
def test_bad_credentials_never_leak(tmp_path, raw, capsys):
    (tmp_path / '.credentials.json').write_text(raw)
    with pytest.raises(auth.CredentialsNotFound) as exc:
        auth.resolve_token(verbose=True)
    assert "PRIVATE" not in str(exc.value) + capsys.readouterr().err


def test_keychain_first(monkeypatch, tmp_path, capsys):
    credentials(tmp_path)
    monkeypatch.setattr(auth.sys, "platform", "darwin")
    def run(command, **kwargs):
        assert command == ["security", "find-generic-password", "-s", "Claude Code-credentials", "-w"]
        return SimpleNamespace(returncode=0, stdout=json.dumps({"claudeAiOauth": {"accessToken": "keychain-token"}}))
    monkeypatch.setattr(auth.subprocess, "run", run)
    assert auth.resolve_token(verbose=True) == "keychain-token"
    assert capsys.readouterr().err == "credentials: macOS keychain\n"


@pytest.mark.parametrize("failure", ["unavailable", "missing", "malformed", "expired", "timeout"])
def test_keychain_failure_uses_file(monkeypatch, tmp_path, failure):
    credentials(tmp_path)
    monkeypatch.setattr(auth.sys, "platform", "darwin")
    def run(*args, **kwargs):
        if failure == "unavailable":
            raise OSError("PRIVATE-TOKEN")
        if failure == "timeout":
            raise subprocess.TimeoutExpired("PRIVATE-TOKEN", 15)
        raw = 'PRIVATE-TOKEN' if failure == "malformed" else json.dumps({"claudeAiOauth": {"accessToken": "old", "expiresAt": 1}})
        return SimpleNamespace(returncode=1 if failure == "missing" else 0, stdout=raw)
    monkeypatch.setattr(auth.subprocess, "run", run)
    assert auth.resolve_token() == "PRIVATE-TOKEN"


def test_empty_config_dir_uses_default(monkeypatch, tmp_path):
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", "")
    monkeypatch.setattr(auth.os.path, "expanduser", lambda path: str(tmp_path / ".claude"))
    assert auth.config_dir() == tmp_path / '.claude'
