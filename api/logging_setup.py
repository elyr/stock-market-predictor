"""
Log format for the server: readable text (default) or one JSON object per line
(``LOG_FORMAT=json``), which log collectors such as Loki or Elasticsearch read
without parsing rules.
"""

import json
import logging
from datetime import datetime, timezone

# Attributes every LogRecord has; anything else was passed with ``extra=`` and is kept
_STANDARD = set(vars(logging.LogRecord('', 0, '', 0, '', (), None))) | {'message', 'asctime', 'taskName'}


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        entry = {
            'time': datetime.fromtimestamp(record.created, tz=timezone.utc).isoformat(timespec='milliseconds'),
            'level': record.levelname.lower(),
            'logger': record.name,
            'message': record.getMessage(),
        }
        if record.exc_info:
            entry['exception'] = self.formatException(record.exc_info)
        for key, value in vars(record).items():
            if key not in _STANDARD and not key.startswith('_'):
                entry[key] = value if isinstance(value, (str, int, float, bool, type(None))) else str(value)
        return json.dumps(entry, ensure_ascii=False)


def configure_logging(fmt: str = 'text', level: str = 'INFO') -> None:
    """Send the app's and uvicorn's logs to stderr in one format."""
    handler = logging.StreamHandler()
    if fmt == 'json':
        handler.setFormatter(JsonFormatter())
    else:
        handler.setFormatter(logging.Formatter('%(asctime)s %(levelname)-7s %(name)s: %(message)s'))
    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(level.upper())
    for name in ('uvicorn', 'uvicorn.error', 'uvicorn.access'):
        logger = logging.getLogger(name)
        logger.handlers = []
        logger.propagate = True
    # Third-party libraries are noisy at INFO
    for name in ('urllib3', 'yfinance', 'peewee', 'alembic', 'mlflow', 'httpx'):
        logging.getLogger(name).setLevel(max(logging.WARNING, root.level))
