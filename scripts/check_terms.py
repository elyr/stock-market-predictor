#!/usr/bin/env python3
"""
Terminology check that CI runs (the "code" job of the Tests workflow).

The Glossary in AGENTS.md gives one name per concept and lists the names it
retires. This script fails when a retired name comes back in:

1. **UI strings**: every non-test ``.ts`` and ``.html`` file under
   ``frontend/src/app`` (templates, tooltips, labels, messages).
2. **API field names and routes**: string keys and route paths in ``api/``,
   ``src/personal/`` and ``src/evaluation/comparator.py`` (the code that shapes
   responses). A route declared with ``deprecated=True`` is exempt by itself.
3. **Python identifiers**: function, class, argument, variable and attribute
   names in ``src``, ``api``, ``scripts`` and ``tests``, split into
   snake_case words.

Not scanned: ``research/``, ``docs/`` (research findings keep the wording of
their day), ``CHANGELOG.md`` (history and the deprecation list), tests'
expected strings, and stored names in ``api/db.py``, ``api/store.py`` and the
migrations (tables and columns are not renamed).

Only retired names that cannot be mistaken for something else are checked. The
glossary also retires "run", "prediction" and "stock" in some senses, but those
words also mean an MLflow run, a stored table, the ``stocks`` universe or a
verb, so no script can tell them apart: reviews check those.

Allowed exceptions are the lists below, each with its reason. Keep them short:
a deprecated alias goes when its release ends (see "Deprecated" in
CHANGELOG.md), and then so does its entry here.

Run it locally with ``python3 scripts/check_terms.py``. Exits non-zero with a
list of problems. It needs only the standard library.
"""

import ast
import re
import subprocess
import sys
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple

ROOT = Path(__file__).resolve().parent.parent

# Retired names (last column of the Glossary) that mean nothing else.
UI_PATTERN = re.compile(
    r"\b(tickers?|recommendations?|ideas?|predictions?|confidence|leaderboards?|projections?"
    r"|risk forecasts?|buy signals?|sell signals?|exit signals?|trend signals?"
    r"|moving-average strategy|live performance|simulations?"
    r"|(?:this|that|the|each|every|last|latest|previous|earlier|later|a|new|another) runs?)\b",
    re.IGNORECASE)
IDENTIFIER_WORDS = {'ticker', 'tickers', 'recommendation', 'recommendations', 'idea', 'ideas', 'leaderboard',
                    'confidence', 'projection', 'projections'}
# API keys and routes that used older names (kept only as deprecated aliases or for stored data)
FIELD_NAMES = {'run', 'runs', 'run_id', 'evaluated_runs', 'ideas', 'ml_confidence', 'recommendation',
               'predictions', 'ticker', 'tickers', 'confidence'}
ROUTE_WORDS = {'runs', 'predictions', 'ideas', 'recommendations', 'tickers', 'leaderboard'}

# git pathspecs: '*' also matches '/', so these reach every depth
UI_FILES = ('frontend/src/app/*.ts', 'frontend/src/app/*.html')
API_FILES = ('api/*.py', 'src/personal/*.py', 'src/evaluation/comparator.py')
STORED = ('api/db.py', 'api/store.py')                    # tables and columns: stored names, not renamed
PYTHON_DIRS = ('src', 'api', 'scripts', 'tests')

# (file, name): why the name is allowed
FIELD_EXCEPTIONS: Dict[Tuple[str, str], str] = {
    ('api/serialization.py', 'ml_confidence'): 'deprecated alias of model_agreement',
    ('api/serialization.py', 'recommendation'): 'deprecated alias of pick_label',
    ('api/service/core.py', 'run'): "deprecated alias of 'analysis' in the asset detail",
    ('api/service/core.py', 'run_id'): 'deprecated alias of analysis_id in the job result',
    ('api/service/core.py', 'evaluated_runs'): 'deprecated alias of evaluated_analyses in the job result',
    ('api/service/track_record.py', 'run'): "deprecated alias of 'analysis'",
    ('api/service/track_record.py', 'runs'): "deprecated alias of 'analyses'",
    ('api/tasks.py', 'evaluated_runs'): 'deprecated alias of evaluated_analyses in the job result',
    ('api/service/models.py', 'run_id'): "an MLflow run id (MLflow's own term, not an analysis)",
    ('src/personal/brief.py', 'ideas'): "deprecated alias of the brief section's 'picks'",
    ('src/evaluation/comparator.py', 'predictions'): "deprecated alias of the summary's 'scores'",
}
IDENTIFIER_EXCEPTIONS: Dict[Tuple[str, str], str] = {
    ('src/data/collector.py', 'ticker'): "yfinance's own Ticker class and its methods",
    ('src/data/collector.py', 'tickers'): "yfinance's own Ticker class and its methods",
    ('tests/test_providers.py', 'ticker'): "a stub of yfinance's Ticker class",
}


