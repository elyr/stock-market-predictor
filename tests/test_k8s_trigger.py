"""
Tests for scripts/k8s_trigger.py against a small fake Ledger server.
"""

import json
import os
import sys
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'scripts'))
import k8s_trigger  # noqa: E402


def serve(outcome: str):
    """A fake server whose scan job finishes with ``outcome`` on the second status check."""
    state = {'polls': 0, 'requests': []}

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def reply(self, body, code=200):
            data = json.dumps(body).encode()
            self.send_response(code)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Content-Length', str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def do_POST(self):
            length = int(self.headers.get('Content-Length', 0))
            state['requests'].append((self.path, json.loads(self.rfile.read(length) or b'{}')))
            self.reply({'id': 'job1', 'status': 'queued'}, 202)

        def do_GET(self):
            state['polls'] += 1
            if state['polls'] < 2:
                self.reply({'id': 'job1', 'status': 'running'})
            elif outcome == 'succeeded':
                self.reply({'id': 'job1', 'status': 'succeeded', 'result': {'assets_scanned': 40, 'new_alerts': 2}})
            elif outcome == 'failed':
                self.reply({'id': 'job1', 'status': 'failed', 'error': 'no data'})
            else:
                self.reply({'id': 'job1', 'status': 'running'})

    server = HTTPServer(('127.0.0.1', 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server, state


@pytest.mark.parametrize('outcome,code', [('succeeded', 0), ('failed', 1)])
def test_waits_for_the_scan_and_reports(outcome, code, capsys):
    server, state = serve(outcome)
    try:
        url = f'http://127.0.0.1:{server.server_port}'
        assert k8s_trigger.main(['--url', url, '--universe', 'crypto', '--session', 'open', '--poll', '0.01']) == code
    finally:
        server.shutdown()
    assert state['requests'] == [('/api/crypto/signals/scan', {'session': 'open'})]
    out = capsys.readouterr()
    assert ('2 new alerts' in out.out) if code == 0 else ('no data' in out.err)


def test_times_out(capsys):
    server, _ = serve('never')
    try:
        url = f'http://127.0.0.1:{server.server_port}'
        assert k8s_trigger.main(['--url', url, '--universe', 'stocks', '--poll', '0.01', '--timeout', '0.2']) == 1
    finally:
        server.shutdown()
    assert 'still running' in capsys.readouterr().err


def test_unreachable_server(capsys):
    assert k8s_trigger.main(['--url', 'http://127.0.0.1:9', '--universe', 'stocks']) == 1
    assert 'Could not reach' in capsys.readouterr().err
