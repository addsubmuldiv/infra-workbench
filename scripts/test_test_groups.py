"""Regression checks for selection, inventory drift and isolated execution."""
import importlib.util
import os
from pathlib import Path
from types import SimpleNamespace

import pytest

spec = importlib.util.spec_from_file_location('test_groups', Path(__file__).with_name('run_tests.py'))
runner = importlib.util.module_from_spec(spec)
spec.loader.exec_module(runner)


def test_inventory_is_complete_and_every_group_selects_existing_tests():
    runner.validate()
    for name in runner.GROUPS:
        selected = runner.select([name])
        assert selected
        assert all((runner.ROOT / path).is_file() for path in selected)
    assert set(runner.select(list(runner.GROUPS))) == runner.inventory()


def test_multiple_groups_deduplicate_and_unknown_groups_fail():
    chosen = runner.select(['assistant', 'mcp', 'assistant'])
    assert len(chosen) == len(set(chosen))
    assert set(chosen) == set(runner.select(['assistant'])) | set(runner.select(['mcp']))
    with pytest.raises(ValueError, match='Unknown group'):
        runner.select(['typo'])


def test_new_or_deleted_tests_require_inventory_update(tmp_path):
    (tmp_path / 'tests').mkdir()
    (tmp_path / 'tests/test_new.py').touch()
    with pytest.raises(ValueError, match='Unassigned'):
        runner.validate(tmp_path, {})
    with pytest.raises(ValueError, match='Missing'):
        runner.validate(tmp_path, {'sample': ['tests/test_new.py', 'tests/test_gone.py']})


def test_execution_uses_isolated_data_and_stops_after_failure(monkeypatch):
    calls = []
    directories = []
    original = os.environ.get('IWB_DATA')

    def run(args, **kwargs):
        calls.append(args)
        assert kwargs['cwd'] == runner.ROOT
        data = Path(kwargs['env']['IWB_DATA'])
        directories.append(data)
        assert data.is_dir() and str(data) != original
        return SimpleNamespace(returncode=7)

    monkeypatch.setattr(runner.subprocess, 'run', run)
    assert runner.execute([['first'], ['must-not-run']]) == 7
    assert calls == [['first']]
    assert not directories[0].exists()
    assert os.environ.get('IWB_DATA') == original


def test_commands_keep_frontend_precheck_and_scope():
    paths = runner.select(['ssh'])
    commands = runner.commands(paths, 'frontend')
    assert commands[0][-2:] == ['scripts/generate-internal-defaults.mjs', '--check']
    assert commands[1][1] == '--test'
    assert all(path.startswith('frontend/tests/') for path in commands[1][2:])
    assert not runner.commands(['tests/test_core.py'], 'frontend')


def test_cli_preview_does_not_execute_tests(monkeypatch, capsys):
    monkeypatch.setattr(runner, 'execute', lambda _: pytest.fail('preview must not execute'))
    assert runner.main(['files', 'mcp', '--scope', 'frontend', '--dry-run']) == 0
    output = capsys.readouterr().out
    assert '--test' in output and 'file-browser.test.mjs' in output
    assert '-m pytest' not in output


@pytest.mark.parametrize('args', [[], ['unknown'], ['--all', 'files'], ['core', '--scope', 'tooling']])
def test_cli_rejects_empty_or_invalid_selection(args):
    with pytest.raises(SystemExit) as result:
        runner.main(args)
    assert result.value.code == 2
