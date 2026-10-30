"""One-shot reminders after every selected device stays idle for a full window."""
import copy
import time
import uuid

from .core import eligible

MAX_SAMPLE_GAP = 30


def device_identity(device):
    return [device.get(key) for key in ('uuid', 'kind', 'name', 'card_id', 'chip_id', 'physical_id')]


class ReservationBook:
    def __init__(self, store, mail=None):
        self.store = store
        self.mail = mail
        self.items = store.load('reservations', [])
        # Time while the collector was stopped cannot count as observed idle time.
        for item in self.items:
            if item['status'] != 'ready':
                item.update(status='unknown', idle_since=None, last_observed=None)
        self.store.save('reservations', self.items)

    def add(self, host, devices, wait_seconds, minimum_gib, now=None):
        active = [item for item in self.items if item['status'] != 'ready']
        ids = [device['id'] for device in devices]
        if any(item['host_id'] == host['id'] and set(item['devices']) == set(ids) for item in active):
            raise ValueError('这些设备已经有预约，请在卡预约页面修改或取消')
        if len(active) >= 100:
            raise ValueError('最多同时保留 100 条等待中的预约')
        item = dict(id=uuid.uuid4().hex, host_id=host['id'], target=host['target'], devices=ids,
                    labels=[device.get('display_id', device['id']) for device in devices],
                    identities={device['id']: device_identity(device) for device in devices},
                    wait_seconds=wait_seconds, minimum_gib=minimum_gib,
                    created_at=time.time() if now is None else now, status='waiting',
                    idle_since=None, last_observed=None, notified_at=None)
        self.items.append(item)
        self.store.save('reservations', self.items)
        return copy.deepcopy(item)

    def update(self, item_id, wait_seconds):
        item = next((item for item in self.items if item['id'] == item_id), None)
        if item is None:
            raise KeyError(item_id)
        if item['status'] == 'ready':
            raise ValueError('这条预约已提醒，请重新选择设备预约')
        item.update(wait_seconds=wait_seconds, status='waiting', idle_since=None, last_observed=None)
        self.store.save('reservations', self.items)
        return copy.deepcopy(item)

    def remove(self, item_id):
        with self.store.db:
            self.store.db.execute("UPDATE mail_outbox SET status='skipped',error='预约记录已删除' WHERE id=? AND status='pending'", (item_id,))
        self.items[:] = [item for item in self.items if item['id'] != item_id]
        self.store.save('reservations', self.items)

    def remove_host(self, host_id):
        with self.store.db:
            self.store.db.executemany("UPDATE mail_outbox SET status='skipped',error='机器已移除' WHERE id=? AND status='pending'",
                                      [(item['id'],) for item in self.items if item['host_id'] == host_id])
        self.items[:] = [item for item in self.items if item['host_id'] != host_id]
        self.store.save('reservations', self.items)

    def observe(self, host_id, snapshot, now=None):
        now = time.time() if now is None else now
        before = copy.deepcopy(self.items)
        events = []
        mail = []
        by_id = {device['id']: device for device in snapshot.get('devices', [])}
        collected = snapshot.get('collected_at')
        fresh = (snapshot.get('status') == 'online' and collected is not None
                 and 0 <= now-collected <= MAX_SAMPLE_GAP)
        for item in self.items:
            if item['host_id'] != host_id or item['status'] == 'ready':
                continue
            devices = [by_id.get(device_id) for device_id in item['devices']]
            if not fresh:
                status = 'unknown'
            elif any(device is None or device_identity(device) != item['identities'][device_id]
                     for device_id, device in zip(item['devices'], devices)):
                status = 'needs_selection'
            elif any(not device.get('processes_known') for device in devices):
                status = 'unknown'
            elif any(not eligible(device, item['minimum_gib']*1024**3)
                     or (device.get('utilization') or 0) > 0 for device in devices):
                status = 'waiting'
            else:
                status = 'settling'
            previous = item['last_observed']
            if (status != 'settling' or item['idle_since'] is None or previous is None
                    or not 0 <= now-previous <= MAX_SAMPLE_GAP):
                item['idle_since'] = now if status == 'settling' else None
            item.update(status=status, last_observed=now if fresh else None)
            if status == 'settling' and now-item['idle_since'] >= item['wait_seconds']:
                item.update(status='ready', notified_at=now)
                minutes = f"{item['wait_seconds']/60:g}"
                events.append((host_id, item['target']+' · 设备 '+', '.join(item['labels'])
                               +f'：预约的设备已连续空闲 {minutes} 分钟，可以使用。启动前请再检查。'))
                if self.mail:
                    payload = self.mail.prepare(item)
                    if payload:
                        mail.append(payload)
        if self.items != before:
            try:
                # Completing a reminder and recording its event commit together.
                self.store.save_with_events('reservations', self.items, events, now, mail)
            except Exception:
                self.items[:] = before
                raise

    def view(self, now=None):
        now = time.time() if now is None else now
        result = copy.deepcopy(self.items)
        mail_statuses = self.store.mail_statuses()
        for item in result:
            item['email'] = mail_statuses.get(item['id'])
            if (item['status'] not in ('ready', 'needs_selection') and item['last_observed'] is not None
                    and not 0 <= now-item['last_observed'] <= MAX_SAMPLE_GAP):
                item.update(status='unknown', idle_since=None)
            item['idle_seconds'] = (max(0, now-item['idle_since'])
                                    if item['status'] == 'settling' and item['idle_since'] is not None else 0)
            item['remaining_seconds'] = max(0, item['wait_seconds']-item['idle_seconds'])
            item.pop('identities', None)
        return result
