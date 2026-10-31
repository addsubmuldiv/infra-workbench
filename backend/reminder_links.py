"""Shared site-local destinations for reservation reminders."""
from urllib.parse import urlencode


def reservation_link(item):
    host = item.get('host_id')
    if not host:
        return '#reservations'
    devices = item.get('matched_devices', []) if item.get('mode') == 'count' else item.get('devices', [])
    query = [('host', host)] + [('device', device) for device in devices]
    return '#overview?' + urlencode(query)


def event_link(event):
    url = event.get('url')
    if isinstance(url, str) and (url.startswith('#overview?') or url == '#reservations'):
        return url
    return '#overview?' + urlencode({'host': event['host']}) if event.get('host') else '#reservations'
