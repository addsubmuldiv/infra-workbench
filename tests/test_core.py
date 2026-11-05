import base64
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from backend.core import parse_nvidia, parse_npu, eligible, TransitionTracker, discover_aliases, install_key_script


def test_gpu_idle_compute_does_not_mean_available():
    devices = parse_nvidia('0, GPU-1, RTX 4090 D, 24564, 23819, 0, 39',
                           'GPU-1, 4308, VLLM::Worker_TP0, 23796')
    assert devices[0]['memory_free'] == 745 * 1024**2
    assert devices[0]['processes'][0]['pid'] == 4308
    assert not eligible(devices[0], 1024**3, True)


def test_npu_uses_hbm_not_zero_host_memory():
    raw = '''| 0     910B3               | OK            | 99.2        38                0 / 0 |
| 0                         | 0000:C1:00.0  | 0           0 / 0          3472 / 65536 |
| No running processes found in NPU 0 |
| 1     910B3               | OK            | 99.2        38                0 / 0 |
| 0                         | 0000:C2:00.0  | 0           0 / 0          3472 / 65536 |
| 1 0 | 123 | python | 1024 |'''
    devices = parse_npu(raw)
    assert devices[0]['memory_total'] == 64 * 1024**3
    assert devices[0]['memory_used'] == 3472 * 1024**2
    assert devices[0]['processes_known'] is True
    assert devices[1]['processes'][0]['pid'] == 123


def test_unknown_output_never_reports_empty_available_devices():
    with pytest.raises(ValueError):
        parse_npu('driver error: inaccessible')
    with pytest.raises(ValueError):
        parse_nvidia('0, GPU-1, RTX, N/A, N/A, N/A, N/A', '')
    assert not eligible({'memory_free': 999999, 'processes_known': False}, 0, True)


def test_alias_discovery_handles_include_duplicates_and_patterns(tmp_path):
    (tmp_path / 'extra').write_text('Host child child-2\n HostName 10.0.0.2\n', encoding='utf-8')
    (tmp_path / 'config').write_text('Host one *.internal !bad\nInclude extra\nHost one\nHost *\n', encoding='utf-8')
    assert discover_aliases(tmp_path / 'config') == ['one', 'child', 'child-2']


def test_notifications_require_two_samples_and_rearm():
    tracker = TransitionTracker()
    assert tracker.feed('r', 'free', 0) is None
    assert tracker.feed('r', 'busy', 10) is None
    assert tracker.feed('r', 'busy', 20) == ('free', 'busy')
    assert tracker.feed('r', 'busy', 30) is None
    assert tracker.feed('r', 'free', 80) is None
    assert tracker.feed('r', 'free', 90) == ('busy', 'free')
    tracker.reset('r')
    assert tracker.feed('r', 'busy', 100) is None


def test_public_key_install_preserves_existing_keys_and_is_idempotent(tmp_path):
    home = tmp_path / 'remote'
    home.mkdir()
    ssh = home / '.ssh'
    ssh.mkdir()
    existing = 'ssh-ed25519 ' + base64.b64encode(b'existing').decode() + ' other'
    key = 'ssh-ed25519 ' + base64.b64encode(b'new-key').decode() + ' infra-workbench'
    (ssh / 'authorized_keys').write_text(existing, encoding='utf-8')
    import os
    env = dict(os.environ, HOME=str(home), USERPROFILE=str(home))
    for _ in range(2):
        result = subprocess.run([sys.executable, '-c', install_key_script(key)], env=env, capture_output=True, text=True)
        assert result.returncode == 0, result.stderr
    lines = (ssh / 'authorized_keys').read_text().splitlines()
    assert lines == [existing, key]


def test_install_rejects_multiline_key():
    with pytest.raises(ValueError):
        install_key_script('ssh-ed25519 AAAA\nmalicious')


def test_ascend950_separate_columns_and_na_bus_preserve_warning():
    raw = '''| NPU ID | Name | Health | Power(W) Temp(C) Hugepages-Usage(page) |
| | | Bus-Id | NPU Util(%) Memory-Usage(MB) HBM-Usage(MB) |
| 0 | Ascend950DT | Warning | 383.7 54 0 / 0 |
| | | NA | 0 0 / 0 4800 / 98304 |
| 1 | Ascend950DT | Warning | 393.8 54 0 / 0 |
| | | NA | 3 0 / 0 4800 / 98304 |
| NPU ID | Process id | Process name | Process memory(MB) | Process id in container |
| No running processes found in NPU 0 |
| 1 | 12345 | python3 | 1024 | 42 |'''
    devices = parse_npu(raw)
    assert len(devices) == 2
    assert devices[0]['name'] == 'Ascend950DT'
    assert devices[0]['memory_total'] == 96 * 1024**3
    assert devices[0]['memory_used'] == 4800 * 1024**2
    assert devices[0]['temperature'] == 54
    assert devices[0]['health'] == 'Warning'
    assert devices[0]['processes_known'] is True
    assert eligible(devices[0], 1024**3, True)
    assert devices[1]['utilization'] == 3
    assert devices[1]['processes'][0] == dict(pid=12345, name='python3', user=None, memory_used=1024**3)
    devices[0]['health'] = 'Alarm'
    assert not eligible(devices[0], 1024**3, True)


