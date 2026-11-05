import csv
import glob
import re
import shlex
from pathlib import Path

MIB = 1024 ** 2


def number(value):
    try:
        return float(value.strip())
    except (ValueError, AttributeError):
        return None


def parse_nvidia(metrics, processes, processes_ok=True):
    devices = []
    for row in csv.reader(metrics.strip().splitlines()):
        if len(row) != 7:
            continue
        index, uuid, name, total, used, util, temp = [x.strip() for x in row]
        total, used = number(total), number(used)
        if total is None or used is None:
            raise ValueError('GPU 显存指标不可读取')
        devices.append(dict(id=index, uuid=uuid, kind='GPU', name=name,
                            memory_total=int(total*MIB), memory_used=int(used*MIB),
                            memory_free=int((total-used)*MIB), utilization=number(util),
                            temperature=number(temp), health='unknown', processes=[], processes_known=processes_ok))
    if not devices:
        raise ValueError('无法识别 NVIDIA 指标输出')
    for row in csv.reader(processes.strip().splitlines()):
        if len(row) != 4:
            if row:
                for d in devices:
                    d['processes_known'] = False
            continue
        uuid, pid, name, memory = [x.strip() for x in row]
        if not pid.isdigit():
            for d in devices:
                d['processes_known'] = False
            continue
        for d in devices:
            if d['uuid'] == uuid:
                amount = number(memory)
                d['processes'].append(dict(pid=int(pid), name=name, user=None,
                                            memory_used=int(amount*MIB) if amount is not None else None))
    return devices


def parse_npu(raw):
    devices, current = [], None
    for line in raw.splitlines():
        # Older tools combine ID/name in one column; 26.x separates them.
        head = re.search(r'^\|\s*(\d+)(?:\s*\|\s*|\s+)(\S+)\s*\|\s*(OK|Warning|Alarm|Unknown|UNKNOWN)\s*\|\s*(?:[\d.]+|NA|N/A|-)\s+([\d.]+|NA|N/A|-)', line)
        if head:
            if current is not None:
                raise ValueError('NPU 芯片指标不完整，不能确认设备总数')
            current = dict(card_id=head[1], kind='NPU', name=head[2] if head[2].startswith('Ascend') else 'Ascend '+head[2],
                           health=head[3], temperature=number(head[4]), utilization=None,
                           processes=[], processes_known=False)
            continue
        if current and (re.search(r'[0-9a-fA-F]{4}:[0-9a-fA-F]{2}:', line) or re.search(r'\|\s*NA\s*\|', line)):
            columns = line.split('|')
            # The metrics are the final populated column in both layouts.
            values = columns[-2] if len(columns) > 3 else ''
            pairs = re.findall(r'(\d+)\s*/\s*(\d+)', values)
            util = re.match(r'\s*(\d+)', values)
            if pairs:
                used, total = map(int, pairs[-1])
                if total <= 0:
                    raise ValueError('NPU HBM 总量不可读取')
                chip_fields = columns[1].split()
                chip_id = chip_fields[0] if chip_fields and chip_fields[0].isdigit() else '0'
                physical_id = chip_fields[1] if len(chip_fields) == 2 and chip_fields[1].isdigit() else None
                current.update(memory_total=total*MIB, memory_used=used*MIB,
                               memory_free=(total-used)*MIB, utilization=int(util[1]) if util else None,
                               chip_id=chip_id, physical_id=physical_id)
                devices.append(current)
                current = None
    if current is not None or not devices:
        raise ValueError('无法识别完整的 npu-smi 设备输出')

    multi_chip = any(sum(other['card_id'] == d['card_id'] for other in devices) > 1 or d['chip_id'] != '0' for d in devices)
    for d in devices:
        d['uuid'] = 'npu-'+d['card_id']+'-'+d['chip_id']
        if d['physical_id'] is not None:
            d['id'] = 'phy:'+d['physical_id']
            d['display_id'] = d['physical_id']
        elif multi_chip:
            d['id'] = 'chip:'+d['card_id']+':'+d['chip_id']
            d['display_id'] = d['card_id']+'/'+d['chip_id']
        else:
            d['id'] = d['display_id'] = d['card_id']
    if len({d['id'] for d in devices}) != len(devices) or len({d['uuid'] for d in devices}) != len(devices):
        raise ValueError('NPU 设备编号重复，无法可靠区分芯片')

    process_table, block_rows, block_valid = False, [], False
    for line in raw.splitlines():
        if re.search(r'\|\s*NPU\s+Chip\s*\|\s*Process id\s*\|', line):
            process_table, block_rows, block_valid = True, [], False
            continue
        if process_table and re.fullmatch(r'\s*\+(?:=+\+)+\s*', line):
            # npu-smi groups all processes of a card between '=' borders.
            # A busy card omits empty dies; only a complete, valid block
            # proves those omitted dies have no reported compute processes.
            cards = {card for card, chip in block_rows}
            if block_valid and len(cards) == 1:
                for d in devices:
                    if d['card_id'] in cards:
                        d['processes_known'] = True
            block_rows, block_valid = [], True
            continue
        empty = re.search(r'No running processes found in NPU\s+(\d+)', line)
        proc = re.search(r'^\|\s*(\d+)\s+(\d+)\s*\|\s*(\d+)\s*\|\s*(.*?)\s*\|\s*(\d+)\s*\|', line)
        proc_new = re.search(r'^\|\s*(\d+)\s*\|\s*(\d+)\s*\|\s*(.*?)\s*\|\s*(\d+)\s*\|\s*(?:\d+|NA)\s*\|', line)
        if process_table:
            complete = re.fullmatch(r'\s*\|\s*(\d+)\s+(\d+)\s*\|\s*\d+\s*\|[^|]+\|\s*\d+\s*\|\s*(?:\d+|NA)\s*\|\s*', line)
            if complete and any(d['card_id'] == complete[1] and d['chip_id'] == complete[2] for d in devices):
                block_rows.append((complete[1], complete[2]))
            else:
                block_valid = False
        for d in devices:
            if empty and empty[1] == d['card_id']:
                d['processes_known'] = True
            if proc and proc[1] == d['card_id'] and proc[2] == d['chip_id']:
                d['processes_known'] = True
                d['processes'].append(dict(pid=int(proc[3]), name=proc[4], user=None, memory_used=int(proc[5])*MIB))
            if proc_new and proc_new[1] == d['card_id']:
                d['processes_known'] = True
                d['processes'].append(dict(pid=int(proc_new[2]), name=proc_new[3], user=None, memory_used=int(proc_new[4])*MIB))
    return devices


