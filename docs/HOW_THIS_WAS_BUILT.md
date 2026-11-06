# How this tool was built (a guide for the next LLM/engineer)

This is a reproducible recipe for rebuilding `claude-usage`, following the
structure of the sibling `cursor-usage` project. The starting point was a
known-good, stdlib-only single-file script written on 2026-10-24 and the
handoff notes that came with it. The standalone project preserves its command,
source order and cache names. Version 0.2.0 reports weekly limits and filters
retired session data from JSON output.

> Scope/ethics: read **your own** local Claude Code login to query **your own**
> subscription usage from Anthropic's servers. Don't use accounts you don't control.

## 1. The goal and the missing command

Goal: show weekly subscription usage and model limits from a shell, so scripts,
hooks, and agents can decide when to back off. `claude --help` and the CLI
reference have no `claude usage` subcommand as of Claude Code 2.1.198. `/usage`
exists inside the interactive session, but cannot supply this usage to
a shell script. The official place to request a CLI equivalent is `/feedback`
in Claude Code.

## 2. The endpoint Claude Code calls

Claude Code's interactive `/usage` (and `/status`) calls:

```http
GET https://api.anthropic.com/api/oauth/usage
Authorization: Bearer <claudeAiOauth.accessToken>
anthropic-beta: oauth-2025-04-20
Accept: application/json
```

This is an **undocumented OAuth endpoint**, not a public API-key usage API.
Use Claude Code's existing OAuth bearer token. The beta header matters. The
request uses stdlib `urllib`, a 15-second timeout, and no retries.

## 3. Finding the token locally

Resolve in this order:

1. `CLAUDE_CODE_OAUTH_TOKEN`, the environment override Claude Code itself honors.
   Use it as-is, without a local expiry check.
2. On macOS, Keychain service **`Claude Code-credentials`** (the service name was
   observed locally, not documented). Read its JSON with
   `security find-generic-password -s "Claude Code-credentials" -w`.
3. The file `<config_dir>/.credentials.json`. This works on Linux and Windows,
   and on macOS when the keychain is unavailable, such as over SSH.

`config_dir = os.environ.get("CLAUDE_CONFIG_DIR") or os.path.expanduser("~/.claude")`.
Thus the default file is `~/.claude/.credentials.json` on macOS/Linux or
`%USERPROFILE%\.claude\.credentials.json` on Windows. Claude Code normally
protects the file with mode 0600. The tool only reads it.

Credential shape (all values redacted; the numeric example illustrates units):

```json
{
  "claudeAiOauth": {
    "accessToken": "<redacted>",
    "refreshToken": "<redacted>",
    "expiresAt": 1792869931685,
    "refreshTokenExpiresAt": "<redacted>",
    "scopes": ["user:file_upload", "user:inference", "user:mcp_servers", "user:plugins", "user:profile", "user:sessions:claude_code"],
    "subscriptionType": "<redacted>",
    "subscriptionTypeSource": "<redacted>",
    "rateLimitTier": "<redacted>"
  },
  "organizationUuid": "<redacted>"
}
```

`expiresAt` is **milliseconds since epoch**, so reject when
`expiresAt / 1000 < time.time()`. Tell the user to open `claude` so it refreshes.
Access tokens lasted roughly a day in observation; any running Claude Code
session keeps them fresh. Do **not** implement refresh: that flow is
undocumented, and writing credentials introduces needless risk. Neither errors
nor verbose logs may contain any part of the JSON, token, or request headers.

## 4. The observed response and fields that matter

The live endpoint was rechecked on 2026-11-06 using the same token resolver,
beta header, HTTP implementation, and timeout as the CLI. It returned a populated
`seven_day` object and a null retired session field. There was no session entry
in `limits`. No replacement short-duration window was observed.

**Used for the default report:** `seven_day.utilization`, `seven_day.resets_at`,
and any populated `seven_day_*` objects containing usage percentages. Nullable
weekly variants observed were `seven_day_oauth_apps`, `seven_day_opus`,
`seven_day_sonnet`, `seven_day_cowork`, and `seven_day_omelette`. Do not interpret
`seven_day_breakdown` as a usage window.

