"""The terminology check (scripts/check_terms.py): it passes on the repository and catches retired names."""

import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / 'scripts'))
import check_terms  # noqa: E402

from api import tasks  # noqa: E402


def make_repo(tmp_path: Path, files: dict) -> Path:
    """A throwaway git repository holding the given files."""
    for name, text in files.items():
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding='utf-8')
    subprocess.run(['git', 'init', '-q'], cwd=tmp_path, check=True)
    subprocess.run(['git', 'add', '-A'], cwd=tmp_path, check=True)
    return tmp_path


def test_repository_uses_the_glossary_names():
    assert check_terms.check_ui() + check_terms.check_api() + check_terms.check_identifiers() == []


@pytest.mark.parametrize('text', [
    '<p>Today\'s ideas</p>', '<p>Every prediction, scored</p>', '<p>The last run failed</p>',
    '<p>Each ticker</p>', '<p>Confidence in the model</p>', '<p>Our recommendations</p>'])
def test_ui_retired_names_are_found(tmp_path, text):
    root = make_repo(tmp_path, {'frontend/src/app/pages/x.html': text})
    assert len(check_terms.check_ui(root)) == 1


def test_ui_verbs_and_config_keys_are_fine(tmp_path):
    root = make_repo(tmp_path, {
        'frontend/src/app/pages/x.html': '<button>Run analysis</button> <p>Run one from the top.</p>',
        'frontend/src/app/pages/y.ts': "const KEY = 'ranking_config.weights.ml_prediction';",
        'frontend/src/app/pages/z.spec.ts': "expect(text).toContain('ideas');"})
    assert check_terms.check_ui(root) == []


def test_api_fields_and_routes_are_found(tmp_path):
    root = make_repo(tmp_path, {
        'api/service/new.py': "def view():\n    return {'run': 1, 'picks': []}\n",
        'api/routes.py': "@api.get('/{universe}/runs')\ndef old():\n    pass\n"})
    problems = check_terms.check_api(root)
    assert any("API field 'run'" in p for p in problems) and any("route '/{universe}/runs'" in p for p in problems)


def test_deprecated_routes_and_stored_names_are_allowed(tmp_path):
    root = make_repo(tmp_path, {
        'api/routes.py': "@api.get('/{universe}/runs', deprecated=True)\ndef old():\n    pass\n",
        'api/store.py': "ROW = {'run_id': 1, 'predictions': 2}\n"})
    assert check_terms.check_api(root) == []


def test_identifiers_are_split_into_words(tmp_path):
    root = make_repo(tmp_path, {
        'src/a.py': "def top_recommendation(ticker):\n    ideas = []\n    return ideas\n",
        'src/b.py': "class LeaderBoard:\n    pass\n\n\ndef rerun_ideal(prediction_run):\n    return prediction_run\n"})
    problems = check_terms.check_identifiers(root)
    words = {p.split("'")[3] for p in problems}
    assert words == {'recommendation', 'ticker', 'ideas'}, problems


def test_evaluate_job_reports_both_names():
    class Service:
        @staticmethod
        def evaluate_outcomes():
            return 3

    assert tasks.evaluate(Service(), None) == {'evaluated_analyses': 3, 'evaluated_runs': 3}
