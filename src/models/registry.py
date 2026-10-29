"""
Model registry: every trained model is recorded in MLflow with its settings,
its out-of-sample scores and the model files, and gets a version number.

One registered model per universe (``ledger-stocks``, ``ledger-crypto``; demo
data adds ``-demo`` so simulated and real models never mix). The version the
app trusts carries the ``champion`` alias.

Two ways the app uses it (see ``api/service.py``):

- **Retraining** (the default): each analysis trains new models, registers
  them as a new version and makes it the champion.
- **Pinned**: after you promote or roll back to a version, the registered
  model is tagged ``pinned``. Analyses then load the champion instead of
  training, until you unpin it.

The tracking URI decides where everything is stored: an MLflow server
(``http://…``) on Kubernetes, or a local SQLite file
(``sqlite:///data/mlflow-demo.db``) when running with ``run.sh``. Only the
lightweight client (``mlflow-skinny``) is needed in the app.
"""

import logging
import os
import tempfile
import time
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

CHAMPION = 'champion'
PINNED_TAG = 'pinned'
MODEL_DIR = 'model'

# Keep a broken or unreachable server from blocking an analysis for minutes
os.environ.setdefault('MLFLOW_HTTP_REQUEST_MAX_RETRIES', '2')
os.environ.setdefault('MLFLOW_HTTP_REQUEST_TIMEOUT', '20')
os.environ.setdefault('MLFLOW_DISABLE_AGENT_HINT', '1')


def _flatten(prefix: str, values: Dict[str, Any], out: Dict[str, float]) -> Dict[str, float]:
    """Numeric leaves of a nested dict as ``prefix.key`` metrics (lists and text are skipped)."""
    for key, value in values.items():
        name = f'{prefix}.{key}' if prefix else str(key)
        if isinstance(value, dict):
            _flatten(name, value, out)
        elif isinstance(value, bool):
            out[name] = float(value)
        elif isinstance(value, (int, float)) and value == value:  # skips NaN
            out[name] = float(value)
    return out


def safe_uri(uri: str) -> str:
    """The tracking URI without credentials, for display."""
    if '@' in uri and '://' in uri:
        scheme, rest = uri.split('://', 1)
        return f"{scheme}://{rest.split('@', 1)[1]}"
    return uri


