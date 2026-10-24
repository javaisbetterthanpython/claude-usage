"""Run claude-usage with ``python -m claude_usage``."""

import sys

from .cli import main

if __name__ == '__main__':
    sys.exit(main())