def test_dual_chip_cards_keep_all_16_devices_and_chip_specific_processes():
    # Mirrors A3-new: chip 1 power is '-' and each chip has its own Phy-ID.
    rows = ['| NPU Name | Health | Power(W) Temp(C) Hugepages-Usage(page) |',
            '| Chip Phy-ID | Bus-Id | AICore(%) Memory-Usage(MB) HBM-Usage(MB) |']
    for card in range(8):
        for chip in range(2):
            physical = card*2+chip
            rows += [f'| {card} Ascend910 | OK | {180 if chip == 0 else "-"} 40 0 / 0 |',
                     f'| {chip} {physical} | 0000:AE:00.0 | 0 0 / 0 {3000+physical} / 65536 |']
    rows += ['| NPU Chip | Process id | Process name | Process memory(MB) | Process id in container |',
             '| No running processes found in NPU 0 |',
             '| 1 0 | 1234 | python | 1473 | NA |',
             '| 1 1 | 5678 | python | 1024 | NA |',
             '| 4 1 | 9000 | lmp | 5321 | NA |']
    devices = parse_npu('\n'.join(rows))
    assert len(devices) == 16
    assert [d['physical_id'] for d in devices] == list(map(str, range(16)))
    assert [d['id'] for d in devices] == ['phy:'+str(i) for i in range(16)]
    assert len({d['uuid'] for d in devices}) == 16
    assert devices[1]['memory_used'] == 3001*1024**2
    assert devices[0]['processes_known'] and devices[1]['processes_known']
    assert devices[2]['processes'][0]['pid'] == 1234
    assert devices[3]['processes'][0]['pid'] == 5678
    assert devices[8]['processes'] == []
    assert devices[8]['processes_known'] is False  # no complete card/chip process record
    assert devices[9]['processes'][0]['pid'] == 9000
    assert devices[9]['card_id'] == '4' and devices[9]['chip_id'] == '1'


def test_single_chip_device_ids_stay_compatible():
    raw = '''| 3 910B3 | OK | 99 40 0 / 0 |
| 0 | 0000:C1:00.0 | 0 0 / 0 3472 / 65536 |
| No running processes found in NPU 3 |'''
    device = parse_npu(raw)[0]
    assert device['id'] == '3'
    assert device['display_id'] == '3'
    assert device['card_id'] == '3' and device['chip_id'] == '0'


def dual_die_process_output(rows, closed=True):
    metrics = []
    for chip in range(2):
        metrics += ['| 5 Ascend910 | OK | 180 44 0 / 0 |',
                    f'| {chip} {10+chip} | 0000:04:00.0 | 0 0 / 0 3000 / 65536 |']
    return '\n'.join(metrics + [
        '| NPU Chip | Process id | Process name | Process memory(MB) | Process id in container |',
        '+===========================+===============+',
        *rows,
        *(['+===========================+===============+'] if closed else []),
    ])


def test_complete_dual_die_process_block_confirms_unlisted_die_is_empty():
    for chip in (0, 1):
        devices = parse_npu(dual_die_process_output([f'| 5 {chip} | 1234 | python | 20153 | NA |']))
        assert devices[chip]['processes'][0]['pid'] == 1234
        idle = devices[1-chip]
        assert idle['processes_known'] is True
        assert idle['processes'] == []
        assert eligible(idle, 0, True)


def test_incomplete_or_invalid_process_block_keeps_unlisted_die_unknown():
    cases = [
        dual_die_process_output(['| 5 0 | 1234 | python | 20153 | NA |'], closed=False),
        dual_die_process_output(['| 5 0 | 1234 | python | 20153 | NA |', '| 5 1 | unreadable |']),
        dual_die_process_output(['| 5 0 | 1234 | python | 20153 | NA |', '| Permission denied |']),
        dual_die_process_output(['| 5 0 | 1234 | python | 20153 | NA |', '| 5 9 | 5678 | python | 10 | NA |']),
    ]
    complete = dual_die_process_output(['| 5 0 | 1234 | python | 20153 | NA |'])
    cases += [
        complete.replace('+===========================+===============+\n', '', 1),
        complete.replace('| NPU Chip | Process id | Process name | Process memory(MB) | Process id in container |', ''),
    ]
    for raw in cases:
        idle = parse_npu(raw)[1]
        assert idle['processes_known'] is False
        assert not eligible(idle, 0, True)
