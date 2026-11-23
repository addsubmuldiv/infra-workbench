"""Synthetic data and a restricted A2UI catalog for the assistant prototype."""

import json
from .a2ui_surface import LAYOUT_INSTRUCTIONS

SAMPLED_AT = '2026-11-23 10:30 HKT'

DEVICES = [
    dict(id='npu_a0', host='npu-a', index=0, model='Ascend 910B', status='idle', used_gib=0, total_gib=64),
    dict(id='npu_a1', host='npu-a', index=1, model='Ascend 910B', status='idle', used_gib=0, total_gib=64),
    dict(id='npu_a2', host='npu-a', index=2, model='Ascend 910B', status='busy', used_gib=51, total_gib=64),
    dict(id='npu_b0', host='npu-b', index=0, model='Ascend 910B', status='busy', used_gib=59, total_gib=64),
    dict(id='npu_b1', host='npu-b', index=1, model='Ascend 910B', status='busy', used_gib=57, total_gib=64),
    dict(id='npu_b2', host='npu-b', index=2, model='Ascend 910B', status='idle', used_gib=0, total_gib=64),
    dict(id='gpu_c0', host='gpu-c', index=0, model='NVIDIA A100', status='unknown', used_gib=None, total_gib=80),
]
PROCESSES = [
    dict(id='p_4102', pid=4102, host='npu-a', device='npu_a2', name='sft-worker', used_gib=51),
    dict(id='p_5210', pid=5210, host='npu-b', device='npu_b0', name='rl-rollout', used_gib=59),
    dict(id='p_5211', pid=5211, host='npu-b', device='npu_b1', name='rl-rollout', used_gib=57),
]


def summarize_host(host):
    devices = [device for device in DEVICES if device['host'] == host]
    known = all(device['used_gib'] is not None for device in devices)
    return dict(id=host, model=devices[0]['model'], devices=len(devices),
                idle=sum(device['status'] == 'idle' for device in devices) if known else None,
                busy=sum(device['status'] == 'busy' for device in devices) if known else None,
                used_gib=sum(device['used_gib'] for device in devices) if known else None,
                total_gib=sum(device['total_gib'] for device in devices),
                sampled_at=SAMPLED_AT if known else None)


DATASETS = {
    'hosts': [summarize_host(host) for host in ('npu-a', 'npu-b', 'gpu-c')],
    'devices': DEVICES,
    'processes': PROCESSES,
}

INSTRUCTIONS = """You are the assistant inside an isolated Infra Workbench prototype.
Use only the synthetic snapshot below. There are no tools or live machines.
An unknown value is missing data. It must never be reported as zero or idle.
A snapshot cannot establish historical duration or the cause of a process starting.
""" + LAYOUT_INSTRUCTIONS + '\nSynthetic snapshot:\n' + json.dumps(DATASETS, ensure_ascii=False)
