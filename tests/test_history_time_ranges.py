from datetime import datetime
from zoneinfo import ZoneInfo

import pytest


def test_recent_window_ends_now_for_today_and_at_day_end_for_past_days():
    from backend.resource_stats_routes import history_time_range
    zone = ZoneInfo('Asia/Hong_Kong')
    now = datetime(2026, 11, 4, 15, 30, tzinfo=zone).timestamp()
    a,b = history_time_range(dict(date='2026-11-04',window_hours='1'),zone,now)
    assert b == now and b-a == 3600
    a,b = history_time_range(dict(date='2026-11-03',window_hours='3'),zone,now)
    assert datetime.fromtimestamp(b,zone).hour == 0 and b-a == 10800


def test_custom_window_uses_selected_timezone_and_rejects_invalid_ranges():
    from backend.resource_stats_routes import history_time_range
    zone = ZoneInfo('Asia/Hong_Kong')
    a,b = history_time_range(dict(date='2026-11-04',start_time='14:00',end_time='16:30'),zone)
    assert b-a == 9000 and datetime.fromtimestamp(a,zone).hour == 14
    for fields in [dict(start_time='16:00',end_time='14:00'),dict(start_time='14:00'),dict(window_hours='99'),dict(window_hours='1',start_time='14:00',end_time='16:00')]:
        with pytest.raises(ValueError):history_time_range(dict(date='2026-11-04',**fields),zone)


def test_nonexistent_dst_time_is_rejected():
    from backend.resource_stats_routes import history_time_range
    with pytest.raises(ValueError):
        history_time_range(dict(date='2026-03-08',start_time='02:30',end_time='04:00'),ZoneInfo('America/New_York'))


def test_history_route_accepts_selected_range_and_rejects_mixed_parameters(tmp_path):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from backend.store import Store
    from backend.resource_stats import ResourceStats
    from backend.resource_stats_routes import register_resource_history_routes
    stats=ResourceStats(Store(tmp_path/'stats.db'))
    app=FastAPI()
    register_resource_history_routes(app,stats,[dict(id='a',target='synthetic')])
    with TestClient(app) as client:
        args=dict(host_ids='a',date='2026-11-03',timezone='Asia/Hong_Kong',kind='GPU',start_time='14:00',end_time='16:00')
        result=client.get('/api/resource-history',params=args)
        assert result.status_code==200,result.text
        assert result.json()['end']-result.json()['start']==7200
        assert datetime.fromtimestamp(result.json()['start'],ZoneInfo('Asia/Hong_Kong')).hour==14
        assert client.get('/api/resource-history',params=dict(args,window_hours='1')).status_code==400
