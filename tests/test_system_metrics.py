import sys
from pathlib import Path
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from backend.remote_probe import parse_cpu_times, cpu_usage, parse_memory


def test_cpu_aggregate_excludes_double_counted_guest_and_idle_iowait():
    before = parse_cpu_times('cpu 100 10 20 1000 20 5 5 0 50 0\ncpu0 1 2 3 4')
    after = parse_cpu_times('cpu 150 10 40 1070 30 5 5 0 80 0')
    assert cpu_usage(before, after) == pytest.approx(46.6666667)


def test_memory_uses_available_not_just_completely_free_pages():
    value = parse_memory('MemTotal: 1024000 kB\nMemFree: 1000 kB\nMemAvailable: 256000 kB\nCached: 5000 kB')
    assert value['memory_total'] == 1000*1024**2
    assert value['memory_available'] == 250*1024**2
    assert value['memory_used'] == 750*1024**2


def test_missing_or_invalid_system_metrics_are_unknown_not_zero():
    assert parse_cpu_times('unreadable') is None
    assert cpu_usage(None, None) is None
    assert cpu_usage((1, 1), (1, 1)) is None
    assert parse_memory('MemTotal: 1 kB') is None
