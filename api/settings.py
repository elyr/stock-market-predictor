"""
Server settings, read from environment variables.

| Variable | Default | Meaning |
|---|---|---|
| ``CONFIG_PATH`` | ``config/config.yaml`` | pipeline configuration |
| ``DEMO_MODE`` | ``false`` | serve synthetic data instead of Yahoo Finance |
| ``DATABASE_PATH`` | ``tracking.database`` in the config | SQLite file for runs and predictions |
| ``FRONTEND_DIST`` | ``frontend/dist/frontend/browser`` | built Angular app to serve at ``/`` |
| ``CORS_ORIGINS`` | ``http://localhost:4200`` | comma-separated origins allowed in development |
| ``SEED_DEMO`` | ``true`` | in demo mode, populate each dashboard on first start |
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
        )
