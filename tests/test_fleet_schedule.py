import math
from backend.polling import FleetSchedule


def test_slots_follow_dynamic_inventory_and_interval():
    s = FleetSchedule()
    s.reconcile(['a', 'b', 'c', 'd'], 8, 100)
    assert [s.due[k] for k in 'abcd'] == [100, 102, 104, 106]
    s.reconcile(['a', 'b'], 4, 101)
    assert s.due == {'a': 101, 'b': 103}
    s.reconcile(['b', 'c'], 10, 102)
    assert s.due == {'b': 102, 'c': 107}


def test_slow_jobs_skip_missed_slots_and_failures_back_off():
    s = FleetSchedule()
    s.reconcile(['a', 'b'], 5, 0)
    s.finish('a', 12, False)
    assert s.due['a'] == 15
    s.finish('b', 12, True)
    assert s.due['b'] >= 16
    assert math.isfinite(s.due['b'])


def test_unchanged_inventory_does_not_move_deadlines():
    s = FleetSchedule()
    s.reconcile(['a', 'b'], 5, 0)
    s.reconcile(['a', 'b'], 5, 2)
    assert s.due['a'] == 0


import pytest

@pytest.mark.parametrize('count', [1, 16, 100, 1000])
@pytest.mark.parametrize('interval', [5, 10, 15, 20, 30])
def test_fleet_size_and_configured_interval_are_variables(count, interval):
    s = FleetSchedule()
    s.reconcile([str(index) for index in range(count)], interval, 100)
    slots=sorted(s.due.values())
    assert slots[0]==100 and slots[-1]<100+interval
    for previous,current in zip(slots,slots[1:]):
        assert current-previous==pytest.approx(interval/count)
    for key in s.due:
        s.finish(key, 100+interval*10, False)
        assert 100+interval*10 < s.due[key] <= 100+interval*11
