"""
Telegram delivery for alerts.

:class:`TelegramChannel` sends each stored notification to one chat with the Bot
API ``sendMessage``. It is a :class:`~api.notifications.NotificationChannel`, so
the :class:`~api.notifications.Notifier` hands it every new notification after
it is stored in the app.

Settings (environment variables, see :mod:`api.settings`):

| Variable | Meaning |
|---|---|
| ``TELEGRAM_BOT_TOKEN`` | the bot's token from BotFather |
| ``TELEGRAM_CHAT_ID`` | the chat that receives the alerts |
| ``TELEGRAM_MIN_SEVERITY`` | ``info``, ``warning`` (default) or ``critical``; ``trend_enter`` is always sent |

The channel is only created when both the token and the chat id are set. A
failed send is logged and swallowed, so it never breaks a scan. The token is
part of the request address, so errors from the HTTP library (which quote it)
are never logged: only their type and Telegram's own description are.
"""

import logging
from typing import Any, Dict, List

import requests

from api.settings import Settings
from src.signals.detector import SEVERITY_ORDER

logger = logging.getLogger(__name__)

API_URL = 'https://api.telegram.org/bot{token}/sendMessage'
CONNECT_TIMEOUT, READ_TIMEOUT = 5, 10  # seconds
MAX_LENGTH = 4096                     # Telegram's limit for one message
ALWAYS_SENT = {'trend_enter'}         # info-level, but you want to know when protection ends
DEFAULT_MIN_SEVERITY = 'warning'


class TelegramChannel:
    """Sends notifications to one Telegram chat."""

    name = 'telegram'

    def __init__(self, token: str, chat_id: str, min_severity: str = DEFAULT_MIN_SEVERITY):
        if min_severity not in SEVERITY_ORDER:
            logger.warning(f"Unknown Telegram minimum severity '{min_severity}'; using '{DEFAULT_MIN_SEVERITY}'")
            min_severity = DEFAULT_MIN_SEVERITY
        self._token = token
        self.chat_id = chat_id
        self.min_severity = min_severity

    def wants(self, notification: Dict[str, Any]) -> bool:
        """Whether this notification is severe enough (or of a type that is always sent)."""
        if notification.get('type') in ALWAYS_SENT:
            return True
        return SEVERITY_ORDER.get(notification.get('severity'), 0) >= SEVERITY_ORDER[self.min_severity]

    @staticmethod
    def message(notification: Dict[str, Any]) -> str:
        """The title and body as plain text, within Telegram's length limit."""
        text = f"{notification['title']}\n\n{notification['body']}"
        return text if len(text) <= MAX_LENGTH else text[:MAX_LENGTH - 1] + '…'

    def deliver(self, notification: Dict[str, Any]) -> None:
        """Send one notification; never raises."""
        if not self.wants(notification):
            return
        try:
            response = requests.post(
                API_URL.format(token=self._token),
                json={'chat_id': self.chat_id, 'text': self.message(notification), 'disable_web_page_preview': True},
                timeout=(CONNECT_TIMEOUT, READ_TIMEOUT),
            )
            if not response.ok:
                logger.warning(f"Telegram refused notification {notification.get('id')} "
                               f"(HTTP {response.status_code}): {self._description(response)}")
        except Exception as error:  # the message of a requests error contains the address, and so the token
            logger.warning(f"Telegram delivery of notification {notification.get('id')} failed "
                           f"({type(error).__name__})")

    @staticmethod
    def _description(response: Any) -> str:
        try:
            return str(response.json().get('description', 'no description'))
        except Exception:
            return 'no description'


def notification_channels(settings: Settings) -> List[Any]:
    """The extra delivery channels the settings ask for (none, or Telegram when both variables are set)."""
    if not (settings.telegram_bot_token and settings.telegram_chat_id):
        return []
    channel = TelegramChannel(settings.telegram_bot_token, settings.telegram_chat_id, settings.telegram_min_severity)
    logger.info(f"Alerts also go to Telegram (minimum severity {channel.min_severity})")
    return [channel]


__all__ = ['TelegramChannel', 'notification_channels']