**Used for `--all`:** `limits[]` and `seven_day_breakdown.rows[]`. The live
`limits` entries contained `kind`, `group`, `percent`, `severity`, `resets_at`,
`scope`, and `is_active`. The scoped entry included `scope.model.id`,
`scope.model.display_name`, and `scope.surface`.

- `utilization` is a float percentage; `resets_at` is ISO 8601 with an offset.
  Convert resets to local time and clamp elapsed countdowns to zero minutes.
- `limits[]` contains overall and scoped weekly limits. `weekly_scoped` adds a
  model cap through `scope.model.display_name`. `--warn` checks all normalized
  weekly windows and weekly entries in `limits`; `--warn-7d` checks only the
  overall `seven_day` window. Both default to an inclusive 70% threshold.
- `seven_day_breakdown` contains `as_of`, `window_started_at`, and `rows` with
  `key`, `display_name`, and `percent`. Sort rows by descending percentage,
  retaining input order for ties.
- `weekly_scoped_shares` contains `limit_index`, `used_percent_of_weekly`, and
  `allowance_percent_of_weekly`. Indices refer to positions in `limits`.
- `extra_usage` describes optional credits, while `spend` describes spending.
  These and `member_dashboard_available`, `pace`, and nullable feature flags
  are retained in JSON without treating them as subscription windows. The live
  `spend` object also included `disabled_reason`, `cap`, `balance`, `auto_reload`,
  `disclaimer`, `can_purchase_credits`, and `can_toggle`.

JSON output preserves other received fields, but removes retired session fields
from endpoint and status-line payloads and session entries from `limits`.
`weekly_scoped_shares.limit_index` is remapped when entries are removed. This
also applies to old cached answers, without mutating their original payload.
An absent or null weekly window renders as unknown in plain output, is omitted
in short output, and never triggers a threshold warning.

## 5. The measured 429 behavior drives the cache design

The first call returned HTTP 200 in well under a second. A second call a few
seconds later returned **429**. Five or six calls over the next few minutes
stayed at 429 for roughly **four minutes**, then a call succeeded. These are
observations, not a guaranteed rate-limit policy.

Consequences:

1. Read `last-usage.json` if younger than **300 seconds** (`FRESH`).
2. Try the live endpoint exactly once; atomically save a successful answer.
3. If that fails, accept `last-usage.json` younger than **3600 seconds** (`MAX_AGE`).
4. If that fails, accept `last-statusline.json` younger than **3600 seconds** with
   a non-empty `rate_limits` object.

Both caches live in the config directory above. Writes use a sibling `.tmp`
file and `os.replace`, so readers see complete JSON. A failed live fetch does
not overwrite the last good answer. HTTP failures say `HTTP <code> from <url>`;
URL errors use their reason. If all sources fail, collect distinct error strings
in source order and join with `; `, then print `claude-usage: <reasons>` to stderr
and exit 1. There are no retries, timer, or polling loop.

## 6. The documented fallback: status-line JSON

Claude Code pipes a JSON object to `statusLine.command` on every repaint. The
subscription fields documented at the status-line reference are:

```json
{
  "model": {"display_name": "Fable 5.1"},
  "rate_limits": {
    "seven_day": {"used_percentage": 59, "resets_at": 1792100000}
  }
}
```

`used_percentage` is percent used. **`resets_at` is Unix epoch seconds**, unlike
credential expiry in milliseconds. Map it to an ISO 8601 UTC timestamp for the
shared report shape. `rate_limits.spend_limit` is for gateway deployments, not
a weekly subscription window.

The documented subscription `rate_limits` fields are **Pro/Max only**, available
only after the session's first API response. Each window may be absent
independently and is dropped after its reset time passes. The fallback can lag:
it updates only while an active session repaints.

That is why `--statusline` exists: it captures the documented feed into
`last-statusline.json`, while printing `Model · 7d N%` with missing parts
omitted. Configure it by merging this into Claude Code's settings:

```json
{"statusLine": {"type": "command", "command": "claude-usage --statusline"}}
```

