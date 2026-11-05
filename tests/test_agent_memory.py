import asyncio
import sqlite3

import pytest

from backend.agent_memory import create_agent_memory


def bundle(path, profile='p1', hosts=None):
    return create_agent_memory(sqlite3.connect(path, check_same_thread=False), profile, hosts)


def test_native_memory_persists_and_injects(tmp_path):
    path = tmp_path / 'store.db'
    first = bundle(path)
    assert first.backend.write('/memories/AGENTS.md', 'Prefer concise Chinese explanations.').error is None
    second = bundle(path)
    update = second.middleware.before_agent({}, None, {})
    assert update['memory_contents']['/memories/AGENTS.md'] == 'Prefer concise Chinese explanations.'
    assert asyncio.run(second.backend.aread('/memories/AGENTS.md')).file_data['content'] == 'Prefer concise Chinese explanations.'


def test_memory_profile_and_exact_host_scope_are_isolated(tmp_path):
    path = tmp_path / 'store.db'
    owner = bundle(path, hosts={'a', 'b'})
    owner.backend.write('/memories/AGENTS.md', 'Use table output.')
    assert bundle(path, hosts={'b', 'a'}).backend.read('/memories/AGENTS.md').error is None
    for candidate in [bundle(path), bundle(path, hosts=set()), bundle(path, hosts={'a'}), bundle(path, profile='p2', hosts={'a', 'b'})]:
        assert candidate.backend.read('/memories/AGENTS.md').error


@pytest.mark.parametrize('content', ['x' * 4097, 'password=hello', 'API_KEY: sk-abcdefghi', '-----BEGIN OPENSSH PRIVATE KEY-----', '2026-11-05 11:20:30 ERROR connection lost'])
def test_invalid_memory_never_replaces_existing(tmp_path, content):
    memory = bundle(tmp_path / 'store.db')
    memory.backend.write('/memories/AGENTS.md', 'Use Chinese.')
    with pytest.raises(ValueError):
        memory.backend.write('/memories/AGENTS.md', content)
    assert memory.backend.read('/memories/AGENTS.md').file_data['content'] == 'Use Chinese.'


@pytest.mark.parametrize('path', ['/memories/../AGENTS.md', '/memories/secret.txt', '/memories/a/AGENTS.md', '/memories/AGENTS.md/../../config'])
def test_memory_paths_are_restricted(tmp_path, path):
    memory = bundle(tmp_path / 'store.db')
    with pytest.raises(ValueError):
        memory.backend.write(path, 'Hello')


def test_reject_cross_namespace_and_edit_secrets(tmp_path):
    memory = bundle(tmp_path / 'store.db')
    memory.backend.write('/memories/AGENTS.md', 'Use Chinese.')
    with pytest.raises(ValueError):
        memory.backend.edit('/memories/AGENTS.md', 'Chinese', 'password=bad')
    with pytest.raises(ValueError):
        memory.store.get(('other',), '/AGENTS.md')


def test_forget_and_next_turn_reload(tmp_path):
    memory = bundle(tmp_path / 'store.db')
    memory.backend.write('/memories/AGENTS.md', 'Use Chinese.')
    old_state = memory.middleware.before_agent({}, None, {})
    memory.backend.write('/memories/AGENTS.md', '')
    # Native middleware caches memory in graph state; the runtime must clear
    # this key before each turn, including after a scope/profile change.
    assert memory.middleware.before_agent(old_state, None, {}) is None
    assert memory.middleware.before_agent({}, None, {})['memory_contents'] == {'/memories/AGENTS.md': ''}


def test_upload_cannot_bypass_memory_validation(tmp_path):
    memory = bundle(tmp_path / 'store.db')
    with pytest.raises(ValueError):
        memory.backend.upload_files([('/memories/AGENTS.md', b'password=bad')])
    assert memory.backend.read('/memories/AGENTS.md').error
