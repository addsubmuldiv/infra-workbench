"""Choose one notification channel and track desktop submissions."""
import time
from typing import Annotated, Literal

from fastapi import HTTPException
from pydantic import BaseModel, Field, StrictBool

from .interface_language import tr
from .notifications import MAX_NOTIFICATION_AGE


class DesktopDeliveryUpdate(BaseModel):
    status: Literal['sending', 'submitted', 'failed', 'disabled', 'skipped']
    error: str = Field(default='', max_length=500)


class DesktopPoll(BaseModel):
    enabled: StrictBool


class BrowserClaim(BaseModel):
    ids: list[Annotated[int, Field(strict=True, gt=0)]] = Field(max_length=100)


def register_desktop_notification_routes(app, store):
    desktop_until = 0.0
    assigned: dict[int, tuple[Literal['desktop', 'browser'], float]] = {}

    def expire_assignments():
        cutoff = time.time() - MAX_NOTIFICATION_AGE
        for event_id, (_, created) in list(assigned.items()):
            if created < cutoff:
                del assigned[event_id]

    @app.get('/api/notifications/desktop-pending')
    async def pending_desktop_deliveries():
        return {'events': store.pending_desktop_events()}

    @app.post('/api/notifications/desktop-events')
    async def desktop_events(body: DesktopPoll):
        nonlocal desktop_until
        # The tray polls every two seconds. Expiry also covers a detached tray exiting.
        desktop_until = time.monotonic() + 8 if body.enabled else 0
        expire_assignments()
        events = {event['id']: event for event in (*store.events(), *store.pending_desktop_events())}
        available = []
        for event_id, event in events.items():
            if body.enabled:
                if event_id in assigned and assigned[event_id][0] == 'browser':
                    continue
                if event['notify'] and event['desktop_status'] in (None, 'pending'):
                    assigned[event_id] = ('desktop', event['created'])
            available.append(event)
        return {'events': available}

    @app.post('/api/notifications/browser-claim')
    async def claim_browser_events(body: BrowserClaim):
        if time.monotonic() < desktop_until:
            return {'ids': []}
        expire_assignments()
        requested = set(body.ids)
        claimed = []
        for event in reversed(store.events()):
            event_id = event['id']
            status = event['desktop_status']
            if event_id not in requested or event_id in assigned or not event['notify']:
                continue
            if status not in (None, 'pending', 'disabled', 'failed'):
                continue
            if status == 'pending':
                store.transition_desktop(event['reservation_id'], 'skipped',
                                         tr('已交给浏览器通知', 'Assigned to browser notifications'))
            assigned[event_id] = ('browser', event['created'])
            claimed.append(event_id)
        return {'ids': claimed}

    @app.post('/api/notifications/{reservation_id}/desktop')
    async def update_desktop_delivery(reservation_id: str, body: DesktopDeliveryUpdate):
        try:
            return store.transition_desktop(reservation_id, body.status, body.error)
        except KeyError:
            raise HTTPException(404, '预约通知不存在') from None
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from None
