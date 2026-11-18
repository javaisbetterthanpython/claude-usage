"""Turn endpoint and status-line payloads into compact usage reports."""

from datetime import datetime, timezone


def shape(data, source):
    """Normalize usage windows and retain the untouched payload for JSON output."""
    if not isinstance(data, dict):
        raise ValueError("usage data is not a JSON object")
    out = {"source": source, "raw": data}
    status = source.startswith("status line")
    windows = (data.get("rate_limits") or {}) if status else data
    keys = ["seven_day"] + sorted(key for key, value in windows.items()
                                   if key.startswith("seven_day_") and isinstance(value, dict)
                                   and ("utilization" in value or "used_percentage" in value))
    if isinstance(windows.get("five_hour"), dict):
        keys.insert(0, "five_hour")
    for key in keys:
        window = windows.get(key) or {}
        reset = window.get("resets_at")
        if status and reset is not None:
            reset = datetime.fromtimestamp(reset, timezone.utc).isoformat()
        used = window.get("used_percentage" if status else "utilization")
        out[key] = {"utilization": float(used) if used is not None else None,
                    "resets_at": reset}
    return out


def usage_windows(usage):
    """Yield normalized usage windows in display order."""
    return ((key, window) for key, window in usage.items()
            if key in ("five_hour", "seven_day") or key.startswith("seven_day_"))


def window_label(key, short=False):
    if key == "five_hour":
        return "5h" if short else "5-hour"
    label = "7d" if short else "7-day"
    suffix = key[len("seven_day"):].strip("_").replace("_", " ")
    return f"{label} {suffix}" if suffix else label


def warning_reached(usage, threshold):
    """Check normalized windows and the endpoint's session and weekly limits."""
    values = [window['utilization'] for _, window in usage_windows(usage)]
    values.extend(limit.get('percent') for limit in usage['raw'].get('limits') or []
                  if limit.get('group') in ('session', 'weekly') or limit.get('kind') == 'session'
                  or limit.get('kind', '').startswith('weekly_'))
    return any(value is not None and float(value) >= threshold for value in values)


def when(iso):
    if not iso:
        return "reset time unknown"
    t = datetime.fromisoformat(iso.replace("Z", "+00:00")).astimezone()
    now = datetime.now(t.tzinfo)
    mins = max(0, int((t - now).total_seconds() // 60))
    h, m = divmod(mins, 60)
    span = f"{h}h{m:02d}m" if h else f"{m}m"
    day = "" if t.date() == now.date() else t.strftime("%a ")
    return f"resets {day}{t:%H:%M} (in {span})"


def pct(window):
    used = window.get("utilization")
    return "?" if used is None else f"{used:.0f}%"


def render_plain(usage):
    out = []
    for key, window in usage_windows(usage):
        out.append(f"{window_label(key)}: {pct(window)} used, {when(window['resets_at'])}")
    if usage['source'] != 'endpoint':
        out.append(f"(from the {usage['source']})")
    return '\n'.join(out)


def render_short(usage):
    """Render the same compact line for ``--format short`` and ``--statusline``."""
    model = (usage['raw'].get('model') or {}).get('display_name')
    parts = [model] if model else []
    for key, window in usage_windows(usage):
        if window['utilization'] is not None:
            parts.append(f"{window_label(key, short=True)} {pct(window)}")
    return ' · '.join(parts)


def render_limits(usage):
    """Render per-limit detail and the weekly surface split, when available."""
    if usage['source'].startswith('status line'):
        return '(details not available from the status-line source)'
    raw = usage['raw']
    out = []
    limits = raw.get('limits') or []
    if limits:
        out.append('%-16s %7s  %-10s %-7s %-12s %s' %
                   ('kind', 'percent', 'severity', 'active', 'model', 'reset'))
        out.append('-' * 78)
        for limit in limits:
            model = ((limit.get('scope') or {}).get('model') or {}).get('display_name', '')
            out.append('%-16s %7s  %-10s %-7s %-12s %s' % (
                limit.get('kind', '?'), pct({'utilization': limit.get('percent')}),
                limit.get('severity', '?'), 'active' if limit.get('is_active') else '',
                model, when(limit.get('resets_at')),
            ))
    rows = (raw.get('seven_day_breakdown') or {}).get('rows') or []
    if rows:
        out.append(', '.join('%s %s' % (row.get('display_name', row.get('key', '?')),
                                      pct({'utilization': row.get('percent')}))
                             for row in sorted(rows, key=lambda row: -(row.get('percent') or 0))))
    return '\n'.join(out)
