"""Security headers and the Content Security Policy."""

import base64
import hashlib

from fastapi.testclient import TestClient

from api.main import create_app
from api.security import content_security_policy, inline_script_hashes
from api.settings import Settings


def test_inline_scripts_are_allowed_by_hash_only():
    page = ('<script src="main.js" type="module"></script>'
            '<script>document.title = "x"</script><script> </script>')
    expected = base64.b64encode(hashlib.sha256(b'document.title = "x"').digest()).decode()
    assert inline_script_hashes(page) == [f"'sha256-{expected}'"]
    # Unusual but valid markup is still found: upper case, spaces before '>'
    assert inline_script_hashes('<SCRIPT >document.title = "x"</script >') == [f"'sha256-{expected}'"]


def test_policy_reads_the_built_index(tmp_path):
    index = tmp_path / 'index.html'
    index.write_text('<html><script>run()</script></html>')
    policy = content_security_policy(str(index))
    assert "script-src 'self' 'sha256-" in policy
    assert "frame-ancestors 'none'" in policy and "object-src 'none'" in policy
    assert "'unsafe-eval'" not in policy
    assert 'sha256' not in content_security_policy(str(tmp_path / 'missing.html'))


def test_every_response_carries_security_headers(fast_config_path, tmp_path):
    settings = Settings(config_path=fast_config_path, demo_mode=True, seed_demo=False,
                        database_path=str(tmp_path / 'db.sqlite'), model_registry='off',
                        frontend_dist=str(tmp_path / 'dist'))
    with TestClient(create_app(settings)) as client:
        health = client.get('/api/health')
        assert health.headers['X-Content-Type-Options'] == 'nosniff'
        assert health.headers['X-Frame-Options'] == 'DENY'
        assert health.headers['Referrer-Policy'] == 'no-referrer'
        assert "default-src 'self'" in health.headers['Content-Security-Policy']
        docs = client.get('/api/docs')
        assert docs.headers['X-Content-Type-Options'] == 'nosniff'
        assert 'Content-Security-Policy' not in docs.headers  # Swagger UI loads from a CDN