class ModelRegistry:
    """Versions of each universe's models, stored in MLflow."""

    def __init__(self, tracking_uri: str, artifact_root: Optional[str] = None, demo: bool = False,
                 prefix: str = 'ledger', ui_url: Optional[str] = None):
        self.tracking_uri = tracking_uri
        self.artifact_root = artifact_root
        self.demo = demo
        self.prefix = prefix
        self.ui_url = ui_url
        self._client = None

    @property
    def client(self):
        """The MLflow client, created on first use (importing MLflow and opening its store takes seconds)."""
        if self._client is None:
            from mlflow import MlflowClient  # imported here so the rest of the app never needs MLflow

            self._client = MlflowClient(tracking_uri=self.tracking_uri, registry_uri=self.tracking_uri)
        return self._client

    # ---------------------------------------------------------------- names

    def name(self, universe: str) -> str:
        return f"{self.prefix}-{universe}{'-demo' if self.demo else ''}"

    def _experiment_id(self, universe: str) -> str:
        name = self.name(universe)
        experiment = self.client.get_experiment_by_name(name)
        if experiment is not None:
            return experiment.experiment_id
        location = None
        if self.artifact_root:
            os.makedirs(os.path.join(self.artifact_root, name), exist_ok=True)
            location = 'file://' + os.path.abspath(os.path.join(self.artifact_root, name))
        return self.client.create_experiment(name, artifact_location=location,
                                             tags={'universe': universe, 'demo': str(self.demo).lower()})

    def _ensure_registered(self, universe: str) -> None:
        from mlflow.exceptions import MlflowException

        name = self.name(universe)
        try:
            self.client.get_registered_model(name)
        except MlflowException:
            self.client.create_registered_model(
                name, tags={'universe': universe, 'demo': str(self.demo).lower()},
                description=f'Ledger {universe} return and volatility models'
                            f"{' (simulated demo data)' if self.demo else ''}.")

    # ------------------------------------------------------------- register

    def register(self, universe: str, model_dir: str, params: Dict[str, Any], metrics: Dict[str, Any],
                 tags: Optional[Dict[str, str]] = None, promote: bool = True) -> Dict[str, Any]:
        """
        Record a training run and its model files, and register them as a new version.

        Args:
            model_dir: folder with the model files (saved as the run's ``model`` artifact)
            params: settings the model was trained with (logged as parameters)
            metrics: out-of-sample scores; nested dicts are flattened to ``a.b`` names
            promote: make the new version the champion

        Returns:
            The new version (see ``describe_version``)
        """
        from mlflow.entities import Metric, Param, RunTag

        experiment_id = self._experiment_id(universe)
        tags = {k: str(v) for k, v in (tags or {}).items() if v is not None}
        data_date = str(params.get('data_date', ''))
        run = self.client.create_run(experiment_id, run_name=f'{universe} {data_date}'.strip(),
                                     tags={'universe': universe, **tags})
        run_id = run.info.run_id
        try:
            now = int(time.time() * 1000)
            flat = _flatten('', metrics, {})
            self.client.log_batch(
                run_id,
                metrics=[Metric(k, v, now, 0) for k, v in flat.items()],
                params=[Param(k, str(v)[:6000]) for k, v in params.items() if v is not None],
                tags=[RunTag('mlflow.note.content',
                             f'{universe} models trained on prices up to {data_date}.')])
            self.client.log_artifacts(run_id, model_dir, MODEL_DIR)
            self.client.set_terminated(run_id)
        except Exception:
            self.client.set_terminated(run_id, status='FAILED')
            raise

        self._ensure_registered(universe)
        version = self.client.create_model_version(
            self.name(universe), f'{run.info.artifact_uri}/{MODEL_DIR}', run_id,
            tags={'data_date': data_date, **{k: v for k, v in tags.items() if k in ('git_commit', 'app_version')}},
            description=f'Trained on prices up to {data_date}.')
        if promote:
            self.client.set_registered_model_alias(self.name(universe), CHAMPION, version.version)
        logger.info(f'Registered {self.name(universe)} version {version.version} (run {run_id})')
        return self.describe_version(universe, version.version)

    # ---------------------------------------------------------------- query

    def champion(self, universe: str) -> Optional[str]:
        """The champion's version number, or None."""
        from mlflow.exceptions import MlflowException

        try:
            return str(self.client.get_model_version_by_alias(self.name(universe), CHAMPION).version)
        except MlflowException:
            return None

    def pinned(self, universe: str) -> bool:
        from mlflow.exceptions import MlflowException

        try:
            tags = self.client.get_registered_model(self.name(universe)).tags or {}
        except MlflowException:
            return False
        return tags.get(PINNED_TAG) == 'true'

    def describe_version(self, universe: str, version: str, champion: Optional[str] = None) -> Dict[str, Any]:
        mv = self.client.get_model_version(self.name(universe), str(version))
        run = self.client.get_run(mv.run_id)
        champion = champion if champion is not None else self.champion(universe)
        return {
            'version': str(mv.version),
            'created_at': _iso(mv.creation_timestamp),
            'run_id': mv.run_id,
            'run_name': run.info.run_name,
            'status': run.info.status,
            'champion': str(mv.version) == champion,
            'data_date': (mv.tags or {}).get('data_date') or run.data.params.get('data_date'),
            'git_commit': run.data.tags.get('git_commit'),
            'params': dict(run.data.params),
            'metrics': dict(run.data.metrics),
            'run_url': self._run_url(run.info.experiment_id, mv.run_id),
        }

    def versions(self, universe: str, limit: int = 50) -> List[Dict[str, Any]]:
        """Registered versions, newest first."""
        from mlflow.exceptions import MlflowException

        try:
            found = self.client.search_model_versions(f"name='{self.name(universe)}'")
        except MlflowException:
            return []
        champion = self.champion(universe)
        ordered = sorted(found, key=lambda v: int(v.version), reverse=True)[:limit]
        return [self.describe_version(universe, v.version, champion) for v in ordered]

    def summary(self, universe: str) -> Dict[str, Any]:
        return {
            'enabled': True,
            'name': self.name(universe),
            'tracking_uri': safe_uri(self.tracking_uri),
            'ui_url': self.ui_url,
            'champion': self.champion(universe),
            'pinned': self.pinned(universe),
            'versions': self.versions(universe),
        }

    def _run_url(self, experiment_id: str, run_id: str) -> Optional[str]:
        if not self.ui_url:
            return None
        return f"{self.ui_url.rstrip('/')}/#/experiments/{experiment_id}/runs/{run_id}"

    # --------------------------------------------------------------- change

    def promote(self, universe: str, version: str, pin: bool = True) -> Dict[str, Any]:
        """Make ``version`` the champion (and by default pin it, so analyses use it as is)."""
        self.client.get_model_version(self.name(universe), str(version))  # raises if unknown
        self.client.set_registered_model_alias(self.name(universe), CHAMPION, str(version))
        self.set_pinned(universe, pin)
        return self.summary(universe)

    def set_pinned(self, universe: str, pinned: bool) -> None:
        self._ensure_registered(universe)
        if pinned:
            self.client.set_registered_model_tag(self.name(universe), PINNED_TAG, 'true')
        elif self.pinned(universe):
            self.client.delete_registered_model_tag(self.name(universe), PINNED_TAG)

    # ----------------------------------------------------------------- load

    def download(self, universe: str, version: str, destination: Optional[str] = None) -> str:
        """Copy a version's model files to a local folder and return it."""
        mv = self.client.get_model_version(self.name(universe), str(version))
        destination = destination or tempfile.mkdtemp(prefix=f'ledger-{universe}-v{version}-')
        path = self.client.download_artifacts(mv.run_id, MODEL_DIR, destination)
        return path


def _iso(milliseconds: Optional[int]) -> Optional[str]:
    if not milliseconds:
        return None
    from datetime import datetime, timezone
    return datetime.fromtimestamp(milliseconds / 1000, tz=timezone.utc).isoformat(timespec='seconds')

