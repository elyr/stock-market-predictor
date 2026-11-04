"""
The model registry: register trained models, list, promote and pin versions.

Part of :class:`api.service.UniverseService`; methods use the shared
state set up in ``core.py`` (pipeline, store, settings).
"""

import logging
import os
import subprocess
import tempfile
from typing import Any, Dict, Optional

from api.settings import Settings, registry_settings

logger = logging.getLogger(__name__)


def git_commit() -> Optional[str]:
    """The commit the app runs from: GIT_COMMIT (set in the image) or git itself."""
    commit = os.environ.get('GIT_COMMIT')
    if commit:
        return commit
    try:
        return subprocess.run(['git', 'rev-parse', '--short', 'HEAD'], capture_output=True, text=True,
                              timeout=5, cwd=os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
                              ).stdout.strip() or None
    except (OSError, subprocess.SubprocessError):
        return None


def create_registry(settings: Settings):
    """The MLflow model registry, or None when MODEL_REGISTRY=off."""
    if settings.model_registry == 'off':
        return None
    from src.models.registry import ModelRegistry

    uri, artifact_root = settings.mlflow_tracking_uri, settings.mlflow_artifact_root
    if not uri:
        defaults = registry_settings(settings.database_path)
        uri, artifact_root = defaults['mlflow_tracking_uri'], defaults['mlflow_artifact_root']
    return ModelRegistry(uri, artifact_root=artifact_root or None, demo=settings.demo_mode,
                         ui_url=settings.mlflow_ui_url or None)

class ModelsMixin:
    """The model registry: register trained models, list, promote and pin versions."""

    def _register_models(self, summary: Dict[str, Any]) -> Dict[str, Any]:
        """Record the models just trained as a new registry version (the champion unless pinned meanwhile)."""
        registry = self.registry
        if registry is None or not self.pipeline.ml_trained:
            return {}
        p = self.pipeline
        params = {
            'universe': self.universe, 'data_date': summary.get('data_date'), 'horizon_days': p.horizon,
            'target': summary.get('target'), 'assets': summary.get('total_analyzed'),
            'models': ','.join(summary.get('ml_models_used') or []),
            'features': len(p.predictor.feature_columns), 'demo': self.settings.demo_mode,
            'weights': ','.join(f'{k}={v}' for k, v in sorted(p.weights.items())),
        }
        metrics = {'quality': summary.get('model_quality') or {},
                   'volatility': {k: v for k, v in (summary.get('volatility_model') or {}).items() if k != 'horizon'},
                   'test_accuracy': {k: v for k, v in (summary.get('ml_test_accuracy') or {}).items()}}
        tags = {'git_commit': git_commit()}
        try:
            with tempfile.TemporaryDirectory(prefix=f'ledger-{self.universe}-') as tmp:
                p.export_models(tmp)
                # Promote unless someone pinned a version while this analysis was running
                version = registry.register(self.universe, tmp, params, metrics, tags,
                                            promote=not registry.pinned(self.universe))
            return {'version': version['version'], 'run_id': version['run_id']}
        except Exception as e:  # the analysis is still useful without the registry
            logger.warning(f'Could not register the {self.universe} models: {e}')
            return {'error': f'Not registered: {e}'}

    def models(self) -> Dict[str, Any]:
        if self.registry is None:
            return {'enabled': False, 'versions': [], 'champion': None, 'pinned': False}
        return {**self.registry.summary(self.universe), 'loaded_version': self.loaded_version}

    def promote_model(self, version: str, pin: bool = True) -> Dict[str, Any]:
        self._require_registry()
        self.registry.promote(self.universe, version, pin=pin)
        return self.models()

    def unpin_model(self) -> Dict[str, Any]:
        self._require_registry()
        self.registry.set_pinned(self.universe, False)
        return self.models()

    def _require_registry(self) -> None:
        if self.registry is None:
            raise RuntimeError('The model registry is turned off (MODEL_REGISTRY=off)')