def eligible(device, minimum, no_processes=True):
    return (device.get('memory_free') is not None and device['memory_free'] >= minimum
            and device.get('health') != 'Alarm'
            and (not no_processes or (device.get('processes_known') is True and not device.get('processes'))))


def discover_aliases(config):
    aliases, seen = [], set()

    def visit(path, depth=0):
        path = Path(path).expanduser().resolve()
        if path in seen or depth > 10 or not path.is_file():
            return
        seen.add(path)
        for line in path.read_text(encoding='utf-8-sig', errors='replace').splitlines():
            try:
                tokens = shlex.split(line, comments=True, posix=True)
            except ValueError:
                continue
            if not tokens:
                continue
            if tokens[0].lower() == 'host':
                for alias in tokens[1:]:
                    if not any(c in alias for c in '*?!') and alias not in aliases:
                        aliases.append(alias)
            if tokens[0].lower() == 'include':
                for pattern in tokens[1:]:
                    expanded = Path(pattern).expanduser()
                    if not expanded.is_absolute():
                        expanded = Path(config).parent / expanded
                    for included in sorted(glob.glob(str(expanded))):
                        visit(included, depth+1)
    visit(config)
    return aliases


def install_key_script(public_key):
    if '\n' in public_key or '\r' in public_key or not re.fullmatch(r'ssh-ed25519 [A-Za-z0-9+/=]+(?: [\w@. -]+)?', public_key):
        raise ValueError('无效的公钥')
    # Sent over SSH stdin; no password or shell interpolation.
    return '''import os
from pathlib import Path
key = %r
folder = Path.home() / '.ssh'
folder.mkdir(mode=0o700, exist_ok=True)
path = folder / 'authorized_keys'
with path.open('a+', encoding='utf-8') as f:
    f.seek(0)
    old = f.read()
    blob = key.split()[1]
    if not any(blob in line.split() for line in old.splitlines()):
        f.write(('\\n' if old and not old.endswith('\\n') else '') + key + '\\n')
os.chmod(folder, 0o700)
os.chmod(path, 0o600)
print('公钥已追加（已有公钥保持不变）')
''' % public_key


class TransitionTracker:
    def __init__(self):
        self.states = {}

    def reset(self, key):
        self.states.pop(key, None)

    def feed(self, key, state, now):
        if key not in self.states:
            self.states[key] = [state, state, 0, -1e10]
            return None
        entry = self.states[key]
        if entry[1] != state:
            entry[1], entry[2] = state, 1
        else:
            entry[2] += 1
        if state != entry[0] and entry[2] >= 2:
            old = entry[0]
            entry[0] = state
            if now - entry[3] >= 60:
                entry[3] = now
                return old, state
        return None
