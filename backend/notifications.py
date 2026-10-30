"""Keep connection churn in the UI, never in desktop notification history."""
import math
import time

QUIET_SUFFIXES = (
    '：SSH 连接失败',
    '：采集已恢复',
    '：已连接，远端采集失败',
    '：已连接，设备解析失败',
)
MAX_NOTIFICATION_AGE = 120


def should_notify(event, now=None):
    if event.get('notify') is False:
        return False
    message = event.get('message', '')
    if not isinstance(message, str) or not message or message.endswith(QUIET_SUFFIXES):
        return False
    created = event.get('created')
    if created is not None:
        if type(created) not in (int, float) or not math.isfinite(created):
            return False
        age = (time.time() if now is None else now) - created
        if not -30 <= age <= MAX_NOTIFICATION_AGE:
            return False
    return True
