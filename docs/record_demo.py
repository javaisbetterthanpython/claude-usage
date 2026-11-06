#!/usr/bin/env python3
"""Render docs/demo.gif with agg using the real CLI and illustrative local caches.

Run from a checkout: python3 docs/record_demo.py
Requires agg (https://github.com/asciinema/agg) on PATH. No credentials or network
are used by the recorded commands. The temporary asciicast is deleted afterward.
"""

import json
import os
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def main():
    agg = shutil.which('agg')
    if not agg:
        raise SystemExit('Install agg from https://github.com/asciinema/agg/releases first.')

    reset = (datetime.now(timezone.utc) + timedelta(days=2)).replace(
        hour=3, minute=0, second=0, microsecond=0)
    payload = {
        'seven_day': {'utilization': 59, 'resets_at': reset.isoformat()},
        'limits': [
            {'kind': 'weekly_all', 'group': 'weekly', 'percent': 59,
             'severity': 'normal', 'is_active': True, 'resets_at': reset.isoformat()},
            {'kind': 'weekly_scoped', 'group': 'weekly', 'percent': 6,
             'severity': 'normal', 'is_active': False, 'resets_at': reset.isoformat(),
             'scope': {'model': {'display_name': 'Claude'}}},
        ],
        'seven_day_breakdown': {'rows': [
            {'display_name': 'Claude Code', 'percent': 96},
            {'display_name': 'Cowork', 'percent': 4},
            {'display_name': 'Chats', 'percent': 0},
            {'display_name': 'Other', 'percent': 0},
        ]},
    }
    status = {'model': {'display_name': 'Claude'}, 'rate_limits': {
        'seven_day': {'used_percentage': 59, 'resets_at': reset.timestamp()},
    }}
    events = []
    elapsed = 0.0

    def emit(text, delay=0.0):
        nonlocal elapsed
        elapsed += delay
        events.append([round(elapsed, 3), 'o', text.replace('\n', '\r\n')])

    def page():
        emit('\x1b[2J\x1b[H\x1b[?25l'
             '\x1b[1;36mclaude-usage | weekly subscription limits\x1b[0m\n'
             '\x1b[90mIllustrative data | local cache | no network\x1b[0m\n\n')

    with tempfile.TemporaryDirectory(prefix='claude-usage-demo-') as directory:
        config = Path(directory)
        env = dict(os.environ, CLAUDE_CONFIG_DIR=directory, TZ='UTC',
                   PYTHONPATH=str(ROOT / 'src'), PYTHONIOENCODING='utf-8')
        env.pop('CLAUDE_CODE_OAUTH_TOKEN', None)

        def record(args, expected=0, stdin=None, show_exit=False):
            (config / 'last-usage.json').write_text(json.dumps(payload), encoding='utf-8')
            command = 'claude-usage' + ((' ' + ' '.join(args)) if args else '')
            if show_exit:
                command += '; echo "exit: $?"'
            emit('\x1b[32m$ \x1b[0m')
            for char in command:
                emit(char, 0.035)
            emit('\n', 0.2)
            result = subprocess.run([sys.executable, '-m', 'claude_usage'] + args,
                                    input=stdin, capture_output=True, text=True,
                                    cwd=ROOT, env=env, timeout=15)
            if result.returncode != expected or result.stderr:
                raise RuntimeError(f'{command} failed: {result.stderr}')
            emit(result.stdout, 0.15)
            if show_exit:
                emit(f'exit: {result.returncode}\n')

        page()
        record([])
        elapsed += 4
        page()
        record(['--all'])
        elapsed += 6
        page()
        record(['--warn', '50'], expected=1, show_exit=True)
        elapsed += 4
        page()
        record(['--format', 'short'])
        emit('\n\x1b[90mClaude Code supplies status JSON on stdin:\x1b[0m\n\n', 2)
        record(['--statusline'], stdin=json.dumps(status))
        cast = config / 'demo.cast'
        with cast.open('w', encoding='utf-8') as stream:
            stream.write(json.dumps({'version': 2, 'width': 96, 'height': 20,
                                     'title': 'claude-usage weekly limits demo'}) + '\n')
            for event in events:
                stream.write(json.dumps(event) + '\n')
        subprocess.run([agg, '--theme', 'github-dark', '--font-size', '17',
                        '--font-family', 'DejaVu Sans Mono', '--idle-time-limit', '8',
                        '--last-frame-duration', '5', str(cast), str(ROOT / 'docs/demo.gif')],
                       check=True)
    print('Regenerated docs/demo.gif')


if __name__ == '__main__':
    main()
