"""Resolve Claude Code's OAuth access token from local credential stores.

Priority: explicit environment override, macOS Keychain, credentials JSON.
Only Claude Code refreshes tokens; this tool never writes credentials. Errors
and verbose notes can identify the source and plan without exposing tokens.
"""

import json
import os
import subprocess
import sys
import time
from pathlib import Path

KEYCHAIN_SERVICE = "Claude Code-credentials"


class CredentialsNotFound(RuntimeError):
    """Raised when no usable Claude Code OAuth access token can be located."""


def config_dir():
    return Path(os.environ.get("CLAUDE_CONFIG_DIR") or os.path.expanduser("~/.claude"))


def _oauth_from_credentials(creds):
    try:
        oauth = creds.get("claudeAiOauth") or {}
        token = oauth.get("accessToken")
        expires = oauth.get("expiresAt")
        expired = expires is not None and float(expires) / 1000 < time.time()
    except (AttributeError, TypeError, ValueError):
        raise CredentialsNotFound("could not read Claude Code credentials; run `claude` once to log in") from None
    if not isinstance(token, str) or not token:
        raise CredentialsNotFound("credentials hold no OAuth access token; run `claude` once to log in")
    if expired:
        raise CredentialsNotFound("the access token has expired; open `claude` so it refreshes")
    return oauth


def _log(verbose, source):
    if verbose:
        print("credentials: " + source, file=sys.stderr)


def _resolve_credentials(config):
    override = os.environ.get("CLAUDE_CODE_OAUTH_TOKEN")
    if override:
        return override, None, "CLAUDE_CODE_OAUTH_TOKEN"

    keychain_error = None
    if sys.platform == "darwin":
        try:
            out = subprocess.run(
                ["security", "find-generic-password", "-s", KEYCHAIN_SERVICE, "-w"],
                capture_output=True, text=True, timeout=15,
            )
            if out.returncode == 0:
                oauth = _oauth_from_credentials(json.loads(out.stdout))
                return oauth["accessToken"], oauth, "macOS keychain"
        except CredentialsNotFound as exc:
            keychain_error = exc
        except (OSError, ValueError, subprocess.SubprocessError):
            pass

    path = (Path(config) if config is not None else config_dir()) / '.credentials.json'
    try:
        with path.open(encoding="utf-8") as stream:
            creds = json.load(stream)
    except (OSError, ValueError):
        if keychain_error is not None:
            raise keychain_error from None
        raise CredentialsNotFound("no readable Claude Code credentials file; run `claude` once to log in") from None
    oauth = _oauth_from_credentials(creds)
    return oauth["accessToken"], oauth, "credentials file"


def resolve_token(config=None, verbose=False):
    """Return an access token, trying the file if the keychain is unavailable."""
    token, _, source = _resolve_credentials(config)
    _log(verbose, source)
    return token


def resolve_plan(config=None):
    """Return the plan and optional tier for verbose diagnostics."""
    try:
        _, oauth, _ = _resolve_credentials(config)
        if oauth is None:
            return None
        subscription = oauth.get("subscriptionType") or ""
        tier = oauth.get("rateLimitTier") or ""
        if not isinstance(subscription, str) or not isinstance(tier, str):
            return None
        if "max_20x" in tier:
            plan = "Ultra"
        elif "max_5x" in tier:
            plan = "Max"
        else:
            plan = subscription.title() or "unknown"
        return f"{plan} ({tier})" if tier else plan
    except Exception:
        return None
