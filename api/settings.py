"""
Server settings, read from environment variables.

| Variable | Default | Meaning |
|---|---|---|
| ``CONFIG_PATH`` | ``config/config.yaml`` | pipeline configuration |
| ``DEMO_MODE`` | ``false`` | serve synthetic data instead of Yahoo Finance |
| ``DATABASE_PATH`` | ``tracking.database`` in the config | SQLite file for runs and predictions |
| ``DATABASE_URL`` | none | a PostgreSQL database instead, e.g. ``postgresql+psycopg://user:pass@host:5432/ledger`` |
| ``JOB_QUEUE`` | ``inline`` | ``inline`` runs jobs in the server; ``redis`` queues them for worker processes (``python -m api.worker``) |
| ``REDIS_URL`` | none | the Redis server for ``JOB_QUEUE=redis``, e.g. ``redis://redis:6379/0`` |
| ``FRONTEND_DIST`` | ``frontend/dist/frontend/browser`` | built Angular app to serve at ``/`` |
| ``CORS_ORIGINS`` | ``http://localhost:4200`` | comma-separated origins allowed in development |
| ``SEED_DEMO`` | ``true`` | in demo mode, populate each dashboard on first start |
| ``MODEL_REGISTRY`` | ``mlflow`` | ``mlflow`` records and versions every trained model; ``off`` keeps only the latest model in memory |
| ``MLFLOW_TRACKING_URI`` | ``sqlite:///…/mlflow-<database>.db`` next to the database | MLflow server or store for the model registry |
| ``MLFLOW_UI_URL`` | none | address of the MLflow web UI, for links from the app |
| ``LOG_FORMAT`` | ``text`` | ``json`` writes one JSON object per log line |
| ``LOG_LEVEL`` | ``INFO`` | minimum level of the app's logs |
| ``INTERNAL_SCHEDULER`` | ``true`` | run scheduled scans and analyses inside the server; set to ``false`` when an outside scheduler (e.g. Kubernetes CronJobs) triggers them |
"""

import os
from dataclasses import dataclass, field
from typing import List

from src.data.collector import PROJECT_ROOT, load_config


def _flag(name: str, default: bool) -> bool:
    value = os.environ.get(name)
    if value is None:
        return default
    return value.strip().lower() in ('1', 'true', 'yes', 'on')


def _resolve(path: str) -> str:
    return path if os.path.isabs(path) else os.path.join(PROJECT_ROOT, path)


@dataclass
class Settings:
    config_path: str = 'config/config.yaml'
    demo_mode: bool = False
    database_path: str = ''
    frontend_dist: str = ''
    cors_origins: List[str] = field(default_factory=lambda: ['http://localhost:4200'])
    seed_demo: bool = True
    internal_scheduler: bool = True
    database_url: str = ''
    job_queue: str = 'inline'
    redis_url: str = ''
    model_registry: str = 'mlflow'
    log_format: str = ''
    log_level: str = 'INFO'
    mlflow_tracking_uri: str = ''
    mlflow_artifact_root: str = ''
    mlflow_ui_url: str = ''

    @classmethod
    def from_env(cls) -> 'Settings':
        config_path = os.environ.get('CONFIG_PATH', 'config/config.yaml')
        config = load_config(config_path)
        database = os.environ.get('DATABASE_PATH') or config.get('tracking', {}).get('database', 'data/predictions.db')
        return cls(
            config_path=config_path,
            demo_mode=_flag('DEMO_MODE', False),
            database_path=_resolve(database),
            frontend_dist=_resolve(os.environ.get('FRONTEND_DIST', 'frontend/dist/frontend/browser')),
            cors_origins=[o.strip() for o in os.environ.get('CORS_ORIGINS', 'http://localhost:4200').split(',') if o.strip()],
            seed_demo=_flag('SEED_DEMO', True),
            internal_scheduler=_flag('INTERNAL_SCHEDULER', True),
            database_url=os.environ.get('DATABASE_URL', '').strip(),
            job_queue=os.environ.get('JOB_QUEUE', 'inline').strip().lower(),
            redis_url=os.environ.get('REDIS_URL', '').strip(),
            log_format=os.environ.get('LOG_FORMAT', 'text').strip().lower(),
            log_level=os.environ.get('LOG_LEVEL', 'INFO').strip().upper(),
            **registry_settings(_resolve(database)),
        )


def registry_settings(database_path: str) -> dict:
    """
    Model registry location. Without ``MLFLOW_TRACKING_URI`` it is a SQLite file
    and an artifact folder next to the app's database, so demo and live models
    (``demo.db``, ``predictions.db``) are kept apart, like their data.
    """
    mode = os.environ.get('MODEL_REGISTRY', 'mlflow').strip().lower()
    if mode not in ('mlflow', 'off'):
        raise ValueError(f"MODEL_REGISTRY must be 'mlflow' or 'off', got {mode!r}")
    uri = os.environ.get('MLFLOW_TRACKING_URI', '').strip()
    artifact_root = ''
    if not uri:
        directory = os.path.dirname(database_path) or '.'
        stem = os.path.splitext(os.path.basename(database_path))[0]
        uri = 'sqlite:///' + os.path.abspath(os.path.join(directory, f'mlflow-{stem}.db'))
        artifact_root = os.path.abspath(os.path.join(directory, f'mlartifacts-{stem}'))
    return {'model_registry': mode, 'mlflow_tracking_uri': uri, 'mlflow_artifact_root': artifact_root,
            'mlflow_ui_url': os.environ.get('MLFLOW_UI_URL', '').strip()}
