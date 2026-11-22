"""
The run paths (run.sh, docker-compose.yml, kube.sh with the Helm chart) share
their logic and defaults. A few defaults are written in more than one file
because the chart cannot read files outside itself; these tests fail when the
copies disagree. The table "Settings the run paths define twice" in
docs/GUIDE.md lists them.
"""

import re
import subprocess
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parent.parent
CHART = ROOT / 'deploy' / 'helm' / 'ledger'


def read(path: Path) -> str:
    return path.read_text(encoding='utf-8')


def shell_value(script: str, name: str) -> str:
    """The quoted value of a NAME="value" assignment at the start of a line."""
    match = re.search(rf'^{name}="([^"]*)"', read(ROOT / script), re.MULTILINE)
    assert match, f'{name} not found in {script}'
    return match.group(1)


def bash(script: str) -> subprocess.CompletedProcess:
    return subprocess.run(['bash', '-c', script], cwd=ROOT, capture_output=True, text=True, timeout=60)


@pytest.fixture(scope='module')
def compose() -> dict:
    return yaml.safe_load(read(ROOT / 'docker-compose.yml'))['services']['ledger']


@pytest.fixture(scope='module')
def values() -> dict:
    return yaml.safe_load(read(CHART / 'values.yaml'))


def test_every_path_starts_in_demo_mode(compose, values):
    assert compose['environment']['DEMO_MODE'] == '${DEMO_MODE:-true}'
    assert values['mode'] == 'demo'
    assert shell_value('scripts/lib/common.sh', 'MODE') == 'demo'
    # the scripts take it from common.sh instead of setting it again
    assert not re.search(r'^MODE=', read(ROOT / 'run.sh'), re.MULTILINE)
    assert not re.search(r'^MODE=', read(ROOT / 'kube.sh'), re.MULTILINE)


def test_database_files_are_named_alike():
    demo, live = '/app/data/demo.db', '/app/data/predictions.db'
    compose = yaml.safe_load(read(ROOT / 'docker-compose.yml'))['services']['ledger']
    assert compose['environment']['DATABASE_PATH'] == '${DATABASE_PATH:-' + demo + '}'
    helpers = read(CHART / 'templates' / '_helpers.tpl')
    assert demo in helpers and live in helpers
    run_sh = read(ROOT / 'run.sh')
    assert f'database="{demo}"' in run_sh and f'database="{live}"' in run_sh


def test_container_port_and_data_directory_match():
    dockerfile = read(ROOT / 'Dockerfile')
    assert 'EXPOSE 8000' in dockerfile and '"--port", "8000"' in dockerfile
    compose = yaml.safe_load(read(ROOT / 'docker-compose.yml'))['services']['ledger']
    assert compose['ports'][0].endswith(':8000')
    assert 'containerPort: 8000' in read(CHART / 'templates' / 'deployment.yaml')
    assert 'VOLUME ["/app/data"]' in dockerfile
    assert 'ledger-data:/app/data' in compose['volumes']
    assert 'mountPath: /app/data' in read(CHART / 'templates' / 'deployment.yaml')


def test_hostnames_in_kube_sh_match_the_chart(values):
    assert shell_value('kube.sh', 'HOST') == values['ingress']['host']
    assert shell_value('kube.sh', 'MLFLOW_HOST') == values['mlflow']['ingress']['host']
    assert shell_value('kube.sh', 'GRAFANA_HOST') == values['monitoring']['grafana']['ingress']['host']
    assert shell_value('kube.sh', 'PROMETHEUS_HOST') == values['monitoring']['prometheus']['ingress']['host']


def test_published_image_name_is_the_same_in_kube_sh_and_gitops():
    release = yaml.safe_load(read(ROOT / 'deploy' / 'gitops' / 'apps' / 'ledger' / 'release-values.yaml'))
    assert shell_value('kube.sh', 'GHCR_IMAGE') == release['image']['repository']
    # the local image has the same name in the chart's default and in kube.sh
    values = yaml.safe_load(read(CHART / 'values.yaml'))
    assert shell_value('kube.sh', 'IMAGE_REPO') == values['image']['repository']


def test_python_version_matches_the_image():
    version = shell_value('run.sh', 'PYTHON_VERSION')
    assert f'FROM python:{version}-slim' in read(ROOT / 'Dockerfile')


def test_the_guide_lists_the_shared_settings():
    guide = read(ROOT / 'docs' / 'GUIDE.md')
    section = guide.split('### Settings the run paths define twice', 1)[1].split('\n### ', 1)[0]
    for name in ('DEMO_MODE', 'DATABASE_PATH', 'ALPHA_VANTAGE_API_KEY', 'GHCR_IMAGE', 'PYTHON_VERSION', 'LOG_FORMAT'):
        assert name in section, f'{name} is missing from the table'


