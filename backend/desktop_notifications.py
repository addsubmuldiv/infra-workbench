"""Durable acknowledgements for Windows notification API requests."""
from typing import Literal

from fastapi import HTTPException
from pydantic import BaseModel, Field


class DesktopDeliveryUpdate(BaseModel):
    status: Literal['sending', 'submitted', 'failed', 'disabled', 'skipped']
    error: str = Field(default='', max_length=500)


def register_desktop_notification_routes(app, store):
    @app.get('/api/notifications/desktop-pending')
    async def pending_desktop_deliveries():
        return {'events': store.pending_desktop_events()}

    @app.post('/api/notifications/{reservation_id}/desktop')
    async def update_desktop_delivery(reservation_id: str, body: DesktopDeliveryUpdate):
        try:
            return store.transition_desktop(reservation_id, body.status, body.error)
        except KeyError:
            raise HTTPException(404, '预约通知不存在') from None
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from None
