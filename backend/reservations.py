"""One-shot reminders after every selected device stays idle for a full window."""
import copy
import math
import time
import uuid

from .core import eligible
from .reminder_links import reservation_link

MAX_SAMPLE_GAP = 30


def device_identity(device):
    return [device.get(key) for key in ('uuid', 'kind', 'name', 'card_id', 'chip_id', 'physical_id')]


def known_utilization(device):
    value = device.get('utilization')
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value) and 0 <= value <= 100


class ReservationBook:
    def __init__(self, store, mail=None):
        self.store = store
        self.mail = mail
        self.items = store.load('reservations', [])
        # Time while the collector was stopped cannot count as observed idle time.
        for item in self.items:
            if item['status'] != 'ready':
                item.update(status='unknown', idle_since=None, last_observed=None)
                if item.get('mode') == 'count':
                    item['available_count'] = None
        self.store.save('reservations', self.items)

    def _check_duplicate(self, candidate, exclude=None):
        mode = candidate.get('mode', 'fixed')
        active = [item for item in self.items if item['status'] != 'ready' and item['id'] != exclude]
        if any(item['host_id'] == candidate['host_id'] and item.get('mode', 'fixed') == mode
               and (set(item['devices']) == set(candidate['devices']) if mode == 'fixed' else
                    item.get('required_count') == candidate.get('required_count') and item.get('kind') == candidate.get('kind')
                    and item['minimum_gib'] == candidate['minimum_gib']) for item in active):
            raise ValueError('这些设备已经有预约，请在卡预约页面修改或取消')
        if exclude is None and len(active) >= 100:
            raise ValueError('最多同时保留 100 条等待中的预约')

    @staticmethod
    def _selection(item, host, devices, mode, required_count, kind):
        item.update(host_id=host['id'], target=host['target'], mode=mode,
                    devices=[device['id'] for device in devices] if mode == 'fixed' else [],
                    required_count=required_count if mode == 'count' else None,
                    kind=kind if mode == 'count' else None,
                    labels=[device.get('display_id', device['id']) for device in devices] if mode == 'fixed' else [],
                    identities={device['id']: device_identity(device) for device in devices} if mode == 'fixed' else {})
        item.pop('matched_devices', None)
        item.pop('available_count', None)

    def add(self, host, devices, wait_seconds, minimum_gib, now=None, *, mode='fixed', required_count=None, kind=None, email_notify=False, base_url='http://127.0.0.1:8765/'):
        item = dict(id=uuid.uuid4().hex, wait_seconds=wait_seconds, minimum_gib=minimum_gib,
                    email_notify=email_notify, base_url=base_url,
                    created_at=time.time() if now is None else now, status='waiting',
                    idle_since=None, last_observed=None, notified_at=None)
        self._selection(item, host, devices, mode, required_count, kind)
        self._check_duplicate(item)
        self.items.append(item)
        try:
            self.store.save('reservations', self.items)
        except Exception:
            self.items.remove(item)
            self.store.db.rollback()
            raise
        return copy.deepcopy(item)

    def get(self, item_id):
        item = next((item for item in self.items if item['id'] == item_id), None)
        if item is None:
            raise KeyError(item_id)
        return copy.deepcopy(item)

    def update(self, item_id, wait_seconds=None, *, host=None, devices=None, mode=None,
               required_count=None, kind=None, minimum_gib=None, email_notify=None, base_url=None):
        candidate = self.get(item_id)
        if candidate['status'] == 'ready':
            raise ValueError('这条预约已提醒，请重新选择设备预约')
        if host is not None:
            self._selection(candidate, host, devices, mode, required_count, kind)
        for key, value in dict(wait_seconds=wait_seconds, minimum_gib=minimum_gib,
                               email_notify=email_notify, base_url=base_url).items():
            if value is not None:
                candidate[key] = value
        candidate.update(status='waiting', idle_since=None, last_observed=None, notified_at=None)
        candidate.pop('matched_devices', None)
        candidate.pop('available_count', None)
        self._check_duplicate(candidate, exclude=item_id)
        index = next(index for index, item in enumerate(self.items) if item['id'] == item_id)
        before = self.items[index]
        self.items[index] = candidate
        try:
            self.store.save('reservations', self.items)
        except Exception:
            self.items[index] = before
            self.store.db.rollback()
            raise
        return copy.deepcopy(candidate)

    def _skip_desktop(self, ids, reason):
        if self.store.db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='desktop_outbox'").fetchone():
            self.store.db.executemany("UPDATE desktop_outbox SET status='skipped',error=?,updated=? WHERE id=? AND status='pending'",
                                      [(reason, time.time(), item_id) for item_id in ids])

    def remove(self, item_id):
        with self.store.db:
            self._skip_desktop([item_id], '预约记录已删除')
            self.store.db.execute("UPDATE mail_outbox SET status='skipped',error='预约记录已删除' WHERE id=? AND status='pending'", (item_id,))
        self.items[:] = [item for item in self.items if item['id'] != item_id]
        self.store.save('reservations', self.items)

    def remove_host(self, host_id):
        with self.store.db:
            self._skip_desktop([item['id'] for item in self.items if item['host_id'] == host_id], '机器已移除')
            self.store.db.executemany("UPDATE mail_outbox SET status='skipped',error='机器已移除' WHERE id=? AND status='pending'",
                                      [(item['id'],) for item in self.items if item['host_id'] == host_id])
        self.items[:] = [item for item in self.items if item['host_id'] != host_id]
        self.store.save('reservations', self.items)

    def observe(self, host_id, snapshot, now=None):
        active = [item for item in self.items if item['host_id'] == host_id and item['status'] != 'ready']
        if not active:
            return
        now = time.time() if now is None else now
        before = {item['id']: copy.deepcopy(item) for item in active}
        events = []
        mail = []
        desktop = []
        by_id = {device['id']: device for device in snapshot.get('devices', [])}
        collected = snapshot.get('collected_at')
        fresh = (snapshot.get('status') == 'online' and collected is not None
                 and 0 <= now-collected <= MAX_SAMPLE_GAP)
        for item in active:
            devices = [by_id.get(device_id) for device_id in item['devices']]
            count_mode = item.get('mode') == 'count'
            if count_mode:
                candidates = [device for device in by_id.values() if device.get('kind') == item['kind']]
                available = [device for device in candidates if eligible(device, item['minimum_gib']*1024**3)
                             and known_utilization(device) and device['utilization'] == 0]
                item['available_count'] = len(available) if fresh else None
            if not fresh:
                status = 'unknown'
            elif count_mode:
                status = ('settling' if len(available) >= item['required_count'] else
                          'unknown' if any(not device.get('processes_known') or not known_utilization(device) for device in candidates) else 'waiting')
            elif any(device is None or device_identity(device) != item['identities'][device_id]
                     for device_id, device in zip(item['devices'], devices)):
                status = 'needs_selection'
            elif any(not device.get('processes_known') or not known_utilization(device) for device in devices):
                status = 'unknown'
            elif any(not eligible(device, item['minimum_gib']*1024**3)
                     or device['utilization'] > 0 for device in devices):
                status = 'waiting'
            else:
                status = 'settling'
            previous = item['last_observed']
            if (status != 'settling' or item['idle_since'] is None or previous is None
                    or not 0 <= now-previous <= MAX_SAMPLE_GAP):
                item['idle_since'] = now if status == 'settling' else None
            item.update(status=status, last_observed=now if fresh else None)
            if status == 'settling' and now-item['idle_since'] >= item['wait_seconds']:
                if count_mode:
                    matched = available[:item['required_count']]
                    item['matched_devices'] = [device['id'] for device in matched]
                    item['labels'] = [device.get('display_id', device['id']) for device in matched]
                item.update(status='ready', notified_at=now)
                minutes = f"{item['wait_seconds']/60:g}"
                description = (f"至少 {item['required_count']} 个 {item['kind']} 的可用数量条件已持续满足"
                               if count_mode else '预约的设备已连续空闲')
                events.append((host_id, item['target']+' · 设备 '+', '.join(item['labels'])
                               +f'：{description} {minutes} 分钟，可以使用。启动前请再检查。'))
                desktop.append(dict(id=item['id'], url=reservation_link(item)))
                if self.mail:
                    payload = self.mail.prepare(item)
                    if payload:
                        mail.append(payload)
        if any(item != before[item['id']] for item in active):
            try:
                # Completing a reminder and recording its event commit together.
                self.store.save_with_events('reservations', self.items, events, now, mail, desktop)
            except Exception:
                self.items[:] = [before.get(item['id'], item) for item in self.items]
                raise

    def view(self, now=None):
        now = time.time() if now is None else now
        result = [{key: copy.deepcopy(value) for key, value in item.items() if key != 'identities'}
                  for item in self.items]
        mail_statuses = self.store.mail_statuses(item['id'] for item in self.items)
        desktop_statuses = self.store.desktop_statuses((item['id'] for item in self.items), now)
        for item in result:
            item['desktop'] = desktop_statuses.get(item['id'])
            item['url'] = reservation_link(item)
            item['email'] = mail_statuses.get(item['id'])
            if (item['status'] not in ('ready', 'needs_selection') and item['last_observed'] is not None
                    and not 0 <= now-item['last_observed'] <= MAX_SAMPLE_GAP):
                item.update(status='unknown', idle_since=None)
                if item.get('mode') == 'count':
                    item['available_count'] = None
            item['idle_seconds'] = (max(0, now-item['idle_since'])
                                    if item['status'] == 'settling' and item['idle_since'] is not None else 0)
            item['remaining_seconds'] = max(0, item['wait_seconds']-item['idle_seconds'])
            item.pop('identities', None)
        return result
