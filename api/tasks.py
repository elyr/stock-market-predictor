"""
The kinds of background job, by name. A job is stored as its kind, universe
and JSON parameters, so the server can hand it to any worker process (see
api/jobs.py); each function here receives the universe's service, the job (to
report progress) and those parameters.
"""

from typing import Any, Callable, Dict

Task = Callable[..., Any]


def analysis(service, job, top_n=None, symbols=None):
    return service.run_analysis(job, top_n=top_n, symbols=symbols)


def scan(service, job, session='close', lookback=1):
    return service.scan_signals(job, session=session, lookback=lookback)


def seed(service, job):
    return service.seed_demo(job)


def backtest(service, job, params=None):
    return service.run_backtest(job, params or {})


def forecast(service, job):
    return service.refresh_forecasts(job)


def evaluate(service, job):
    return {'evaluated_runs': service.evaluate_outcomes()}


def experiment(service, job, experiment_id):
    return service.run_experiment(job, experiment_id)


def lockbox(service, job, experiment_id):
    return service.check_lockbox(job, experiment_id)


TASKS: Dict[str, Task] = {
    'analysis': analysis,
    'scan': scan,
    'seed': seed,
    'backtest': backtest,
    'evaluate': evaluate,
    'forecast': forecast,
    'experiment': experiment,
    'lockbox': lockbox,
}

# Longest a job may run before it is stopped and marked failed (seconds)
TIMEOUTS = {'analysis': 3600, 'seed': 3600, 'backtest': 7200, 'experiment': 7200, 'lockbox': 7200,
            'scan': 1800, 'evaluate': 1800, 'forecast': 1800}