It short-circuits before credential lookup or network activity. Invalid JSON
or a non-object input prints nothing and returns 0; cache write failures are
also silent so the status line never shows a traceback. This mode never calls
the OAuth endpoint, even when the cache is old.

## 7. Turning the script into a package

Use the sibling `cursor-usage-cli` conventions: setuptools, a `src/` layout,
module docstrings, small functions, pytest assertions, a centered README title
and badge row, and MIT contributor licensing.

- `auth.py`: environment → macOS Keychain → file, expiry check, safe source-only logs.
- `api.py`: injectable config directory, one `_get_json` HTTP seam, atomic caches,
  source order, distinct failures. Tests mock the seam and use `os.utime` for ages.
- `report.py`: normalize weekly `{utilization, resets_at}` windows plus `source`
  and filtered `raw`; local reset times, percentages, plain/short/detail renderers.
- `cli.py`: argparse, `main(argv=None)` returning an int, hidden status-line mode.
  `__main__.py` uses `sys.exit(main())`.
- New flags: `--warn-7d [N]`, `--all`, `--format {plain,json,short}`, safe `-v`, `-V`.
  Keep `--warn [N]` (default 70, inclusive), `--json` with `indent=1`, weekly
  plain output, and the `claude-usage` command name.

`--json` and `--format` set the same argparse destination; the last wins.
`--all` adds detail only to plain output. Missing window utilization never
triggers a threshold warning. Exit codes remain 0 for success, 1 for either threshold
or unavailable data, 2 for argparse errors.

The PyPI distribution is **`claude-usage-limits`**, because `claude-usage`,
`claude-usage-cli`, and `claude-code-usage` were already taken. The repo and
console command remain `claude-usage`; the import is `claude_usage`.

## 8. Cross-OS notes

Only the keychain subprocess is macOS-specific. Linux/Windows use the credentials
file; macOS falls back to the same file when its keychain is unavailable. There
is no `jq`, requests, optional keyring dependency, shell subprocess for HTTP,
or platform-specific cache implementation. Paths use `pathlib`, timestamps use
stdlib `datetime`, and HTTP uses `urllib`.

Python 3.9+ is the compatibility floor. Use neither `match` nor `X | Y` type
unions. Windows support follows the file and stdlib paths; it was not validated
on a real Windows machine during the original observation. Over SSH, opening
`claude` to log in or refresh remains the recovery path.

## 9. How to re-verify quickly (one-liner, macOS)

**Run this once, not in a loop.** A second request seconds later can cause
minutes of 429s. Do not enable shell tracing (`set -x`). The token stays in a
shell variable and is never echoed. This bypasses the tool's cache deliberately:

```bash
CLAUDE_USAGE_TOKEN=$(security find-generic-password -s "Claude Code-credentials" -w | python3 -c 'import json,sys; print(json.load(sys.stdin)["claudeAiOauth"]["accessToken"])'); curl -sS -H "Authorization: Bearer $CLAUDE_USAGE_TOKEN" -H "anthropic-beta: oauth-2025-04-20" -H "Accept: application/json" https://api.anthropic.com/api/oauth/usage; unset CLAUDE_USAGE_TOKEN
```

If that returns a `seven_day` usage object, the protocol still works. For ordinary
verification use the mocked test suite instead:

```bash
python3.12 -m venv .venv
.venv/bin/pip install -e . pytest
.venv/bin/pytest -q
.venv/bin/claude-usage --help
.venv/bin/claude-usage --version
```

## Reference links

- Status line JSON (documented `rate_limits`): https://code.claude.com/docs/en/statusline.md
- Credential storage: https://code.claude.com/docs/en/authentication.md
- `/usage` description and the "usage endpoint is rate limited" remark: https://code.claude.com/docs/en/costs.md
- Limit error messages: https://code.claude.com/docs/en/errors.md
- CLI reference (confirms there is no `claude usage` subcommand as of 2.1.198): https://code.claude.com/docs/en/cli-reference.md
- Third-party report of persistent 429s from the endpoint (unverified): https://claudeissues.com/issue/31021-oauth-usage-api-api-oauth-usage-returns-persistent-429-rate-limit
- Sibling project with the same layout and publishing flow: https://github.com/javaisbetterthanpython/cursor-usage
