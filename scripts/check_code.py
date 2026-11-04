#!/usr/bin/env python3
"""
Code health checks that CI runs (the "code" job of the Tests workflow).

1. **File size.** No Python or TypeScript file over 500 lines. Files that were
   already longer are listed in ``OVER_LIMIT`` with their size when the check
   was added: they may shrink but not grow, and an entry is removed once its
   file is under the limit. The list must end up empty.
2. **Unused code.** No unused function, method or class (vulture), and no
   unused import or local variable (ruff). Code that only a framework calls
   (routes, migrations, callbacks) is ignored by name or decorator below.

Run it locally with ``python3 scripts/check_code.py`` (needs ``pip install
vulture ruff``). Exits non-zero with a list of problems.
"""

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LIMIT = 500

# Longer than the limit when this check was added: may shrink, not grow.
OVER_LIMIT = {
    'src/models/ml_models.py': 674,
    'src/analysis/technical_indicators.py': 612,
    'frontend/src/app/core/models.ts': 588,
    'api/main.py': 573,
    'scripts/backup.py': 516,
    'api/store.py': 505,
}

PYTHON_DIRS = ['src', 'api', 'scripts', 'tests']
# Called by a framework, not by our code
IGNORE_DECORATORS = ['@app.*', '@api.*', '@event.listens_for', '@*.command', '@*.group', '@pytest.fixture']
IGNORE_NAMES = ['upgrade', 'downgrade',                             # Alembic migrations
                'collect',                                          # Prometheus collector
                'handle_starttag', 'handle_endtag', 'handle_data',  # HTMLParser callbacks
                'pytest_*', 'log_message', 'do_GET', 'do_POST']     # pytest hooks, test HTTP server
REPORTED_KINDS = ('unused function', 'unused method', 'unused class', 'unused property', 'unused import')


def tracked_files(*patterns: str) -> list:
    out = subprocess.run(['git', 'ls-files', *patterns], cwd=ROOT, capture_output=True, text=True, check=True)
    return [line for line in out.stdout.splitlines() if line]


def check_sizes() -> list:
    problems = []
    for path in tracked_files('*.py', '*.ts'):
        if path.endswith('.spec.ts'):
            continue
        lines = sum(1 for _ in open(ROOT / path, encoding='utf-8'))
        allowed = OVER_LIMIT.get(path, LIMIT)
        if lines > allowed:
            problems.append(f'{path}: {lines} lines (limit {allowed}); split it by responsibility')
        elif path in OVER_LIMIT and lines <= LIMIT:
            problems.append(f'{path}: now {lines} lines, under the limit: remove it from OVER_LIMIT')
    for path in OVER_LIMIT:
        if not (ROOT / path).exists():
            problems.append(f'{path}: no longer exists: remove it from OVER_LIMIT')
    return problems


def check_unused() -> list:
    vulture = subprocess.run(
        [sys.executable, '-m', 'vulture', *PYTHON_DIRS, '--min-confidence', '60',
         '--ignore-decorators', ','.join(IGNORE_DECORATORS), '--ignore-names', ','.join(IGNORE_NAMES)],
        cwd=ROOT, capture_output=True, text=True)
    problems = [line for line in vulture.stdout.splitlines() if any(k in line for k in REPORTED_KINDS)]
    ruff = subprocess.run(
        [sys.executable, '-m', 'ruff', 'check', '--select', 'F401,F811,F841', '--output-format', 'concise',
         '--quiet', *PYTHON_DIRS], cwd=ROOT, capture_output=True, text=True)
    problems += [line for line in ruff.stdout.splitlines() if line.strip()]
    return problems


def main() -> int:
    problems = check_sizes() + check_unused()
    for problem in problems:
        print(problem)
    if problems:
        print(f'\n{len(problems)} problem(s). See scripts/check_code.py for what is checked and why.')
        return 1
    print('Code checks passed: file sizes within limits, no unused code.')
    return 0


if __name__ == '__main__':
    sys.exit(main())
