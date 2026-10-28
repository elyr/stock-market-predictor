"""
Turning detected signals into notifications.

Every signal is first stored in the database, which is the in-app channel:
the web app reads notifications from there. After a notification is stored
(i.e. it passed deduplication and the cooldown), it is handed to every extra
channel. None are configured yet; Telegram, email or Discord can be added by
implementing :class:`NotificationChannel` and passing it to :class:`Notifier`,
without changing how signals are detected.

This module also works out when the twice-daily scans run.
"""

import logging
from datetime import datetime, timedelta
from typing import Any, Dict, Iterable, List, Optional, Protocol, Tuple
from zoneinfo import ZoneInfo

from api.store import NotificationStore
from src.signals import Signal

logger = logging.getLogger(__name__)


class NotificationChannel(Protocol):
    """An outbound channel. ``deliver`` receives the stored notification as a dict."""

    name: str

    def deliver(self, notification: Dict[str, Any]) -> None: ...


class Notifier:
    def __init__(self, store: NotificationStore, channels: Iterable[NotificationChannel] = (),
                 cooldown_hours: float = 12):
        self.store = store
        self.channels = list(channels)
        self.cooldown_hours = cooldown_hours

    def publish(self, universe: str, signals: Iterable[Signal], session: Optional[str] = None) -> List[Dict[str, Any]]:
        """Store new signals as notifications and fan them out; returns the ones actually created."""
        created = []
        for signal in signals:
            notification_id = self.store.add(universe, signal.to_dict(), signal.dedupe_key(universe),
                                             session=session, cooldown_hours=self.cooldown_hours)
            if notification_id is None:
                continue
            notification = self.store.get(notification_id)
            created.append(notification)
            for channel in self.channels:
                try:
                    channel.deliver(notification)
                except Exception as e:  # one failing channel must not block the others
                    logger.warning(f"Channel {getattr(channel, 'name', channel)} failed: {e}")
        return created


def _parse(clock: str) -> Tuple[int, int]:
    hour, minute = clock.split(':')
    return int(hour), int(minute)


def scan_times(schedule: Dict[str, Any], universe: str, now: datetime,
               days: int = 8) -> List[Tuple[datetime, str]]:
    """
    Upcoming (time, session) pairs for a universe, in the schedule's time zone.

    Two scans a day: ``open`` (after the US open) and ``close`` (after the US
    close). Stocks skip weekends when ``stocks_weekdays_only`` is set; crypto
    trades every day so it is scanned every day.
    """
    tz = ZoneInfo(schedule.get('timezone', 'America/New_York'))
    local_now = now.astimezone(tz)
    weekdays_only = universe == 'stocks' and schedule.get('stocks_weekdays_only', True)
    result = []
    for offset in range(days):
        day = (local_now + timedelta(days=offset)).date()
        if weekdays_only and day.weekday() >= 5:
            continue
        for session in ('open', 'close'):
            hour, minute = _parse(schedule.get(session, '09:45' if session == 'open' else '16:15'))
            moment = datetime(day.year, day.month, day.day, hour, minute, tzinfo=tz)
            if moment > local_now:
                result.append((moment, session))
    return sorted(result)


def next_scan(schedule: Dict[str, Any], universe: str, now: datetime) -> Optional[Tuple[datetime, str]]:
    upcoming = scan_times(schedule, universe, now)
    return upcoming[0] if upcoming else None
