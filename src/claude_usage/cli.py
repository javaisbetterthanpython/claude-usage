"""Command-line entry point for claude-usage."""

import argparse
import json
import sys

from . import __version__
from .api import usage, write_cache
from .auth import config_dir
from .report import render_limits, render_plain, render_short, shape


def build_parser():
    p = argparse.ArgumentParser(
        prog='claude-usage',
        description="Show Claude subscription rate limits: the 5-hour and 7-day usage windows.",
    )
    p.add_argument('--json', action='store_const', dest='format', const='json',
                   help='print the raw JSON that was used (alias for --format json)')
    p.add_argument('--warn', type=int, nargs='?', const=70, metavar='N',
                   help='exit 1 when the 5-hour window is at or above N%% (default 70)')
    p.add_argument('--warn-7d', type=int, nargs='?', const=70, metavar='N',
                   help='exit 1 when the 7-day window is at or above N%% (default 70)')
    p.add_argument('--all', action='store_true',
                   help='add per-limit details and the weekly surface breakdown (plain format)')
    p.add_argument('--format', choices=('plain', 'json', 'short'), default='plain',
                   help='output format (default: plain)')
    p.add_argument('--statusline', action='store_true', help=argparse.SUPPRESS)
    p.add_argument('-v', '--verbose', action='store_true',
                   help='log credential and usage sources to stderr')
    p.add_argument('-V', '--version', action='version', version='claude-usage %s' % __version__)
    return p


def statusline():
    """Cache Claude Code's stdin payload and print a line, silently on failure."""
    try:
        data = json.loads(sys.stdin.read())
        if not isinstance(data, dict):
            return 0
        line = render_short(shape(data, 'status line, 0 min ago'))
        write_cache(config_dir() / 'last-statusline.json', data)
        print(line)
    except (OSError, ValueError, TypeError, AttributeError, OverflowError):
        pass
    return 0


def main(argv=None):
    args = build_parser().parse_args(argv)
    if args.statusline:
        return statusline()
    try:
        out = usage(verbose=args.verbose)
        if args.format == 'json':
            json.dump(out['raw'], sys.stdout, indent=1)
            print()
        elif args.format == 'short':
            print(render_short(out))
        else:
            print(render_plain(out))
            if args.all:
                details = render_limits(out)
                if details:
                    print(details)
    except (RuntimeError, OSError, ValueError, TypeError, AttributeError, OverflowError) as exc:
        print('claude-usage: ' + str(exc), file=sys.stderr)
        return 1
    for threshold, key in ((args.warn, 'five_hour'), (args.warn_7d, 'seven_day')):
        if threshold is not None and (out[key]['utilization'] or 0) >= threshold:
            return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
