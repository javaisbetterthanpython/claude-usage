"""Turn endpoint and status-line payloads into compact usage reports."""

from datetime import datetime, timezone


def shape(data, source):
    """Normalize either source, retaining its untouched payload for ``--json``."""
    if not isinstance(data, dict):
        raise ValueError("usage data is not a JSON object")
    out = {"source": source, "raw": data}
    status = source.startswith("status line")
    windows = (data.get("rate_limits") or {}) if status else data
    for key in ("five_hour", "seven_day"):
        window = windows.get(key) or {}
        reset = window.get("resets_at")
        if status and reset is not None:
            reset = datetime.fromtimestamp(reset, timezone.utc).isoformat()
        used = window.get("used_percentage" if status else "utilization")
        out[key] = {"utilization": float(used) if used is not None else None,
                    "resets_at": reset}
    return out


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
    for label, key in (("5-hour:", "five_hour"), ("7-day: ", "seven_day")):
        window = usage[key]
        out.append(f"{label} {pct(window)} used, {when(window['resets_at'])}")
    if usage['source'] != 'endpoint':
        out.append(f"(from the {usage['source']})")
    return '\n'.join(out)


def render_short(usage):
    """Render the same compact line for ``--format short`` and ``--statusline``."""
    model = (usage['raw'].get('model') or {}).get('display_name')
    parts = [model] if model else []
    for label, key in (("5h", "five_hour"), ("7d", "seven_day")):
        if usage[key]['utilization'] is not None:
            parts.append(f"{label} {pct(usage[key])}")
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
