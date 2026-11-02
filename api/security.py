"""
Security headers for every response.

- Every response gets `X-Content-Type-Options`, `Referrer-Policy`, `X-Frame-Options`,
  `Permissions-Policy` and `Cross-Origin-Opener-Policy`.
- The web app also gets a Content Security Policy:
  - scripts only from this server, plus the inline scripts of the built `index.html`
    (allowed by their SHA-256, computed at start-up, so a rebuilt app keeps working);
  - no framing, no plugins, and requests only to this server.
- Styles allow inline styles: Angular writes component styles inline.
- The interactive API docs (`/api/docs`) load Swagger UI from a CDN, so they are
  left without the policy.
"""

import base64
import hashlib
import os
from html.parser import HTMLParser
from typing import Dict, List, Optional

BASE_HEADERS: Dict[str, str] = {
    'X-Content-Type-Options': 'nosniff',
    'Referrer-Policy': 'no-referrer',
    'X-Frame-Options': 'DENY',
    'Permissions-Policy': 'camera=(), microphone=(), geolocation=(), payment=(), usb=()',
    'Cross-Origin-Opener-Policy': 'same-origin',
}

NO_CSP_PREFIXES = ('/api/docs', '/api/openapi.json')

class _InlineScripts(HTMLParser):
    """Collects the text of every <script> without a src attribute, exactly as written."""

    def __init__(self):
        super().__init__(convert_charrefs=False)
        self.scripts: List[str] = []
        self._current: Optional[List[str]] = None

    def handle_starttag(self, tag, attrs):
        if tag == 'script' and not any(name == 'src' for name, _ in attrs):
            self._current = []

    def handle_endtag(self, tag):
        if tag == 'script' and self._current is not None:
            self.scripts.append(''.join(self._current))
            self._current = None

    def handle_data(self, data):
        if self._current is not None:
            self._current.append(data)


def inline_script_hashes(index_html: str) -> List[str]:
    """CSP source expressions ('sha256-…') for every inline script in a page."""
    parser = _InlineScripts()
    parser.feed(index_html)
    parser.close()
    return [f"'sha256-{base64.b64encode(hashlib.sha256(body.encode()).digest()).decode()}'"
            for body in parser.scripts if body.strip()]


def content_security_policy(index_path: Optional[str] = None) -> str:
    hashes: List[str] = []
    if index_path and os.path.isfile(index_path):
        with open(index_path, encoding='utf-8') as f:
            hashes = inline_script_hashes(f.read())
    directives = {
        'default-src': ["'self'"],
        'script-src': ["'self'", *hashes],
        'style-src': ["'self'", "'unsafe-inline'"],
        'img-src': ["'self'", 'data:'],
        'font-src': ["'self'", 'data:'],
        'connect-src': ["'self'"],
        'object-src': ["'none'"],
        'base-uri': ["'self'"],
        'form-action': ["'self'"],
        'frame-ancestors': ["'none'"],
    }
    return '; '.join(f"{name} {' '.join(values)}" for name, values in directives.items())


def headers_for(path: str, csp: str) -> Dict[str, str]:
    headers = dict(BASE_HEADERS)
    if not path.startswith(NO_CSP_PREFIXES):
        headers['Content-Security-Policy'] = csp
    return headers