def tracked(patterns: Tuple[str, ...], root: Path) -> List[str]:
    """Tracked files matching git pathspecs, sorted."""
    out = subprocess.run(['git', 'ls-files', *patterns], cwd=root, capture_output=True, text=True, check=True)
    return sorted(line for line in out.stdout.splitlines() if line)


def check_ui(root: Path = ROOT) -> List[str]:
    """Retired names in UI strings."""
    problems = []
    for path in tracked(UI_FILES, root):
        if path.endswith('.spec.ts'):
            continue
        for number, line in enumerate((root / path).read_text(encoding='utf-8').splitlines(), 1):
            match = UI_PATTERN.search(line)
            if match:
                problems.append(f"{path}:{number}: UI text uses the retired name '{match.group(0)}'")
    return problems


def _parse(path: str, root: Path) -> Optional[ast.AST]:
    try:
        return ast.parse((root / path).read_text(encoding='utf-8'))
    except SyntaxError:
        return None


def _deprecated_routes(tree: ast.AST) -> Set[int]:
    """Line numbers of string literals inside route decorators that pass ``deprecated=True``."""
    exempt: Set[int] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and any(
                k.arg == 'deprecated' and isinstance(k.value, ast.Constant) and k.value.value is True
                for k in node.keywords):
            exempt.update(n.lineno for n in ast.walk(node) if isinstance(n, ast.Constant))
    return exempt


def check_api(root: Path = ROOT) -> List[str]:
    """Retired field names and route words in the code that shapes API responses."""
    problems = []
    for path in tracked(API_FILES, root):
        if path in STORED or '/migrations/' in path:
            continue
        tree = _parse(path, root)
        if tree is None:
            continue
        exempt = _deprecated_routes(tree)
        for node in ast.walk(tree):
            if not (isinstance(node, ast.Constant) and isinstance(node.value, str)) or node.lineno in exempt:
                continue
            value = node.value
            if value in FIELD_NAMES and (path, value) not in FIELD_EXCEPTIONS:
                problems.append(f"{path}:{node.lineno}: API field '{value}' is retired; see the Glossary")
            elif value.startswith('/') and ROUTE_WORDS & set(re.split(r'[/._{}-]+', value)):
                problems.append(f"{path}:{node.lineno}: route '{value}' uses a retired name; "
                                "keep an old route only with deprecated=True")
    return problems


def _names(node: ast.AST) -> List[str]:
    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
        return [node.name]
    if isinstance(node, ast.arg):
        return [node.arg]
    if isinstance(node, ast.Name):
        return [node.id]
    if isinstance(node, ast.Attribute):
        return [node.attr]
    if isinstance(node, ast.keyword) and node.arg:
        return [node.arg]
    return []


def check_identifiers(root: Path = ROOT) -> List[str]:
    """Retired words in Python identifiers (split at underscores and capitals)."""
    problems = []
    for path in tracked(tuple(f'{d}/*.py' for d in PYTHON_DIRS), root):
        if path == 'scripts/check_terms.py':
            continue                                     # it names the retired words on purpose
        tree = _parse(path, root)
        if tree is None:
            continue
        seen: Set[Tuple[int, str]] = set()
        for node in ast.walk(tree):
            for name in _names(node):
                words = {w.lower() for w in re.split(r'_|(?<=[a-z])(?=[A-Z])', name) if w}
                for word in sorted(words & IDENTIFIER_WORDS):
                    key = (getattr(node, 'lineno', 0), name)
                    if (path, word) not in IDENTIFIER_EXCEPTIONS and key not in seen:
                        seen.add(key)
                        problems.append(f"{path}:{key[0]}: identifier '{name}' uses the retired name '{word}'")
    return problems


def main() -> int:
    problems = check_ui() + check_api() + check_identifiers()
    if problems:
        print('Terminology problems (the Glossary in AGENTS.md lists the names to use):')
        for problem in problems:
            print(f'  - {problem}')
        return 1
    print('Terminology check passed: no retired names in UI strings, API fields or Python identifiers.')
    return 0


if __name__ == '__main__':
    sys.exit(main())
