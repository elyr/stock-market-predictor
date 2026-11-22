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
3. **Component layout.** Every Angular component in ``frontend/src/app`` is laid
   out one way: a template of 40 lines or fewer is inline, with inline styles;
   a longer one lives in ``<component>.html`` with its styles in
   ``<component>.scss``, next to the component file and named after it.

Run it locally with ``python3 scripts/check_code.py`` (needs ``pip install
vulture ruff``). Exits non-zero with a list of problems.
"""

import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LIMIT = 500
TEMPLATE_LIMIT = 40   # longest inline component template, in lines
COMPONENT_DIR = 'frontend/src/app'

# Longer than the limit when this check was added: may shrink, not grow.
OVER_LIMIT = {
    'src/models/ml_models.py': 674,
    'src/analysis/technical_indicators.py': 612,
    'api/main.py': 542,
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


def line_count(text: str) -> int:
    """Lines of a template or stylesheet, not counting blank lines at either end."""
    return len(text.strip().splitlines())


def check_component_layout(root: Path = ROOT, files: list = None) -> list:
    """The convention in the module docstring. ``files`` are paths relative to ``root``."""
    files = tracked_files(f'{COMPONENT_DIR}/*') if files is None else files
    problems = []
    components = set()
    for path in files:
        if not path.endswith('.ts') or path.endswith('.spec.ts'):
            continue
        text = (root / path).read_text(encoding='utf-8')
        if '@Component(' not in text:
            continue
        stem = path[:-3]
        components.add(stem)
        name = Path(stem).name
        inline = re.search(r'^\s*template:\s*`(.*?)`', text, re.S | re.M)
        template_url = re.search(r"^\s*templateUrl:\s*'([^']*)'", text, re.M)
        style_url = re.search(r"^\s*styleUrl:\s*'([^']*)'", text, re.M)
        inline_styles = re.search(r'^\s*styles:', text, re.M)
        if bool(inline) == bool(template_url):
            problems.append(f'{path}: use either an inline template or templateUrl, not both or neither')
        elif inline:
            lines = line_count(inline.group(1))
            if lines > TEMPLATE_LIMIT:
                problems.append(f'{path}: inline template has {lines} lines (limit {TEMPLATE_LIMIT}); move it to '
                                f'{name}.html and its styles to {name}.scss')
            if style_url or re.search(r'^\s*styleUrls:', text, re.M):
                problems.append(f'{path}: an inline template needs inline styles, not a stylesheet file')
        else:
            if template_url.group(1) != f'./{name}.html':
                problems.append(f"{path}: templateUrl must be './{name}.html'")
            if not style_url or style_url.group(1) != f'./{name}.scss':
                problems.append(f"{path}: use styleUrl: './{name}.scss' next to a template file")
            if inline_styles or re.search(r'^\s*styleUrls:', text, re.M):
                problems.append(f'{path}: styles belong in {name}.scss when the template is in {name}.html')
            html = root / f'{stem}.html'
            if not html.exists():
                problems.append(f'{path}: {name}.html does not exist')
            elif line_count(html.read_text(encoding='utf-8')) <= TEMPLATE_LIMIT:
                problems.append(f'{stem}.html has {line_count(html.read_text(encoding="utf-8"))} lines '
                                f'(a template of {TEMPLATE_LIMIT} or fewer is inline): move it into {name}.ts')
            if style_url and not (root / f'{stem}.scss').exists():
                problems.append(f'{path}: {name}.scss does not exist')
    for path in files:
        if path.endswith(('.html', '.scss')) and path.startswith(COMPONENT_DIR + '/') \
                and path.rsplit('.', 1)[0] not in components:
            problems.append(f'{path}: no component {Path(path).stem}.ts uses this file')
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
    problems = check_sizes() + check_component_layout() + check_unused()
    for problem in problems:
        print(problem)
    if problems:
        print(f'\n{len(problems)} problem(s). See scripts/check_code.py for what is checked and why.')
        return 1
    print('Code checks passed: file sizes within limits, component layout, no unused code.')
    return 0


if __name__ == '__main__':
    sys.exit(main())