# ---------------------------------------------------------- shared script logic


def test_both_scripts_parse_the_shared_options_with_common_sh():
    for script in ('run.sh', 'kube.sh'):
        text = read(ROOT / script)
        assert 'parse_common_option' in text and 'common_options_help' in text
        # none of the shared options is parsed a second time
        for option in ('--live)', '--demo)', '--no-update)', '--no-browser)', '--no-system-packages)', '--branch)'):
            assert option not in text, f'{script} handles {option} itself'


def test_parse_common_option_sets_the_shared_variables():
    result = bash('''
        set -euo pipefail
        ROOT="$PWD"; SELF=test.sh; PORT=1234; ORIGINAL_ARGS=()
        source scripts/lib/common.sh
        echo "defaults $MODE $UPDATE $BRANCH $SYSTEM_PACKAGES $OPEN_BROWSER $PORT"
        for args in "--live" "--demo" "--no-update" "--no-browser" "--no-system-packages" "--port 99" "--port=98" "--branch dev" "--branch=feature/x"; do
            MODE=demo; UPDATE=1; BRANCH=main; SYSTEM_PACKAGES=1; OPEN_BROWSER=1; PORT=1234
            # shellcheck disable=SC2086
            set -- $args
            parse_common_option "$@"
            echo "$args -> shift $COMMON_SHIFT: $MODE $UPDATE $BRANCH $SYSTEM_PACKAGES $OPEN_BROWSER $PORT"
        done
        parse_common_option --bogus || echo "--bogus not handled"
    ''')
    assert result.returncode == 0, result.stderr
    lines = result.stdout.splitlines()
    assert lines[0] == 'defaults demo 1 main 1 1 1234'
    assert lines[1] == '--live -> shift 0: live 1 main 1 1 1234'
    assert lines[3] == '--no-update -> shift 0: demo 0 main 1 1 1234'
    assert lines[6] == '--port 99 -> shift 1: demo 1 main 1 1 99'
    assert lines[7] == '--port=98 -> shift 0: demo 1 main 1 1 98'
    assert lines[8] == '--branch dev -> shift 1: demo 1 dev 1 1 1234'
    assert lines[9] == '--branch=feature/x -> shift 0: demo 1 feature/x 1 1 1234'
    assert lines[-1] == '--bogus not handled'


@pytest.mark.parametrize('port', ['0', '65536', 'abc', ''])
def test_both_scripts_reject_a_bad_port(port):
    for script, command in (('run.sh', []), ('kube.sh', ['help'])):
        result = subprocess.run(['bash', script, f'--port={port}', '--no-update', *command], cwd=ROOT,
                                capture_output=True, text=True, timeout=60)
        assert result.returncode != 0 and 'Invalid port' in result.stderr, script


def test_predict_now_is_a_deprecated_alias_of_analyse_now():
    result = bash('''
        set -uo pipefail
        source ./kube.sh --no-update help >/dev/null 2>&1 || true
        COMMAND=predict-now; CMD_ARG=""
        apply_deprecated_names
        echo "command: $COMMAND"
        COMMAND=logs; CMD_ARG=prediction
        apply_deprecated_names
        echo "logs: $CMD_ARG"
        COMMAND=analyse-now; CMD_ARG=""
        apply_deprecated_names
        echo "unchanged: $COMMAND"
    ''')
    assert 'command: analyse-now' in result.stdout, result.stderr
    assert 'logs: analysis' in result.stdout
    assert 'unchanged: analyse-now' in result.stdout
    assert result.stderr.count('Warning:') == 2
    assert 'predict-now is now ./kube.sh analyse-now' in result.stderr


def test_kube_sh_lists_analyse_now_and_not_predict_now_as_the_command():
    result = subprocess.run(['bash', 'kube.sh', 'help'], cwd=ROOT, capture_output=True, text=True, timeout=60)
    assert result.returncode == 0
    assert '  analyse-now ' in result.stdout and '(predict-now still works, but is deprecated)' in result.stdout


def test_chart_uses_the_new_value_name_and_keeps_the_old_one_empty(values):
    assert 'dailyAnalysis' in values and values['dailyPrediction'] == {}
    for profile in ('values-laptop.yaml', 'values-desktop.yaml'):
        text = yaml.safe_load(read(CHART / profile))
        assert 'dailyAnalysis' in text and 'dailyPrediction' not in text
