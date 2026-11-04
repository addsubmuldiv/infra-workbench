"""Shared site-local destinations for reservation reminders."""
from urllib.parse import urlencode, parse_qs


def reservation_link(item):
    if item.get('mode') in ('specified', 'cluster_any'):
        return '#reservations?' + urlencode({'group': item['id']})
    host = item.get('host_id')
    if not host:
        return '#reservations'
    devices = item.get('matched_devices', []) if item.get('mode') == 'count' else item.get('devices', [])
    query = [('host', host)] + [('device', device) for device in devices]
    return '#overview?' + urlencode(query)


def event_link(event):
    url = event.get('url')
    if isinstance(url, str) and url.startswith('#reservations?'):
        query = parse_qs(url.split('?', 1)[1], strict_parsing=False)
        if set(query) == {'group'} and len(query['group']) == 1 and query['group'][0].isalnum():
            return url
    if isinstance(url, str) and (url.startswith('#overview?') or url == '#reservations'):
        return url
    return '#overview?' + urlencode({'host': event['host']}) if event.get('host') else '#reservations'
